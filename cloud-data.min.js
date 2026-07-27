(() => {
  "use strict";

  const rawConfig = window.NANAIMO_CLOUD_CONFIG || {};
  const configuredBase = String(rawConfig.baseUrl || "").trim().replace(/\/+$/, "");
  const enabled = Boolean(rawConfig.enabled)
    && /^https:\/\/[a-z0-9.-]+(?:\.workers\.dev|\.pages\.dev|\.[a-z0-9.-]+)$/i.test(configuredBase)
    && !configuredBase.includes("REPLACE-WITH");
  const localFallback = rawConfig.localFallback !== false;

  function rootPrefix() {
    const host = document.querySelector("[data-shared-header][data-root], [data-shared-footer][data-root]");
    const root = host?.dataset?.root || ".";
    return root === "." ? "" : `${root.replace(/\/$/, "")}/`;
  }

  function normalizePath(value) {
    const raw = String(value || "").trim().replace(/\\/g, "/");
    if (!raw || /[\u0000-\u001f]/.test(raw)) return "";
    try {
      const parsed = new URL(raw);
      if (["http:", "https:"].includes(parsed.protocol)) return parsed.href;
    } catch (_error) {}

    const [path, suffix = ""] = raw.split(/(?=[?#])/u, 2);
    let clean = path.replace(/^\/+/, "").replace(/^\.\//, "");
    while (clean.startsWith("../")) clean = clean.slice(3);
    if (!clean || clean.split("/").includes("..")) return "";
    return `${clean}${suffix}`;
  }

  function objectKey(value) {
    const normalized = normalizePath(value);
    if (!normalized || /^https?:/i.test(normalized)) return "";
    return normalized.replace(/[?#].*$/, "");
  }

  function isCloudPath(value) {
    const key = objectKey(value);
    if (!key) return false;
    if (["collection-status.json", "archive-manifest.json"].includes(key)) return true;
    if (/^(?:data|archive|text|bylaws\/pdf)\//i.test(key)) return true;
    if (/^council\//i.test(key) && !/^council\/(?:index\.html|list\.js)$/i.test(key)) return true;
    return false;
  }

  function localUrl(value) {
    const normalized = normalizePath(value);
    if (!normalized) return "";
    if (/^https?:/i.test(normalized)) return normalized;
    return `${rootPrefix()}${normalized}`;
  }

  function url(value) {
    const normalized = normalizePath(value);
    if (!normalized) return "";
    if (/^https?:/i.test(normalized)) return normalized;
    if (enabled && isCloudPath(normalized)) return `${configuredBase}/${normalized}`;
    return localUrl(normalized);
  }

  function isCloudUrl(value) {
    if (!enabled) return false;
    try {
      const target = new URL(String(value || ""), location.href);
      return target.origin === new URL(configuredBase).origin;
    } catch (_error) {
      return false;
    }
  }

  async function fetchRuntime(value, init = {}) {
    const primaryUrl = url(value);
    if (!primaryUrl) throw new TypeError("Invalid Nanaimo runtime path");

    let primaryResponse;
    try {
      primaryResponse = await window.fetch(primaryUrl, init);
      if (primaryResponse.ok || !enabled || !localFallback || !isCloudUrl(primaryUrl)) {
        return primaryResponse;
      }
    } catch (error) {
      if (!enabled || !localFallback || !isCloudUrl(primaryUrl)) throw error;
    }

    const fallbackUrl = localUrl(value);
    if (!fallbackUrl || fallbackUrl === primaryUrl) return primaryResponse;
    return window.fetch(fallbackUrl, init);
  }

  function asset(value) {
    return url(value);
  }

  function status() {
    return {
      enabled,
      baseUrl: enabled ? configuredBase : "",
      localFallback,
      mode: enabled ? "cloud" : "local"
    };
  }

  function rewriteRuntimeLinks(root = document) {
    for (const link of root.querySelectorAll("[data-runtime-file]")) {
      let logical = String(link.dataset.runtimeFile || "").trim();
      if (!logical || !/[./]/.test(logical)) {
        logical = String(link.getAttribute("href") || "").trim();
      }
      logical = normalizePath(logical);
      if (!logical) continue;
      if (!logical.includes("/") && /\.json(?:$|[?#])/i.test(logical)) logical = `data/${logical}`;
      const resolved = url(logical);
      if (resolved) link.setAttribute("href", resolved);
    }
  }

  window.NanaimoData = Object.freeze({
    asset,
    baseUrl: enabled ? configuredBase : "",
    fetch: fetchRuntime,
    isCloudPath,
    isCloudUrl,
    localUrl,
    normalizePath,
    rewriteRuntimeLinks,
    status,
    url
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => rewriteRuntimeLinks(), { once: true });
  } else {
    rewriteRuntimeLinks();
  }
})();
