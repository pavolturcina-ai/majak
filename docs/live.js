/*
 * MAJÁK — live-mode adapter for the report engine (report / zoznam / osoby).
 *
 * Loaded AFTER the page's inline engine script. When a token is present it:
 *   1. fetches GET /days/current and maps it into the engine's `state` shape,
 *   2. wraps the engine's mutation functions (toggleDone / saveEdit / del /
 *      move / setList) so edits also persist to the API.
 * Everything is guarded — if the API is unreachable or a token isn't set, the
 * page keeps working over its embedded snapshot (localStorage). No engine code
 * is modified; this only overrides globals defined by classic scripts.
 */
(function (g) {
  "use strict";

  var API_KEY = "majak.apiBase", TOK_KEY = "majak.token";
  var DEFAULT_API = "https://majak-api.onrender.com/api";

  function base() { return (localStorage.getItem(API_KEY) || DEFAULT_API).replace(/\/$/, ""); }
  function token() { return localStorage.getItem(TOK_KEY) || ""; }
  function enabled() { return !!token(); }
  function authHeaders(json) {
    var h = { Authorization: "Bearer " + token() };
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  async function apiGet(path) {
    var r = await fetch(base() + path, { headers: authHeaders(false) });
    if (!r.ok) throw new Error("GET " + path + " -> " + r.status);
    return r.json();
  }
  async function apiSend(method, path, body) {
    var r = await fetch(base() + path, {
      method: method, headers: authHeaders(true),
      body: body == null ? undefined : JSON.stringify(body),
    });
    if (!r.ok) throw new Error(method + " " + path + " -> " + r.status);
    return r.json().catch(function () { return {}; });
  }

  // ── mapping: API DayView -> engine state shape ──────────────────────────────
  var SEC_TITLES = {
    top: "TOP — čo nesmie spadnúť", decision: "Rozhodnutia", good: "Dobré správy",
    threat: "Hrozby", deleg: "Delegovať", quick: "Rýchle výhry", radar: "Radar",
  };
  var SEC_NUM = { top: "01", decision: "02", good: "03", threat: "04", deleg: "05", quick: "06", radar: "07" };
  var SEC_ORDER = ["top", "decision", "good", "threat", "deleg", "quick", "radar"];

  function mapChips(chips) {
    if (!Array.isArray(chips)) return [];
    return chips.map(function (c) {
      if (Array.isArray(c)) return [String(c[0] || ""), String(c[1] != null ? c[1] : c[0])];
      if (c && typeof c === "object") return [String(c.kind || c.key || "tag"), String(c.label || c.value || "")];
      return ["tag", String(c)];
    }).filter(function (p) { return p[1]; });
  }
  function fmtDay(iso) {
    if (!iso) return "";
    var p = String(iso).split("-");
    return p.length === 3 ? (+p[2]) + "." + (+p[1]) + "." : iso;
  }
  function mapItem(o, srcTitles) {
    return {
      _id: o.id,
      t: o.title, d: o.description || "",
      rail: o.rail || "signal",
      own: o.owners || [],
      chips: mapChips(o.chips),
      done: o.status === "done",
      list: o.list_kind || undefined,
      day: fmtDay(o.entered_day),
      carry: o.carry_from ? "(prenesené)" : undefined,
      ctx: (o.grounding || []).map(function (gr) {
        return {
          q: gr.quote || "", who: "",
          src: (srcTitles && srcTitles[gr.source_id]) || "",
          loc: gr.locator || "", url: gr.url || null,
        };
      }),
    };
  }
  function mapDay(view, srcTitles) {
    var sections = SEC_ORDER.map(function (id) {
      var items = (view.sections && view.sections[id]) || [];
      return {
        id: id, num: SEC_NUM[id], title: SEC_TITLES[id],
        track: id === "top", numbered: id === "top",
        items: items.map(function (o) { return mapItem(o, srcTitles); }),
      };
    });
    return { dayTitle: view.date || "", pulse: view.pulse || "", human: view.summary || "", sections: sections };
  }

  async function loadState() {
    var view = await apiGet("/days/current");
    var srcTitles = {};
    try {
      var srcs = await apiGet("/sources");
      (srcs || []).forEach(function (s) { srcTitles[s.id] = s.title; });
    } catch (e) { /* sources are optional for display */ }
    return mapDay(view, srcTitles);
  }

  g.MajakLive = {
    enabled: enabled,
    loadState: loadState,
    patchItem: function (id, patch) { return apiSend("PATCH", "/items/" + id, patch); },
    setStatus: function (id, status, reason) { return apiSend("POST", "/items/" + id + "/status", { status: status, reason: reason }); },
    setList: function (id, kind) { return apiSend("POST", "/items/" + id + "/list", { kind: kind }); },
    reorder: function (ids) { return apiSend("POST", "/items/reorder", { ordered_ids: ids }); },
    // exported for tests
    _map: { mapDay: mapDay, mapItem: mapItem, mapChips: mapChips, fmtDay: fmtDay },
  };
})(typeof window !== "undefined" ? window : globalThis);

// ── init + wrappers (runs after the engine script) ────────────────────────────
(function () {
  "use strict";
  if (typeof window === "undefined" || !window.MajakLive || !MajakLive.enabled()) return;

  function logErr(e) { try { console.warn("[MajakLive]", e && e.message ? e.message : e); } catch (_) {} }
  function itemAt(si, ii) { try { return state.sections[si].items[ii]; } catch (e) { return null; } }
  function sectionIds(si) {
    try { return state.sections[si].items.map(function (x) { return x._id; }).filter(Boolean); }
    catch (e) { return []; }
  }

  // toggleDone -> POST /items/{id}/status
  var _toggleDone = window.toggleDone;
  if (_toggleDone) window.toggleDone = function (si, ii) {
    var id = itemAt(si, ii) && itemAt(si, ii)._id;
    _toggleDone(si, ii);
    var it = itemAt(si, ii);
    if (id && it) MajakLive.setStatus(id, it.done ? "done" : "open").catch(logErr);
  };

  // saveEdit -> PATCH /items/{id}
  var _saveEdit = window.saveEdit;
  if (_saveEdit) window.saveEdit = function (si, ii) {
    var it = itemAt(si, ii);
    _saveEdit(si, ii);
    if (it && it._id) MajakLive.patchItem(it._id, { title: it.t, description: it.d, rail: it.rail, owners: it.own }).catch(logErr);
  };

  // setList -> POST /items/{id}/list
  var _setList = window.setList;
  if (_setList) window.setList = function (si, ii, kind) {
    var id = itemAt(si, ii) && itemAt(si, ii)._id;
    _setList(si, ii, kind);
    if (id) MajakLive.setList(id, kind || null).catch(logErr);
  };

  // move -> POST /items/reorder (section order)
  var _move = window.move;
  if (_move) window.move = function (si, ii, dir) {
    _move(si, ii, dir);
    var ids = sectionIds(si);
    if (ids.length) MajakLive.reorder(ids).catch(logErr);
  };

  // del -> POST /items/{id}/status {deleted} (API needs a reason)
  var _del = window.del;
  if (_del) window.del = function (si, ii) {
    var it = itemAt(si, ii);
    if (!it) return;
    if (!confirm('Zmazať položku?\n\n„' + (it.t || "") + '"')) return;
    var reason = prompt("Dôvod zmazania (uloží sa do histórie):", "manuálne zmazané") || "manuálne zmazané";
    var id = it._id;
    try {
      state.sections[si].items.splice(ii, 1);
      if (window.editing && editing.si === si) editing = null;
      save(); render();
    } catch (e) { logErr(e); }
    if (id) MajakLive.setStatus(id, "deleted", reason).catch(logErr);
  };

  // Load live data and re-render (falls back silently to the snapshot on error).
  MajakLive.loadState().then(function (st) {
    try {
      state = st;                       // shared global lexical binding (classic scripts)
      if (typeof showAll !== "undefined") { try { showAll = true; } catch (e) {} }
      if (window.renderFilter) renderFilter();
      if (window.render) render();
      var badge = document.getElementById("saved");
      if (badge) badge.innerHTML = '<b style="color:var(--signal)">● naživo</b>';
    } catch (e) { logErr(e); }
  }).catch(function (e) {
    logErr(e); // keep the embedded snapshot
  });
})();
