const PUBLIC_KEYS = new Set(["collection-status.json", "archive-manifest.json"]);
const PUBLIC_PREFIXES = ["data/", "archive/", "bylaws/pdf/", "council/", "text/"];

function allowedKey(key) {
  if (!key || key.endsWith("/") || key.includes("..") || /[\u0000-\u001f]/.test(key)) return false;
  return PUBLIC_KEYS.has(key) || PUBLIC_PREFIXES.some(prefix => key.startsWith(prefix));
}

function corsHeaders(request, env) {
  const configured = String(env.ALLOWED_ORIGINS || "*").split(",").map(value => value.trim()).filter(Boolean);
  const origin = request.headers.get("Origin") || "";
  const allowOrigin = configured.includes("*") ? "*" : (configured.includes(origin) ? origin : "null");
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range, If-Match, If-None-Match, If-Modified-Since, If-Unmodified-Since",
    "Access-Control-Expose-Headers": "Accept-Ranges, Cache-Control, Content-Length, Content-Range, Content-Type, ETag, Last-Modified",
    "Access-Control-Max-Age": "86400",
    "Vary": configured.includes("*") ? "Accept-Encoding" : "Origin, Accept-Encoding"
  };
}

function cacheControl(key) {
  if (key === "collection-status.json") return "public, max-age=30, s-maxage=60, must-revalidate";
  if (key.startsWith("data/")) return "public, max-age=60, s-maxage=300, must-revalidate";
  if (/\.(?:pdf|txt)$/i.test(key)) return "public, max-age=3600, s-maxage=86400";
  return "public, max-age=300, s-maxage=900, must-revalidate";
}

function baseHeaders(request, env, key = "") {
  const headers = new Headers(corsHeaders(request, env));
  headers.set("Cache-Control", cacheControl(key));
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  headers.set("Referrer-Policy", "no-referrer");
  return headers;
}

function jsonResponse(request, env, body, status = 200) {
  const headers = baseHeaders(request, env, "collection-status.json");
  headers.set("Content-Type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(body, null, 2), { status, headers });
}

function applyObjectHeaders(headers, object, key) {
  object.writeHttpMetadata(headers);
  headers.set("ETag", object.httpEtag);
  headers.set("Accept-Ranges", "bytes");
  headers.set("Cache-Control", cacheControl(key));
  if (!headers.has("Content-Type")) {
    if (key.endsWith(".json")) headers.set("Content-Type", "application/json; charset=utf-8");
    else if (key.endsWith(".pdf")) headers.set("Content-Type", "application/pdf");
    else if (key.endsWith(".txt")) headers.set("Content-Type", "text/plain; charset=utf-8");
  }
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: baseHeaders(request, env) });
    }
    if (!['GET', 'HEAD'].includes(request.method)) {
      return jsonResponse(request, env, { error: "Method not allowed" }, 405);
    }

    const url = new URL(request.url);
    let key;
    try {
      key = decodeURIComponent(url.pathname.replace(/^\/+/, ""));
    } catch (_error) {
      return jsonResponse(request, env, { error: "Invalid path" }, 400);
    }

    if (!key) {
      return jsonResponse(request, env, {
        service: "Nanaimo Bylaw Tracker cloud data",
        storage: "Cloudflare R2",
        directoryListing: false,
        status: `${url.origin}/collection-status.json`
      });
    }

    if (url.pathname.endsWith("/")) {
      return jsonResponse(request, env, {
        error: "Protected / directory listing disabled",
        message: "Archive files may be accessed through their recorded links."
      }, 403);
    }

    if (!allowedKey(key)) return jsonResponse(request, env, { error: "Not found" }, 404);

    if (request.method === "HEAD") {
      const object = await env.NANAIMO_DATA.head(key);
      if (!object) return jsonResponse(request, env, { error: "Not found" }, 404);
      const headers = baseHeaders(request, env, key);
      applyObjectHeaders(headers, object, key);
      headers.set("Content-Length", String(object.size));
      return new Response(null, { status: 200, headers });
    }

    const getOptions = { onlyIf: request.headers };
    const hasRangeRequest = request.headers.has("Range");
    if (hasRangeRequest) getOptions.range = request.headers;

    const object = await env.NANAIMO_DATA.get(key, getOptions);
    if (object === null) return jsonResponse(request, env, { error: "Not found" }, 404);
    if (!('body' in object)) {
      const headers = baseHeaders(request, env, key);
      headers.set("ETag", object.httpEtag);
      const notModified = request.headers.has("If-None-Match") || request.headers.has("If-Modified-Since");
      return new Response(null, { status: notModified ? 304 : 412, headers });
    }

    const headers = baseHeaders(request, env, key);
    applyObjectHeaders(headers, object, key);
    let status = 200;
    if (hasRangeRequest && object.range) {
      const offset = object.range.offset ?? 0;
      const length = object.range.length ?? object.size;
      headers.set("Content-Range", `bytes ${offset}-${offset + length - 1}/${object.size}`);
      headers.set("Content-Length", String(length));
      status = 206;
    } else {
      headers.set("Content-Length", String(object.size));
    }
    return new Response(object.body, { status, headers });
  }
};
