(() => {
  const paths = {
    bylaws: "data/bylaws.json",
    summary: "data/bylaws-summary.json",
    councilItems: "data/council-items.json",
    committeeItems: "data/committee-items.json",
    councilMeetings: "data/council-meetings.json",
    councilDocuments: "data/council-documents.json"
  };

  const text = (id, value) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  };

  const rowsFrom = (payload, property) => {
    if (Array.isArray(payload)) return payload;
    return Array.isArray(payload?.[property]) ? payload[property] : [];
  };

  const normalizeCategory = value => String(value || "") === "Transportation & Parking"
    ? "Transportation"
    : String(value || "");

  const meetingGroup = item => {
    const explicit = String(item?.meeting_group || "").toLowerCase();
    if (["committee", "board", "commission", "panel"].includes(explicit)) return "committee";
    if (["council", "public-hearing"].includes(explicit)) return "council";
    const title = String(item?.meeting_title || item?.title || "").toLowerCase();
    return /committee|board|commission|panel|governance and priorities|finance and audit/.test(title)
      ? "committee"
      : "council";
  };

  const meetingCount = payload => {
    const meetings = rowsFrom(payload, "meetings");
    const identities = new Set();
    for (const meeting of meetings) {
      const identity = String(
        meeting?.id || meeting?.meeting_id || meeting?.url || meeting?.source_url
        || `${meeting?.date || ""}|${meeting?.title || meeting?.name || ""}`
      ).trim().toLowerCase();
      if (identity) identities.add(identity);
    }
    return identities.size;
  };

  const documentCount = payload => {
    const documents = rowsFrom(payload, "documents");
    const identities = new Set();
    for (const document of documents) {
      const identity = String(
        document?.id || document?.document_id || document?.url || document?.source_url
        || document?.pdf_url || document?.local_path || document?.title || JSON.stringify(document)
      ).trim().toLowerCase();
      if (identity) identities.add(identity);
    }
    return identities.size;
  };

  const archivedPdfPaths = (payload, type) => {
    const records = type === "bylaw" ? rowsFrom(payload, "bylaws") : rowsFrom(payload, "documents");
    const fields = type === "bylaw"
      ? ["local_pdf", "pdf_archive_path", "archive_path"]
      : ["local_path", "archive_path", "local_document"];
    const found = new Set();
    for (const record of records) {
      for (const field of fields) {
        const path = String(record?.[field] || "").trim().replace(/\\/g, "/");
        if (/\.pdf(?:$|[?#])/i.test(path)) {
          found.add(path.split(/[?#]/)[0].toLowerCase());
          break;
        }
      }
    }
    return found;
  };

  const fetchJson = async url => {
    const separator = url.includes("?") ? "&" : "?";
    const response = await NanaimoData.fetch(`${url}${separator}ts=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`${url} HTTP ${response.status}`);
    return response.json();
  };

  const setUnavailable = ids => ids.forEach(id => text(id, "—"));

  async function loadDataSummary() {
    const entries = Object.entries(paths);
    const results = await Promise.allSettled(entries.map(([, url]) => fetchJson(url)));
    const data = Object.fromEntries(entries.map(([key], index) => [
      key,
      results[index].status === "fulfilled" ? results[index].value : null
    ]));

    const bylaws = rowsFrom(data.bylaws, "bylaws");
    if (data.bylaws) {
      const categories = new Set(bylaws.map(row => normalizeCategory(row?.category)).filter(Boolean));
      const years = new Set(bylaws.map(row => String(row?.year || "")).filter(year => /^\d{4}$/.test(year)));
      const total = bylaws.length.toLocaleString();
      text("data-total", total);
      text("data-categories", categories.size.toLocaleString());
      text("data-years", years.size.toLocaleString());
      text("stat-online", total);
      text("stat-connected", total);
      const connectedNote = document.querySelector("#stat-connected")?.parentElement?.querySelector("small");
      if (connectedNote) connectedNote.textContent = `${total} records connected`;
    } else {
      setUnavailable(["data-total", "data-categories", "data-years", "stat-online", "stat-connected"]);
    }

    const fallbackAmended = bylaws.filter(row => row?.legal_status === "Amendment bylaw" || row?.relationships?.amends?.length).length;
    const fallbackRepealed = bylaws.filter(row => ["Repealed", "Replaced"].includes(row?.legal_status)
      || row?.relationships?.repealed_by?.length || row?.relationships?.replaced_by?.length).length;
    const amended = data.summary ? Number(data.summary.amendment_bylaw_count) : Number.NaN;
    const repealed = data.summary ? Number(data.summary.repealed_or_replaced_count) : Number.NaN;
    text("stat-amended", (Number.isFinite(amended) ? amended : fallbackAmended).toLocaleString());
    text("stat-repealed", (Number.isFinite(repealed) ? repealed : fallbackRepealed).toLocaleString());

    const allCouncilItems = rowsFrom(data.councilItems, "items");
    const dedicatedCommitteeItems = data.committeeItems ? rowsFrom(data.committeeItems, "items") : null;
    const councilItems = allCouncilItems.filter(item => meetingGroup(item) === "council");
    const committeeItems = dedicatedCommitteeItems || allCouncilItems.filter(item => meetingGroup(item) === "committee");
    text("stat-council-items", data.councilItems ? councilItems.length.toLocaleString() : "—");
    text("stat-committee-items", (data.committeeItems || data.councilItems) ? committeeItems.length.toLocaleString() : "—");

    const meetings = data.councilMeetings ? meetingCount(data.councilMeetings) : null;
    const documents = data.councilDocuments ? documentCount(data.councilDocuments) : null;
    text("stat-council-meetings", meetings === null ? "—" : meetings.toLocaleString());
    text("data-council-documents", documents === null ? "—" : documents.toLocaleString());

    const archived = new Set();
    if (data.bylaws) archivedPdfPaths(data.bylaws, "bylaw").forEach(path => archived.add(path));
    if (data.councilDocuments) archivedPdfPaths(data.councilDocuments, "council").forEach(path => archived.add(path));
    text("stat-archived-pdfs", archived.size ? archived.size.toLocaleString() : "—");

    const status = document.getElementById("data-status");
    if (status) {
      const loaded = results.filter(result => result.status === "fulfilled").length;
      if (!data.bylaws) {
        status.textContent = `The main bylaw dataset is unavailable. ${loaded} of ${results.length} supporting datasets loaded.`;
      } else {
        const details = [
          `${bylaws.length.toLocaleString()} bylaw records`,
          documents === null ? null : `${documents.toLocaleString()} Council documents`,
          data.councilItems ? `${councilItems.length.toLocaleString()} Council items` : null,
          (data.committeeItems || data.councilItems) ? `${committeeItems.length.toLocaleString()} committee items` : null,
          meetings === null ? null : `${meetings.toLocaleString()} Council meetings`,
          archived.size ? `${archived.size.toLocaleString()} recorded archived PDFs` : null
        ].filter(Boolean);
        status.textContent = `Loaded ${details.join(", ")}.`;
      }
    }

    results.forEach((result, index) => {
      if (result.status === "rejected") console.warn(`[NBT] ${entries[index][0]} unavailable`, result.reason);
    });
  }

  async function runtimeFileAvailable(url) {
    try {
      let response = await NanaimoData.fetch(url, { method: "HEAD", cache: "no-store" });
      if (response.status === 405 || response.status === 501) {
        response = await NanaimoData.fetch(url, { cache: "no-store", headers: { Range: "bytes=0-0" } });
      }
      return response.ok || response.status === 206;
    } catch (_error) {
      return false;
    }
  }

  async function verifyRuntimeLinks() {
    const links = [...document.querySelectorAll("[data-runtime-file]")];
    await Promise.all(links.map(async link => {
      const href = link.getAttribute("href");
      if (!href || await runtimeFileAvailable(href)) return;
      link.classList.add("runtime-file-unavailable");
      link.setAttribute("aria-disabled", "true");
      link.removeAttribute("href");
      link.title = "This runtime file is not included in deployment releases and is not currently available on this server.";
      const note = document.createElement("small");
      note.textContent = "Not currently available";
      link.append(note);
    }));
  }

  loadDataSummary().catch(error => {
    console.error("[NBT] Data summary failed", error);
    setUnavailable([
      "data-total", "data-categories", "data-years", "data-council-documents", "stat-online",
      "stat-connected", "stat-amended", "stat-repealed", "stat-council-items", "stat-committee-items",
      "stat-council-meetings", "stat-archived-pdfs"
    ]);
    text("data-status", "The current dataset summary could not be loaded.");
  });
  verifyRuntimeLinks();
})();
