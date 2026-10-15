/* ImmXrsive shared script: loaded by index, student, intake and upload.
   Exposes one global: window.IMX */
(function () {
  "use strict";

  /* ---------- Config ---------- */
  var API_URL = "https://immxrsive-api.onrender.com/api/directory";
  var TIMEOUT_MS = 45000;
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Shown only when the live API cannot be reached.
  var SAMPLE = [
    { name: "Amara Okafor", headline: "Full-stack engineer building accessible fintech dashboards", program: "BSc Computer Science", bio: "I build interfaces people can actually use, from design tokens to database indexes. Last summer I shipped a budgeting dashboard used by 2,000 students.\nLooking for a team that cares about accessibility and fast feedback loops.", status: "Current", availability: ["Internship", "Full-time"], skills: ["TypeScript", "React", "Node.js", "PostgreSQL", "Figma"] },
    { name: "Daniel Reyes", headline: "Backend developer focused on APIs and distributed systems", program: "BSc Computer Science, Software Engineering", bio: "I like boring, reliable infrastructure. Built a job queue in Go that processes 40k events a minute for a campus ride-share project.", status: "Alumni", availability: ["Contract", "Full-time"], skills: ["Go", "Docker", "Redis", "gRPC", "AWS"] },
    { name: "Priya Nair", headline: "ML engineer exploring computer vision for agriculture", program: "BSc Applied Computing", bio: "My capstone trained a crop disease classifier on 18k labelled leaf photos and ran it on a Raspberry Pi in the field.", status: "Current", availability: ["Internship"], skills: ["Python", "PyTorch", "OpenCV", "FastAPI", "XR"] },
    { name: "Marcus Lee", headline: "Mobile developer shipping cross-platform apps", program: "BSc Computer Science", bio: "Two apps in the stores, one with a 4.8 rating. I care about startup time, offline support and clean architecture.", status: "Alumni", availability: ["Contract"], skills: ["Flutter", "Dart", "Kotlin", "Firebase", "Swift"] },
    { name: "Sofia Mendes", headline: "Product designer who writes production CSS", program: "BA Digital Media and Design", bio: "I move between Figma and the browser without handoff friction. Strong on design systems, motion and component libraries.", status: "Current", availability: ["Internship", "Contract"], skills: ["Figma", "CSS", "JavaScript", "Accessibility", "Svelte"] },
    { name: "Kwame Asante", headline: "Security-minded engineer and CTF player", program: "BSc Cybersecurity", bio: "Regular on student CTF teams and a volunteer pen-tester for local nonprofits. I enjoy turning findings into fixes the team will adopt.", status: "Alumni", availability: ["Full-time"], skills: ["Python", "Burp Suite", "Linux", "Rust", "Networking"] },
    { name: "Hannah Becker", headline: "Data engineer who loves clean pipelines", program: "BSc Data Science", bio: "I build ETL pipelines, test them properly and document them. Comfortable with warehouses, orchestration and dashboards.", status: "Current", availability: ["Internship", "Full-time"], skills: ["SQL", "Airflow", "dbt", "Python", "BigQuery", "Tableau"] },
    { name: "Ravi Patel", headline: "Game developer and graphics tinkerer", program: "BSc Game Development", bio: "I made a multiplayer physics sandbox in Unity and a software rasteriser in C++ for fun. Always up for a game jam.", status: "Current", availability: ["Internship", "Contract"], skills: ["C++", "Unity", "C#", "OpenGL", "XR", "3D"] },
    { name: "Elena Petrova", headline: "DevOps engineer automating everything twice", program: "BSc Information Technology", bio: "CI that finishes in under five minutes and deploys that nobody has to babysit. I write the runbooks, too.", status: "Alumni", availability: ["Contract", "Full-time"], skills: ["Kubernetes", "Terraform", "GitHub Actions", "Bash", "Prometheus"] },
    { name: "Jonah Weiss", headline: "Spatial computing developer prototyping in WebXR", program: "BSc Applied Computing", bio: "I prototype headset and browser experiences, mostly with Three.js and a lot of user testing in the hallway.", status: "Current", availability: ["Internship"], skills: ["Three.js", "WebXR", "JavaScript", "3D", "Accessibility"] }
  ];
  // Optional. Live API profiles can send their own "projects": [{title, role, summary}].
  var SAMPLE_PROJECTS = {
    "Amara Okafor": [{ title: "Student budgeting dashboard", role: "Full-stack lead", summary: "Accessible spending dashboard used by 2,000 students." }],
    "Daniel Reyes": [{ title: "Campus ride-share job queue", role: "Backend engineer", summary: "Go job queue processing about 40k events a minute." }],
    "Priya Nair": [{ title: "Crop disease classifier", role: "ML engineer", summary: "Trained on 18k leaf photos and run on a Raspberry Pi in the field." }],
    "Marcus Lee": [{ title: "Cross-platform mobile apps", role: "Mobile developer", summary: "Two apps in the stores, one rated 4.8." }],
    "Ravi Patel": [{ title: "Multiplayer physics sandbox", role: "Game developer", summary: "Unity sandbox, plus a software rasteriser written in C++." }],
    "Jonah Weiss": [{ title: "WebXR prototypes", role: "Spatial developer", summary: "Headset and browser experiences built with Three.js and tested with users." }]
  };

  /* ---------- Helpers ---------- */
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function str(v) { return v == null ? "" : String(v).trim(); }
  function lc(s) { return s.toLowerCase(); }
  function list(v) {
    if (Array.isArray(v)) return v.map(str).filter(Boolean);
    if (typeof v === "string" && v.trim()) return v.split(",").map(str).filter(Boolean);
    return [];
  }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function fillTags(c, items) { c.replaceChildren(); items.forEach(function (s) { c.appendChild(el("span", "tag", s)); }); }
  function toast(msg) {
    var t = el("div", "toast", msg);
    t.setAttribute("role", "status");
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2600);
  }
  // Student ids go into URLs, so only allow a safe character set.
  function validId(id) { return /^[A-Za-z0-9_-]{1,40}$/.test(id || ""); }
  function studentUrl(id) { return "student.html?id=" + encodeURIComponent(id); }
  function intakeUrl(id) { return "intake.html?source_id=" + encodeURIComponent(id); }

  /* ---------- Data ---------- */
  // Uses the API's own "id" when it sends one, otherwise S01, S02... by position in the list.
  function normalize(p, i) {
    var o = {
      id: str(p && p.id) || ("S" + pad2(i + 1)),
      name: str(p && p.name) || "Unnamed profile",
      headline: str(p && p.headline),
      program: str(p && p.program),
      bio: str(p && p.bio),
      status: str(p && p.status),
      availability: list(p && p.availability),
      skills: list(p && p.skills),
      projects: Array.isArray(p && p.projects) ? p.projects : (SAMPLE_PROJECTS[str(p && p.name)] || [])
    };
    o.hay = lc([o.name, o.headline, o.program, o.bio, o.status, o.skills.join(" "), o.availability.join(" ")].join(" "));
    return o;
  }

  // Resolves { data: [normalized profiles], live: boolean }. Never rejects: falls back to SAMPLE.
  // The first request to free hosting can be slow, so a successful response is cached for the tab session.
  function loadDirectory(onSlow) {
    try {
      var c = JSON.parse(sessionStorage.getItem("imx_dir") || "null");
      if (Array.isArray(c) && c.length) return Promise.resolve({ data: c.map(normalize), live: true });
    } catch (e) {}
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, TIMEOUT_MS);
    var slow = setTimeout(function () { if (onSlow) onSlow(); }, 4000);
    return fetch(API_URL, { headers: { "Accept": "application/json" }, signal: controller.signal })
      .then(function (res) { if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function (data) {
        var arr = Array.isArray(data) ? data : (data && Array.isArray(data.data) ? data.data : null);
        if (!arr) throw new Error("Unexpected response shape");
        try { sessionStorage.setItem("imx_dir", JSON.stringify(arr)); } catch (e) {}
        return { data: arr.map(normalize), live: true };
      })
      .catch(function () { return { data: SAMPLE.map(normalize), live: false }; })
      .then(function (r) { clearTimeout(timer); clearTimeout(slow); return r; });
  }

  /* ---------- Constellation avatar (deterministic per person) ---------- */
  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { return function () { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; var t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function constellation(p, size) {
    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 64 64");
    svg.setAttribute("width", size); svg.setAttribute("height", size);
    svg.setAttribute("class", "const");
    svg.setAttribute("aria-hidden", "true");
    var r = rng(hash(p.name));
    var n = Math.max(4, Math.min(8, p.skills.length + 2));
    var pts = [];
    for (var i = 0; i < n; i++) pts.push({ x: 8 + r() * 48, y: 8 + r() * 48 });
    pts.sort(function (a, b) { return a.x - b.x; });
    var d = "M" + pts.map(function (q) { return q.x.toFixed(1) + " " + q.y.toFixed(1); }).join(" L");
    var path = document.createElementNS(NS, "path");
    path.setAttribute("d", d); path.setAttribute("class", "ln");
    svg.appendChild(path);
    if (n > 5) {
      var extra = document.createElementNS(NS, "path");
      extra.setAttribute("d", "M" + pts[1].x.toFixed(1) + " " + pts[1].y.toFixed(1) + " L" + pts[n - 2].x.toFixed(1) + " " + pts[n - 2].y.toFixed(1));
      extra.setAttribute("class", "ln"); svg.appendChild(extra);
    }
    var hot = Math.floor(r() * n);
    pts.forEach(function (q, idx) {
      var c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", q.x.toFixed(1)); c.setAttribute("cy", q.y.toFixed(1));
      c.setAttribute("r", idx === hot ? 3 : (1.3 + r() * 1.2).toFixed(1));
      c.setAttribute("class", "st" + (idx === hot ? " hot" : ""));
      svg.appendChild(c);
    });
    return svg;
  }

  /* ---------- Starfield + Gargantua ---------- */
  function sky() {
    var cv = $("sky"); if (!cv) return;
    var ctx = cv.getContext("2d"); if (!ctx) return;
    var W = 0, H = 0, dpr = 1, stars = [], parts = [], sy = 0, vel = 0, lastSy = 0, last = 0, R = 90, cx = 0, cy = 0;
    function seed() {
      stars = []; parts = [];
      var n = Math.round(Math.min(320, Math.max(110, (W * H) / 8000)));
      for (var i = 0; i < n; i++) { var z = Math.random(); stars.push({ x: Math.random() * W, y: Math.random() * H, z: z, r: 0.4 + z * 1.1, a: 0.25 + z * 0.6, tw: 0.6 + Math.random() * 1.8, ph: Math.random() * 6.28, c: Math.random() < 0.12 }); }
      var pn = W < 700 ? 420 : 760;
      for (i = 0; i < pn; i++) { var r = 1.45 + Math.pow(Math.random(), 1.6) * 2.6; parts.push({ r: r, a: Math.random() * 6.2832, s: 0.5 / Math.pow(r, 1.5), z: 0.6 + Math.random() * 1.6 }); }
    }
    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth; H = window.innerHeight;
      cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed(); draw(0);
    }
    function disc(p, lens, front) {
      var c = Math.cos(p.a), sn = Math.sin(p.a), t = (p.r - 1.45) / 2.6, x, y;
      if (lens) { var rho = R * (1.1 + t * 0.35); x = cx + c * rho; y = cy + (front ? -sn : sn) * rho * (front ? 0.85 : 1); }
      else { x = cx + c * p.r * R; y = cy + sn * p.r * R * 0.2; }
      var al = (0.5 + 0.5 * c) * (1 - t * 0.55) * (lens && front ? 0.5 : 1);
      ctx.fillStyle = "hsla(" + (195 + t * 20) + "," + (45 + t * 40) + "%," + (92 - t * 40) + "%," + al.toFixed(2) + ")";
      var sz = (0.6 + p.z * 0.8) * (R / 90);
      ctx.fillRect(x, y, sz, sz);
    }
    function hole() {
      var fade = Math.max(0, 1 - sy / (H * 1.05)); if (fade < 0.02) return;
      R = Math.min(W, H) * (W < 700 ? 0.11 : 0.14);
      cx = W < 700 ? W * 0.66 : W * 0.74; cy = (W < 700 ? H * 0.2 : H * 0.36) - sy * 0.55;
      ctx.save(); ctx.globalAlpha = fade;
      var g = ctx.createRadialGradient(cx, cy, R * 0.9, cx, cy, R * 5);
      g.addColorStop(0, "rgba(150,205,230,.28)"); g.addColorStop(0.4, "rgba(70,140,180,.08)"); g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g; ctx.fillRect(cx - R * 5, cy - R * 5, R * 10, R * 10);
      ctx.globalCompositeOperation = "lighter";
      var i, p;
      for (i = 0; i < parts.length; i++) { p = parts[i]; if (Math.sin(p.a) < 0) { disc(p, false); disc(p, true, false); disc(p, true, true); } }
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = "#000"; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.2832); ctx.fill();
      ctx.strokeStyle = "rgba(225,242,250,.9)"; ctx.lineWidth = Math.max(1, R * 0.018); ctx.shadowColor = "#bfe3f2"; ctx.shadowBlur = R * 0.25;
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.015, 0, 6.2832); ctx.stroke(); ctx.shadowBlur = 0;
      ctx.globalCompositeOperation = "lighter";
      for (i = 0; i < parts.length; i++) { p = parts[i]; if (Math.sin(p.a) >= 0) disc(p, false); }
      ctx.restore();
    }
    function draw(t) {
      ctx.clearRect(0, 0, W, H);
      var warp = Math.min(70, Math.abs(vel) * 1.4);
      for (var i = 0; i < stars.length; i++) {
        var s = stars[i], y = (s.y - sy * (0.03 + s.z * 0.12)) % H; if (y < 0) y += H;
        var a = REDUCED ? s.a : s.a * (0.72 + 0.28 * Math.sin(t / 1000 * s.tw + s.ph));
        ctx.globalAlpha = Math.max(0, Math.min(1, a));
        ctx.fillStyle = ctx.strokeStyle = s.c ? "#a9d8ea" : "#e8f1f5";
        if (warp > 3) { ctx.lineWidth = s.r; ctx.beginPath(); ctx.moveTo(s.x, y); ctx.lineTo(s.x, y + warp * s.z * (vel > 0 ? 1 : -1)); ctx.stroke(); }
        else { ctx.beginPath(); ctx.arc(s.x, y, s.r, 0, 6.2832); ctx.fill(); }
      }
      ctx.globalAlpha = 1; hole();
    }
    function frame(t) {
      var dt = Math.min(50, t - last); last = t;
      vel += ((sy - lastSy) - vel) * 0.2; lastSy = sy;
      for (var i = 0; i < parts.length; i++) parts[i].a += parts[i].s * dt * 0.004;
      draw(t); requestAnimationFrame(frame);
    }
    window.addEventListener("resize", resize);
    window.addEventListener("scroll", function () { sy = window.scrollY || 0; if (REDUCED) draw(0); }, { passive: true });
    resize();
    if (!REDUCED) requestAnimationFrame(frame);
  }

  /* ---------- Scroll progress bar + current nav link ---------- */
  function progress() {
    var bar = $("progress"); if (!bar) return;
    var ticking = false;
    function upd() {
      var h = document.documentElement.scrollHeight - window.innerHeight;
      var p = h > 0 ? Math.min(1, Math.max(0, (window.scrollY || 0) / h)) : 0;
      bar.style.transform = "scaleX(" + p + ")";
      ticking = false;
    }
    window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(upd); } }, { passive: true });
    window.addEventListener("resize", upd);
    upd();
  }
  function markNav() {
    var here = (location.pathname.split("/").pop() || "index.html").toLowerCase();
    if (here === "student.html") here = "index.html";
    document.querySelectorAll(".nav-links a").forEach(function (a) {
      var file = (a.getAttribute("href") || "").split("#")[0].toLowerCase();
      if (file === here && !a.getAttribute("href").includes("#")) a.setAttribute("aria-current", "page");
    });
  }

  sky(); progress(); markNav();

  window.IMX = {
    REDUCED: REDUCED, $: $, el: el, str: str, lc: lc, list: list, pad2: pad2, fillTags: fillTags, toast: toast,
    validId: validId, studentUrl: studentUrl, intakeUrl: intakeUrl, loadDirectory: loadDirectory, constellation: constellation
  };
})();