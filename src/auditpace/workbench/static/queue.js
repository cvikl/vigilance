// Queue interaction: one-click views, whole-row navigation, j/k/Enter, scroll restore, live refresh.
// Server state never lives here — every refresh is a GET /queue with the form's filters.
(function () {
  const form = document.getElementById("queue-filters");
  const table = document.getElementById("queue-table");
  if (!form || !table) return;
  const KEY = "vigilance-queue";
  const store = (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) { /* private mode: no restore */ } };
  const read = (k) => { try { return sessionStorage.getItem(k); } catch (e) { return null; } };

  // --- one-click views: set the form's category + sort, then let htmx refresh the table
  const applyChip = (btn) => {
    form.querySelector('select[name="category"]').value = btn.dataset.category;
    form.querySelector('input[name="sort"]').value = btn.dataset.sort;
    htmx.trigger(form, "change");
    document.querySelectorAll("#tiles .tile").forEach((t) => t.classList.toggle("on", t.dataset.category === btn.dataset.category && btn.dataset.sort !== "excess"));
  };
  document.addEventListener("click", (ev) => {
    const chip = ev.target.closest("button.view, button.tile");
    if (chip) { applyChip(chip); return; }
    const row = ev.target.closest("tr.row");
    if (!row || ev.target.closest("button")) return;
    ev.preventDefault();  // the reason cell's <a> goes through the same path so the return trip is remembered
    open(row);
  });
  // a manual category change leaves 'sort' as it was; 'Longest over target' is only reachable by chip

  // --- rows: open, remember where we were
  const open = (row) => {
    store(KEY + ":url", location.pathname + location.search);
    store(KEY + ":y", String(window.scrollY));
    store(KEY + ":case", row.dataset.case);
    location.href = row.dataset.href;
  };
  const rows = () => Array.from(table.querySelectorAll("tr.row"));
  let focusIdx = -1;
  const focus = (i) => {
    const rs = rows();
    if (!rs.length) return;
    focusIdx = Math.max(0, Math.min(rs.length - 1, i));
    rs.forEach((r, k) => r.classList.toggle("focus", k === focusIdx));
    rs[focusIdx].scrollIntoView({ block: "nearest" });
  };
  document.addEventListener("keydown", (ev) => {
    if (ev.target.matches("input, select, textarea")) return;
    if (ev.key === "j") { focus(focusIdx + 1); ev.preventDefault(); }
    else if (ev.key === "k") { focus(focusIdx - 1); ev.preventDefault(); }
    else if (ev.key === "Enter" && focusIdx >= 0) { const r = rows()[focusIdx]; if (r) open(r); }
  });

  // --- coming back from a case: same scroll, the row after the one just reviewed gets the focus
  const restore = () => {
    const url = read(KEY + ":url");
    if (url !== location.pathname + location.search) return;
    const y = parseInt(read(KEY + ":y") || "0", 10);
    const last = read(KEY + ":case");
    const rs = rows();
    const i = rs.findIndex((r) => r.dataset.case === last);
    if (i >= 0) focus(rs[i].classList.contains("done") ? Math.min(i + 1, rs.length - 1) : i);
    window.scrollTo(0, y);
    store(KEY + ":url", "");
  };
  restore();

  // --- live refresh: poll the version; on change re-run the current filters and show what landed
  let seen = new Set(rows().filter((r) => r.classList.contains("new")).map((r) => r.dataset.case));
  const version = () => (document.getElementById("queue-version") || {}).dataset?.version;
  const announce = () => {
    const fresh = rows().filter((r) => r.classList.contains("new") && !seen.has(r.dataset.case));
    fresh.forEach((r) => { seen.add(r.dataset.case); r.classList.add("landed"); });
    if (fresh.length) fresh[0].scrollIntoView({ block: "center", behavior: "smooth" });
  };
  document.body.addEventListener("htmx:afterSwap", (ev) => { if (ev.target === table) { announce(); focusIdx = -1; } });
  const poll = async () => {
    try {
      const r = await fetch("/queue/version", { cache: "no-store" });
      const v = (await r.json()).version;
      if (v && version() && v !== version()) htmx.trigger(form, "refresh");
    } catch (e) { /* server restarting: try again next tick */ }
  };
  setInterval(poll, 2000);
  window.vigilanceQueueRefresh = () => htmx.trigger(form, "refresh");
})();
