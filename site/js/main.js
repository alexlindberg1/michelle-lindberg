const nav = document.querySelector(".nav");
const toggle = document.querySelector(".nav-toggle");
const menu = document.querySelector(".nav-links");

toggle?.addEventListener("click", () => {
  const open = menu.classList.toggle("is-open");
  toggle.setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("menu-open", open);
});

menu?.addEventListener("click", (event) => {
  if (!event.target.closest("a")) return;
  menu.classList.remove("is-open");
  toggle?.setAttribute("aria-expanded", "false");
  document.body.classList.remove("menu-open");
});

const onScroll = () => {
  nav?.classList.toggle("is-scrolled", window.scrollY > 8);
};

onScroll();
window.addEventListener("scroll", onScroll, { passive: true });

const links = [...document.querySelectorAll(".nav-links a[href^='#']")];
const sections = links
  .map((link) => document.querySelector(link.getAttribute("href")))
  .filter(Boolean);

const markCurrent = () => {
  const y = window.scrollY + 140;
  let current = null;
  sections.forEach((section) => {
    if (section.offsetTop <= y) current = section;
  });
  links.forEach((link) => {
    const on = current && link.getAttribute("href") === `#${current.id}`;
    if (on) link.setAttribute("aria-current", "true");
    else link.removeAttribute("aria-current");
  });
};

markCurrent();
window.addEventListener("scroll", markCurrent, { passive: true });

const lensNotes = {
  all: "The full record, in one reading.",
  lab: "Laboratory work first: Valencia, specimens, and clinic procedure.",
  engineering: "The degree path: biological engineering at the University of Georgia.",
  business: "The business thread: a minor, DECA, and Dial One Security.",
};

const lensNote = document.getElementById("lens-note");

const applyLens = (name) => {
  document.body.dataset.lens = name;
  document.querySelectorAll("[data-for]").forEach((el) => {
    const tags = el.dataset.for.split(/\s+/);
    const match = name === "all" || tags.includes(name);
    el.classList.toggle("is-dim", name !== "all" && !match);
    el.classList.toggle("is-lit", name !== "all" && match);
  });
  document.querySelectorAll("[data-lens-btn]").forEach((button) => {
    button.setAttribute("aria-checked", String(button.dataset.lensBtn === name));
  });
  if (lensNote) lensNote.textContent = lensNotes[name] || lensNotes.all;
};

document.querySelectorAll("[data-lens-btn]").forEach((button) => {
  button.addEventListener("click", () => applyLens(button.dataset.lensBtn));
});

document.querySelectorAll(".role").forEach((role) => {
  const toggle = role.querySelector(".role-toggle");
  const tabs = [...role.querySelectorAll(".beats [role='tab']")];
  const copies = [...role.querySelectorAll(".beat-copies p")];
  if (!toggle) return;

  toggle.addEventListener("click", () => {
    const open = role.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", String(open));
    if (!open) return;
    document.querySelectorAll(".role.is-open").forEach((other) => {
      if (other === role) return;
      other.classList.remove("is-open");
      other.querySelector(".role-toggle")?.setAttribute("aria-expanded", "false");
    });
  });

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => {
      tabs.forEach((item, itemIndex) => {
        const on = itemIndex === index;
        item.setAttribute("aria-selected", String(on));
        if (copies[itemIndex]) copies[itemIndex].hidden = !on;
      });
    });
  });
});

const stops = {
  cincinnati: {
    kicker: "Cincinnati, Ohio",
    copy: "Indian Hill High School through May 2024, and the jobs that started there: Dial One Security from 2020, Camargo Trading in 2021–2022, and Kenwood Complete Dentistry in 2023.",
    fill: 0,
  },
  athens: {
    kicker: "Athens, Georgia",
    copy: "University of Georgia, second year. Biological engineering, a business minor, and a 3.4 GPA.",
    fill: 0.5,
  },
  valencia: {
    kicker: "Valencia, Spain",
    copy: "June and July 2026. Veterinary laboratory intern at Sagunto 99: specimens, procedures, and a clinic that worked in Spanish.",
    fill: 1,
  },
};

const routeKicker = document.getElementById("route-kicker");
const routeCopy = document.getElementById("route-copy");
const routeFill = document.getElementById("route-fill");

document.querySelectorAll("[data-stop]").forEach((button) => {
  button.addEventListener("click", () => {
    const stop = stops[button.dataset.stop];
    if (!stop) return;
    document.querySelectorAll("[data-stop]").forEach((item) => {
      const on = item === button;
      item.classList.toggle("is-on", on);
      item.setAttribute("aria-pressed", String(on));
    });
    if (routeKicker) routeKicker.textContent = stop.kicker;
    if (routeCopy) routeCopy.textContent = stop.copy;
    if (routeFill) routeFill.style.setProperty("--route", String(stop.fill));
  });
});

const reveal = document.querySelectorAll(".reveal");
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (reduce || !("IntersectionObserver" in window)) {
  reveal.forEach((el) => el.classList.add("is-in"));
} else {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-in");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.14, rootMargin: "0px 0px -8% 0px" }
  );
  reveal.forEach((el) => observer.observe(el));
}
