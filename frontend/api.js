/*
 * MAJÁK API adapter — Phase 1 frontend seam.
 *
 * Drop this into the existing single-file interactive report and replace the
 * embedded SEED / SOURCES constants with calls to this module. It keeps the
 * existing render/interaction code; only the data source and mutations change.
 *
 * Offline behaviour: reads are cached in localStorage; mutations are queued
 * while offline and replayed (reconciled) on reconnect.
 */
(function (global) {
  "use strict";

  const API_BASE = global.MAJAK_API_BASE || "/api";
  const TOKEN_KEY = "majak.token";
  const CACHE_PREFIX = "majak.cache.";
  const QUEUE_KEY = "majak.mutationQueue";

  function token() {
    return global.MAJAK_TOKEN || localStorage.getItem(TOKEN_KEY) || "";
  }

  function headers(extra) {
    return Object.assign(
      { "Content-Type": "application/json", Authorization: "Bearer " + token() },
      extra || {}
    );
  }

  function cacheGet(key) {
    try {
      const raw = localStorage.getItem(CACHE_PREFIX + key);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function cacheSet(key, value) {
    try {
      localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(value));
    } catch (_) {
      /* quota — ignore */
    }
  }

  async function apiGet(path, cacheKey) {
    try {
      const res = await fetch(API_BASE + path, { headers: headers() });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      if (cacheKey) cacheSet(cacheKey, data);
      return data;
    } catch (err) {
      // Offline / error → serve last good cache if we have it.
      const cached = cacheKey ? cacheGet(cacheKey) : null;
      if (cached) return cached;
      throw err;
    }
  }

  async function apiSend(method, path, body) {
    try {
      const res = await fetch(API_BASE + path, {
        method,
        headers: headers(),
        body: body == null ? undefined : JSON.stringify(body),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      return await res.json();
    } catch (err) {
      // Offline → enqueue for later reconciliation.
      queueMutation({ method, path, body });
      throw err;
    }
  }

  // ── Offline mutation queue ────────────────────────────────────────────────
  function loadQueue() {
    try {
      return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
    } catch (_) {
      return [];
    }
  }

  function saveQueue(q) {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(q));
  }

  function queueMutation(m) {
    const q = loadQueue();
    q.push(Object.assign({ ts: Date.now() }, m));
    saveQueue(q);
  }

  async function reconcile() {
    const q = loadQueue();
    const remaining = [];
    for (const m of q) {
      try {
        const res = await fetch(API_BASE + m.path, {
          method: m.method,
          headers: headers(),
          body: m.body == null ? undefined : JSON.stringify(m.body),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
      } catch (_) {
        remaining.push(m); // still offline / failed → keep for next time
      }
    }
    saveQueue(remaining);
    return { replayed: q.length - remaining.length, pending: remaining.length };
  }

  global.addEventListener("online", reconcile);

  // ── Public API ────────────────────────────────────────────────────────────
  const MajakAPI = {
    API_BASE,
    setToken(t) {
      localStorage.setItem(TOKEN_KEY, t);
    },

    // Reads
    currentDay: () => apiGet("/days/current", "day.current"),
    day: (date) => apiGet("/days/" + date, "day." + date),
    allCurrent: () => apiGet("/days/all-current", "all-current"),
    sources: () => apiGet("/sources", "sources"),
    source: (id) => apiGet("/sources/" + id),
    people: () => apiGet("/people", "people"),
    brief: (id) => apiGet("/people/" + id + "/brief"),
    reviewQueue: () => apiGet("/review-queue", "review"),
    rollup: (from, to) => apiGet("/rollup?from=" + from + "&to=" + to),

    // Mutations (route done/edit/delete/reorder/list-tag to the API)
    edit: (id, patch) => apiSend("PATCH", "/items/" + id, patch),
    markDone: (id) => apiSend("POST", "/items/" + id + "/status", { status: "done" }),
    reopen: (id) => apiSend("POST", "/items/" + id + "/status", { status: "open" }),
    remove: (id, reason) =>
      apiSend("POST", "/items/" + id + "/status", { status: "deleted", reason: reason }),
    saveToList: (id, kind) => apiSend("POST", "/items/" + id + "/list", { kind: kind }),
    reorder: (orderedIds) => apiSend("POST", "/items/reorder", { ordered_ids: orderedIds }),
    resolvePerson: (raw_name, context) =>
      apiSend("POST", "/people/resolve", { raw_name, context }),
    resolveReview: (id, body) => apiSend("POST", "/review-queue/" + id + "/resolve", body),

    reconcile,
  };

  global.MajakAPI = MajakAPI;
})(window);
