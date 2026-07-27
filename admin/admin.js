const ALLOWED_ADMIN_EMAIL = "yardplots@gmail.com";
const accessPanel = document.getElementById("admin-access-panel");
const accessMessage = document.getElementById("admin-access-message");
const loginButton = document.getElementById("admin-login");
const content = document.getElementById("admin-content");
const signOutButton = document.getElementById("admin-sign-out");
const refreshButton = document.getElementById("admin-refresh");
const copyStatus = document.getElementById("admin-copy-status");
const toast = document.getElementById("admin-toast");
let accessCheckId = 0;
let dashboardLoaded = false;

const DATASETS = [
  { key: "bylaws", label: "Bylaws", url: "data/bylaws.json", required: true, extract: payload => rowsFrom(payload, "bylaws") },
  { key: "change-log", label: "Bylaw change log", url: "data/change-log.json", required: false },
  { key: "council-meetings", label: "Council meetings", url: "data/council-meetings.json", required: true, extract: payload => rowsFrom(payload, "meetings") },
  { key: "council-documents", label: "Council documents", url: "data/council-documents.json", required: true, extract: payload => rowsFrom(payload, "documents") },
  { key: "council-items", label: "Council items", url: "data/council-items.json", required: true, extract: payload => rowsFrom(payload, "items") },
  { key: "committee-items", label: "Committee items", url: "data/committee-items.json", required: true, extract: payload => rowsFrom(payload, "items") },
  { key: "council-verification", label: "Council verification", url: "data/council-verification.json", required: false },
  { key: "collection-status", label: "Cloud collection status", url: "collection-status.json", required: false }
];

const ARCHIVE_DATASET = {
  key: "archive",
  label: NanaimoData.status().enabled ? "Cloud archive" : "Archive folder",
  url: "archive/",
  required: false,
  json: false
};

function normalizedEmail(user) {
  return String(user?.email || "").trim().toLowerCase();
}

function rowsFrom(payload, property) {
  if (Array.isArray(payload)) return payload;
  return Array.isArray(payload?.[property]) ? payload[property] : [];
}


function normalizedRecordPath(value) {
  const raw = String(value || "").trim().replace(/\\/g, "/").split(/[?#]/)[0];
  if (!raw || /^https?:\/\//i.test(raw) || !/\.pdf$/i.test(raw)) return "";
  const clean = raw.replace(/^\.\//, "").replace(/^\.\.\//, "").replace(/^\/+/, "");
  return clean.toLowerCase().includes("archive/") ? clean : "";
}

function archiveCandidates(results) {
  const candidates = new Set();
  const fieldMap = {
    bylaws: ["local_pdf", "pdf_archive_path", "archive_path"],
    "council-documents": ["local_path", "archive_path", "local_document"],
    "committee-items": ["local_document", "archive_path", "local_path"]
  };
  for (const result of results) {
    const fields = fieldMap[result.key];
    if (!fields || !Array.isArray(result.rows)) continue;
    for (const record of result.rows) {
      for (const field of fields) {
        const path = normalizedRecordPath(record?.[field]);
        if (path) {
          candidates.add(path);
          break;
        }
      }
    }
  }
  return [...candidates];
}

async function inspectArchive(results) {
  const candidates = archiveCandidates(results);
  for (const path of candidates.slice(0, 12)) {
    try {
      const separator = path.includes("?") ? "&" : "?";
      const checkPath = `${path}${separator}admin_check=${Date.now()}`;
      let response = await NanaimoData.fetch(checkPath, { method: "HEAD", cache: "no-store" });
      if (response.status === 405 || response.status === 501) {
        response = await NanaimoData.fetch(checkPath, {
          cache: "no-store",
          headers: { Range: "bytes=0-0" }
        });
      }
      if (response.ok || response.status === 206) {
        return {
          ...ARCHIVE_DATASET,
          available: true,
          protected: true,
          verifiedRecordedFile: true,
          payload: null,
          rows: null,
          modified: response.headers.get("last-modified"),
          size: response.headers.get("content-length"),
          error: "Archive files may be accessed through their recorded links. A recorded archived PDF was verified without listing the folder."
        };
      }
    } catch (_error) {
      // Try another recorded archive path.
    }
  }
  return {
    ...ARCHIVE_DATASET,
    available: false,
    protected: false,
    payload: null,
    rows: null,
    error: candidates.length
      ? "Protected / directory listing disabled. The recorded archived PDFs checked by this page were not reachable."
      : "Protected / directory listing disabled. No recorded archive PDF was available to verify."
  };
}

function bylawSummaryStatus(record) {
  const legalStatus = String(record?.legal_status || "").trim().toLowerCase();
  const relationships = record?.relationships || {};
  if (["repealed", "replaced", "repealing bylaw", "replacement bylaw"].includes(legalStatus)
      || relationships.repealed_by?.length || relationships.replaced_by?.length) return "repealed";
  if (legalStatus === "consolidated" || relationships.consolidates?.length) return "consolidated";
  if (legalStatus === "amendment bylaw" || relationships.amends?.length) return "amended";
  return "published";
}

function distinctCount(rows, fields) {
  const values = new Set();
  for (const row of rows) {
    const value = fields.map(field => row?.[field]).find(Boolean);
    if (value) values.add(String(value).trim().toLowerCase());
  }
  return values.size;
}

function recordedPdfCount(results) {
  const paths = new Set();
  const fieldMap = {
    bylaws: ["local_pdf", "pdf_archive_path", "archive_path"],
    "council-documents": ["local_path", "archive_path", "local_document"],
    "committee-items": ["local_document", "archive_path", "local_path"]
  };
  for (const result of results) {
    const fields = fieldMap[result.key];
    if (!fields || !Array.isArray(result.rows)) continue;
    for (const row of result.rows) {
      const value = fields.map(field => row?.[field]).find(path => /\.pdf(?:$|[?#])/i.test(String(path || "")));
      if (value) paths.add(String(value).trim().replace(/\\/g, "/").split(/[?#]/)[0].toLowerCase());
    }
  }
  return paths.size;
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return "Size unavailable";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 ** 2)).toFixed(1)} MB`;
}

function formatDate(value) {
  if (!value) return "Modified time unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Modified time unavailable";
  return `Modified ${new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Vancouver"
  }).format(date)}`;
}

function showToast(message) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2200);
}

async function fetchDataset(dataset) {
  const response = await NanaimoData.fetch(`${dataset.url}?ts=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) {
    if (dataset.key === "archive" && response.status === 403) {
      return {
        ...dataset,
        available: true,
        protected: true,
        payload: null,
        rows: null,
        modified: response.headers.get("last-modified"),
        size: response.headers.get("content-length"),
        error: "HTTP 403 · Directory listing is disabled; recorded archive file links can still be served."
      };
    }
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = dataset.json === false ? null : await response.json();
  return {
    ...dataset,
    available: true,
    payload,
    rows: dataset.extract ? dataset.extract(payload) : null,
    modified: response.headers.get("last-modified"),
    size: response.headers.get("content-length")
  };
}

function renderHealth(results) {
  const healthList = document.getElementById("admin-file-health");
  const healthCount = document.getElementById("admin-health-count");
  const available = results.filter(result => result.available).length;
  const requiredMissing = results.filter(result => result.required && !result.available);
  healthCount.textContent = `${available}/${results.length}`;
  healthList.innerHTML = results.map(result => {
    const statusClass = result.protected ? "protected" : (result.available ? "available" : (result.required ? "missing" : "optional"));
    const statusText = result.protected ? "Protected / directory listing disabled" : (result.available ? "Available" : (result.required ? "Missing" : "Unavailable"));
    const meta = result.protected
      ? result.error
      : (result.available ? `${formatDate(result.modified)} · ${formatBytes(result.size)}` : (result.error || "File could not be loaded"));
    return `<article class="admin-health-row">
      <span class="admin-health-indicator ${statusClass}" aria-hidden="true"></span>
      <div><strong>${result.label}</strong><small>${meta}</small></div>
      <span class="admin-health-status ${statusClass}">${statusText}</span>
    </article>`;
  }).join("");

  const overallDot = document.getElementById("admin-overall-dot");
  const overallStatus = document.getElementById("admin-overall-status");
  overallDot.className = `admin-status-dot ${requiredMissing.length ? "warning" : "healthy"}`;
  overallStatus.textContent = requiredMissing.length
    ? `${requiredMissing.length} required dataset${requiredMissing.length === 1 ? "" : "s"} unavailable`
    : "Required runtime datasets are available";
}

function updateSummary(results) {
  const bylawResult = results.find(result => result.key === "bylaws" && result.available);
  const councilMeetings = results.find(result => result.key === "council-meetings" && result.available)?.rows || [];
  const councilDocuments = results.find(result => result.key === "council-documents" && result.available)?.rows || [];
  const councilItems = results.find(result => result.key === "council-items" && result.available)?.rows || [];
  const committeeItems = results.find(result => result.key === "committee-items" && result.available)?.rows || [];
  const archiveResult = results.find(result => result.key === "archive");
  const collectionStatus = results.find(result => result.key === "collection-status" && result.available)?.payload || null;
  const rows = bylawResult?.rows || [];
  const categories = new Set(rows.map(row => row.category).filter(Boolean));
  const years = [...new Set(rows.map(row => Number(row.year)).filter(year => Number.isInteger(year) && year > 1800))].sort((a, b) => a - b);
  const civicRecordCount = councilDocuments.length + committeeItems.length;
  const statusCounts = { published: 0, amended: 0, consolidated: 0, repealed: 0 };
  for (const row of rows) statusCounts[bylawSummaryStatus(row)] += 1;
  const committeeGroups = distinctCount(committeeItems, ["committee_name", "committee", "meeting_title", "group_name"]);
  const pdfCount = recordedPdfCount(results);

  document.getElementById("data-total").textContent = bylawResult ? rows.length.toLocaleString() : "—";
  document.getElementById("data-categories").textContent = bylawResult ? categories.size.toLocaleString() : "—";
  document.getElementById("data-years").textContent = years.length ? years.length.toLocaleString() : "—";
  document.getElementById("data-year-range").textContent = years.length
    ? (years.length === 1 ? String(years[0]) : `${years[0]}–${years[years.length - 1]}`)
    : "Distinct years found";
  document.getElementById("data-civic-records").textContent = civicRecordCount.toLocaleString();
  document.getElementById("data-published").textContent = bylawResult ? statusCounts.published.toLocaleString() : "—";
  document.getElementById("data-amended").textContent = bylawResult ? statusCounts.amended.toLocaleString() : "—";
  document.getElementById("data-consolidated").textContent = bylawResult ? statusCounts.consolidated.toLocaleString() : "—";
  document.getElementById("data-repealed").textContent = bylawResult ? statusCounts.repealed.toLocaleString() : "—";

  const status = document.getElementById("data-status");
  if (bylawResult) {
    const yearLabel = years.length
      ? (years.length === 1 ? String(years[0]) : `${years[0]}–${years[years.length - 1]}`)
      : "year range unavailable";
    const archiveLabel = archiveResult?.verifiedRecordedFile
      ? "The archive check verified a recorded PDF"
      : "The archive check did not verify a recorded PDF";
    const storage = NanaimoData.status();
    const storageLabel = storage.enabled
      ? `Cloud data is active at ${storage.baseUrl}`
      : "Local runtime data mode is active";
    const collectionLabel = collectionStatus?.generatedAt
      ? `Latest cloud publish: ${formatDate(collectionStatus.generatedAt).replace(/^Modified /, "")}`
      : "Cloud publish time unavailable";
    status.textContent = `Loaded ${rows.length.toLocaleString()} bylaws across ${categories.size.toLocaleString()} categories and ${years.length.toLocaleString()} years (${yearLabel}): ${statusCounts.published.toLocaleString()} published, ${statusCounts.amended.toLocaleString()} amended, ${statusCounts.consolidated.toLocaleString()} consolidated, and ${statusCounts.repealed.toLocaleString()} repealed or replaced. Civic data includes ${councilMeetings.length.toLocaleString()} Council meetings, ${councilDocuments.length.toLocaleString()} Council documents, ${councilItems.length.toLocaleString()} Council items, and ${committeeItems.length.toLocaleString()} committee items across ${committeeGroups.toLocaleString()} groups. ${pdfCount.toLocaleString()} unique PDF paths are recorded. ${archiveLabel}. ${storageLabel}. ${collectionLabel}.`;
  } else {
    status.textContent = "The primary bylaw dataset could not be loaded. Review the missing-file status above before using public counts.";
  }
}

function updateRuntimeLinks(results) {
  const resultMap = new Map();
  for (const result of results) {
    resultMap.set(result.key, result);
    if (result.url) resultMap.set(result.url, result);
  }
  document.querySelectorAll("[data-runtime-file]").forEach(link => {
    const result = resultMap.get(link.dataset.runtimeFile);
    if (!result) return;
    const usable = result.available && !result.protected;
    link.classList.toggle("runtime-file-unavailable", !usable);
    link.classList.toggle("runtime-file-protected", Boolean(result.protected));
    link.setAttribute("aria-disabled", usable ? "false" : "true");
    if (!usable) {
      link.dataset.savedHref ||= link.getAttribute("href") || "";
      link.removeAttribute("href");
      link.title = result.protected
        ? "Protected / directory listing disabled. Archive files may be accessed through their recorded links."
        : "This runtime file is not currently available on this server.";
      let note = link.querySelector("small.admin-unavailable-note");
      if (!note) {
        note = document.createElement("small");
        note.className = "admin-unavailable-note";
        link.append(note);
      }
      note.textContent = result.protected
        ? "Archive files may be accessed through their recorded links."
        : "Not currently available";
    } else if (!link.getAttribute("href") && link.dataset.savedHref) {
      link.setAttribute("href", NanaimoData.url(link.dataset.runtimeFile) || link.dataset.savedHref);
      link.removeAttribute("aria-disabled");
      link.removeAttribute("title");
      link.querySelector("small.admin-unavailable-note")?.remove();
    }
  });
}

async function loadDashboard({ announce = false } = {}) {
  refreshButton.disabled = true;
  refreshButton.textContent = "Refreshing…";
  document.getElementById("admin-overall-dot").className = "admin-status-dot checking";
  document.getElementById("admin-overall-status").textContent = "Checking runtime datasets…";

  const settled = await Promise.allSettled(DATASETS.map(fetchDataset));
  const results = settled.map((result, index) => result.status === "fulfilled"
    ? result.value
    : { ...DATASETS[index], available: false, error: result.reason?.message || "Load failed" });
  results.push(await inspectArchive(results));

  renderHealth(results);
  updateSummary(results);
  updateRuntimeLinks(results);
  document.getElementById("admin-last-checked").textContent = `Checked ${new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "America/Vancouver"
  }).format(new Date())}`;
  refreshButton.disabled = false;
  refreshButton.textContent = "Refresh";
  dashboardLoaded = true;
  if (announce) showToast("Admin data refreshed");
}

function showDenied(user, configured = true) {
  content.hidden = true;
  accessPanel.hidden = false;
  loginButton.hidden = !configured;
  if (!configured) {
    accessMessage.textContent = "Firebase configuration is incomplete. Return to the homepage or add the deployment Firebase configuration before using admin access.";
    return;
  }
  accessMessage.textContent = user
    ? `This Google account is not authorized. Sign in as ${ALLOWED_ADMIN_EMAIL} or return to the homepage.`
    : "Sign in with the authorized Google account to open this dashboard.";
}

async function getAccountApi() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (window.NBTAccount) return window.NBTAccount;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error("Account services did not load.");
}

async function checkAccess() {
  const checkId = ++accessCheckId;
  try {
    const account = await getAccountApi();
    await account.ready;
    if (checkId !== accessCheckId) return;
    const user = account.user;
    if (!account.configured || normalizedEmail(user) !== ALLOWED_ADMIN_EMAIL) {
      showDenied(user, account.configured);
      return;
    }

    accessPanel.hidden = true;
    content.hidden = false;
    document.getElementById("admin-user-name").textContent = user.displayName || "Authorized administrator";
    document.getElementById("admin-user-email").textContent = user.email || ALLOWED_ADMIN_EMAIL;
    if (!dashboardLoaded) await loadDashboard();
  } catch (error) {
    showDenied(null, false);
    accessMessage.textContent = error.message || "Admin access could not be checked.";
  }
}

async function copyCommand(command, button) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(command);
    } else {
      const input = document.createElement("textarea");
      input.value = command;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.append(input);
      input.select();
      if (!document.execCommand("copy")) throw new Error("Copy failed");
      input.remove();
    }
    const original = button.textContent;
    button.textContent = "Copied";
    copyStatus.textContent = `Copied: ${command}`;
    showToast("Command copied");
    window.setTimeout(() => { button.textContent = original; }, 1500);
  } catch (_error) {
    copyStatus.textContent = "The command could not be copied automatically. Select the command text and copy it manually.";
  }
}

loginButton.addEventListener("click", async () => {
  loginButton.disabled = true;
  accessMessage.textContent = "Opening Google sign-in…";
  try {
    const account = await getAccountApi();
    await account.signInGoogle();
    await checkAccess();
  } catch (error) {
    const account = window.NBTAccount;
    accessMessage.textContent = account?.friendlyAuthError(error) || error.message || "Google sign-in was cancelled.";
  } finally {
    loginButton.disabled = false;
  }
});

signOutButton.addEventListener("click", async () => {
  signOutButton.disabled = true;
  try {
    const account = await getAccountApi();
    await account.signOut();
    dashboardLoaded = false;
    showDenied(null, account.configured);
  } catch (error) {
    showToast(error.message || "Sign out failed");
  } finally {
    signOutButton.disabled = false;
  }
});

refreshButton.addEventListener("click", () => loadDashboard({ announce: true }));
document.addEventListener("click", event => {
  const button = event.target.closest("[data-copy-command]");
  if (button) copyCommand(button.dataset.copyCommand, button);
});
window.addEventListener("nbt-auth-change", checkAccess);
checkAccess();
