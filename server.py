import csv
import hmac
import io
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from ledger import FileLedger, GitLedger

SITE = Path(__file__).resolve().parent / "site"
STATUSES = (
    "To apply",
    "Applied",
    "Responded",
    "Interview",
    "Offer",
    "Rejected",
    "Withdrawn",
)
LIMITS = {
    "company": 160,
    "role": 160,
    "website": 400,
    "location": 120,
    "contact": 160,
    "notes": 4000,
}


def create_app(settings=None):
    settings = settings or settings_from_env()
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.secret_key = settings["secret"]
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings["cookie_secure"],
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    )
    app.config["DASHBOARD_PATH"] = settings["path"]
    app.config["LEDGER"] = settings["ledger"]
    app.config["PASSWORD"] = settings["password"]
    attempts = {}

    prefix = (settings["path"] or "").rstrip("/")

    def private(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["CDN-Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def csrf_token():
        token = session.get("csrf")
        if not token:
            token = secrets.token_urlsafe(24)
            session["csrf"] = token
        return token

    def csrf_ok():
        expected = session.get("csrf", "")
        sent = request.form.get("csrf", "")
        return bool(expected) and hmac.compare_digest(expected, sent)

    def authed():
        return bool(session.get("ok"))

    def key_ok():
        sent = request.headers.get("X-Dashboard-Key", "")
        password = app.config["PASSWORD"]
        return bool(password) and hmac.compare_digest(sent, password)

    def require_login():
        if not authed():
            abort(401)

    def too_many_attempts():
        now = datetime.now(timezone.utc).timestamp()
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ip = ip.split(",")[0].strip()
        recent = [stamp for stamp in attempts.get(ip, []) if now - stamp < 600]
        attempts[ip] = recent
        if len(recent) >= 8:
            return True
        recent.append(now)
        return False

    def clean(form, existing=None):
        company = (form.get("company") or "").strip()
        if not company:
            raise ValueError("Company is required.")
        status = (form.get("status") or "").strip()
        if status not in STATUSES:
            raise ValueError("Choose a status.")
        website = (form.get("website") or "").strip()
        if website and not website.startswith(("http://", "https://")):
            website = "https://" + website
        if website and urlparse(website).scheme not in ("http", "https"):
            raise ValueError("Website must be an http or https link.")
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        raw_interest = form.get("interest")
        if raw_interest is None or raw_interest == "":
            raw_interest = (existing or {}).get("interest", 0)
        try:
            interest = int(raw_interest)
        except (TypeError, ValueError):
            raise ValueError("Interest must be from 0 to 5.")
        if interest < 0 or interest > 5:
            raise ValueError("Interest must be from 0 to 5.")
        item = {
            "id": (existing or {}).get("id") or secrets.token_hex(8),
            "company": company[: LIMITS["company"]],
            "role": (form.get("role") or "").strip()[: LIMITS["role"]],
            "website": website[: LIMITS["website"]],
            "location": (form.get("location") or "").strip()[: LIMITS["location"]],
            "status": status,
            "interest": interest,
            "applied_on": (form.get("applied_on") or "").strip()[:10],
            "deadline": (form.get("deadline") or "").strip()[:10],
            "contact": (form.get("contact") or "").strip()[: LIMITS["contact"]],
            "notes": (form.get("notes") or "").strip()[: LIMITS["notes"]],
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        return item

    def blank():
        return {
            "company": "",
            "role": "",
            "website": "",
            "location": "",
            "status": "To apply",
            "interest": 0,
            "applied_on": "",
            "deadline": "",
            "contact": "",
            "notes": "",
        }

    def render_private(template, **context):
        response = make_response(
            render_template(
                template,
                csrf=csrf_token(),
                path=prefix,
                statuses=STATUSES,
                **context,
            )
        )
        return private(response)

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    @app.get("/")
    def home():
        return send_from_directory(SITE, "index.html")

    if prefix:

        @app.route(prefix, methods=["GET"])
        def entrance():
            if authed():
                return board_response()
            return render_private("login.html", error="")

        @app.post(prefix + "/login")
        def login():
            if not csrf_ok():
                return render_private("login.html", error="Open this page again, then sign in."), 400
            if too_many_attempts():
                return render_private(
                    "login.html",
                    error="Too many attempts. Wait a few minutes and try again.",
                ), 429
            sent = request.form.get("password", "")
            expected = app.config["PASSWORD"]
            if expected and hmac.compare_digest(sent, expected):
                session.clear()
                session["ok"] = True
                session.permanent = True
                return redirect(prefix)
            return render_private("login.html", error="That password is not right."), 401

        @app.post(prefix + "/logout")
        def logout():
            if csrf_ok():
                session.clear()
            return redirect(prefix)

        @app.post(prefix + "/applications")
        def create_application():
            require_login()
            if not csrf_ok():
                abort(400)
            try:
                item = clean(request.form)
            except ValueError as exc:
                return board_response(draft=request.form.to_dict(), error=str(exc)), 400
            app.config["LEDGER"].update(lambda rows: [item, *rows])
            flash(f"Saved {item['company']}.")
            return redirect(prefix)

        @app.get(prefix + "/applications/<application_id>")
        def edit_application(application_id):
            require_login()
            item = find_row(application_id)
            if not item:
                abort(404)
            return render_private("edit.html", item=item, error="")

        @app.post(prefix + "/applications/<application_id>")
        def update_application(application_id):
            require_login()
            if not csrf_ok():
                abort(400)
            existing = find_row(application_id)
            if not existing:
                abort(404)
            try:
                item = clean(request.form, existing)
            except ValueError as exc:
                merged = {**existing, **request.form.to_dict()}
                return render_private("edit.html", item=merged, error=str(exc)), 400

            def mutate(rows):
                return [item if row.get("id") == application_id else row for row in rows]

            app.config["LEDGER"].update(mutate)
            flash(f"Updated {item['company']}.")
            return redirect(prefix)

        @app.post(prefix + "/applications/<application_id>/interest")
        def set_interest(application_id):
            require_login()
            if not csrf_ok():
                abort(400)
            existing = find_row(application_id)
            if not existing:
                abort(404)
            try:
                chosen = int(request.form.get("interest", ""))
            except (TypeError, ValueError):
                abort(400)
            if chosen < 1 or chosen > 5:
                abort(400)
            current = int(existing.get("interest") or 0)
            new_value = 0 if current == chosen else chosen
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

            def mutate(rows):
                updated = []
                for row in rows:
                    if row.get("id") == application_id:
                        row = {**row, "interest": new_value, "updated_at": now}
                    updated.append(row)
                return updated

            app.config["LEDGER"].update(mutate)
            if "application/json" in request.headers.get("Accept", ""):
                return private(jsonify(interest=new_value))
            return redirect(prefix)

        @app.post(prefix + "/applications/<application_id>/delete")
        def delete_application(application_id):
            require_login()
            if not csrf_ok():
                abort(400)

            def mutate(rows):
                return [row for row in rows if row.get("id") != application_id]

            app.config["LEDGER"].update(mutate)
            flash("Deleted that application.")
            return redirect(prefix)

        @app.get(prefix + "/export")
        def export_applications():
            if not authed() and not key_ok():
                if "X-Dashboard-Key" in request.headers:
                    return private(jsonify(error="unauthorized")), 401
                abort(401)
            rows = visible_rows(app.config["LEDGER"].read())
            columns = (
                "id",
                "company",
                "role",
                "website",
                "location",
                "status",
                "interest",
                "applied_on",
                "deadline",
                "contact",
                "notes",
                "created_at",
                "updated_at",
            )
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in columns})
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            response = make_response(buf.getvalue())
            response.headers["Content-Type"] = "text/csv; charset=utf-8"
            response.headers["Content-Disposition"] = (
                f"attachment; filename=applications-{stamp}.csv"
            )
            return private(response)

        @app.get(prefix + "/api/applications")
        def api_list():
            if not key_ok():
                return jsonify(error="unauthorized"), 401
            return private(jsonify(applications=app.config["LEDGER"].read()))

        @app.post(prefix + "/api/applications")
        def api_create():
            if not key_ok():
                return jsonify(error="unauthorized"), 401
            payload = request.get_json(silent=True) or {}
            try:
                item = clean(payload)
            except ValueError as exc:
                return jsonify(error=str(exc)), 400
            app.config["LEDGER"].update(lambda rows: [item, *rows])
            return private(jsonify(application=item)), 201

        @app.route(prefix + "/api/applications/<application_id>", methods=["POST", "PUT"])
        def api_update(application_id):
            if not key_ok():
                return jsonify(error="unauthorized"), 401
            existing = find_row(application_id)
            if not existing:
                return jsonify(error="not found"), 404
            payload = request.get_json(silent=True) or {}
            merged = {**existing, **payload}
            try:
                item = clean(merged, existing)
            except ValueError as exc:
                return jsonify(error=str(exc)), 400

            def mutate(rows):
                return [item if row.get("id") == application_id else row for row in rows]

            app.config["LEDGER"].update(mutate)
            return private(jsonify(application=item))

        def find_row(application_id):
            for row in app.config["LEDGER"].read():
                if row.get("id") == application_id:
                    return row
            return None

        def visible_rows(rows):
            status_filter = request.args.get("status", "").strip()
            query = request.args.get("q", "").strip().lower()
            if status_filter in STATUSES:
                rows = [row for row in rows if row.get("status") == status_filter]
            if query:
                rows = [
                    row for row in rows
                    if query in " ".join(
                        str(row.get(key, ""))
                        for key in ("company", "role", "website", "location", "contact", "notes")
                    ).lower()
                ]
            rows.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
            return rows

        def favicon_for(website):
            try:
                host = urlparse(website or "").hostname or ""
            except ValueError:
                return ""
            host = host.strip().lower()
            if not host:
                return ""
            return f"https://www.google.com/s2/favicons?domain={host}&sz=64"

        def board_response(draft=None, error=""):
            status_filter = request.args.get("status", "").strip()
            if status_filter not in STATUSES:
                status_filter = ""
            rows = app.config["LEDGER"].read()
            counts = {status: 0 for status in STATUSES}
            for row in rows:
                if row.get("status") in counts:
                    counts[row["status"]] += 1
            bits = [f"{counts[status]} {status.lower()}" for status in STATUSES if counts[status]]
            summary = f"{len(rows)} saved"
            if bits:
                summary = summary + ". " + " · ".join(bits)
            table_rows = [
                {**row, "favicon": favicon_for(row.get("website", ""))}
                for row in visible_rows(rows)
            ]
            return render_private(
                "board.html",
                rows=table_rows,
                summary=summary,
                draft=draft if draft is not None else blank(),
                error=error,
                query=request.args.get("q", ""),
                status_filter=status_filter,
            )

    @app.get("/<path:filename>")
    def public_file(filename):
        if prefix and (filename == prefix.lstrip("/") or filename.startswith(prefix.lstrip("/") + "/")):
            abort(404)
        return send_from_directory(SITE, filename)

    @app.errorhandler(401)
    def unauthorized(_error):
        if request.path.startswith(prefix + "/api/"):
            return jsonify(error="unauthorized"), 401
        return redirect(prefix or "/")

    return app


class LazyLedger:
    """Open the private git ledger on the first dashboard request, not at boot.

    The public résumé must stay up even if the ledger key is missing.
    """

    def __init__(self, factory):
        self.factory = factory
        self._ledger = None
        self._lock = threading.Lock()

    def _open(self):
        if self._ledger is None:
            with self._lock:
                if self._ledger is None:
                    self._ledger = self.factory()
        return self._ledger

    def read(self):
        return self._open().read()

    def update(self, mutate):
        return self._open().update(mutate)


def settings_from_env():
    path = os.environ.get("DASHBOARD_PATH", "").strip()
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    secret = os.environ.get("SECRET_KEY", "") or secrets.token_hex(32)
    if os.environ.get("LEDGER_SSH_KEY_B64") and os.environ.get("LEDGER_REPO"):
        ledger = LazyLedger(
            lambda: GitLedger(os.environ["LEDGER_REPO"], os.environ["LEDGER_SSH_KEY_B64"])
        )
    else:
        ledger = FileLedger(os.environ.get("LEDGER_FILE", "data/applications.json"))
    return {
        "path": path,
        "password": password,
        "secret": secret,
        "cookie_secure": os.environ.get("COOKIE_SECURE", "0") == "1",
        "ledger": ledger,
    }


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8766")))
