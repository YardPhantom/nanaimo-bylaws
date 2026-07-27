(() => {
  "use strict";

  const rowsFrom = (payload, key) => Array.isArray(payload)
    ? payload
    : (Array.isArray(payload?.[key]) ? payload[key] : []);

  async function loadAboutDataSummary() {
    try {
      const [bylawResponse, councilResponse] = await Promise.all([
        NanaimoData.fetch(`data/bylaws.json?ts=${Date.now()}`, { cache: "no-store" }),
        NanaimoData.fetch(`data/council-documents.json?ts=${Date.now()}`, { cache: "no-store" })
      ]);
      if (!bylawResponse.ok) throw new Error(`Bylaw data HTTP ${bylawResponse.status}`);

      const rows = rowsFrom(await bylawResponse.json(), "bylaws");
      const categories = new Set(rows.map(item => item?.category).filter(Boolean));
      const years = new Set(rows.map(item => String(item?.year || "")).filter(year => /^\d{4}$/.test(year)));
      document.getElementById("data-total").textContent = rows.length.toLocaleString();
      document.getElementById("data-categories").textContent = categories.size.toLocaleString();
      document.getElementById("data-years").textContent = years.size.toLocaleString();

      let documentCount = 0;
      if (councilResponse.ok) {
        documentCount = rowsFrom(await councilResponse.json(), "documents").length;
      }
      document.getElementById("data-council-documents").textContent = documentCount.toLocaleString();
    } catch (error) {
      console.warn("[NBT] About data summary unavailable", error);
      for (const id of ["data-total", "data-categories", "data-years", "data-council-documents"]) {
        const node = document.getElementById(id);
        if (node) node.textContent = "—";
      }
    }
  }

  async function verifyAboutRuntimeLinks() {
    NanaimoData.rewriteRuntimeLinks();
    for (const link of document.querySelectorAll("[data-runtime-file]")) {
      const key = link.dataset.runtimeFile;
      try {
        const response = await NanaimoData.fetch(key, { method: "HEAD", cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      } catch (_error) {
        link.classList.add("runtime-file-unavailable");
        link.setAttribute("aria-disabled", "true");
        link.removeAttribute("href");
        link.title = "This runtime file is not currently available from cloud or local storage.";
      }
    }
  }

  loadAboutDataSummary();
  verifyAboutRuntimeLinks();
})();
