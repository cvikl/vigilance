// Case page: return to the queue exactly where the reviewer left it (filters + scroll), Esc to go back,
// and after a saved review go back automatically so the queue shows the row ticked in place.
(function () {
  const KEY = "vigilance-queue";
  const read = (k) => { try { return sessionStorage.getItem(k); } catch (e) { return null; } };
  const store = (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) { /* no restore */ } };
  const back = document.getElementById("back-to-queue");
  const url = read(KEY + ":url");
  if (back && url) back.href = url;
  const goBack = () => { location.href = (back && back.href) || "/queue"; };  // back.href keeps ?demo=1 when no stored url
  // big view of the page: the document section fills the window; Esc closes it before it leaves the case
  const expand = document.getElementById("expand-page");
  const setBig = (on) => {
    document.body.classList.toggle("page-big", on);
    if (expand) expand.setAttribute("aria-pressed", on ? "true" : "false");
  };
  if (expand) expand.addEventListener("click", () => setBig(!document.body.classList.contains("page-big")));
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape" || ev.target.matches("input, select, textarea")) return;
    if (document.body.classList.contains("page-big")) { setBig(false); return; }
    goBack();
  });
  // the document tabs follow whichever page is showing, whether chosen from a tab or from "show on page"
  document.body.addEventListener("htmx:afterSwap", (ev) => {
    if (ev.target.id !== "pageview") return;
    const shown = ev.target.querySelector(".pageview")?.dataset.pageId;
    document.querySelectorAll(".doctab").forEach((t) => t.classList.toggle("on", t.dataset.page === shown));
  });
  document.body.addEventListener("htmx:afterSwap", (ev) => {
    if (ev.target.id !== "review-panel" || !ev.target.querySelector("p.ok")) return;
    const caseId = ev.target.querySelector('input[name="case_id"]')?.value;
    if (caseId) store(KEY + ":case", caseId);
    setTimeout(goBack, 700);
  });
})();
