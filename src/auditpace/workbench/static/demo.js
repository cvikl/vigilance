// Judge-facing checklist for the pitch (`?demo=1` only). Ticks C1–C4 when a marked element is seen or
// clicked; C5 is ticked by hand. State lives in sessionStorage so it survives navigation.
(function () {
  const KEY = "auditpace-demo";
  const load = () => {
    try {
      return JSON.parse(sessionStorage.getItem(KEY) || "{}");
    } catch (e) {
      return {};
    }
  };
  const state = load();
  if (!state.t0) state.t0 = Date.now();
  const save = () => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify(state));
    } catch (e) {
      // sessionStorage unavailable (private mode, quota, etc.) — state stays in-memory only.
    }
  };
  save();
  const tick = (c) => { state[c] = true; save(); const b = document.getElementById("demo-" + c); if (b) b.checked = true; };
  ["C1", "C2", "C3", "C4", "C5"].forEach((c) => {
    const b = document.getElementById("demo-" + c);
    if (!b) return;
    b.checked = !!state[c];
    b.addEventListener("change", () => { state[c] = b.checked; save(); });
  });
  const obs = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting && ["C1", "C3"].includes(e.target.dataset.demo)) tick(e.target.dataset.demo);
  }), { threshold: 0.5 });
  const arm = () => document.querySelectorAll("[data-demo]").forEach((el) => {
    if (el.dataset.demoArmed) return;
    el.dataset.demoArmed = "1";
    obs.observe(el);
    el.addEventListener("click", () => tick(el.dataset.demo));
    el.addEventListener("change", () => tick(el.dataset.demo));
  });
  arm();
  document.body.addEventListener("htmx:afterSwap", arm);
  const clock = document.getElementById("demo-clock");
  setInterval(() => {
    const s = Math.floor((Date.now() - state.t0) / 1000);
    if (clock) clock.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }, 1000);
  // held-back arrivals: `n` releases the next one (POST /demo/release); the queue's poll shows it land
  const held = document.getElementById("demo-held");
  const showHeld = async () => {
    try {
      const r = await fetch("/demo/status", { cache: "no-store" });
      const d = await r.json();
      if (held) held.textContent = "held: " + d.pending.length + (d.pending.length ? " (n to release)" : "");
    } catch (e) { /* server away */ }
  };
  showHeld();
  const release = async () => {
    try {
      await fetch("/demo/release", { method: "POST" });
      if (window.vigilanceQueueRefresh) window.vigilanceQueueRefresh();
    } catch (e) { /* nothing to release */ }
    showHeld();
  };
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "n" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.target.matches("input, select, textarea")) return;
    ev.preventDefault();
    release();
  });
  if (held) held.addEventListener("click", release);
  const reset = document.getElementById("demo-reset");
  if (reset) reset.addEventListener("click", (ev) => {
    ev.preventDefault();
    try {
      sessionStorage.removeItem(KEY);
    } catch (e) {
      // ignore — nothing persisted to clear
    }
    location.reload();
  });
})();
