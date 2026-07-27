const params = new URLSearchParams(location.search);
const rawFile = String(params.get("file") || "").trim().replace(/\\/g, "/").replace(/^\.\//, "");
const number = String(params.get("number") || "").trim();
const suppliedTitle = String(params.get("title") || "").trim();
const context = String(params.get("context") || "Archived source document").trim();
const titleNode = document.querySelector("#pdf-title");
const contextNode = document.querySelector("#pdf-context");
const statusNode = document.querySelector("#pdf-status");
const browser = document.querySelector("#pdf-browser");
const download = document.querySelector("#pdf-download");
const returnLink = document.querySelector("#pdf-return");
const star = document.querySelector("#pdf-watch-star");
const zoomLabel = document.querySelector("#pdf-zoom-label");
let zoom = 100;
let resolvedFile = "";

function isSafePdf(path) {
  if (!path || /[\u0000-\u001f]/.test(path)) return false;
  try {
    const parsed = new URL(path);
    return ["http:", "https:"].includes(parsed.protocol)
      && NanaimoData.isCloudUrl(parsed.href)
      && /\.pdf$/i.test(parsed.pathname);
  } catch (_error) {}

  if (path.includes("..") || path.startsWith("/") || /^[a-z][a-z0-9+.-]*:/i.test(path)) return false;
  if (!/\.pdf$/i.test(path.split(/[?#]/)[0])) return false;
  return /^(?:council\/|bylaws\/pdf\/|archive\/)/i.test(path);
}

function pdfUrl(mode = "zoom") {
  const fragment = mode === "fit" ? "#view=FitH" : `#zoom=${zoom}`;
  return `${resolvedFile}${fragment}`;
}

function loadPdf(mode = "zoom") {
  browser.src = pdfUrl(mode);
  zoomLabel.textContent = mode === "fit" ? "Fit" : `${zoom}%`;
}

function updateStar() {
  if (!number || !window.BylawWatchlist) {
    star.hidden = true;
    return;
  }
  const active = window.BylawWatchlist.has(number);
  star.hidden = false;
  star.classList.toggle("active", active);
  star.textContent = active ? "★" : "☆";
  star.setAttribute("aria-pressed", String(active));
  star.setAttribute("aria-label", `${active ? "Remove" : "Add"} Bylaw ${number} ${active ? "from" : "to"} watchlist`);
  star.title = `${active ? "Remove from" : "Add to"} watchlist`;
}

returnLink.addEventListener("click", event => {
  event.preventDefault();
  if (history.length > 1) history.back();
  else location.href = number ? `bylaws/detail.html?number=${encodeURIComponent(number)}` : "council/index.html";
});

if (!isSafePdf(rawFile)) {
  titleNode.textContent = "PDF unavailable";
  contextNode.textContent = "Invalid archived document path";
  statusNode.textContent = "This viewer accepts only approved local or configured cloud archive PDFs.";
  browser.hidden = true;
  document.querySelector(".pdf-viewer-actions").hidden = true;
} else {
  resolvedFile = /^https?:/i.test(rawFile) ? rawFile : NanaimoData.asset(rawFile);
  const fallback = rawFile.split("/").pop().replace(/\.pdf$/i, "").replace(/[-_]+/g, " ");
  titleNode.textContent = suppliedTitle || fallback || "Archived PDF";
  contextNode.textContent = number ? `Bylaw ${number} · ${context}` : context;
  document.title = `${titleNode.textContent} | Nanaimo Bylaw Tracker`;
  download.href = resolvedFile;
  statusNode.textContent = NanaimoData.isCloudUrl(resolvedFile)
    ? "This archived document is streamed securely from cloud storage. Use Back to return without losing filters or results."
    : "The document remains inside Nanaimo Bylaw Tracker. Use Back to return without losing filters or results.";
  loadPdf();
}

document.querySelector("#pdf-zoom-in").addEventListener("click", () => { zoom = Math.min(300, zoom + 25); loadPdf(); });
document.querySelector("#pdf-zoom-out").addEventListener("click", () => { zoom = Math.max(25, zoom - 25); loadPdf(); });
document.querySelector("#pdf-fit").addEventListener("click", () => loadPdf("fit"));
document.querySelector("#pdf-print").addEventListener("click", () => {
  try { browser.contentWindow.focus(); browser.contentWindow.print(); }
  catch (_error) { window.open(resolvedFile, "_blank", "noopener"); }
});
star.addEventListener("click", () => { window.BylawWatchlist?.toggle(number); updateStar(); });
window.addEventListener("bylaw-watchlist-change", updateStar);
updateStar();
