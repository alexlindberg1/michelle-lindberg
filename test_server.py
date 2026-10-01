import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ledger import FileLedger, GitLedger
from server import create_app


PATH = "/r/testledger"
PASSWORD = "correct horse"


def build_app(ledger):
    return create_app({
        "path": PATH,
        "password": PASSWORD,
        "secret": "test-secret",
        "cookie_secure": False,
        "ledger": ledger,
    })


def sign_in(client):
    page = client.get(PATH)
    token = page.get_data(as_text=True).split('name="csrf" value="', 1)[1].split('"', 1)[0]
    response = client.post(PATH + "/login", data={"password": PASSWORD, "csrf": token})
    return response, token


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = FileLedger(Path(self.tmp.name) / "applications.json")
        self.app = build_app(self.ledger)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_public_resume_has_no_tracker_link(self):
        response = self.client.get("/")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Michelle Lindberg", body)
        self.assertNotIn(PATH, body)
        self.assertNotIn("Add an application", body)
        self.assertNotIn("dashboard.css", body)

    def test_unknown_path_is_not_the_tracker(self):
        response = self.client.get("/r/someone-else")
        self.assertEqual(response.status_code, 404)

    def test_password_and_saved_application(self):
        wrong = self.client.get(PATH)
        token = wrong.get_data(as_text=True).split('name="csrf" value="', 1)[1].split('"', 1)[0]
        denied = self.client.post(PATH + "/login", data={"password": "nope", "csrf": token})
        self.assertEqual(denied.status_code, 401)

        sign_in(self.client)
        page = self.client.get(PATH)
        token = page.get_data(as_text=True).split('name="csrf" value="', 1)[1].split('"', 1)[0]
        saved = self.client.post(
            PATH + "/applications",
            data={
                "csrf": token,
                "company": "Rivian",
                "role": "Lab intern",
                "website": "rivian.com/careers",
                "location": "Normal, Illinois",
                "status": "Applied",
                "applied_on": "2026-10-01",
                "deadline": "",
                "contact": "campus@rivian.com",
                "notes": "Submitted the résumé.",
            },
            follow_redirects=True,
        )
        body = saved.get_data(as_text=True)
        self.assertIn("Rivian", body)
        self.assertIn("https://rivian.com/careers", body)
        self.assertIn("Applied", body)
        self.assertIn("Saved Rivian.", body)

        rows = self.ledger.read()
        self.assertEqual(rows[0]["company"], "Rivian")
        edit = self.client.get(PATH + "/applications/" + rows[0]["id"])
        self.assertIn("Edit Rivian", edit.get_data(as_text=True))

    def test_api_key_updates_status(self):
        denied = self.client.post(
            PATH + "/api/applications",
            json={"company": "Genentech", "status": "To apply"},
        )
        self.assertEqual(denied.status_code, 401)
        created = self.client.post(
            PATH + "/api/applications",
            json={"company": "Genentech", "status": "To apply", "website": "https://www.gene.com"},
            headers={"X-Dashboard-Key": PASSWORD},
        )
        self.assertEqual(created.status_code, 201)
        application_id = created.get_json()["application"]["id"]
        updated = self.client.put(
            PATH + f"/api/applications/{application_id}",
            json={"status": "Interview"},
            headers={"X-Dashboard-Key": PASSWORD},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["application"]["status"], "Interview")
        self.assertEqual(updated.get_json()["application"]["company"], "Genentech")

    def test_blank_password_cannot_sign_in(self):
        app = create_app({
            "path": PATH,
            "password": "",
            "secret": "test-secret",
            "cookie_secure": False,
            "ledger": self.ledger,
        })
        client = app.test_client()
        page = client.get(PATH)
        token = page.get_data(as_text=True).split('name="csrf" value="', 1)[1].split('"', 1)[0]
        denied = client.post(PATH + "/login", data={"password": "", "csrf": token})
        self.assertEqual(denied.status_code, 401)


class GitLedgerTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin.git"
            seed = Path(tmp) / "seed"
            subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
            (seed / "applications.json").write_text("[]\n")
            commit = [
                "git", "-c", "user.email=ledger@michellelind.com",
                "-c", "user.name=Application ledger",
            ]
            subprocess.run(["git", "add", "applications.json"], cwd=seed, check=True)
            subprocess.run([*commit, "commit", "-m", "Start ledger"], cwd=seed, check=True)
            subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=seed, check=True)
            subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=seed, check=True)

            ledger = GitLedger(str(origin), key_b64=None)
            ledger.update(lambda rows: rows + [{"id": "1", "company": "Acme"}])
            self.assertEqual(ledger.read()[0]["company"], "Acme")
            stored = json.loads((seed / "applications.json").read_text()) if False else None
            fresh = Path(tmp) / "fresh"
            subprocess.run(["git", "clone", str(origin), str(fresh)], check=True, capture_output=True)
            stored = json.loads((fresh / "applications.json").read_text())
            self.assertEqual(stored[0]["company"], "Acme")


if __name__ == "__main__":
    unittest.main()
