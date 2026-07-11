/*
 * MAJÁK — login gate + review badge (shared across all pages).
 *
 * Loaded FIRST (in <head>). GitHub Pages is public and cannot be password
 * protected, so privacy is enforced client-side: without a valid token the page
 * shows only a login overlay and loads NO data, and the public HTML carries no
 * business data (report/zoznam/osoby ship with empty embedded state; real data
 * comes only from the authenticated API). The "password" is the APP_TOKEN.
 */
(function (g) {
  "use strict";
  var TOK = "majak.token", API = "majak.apiBase", DEF = "https://majak-api.onrender.com/api";
  var LAST = "majak.reviewSeen";

  function base() { return (localStorage.getItem(API) || DEF).replace(/\/$/, ""); }
  function token() { return localStorage.getItem(TOK) || ""; }

  // Hide content until auth resolves (no data leak — just avoids an empty flash).
  if (!token()) {
    try {
      var s = document.createElement("style");
      s.id = "majak-gate-style";
      s.textContent = "body{visibility:hidden!important}";
      (document.head || document.documentElement).appendChild(s);
    } catch (e) { /* ignore */ }
  }

  async function validate(tok) {
    var r = await fetch(base() + "/days", { headers: { Authorization: "Bearer " + tok } });
    return r.ok;
  }

  function reveal() {
    var s = document.getElementById("majak-gate-style");
    if (s) s.remove();
  }

  function showLogin(errorMsg) {
    reveal(); // reveal so the overlay is visible; overlay itself covers content
    var wrap = document.createElement("div");
    wrap.id = "majak-login";
    wrap.innerHTML =
      '<div class="ml-card">' +
      '<div class="ml-logo"><span class="ml-beacon"></span><b>MAJÁK</b></div>' +
      '<div class="ml-sub">Súkromný prístup</div>' +
      '<input id="ml-pw" type="password" placeholder="Prístupový kód" autocomplete="current-password" />' +
      '<button id="ml-go">Prihlásiť</button>' +
      '<div class="ml-err" id="ml-err">' + (errorMsg || "") + "</div>" +
      "</div>";
    document.body.appendChild(wrap);
    var pw = document.getElementById("ml-pw");
    var go = document.getElementById("ml-go");
    var err = document.getElementById("ml-err");
    pw.focus();
    async function submit() {
      go.disabled = true; err.textContent = "Overujem…";
      var val = pw.value.trim();
      try {
        if (await validate(val)) {
          localStorage.setItem(TOK, val);
          location.reload();
        } else {
          err.textContent = "Nesprávny kód."; go.disabled = false;
        }
      } catch (e) {
        err.textContent = "API nedostupné: " + e.message; go.disabled = false;
      }
    }
    go.onclick = submit;
    pw.addEventListener("keydown", function (e) { if (e.key === "Enter") submit(); });
  }

  function injectStyle() {
    var css =
      "#majak-login{position:fixed;inset:0;z-index:99999;display:grid;place-items:center;" +
      "background:#0f1413;font-family:Inter,system-ui,sans-serif}" +
      ".ml-card{background:#161d1c;border:1px solid #27302d;border-radius:16px;padding:30px 28px;" +
      "width:320px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,.5);text-align:center}" +
      ".ml-logo{display:flex;gap:10px;align-items:center;justify-content:center;color:#e7ece9}" +
      ".ml-logo b{font-family:'Space Grotesk',sans-serif;font-weight:700;letter-spacing:.16em;font-size:18px}" +
      ".ml-beacon{width:26px;height:26px;border-radius:7px;border:1px solid #27302d;" +
      "background:radial-gradient(circle at 50% 32%,#3fa9bb 0 26%,transparent 27%),#161d1c}" +
      ".ml-sub{color:#6c7a74;font-size:12.5px;margin:6px 0 20px;font-family:'IBM Plex Mono',monospace;letter-spacing:.08em;text-transform:uppercase}" +
      "#ml-pw{width:100%;font-size:15px;padding:11px 12px;border-radius:9px;border:1px solid #27302d;" +
      "background:#0f1413;color:#e7ece9;margin-bottom:12px}" +
      "#ml-pw:focus{outline:none;border-color:#3fa9bb}" +
      "#ml-go{width:100%;font-size:14px;font-weight:600;padding:11px;border-radius:9px;border:0;" +
      "background:#3fa9bb;color:#08201f;cursor:pointer}" +
      "#ml-go:hover{background:#5cc0d0}#ml-go:disabled{opacity:.6;cursor:default}" +
      ".ml-err{color:#e0685c;font-size:12.5px;min-height:16px;margin-top:12px}" +
      ".majak-badge{display:inline-block;min-width:16px;padding:0 5px;margin-left:6px;border-radius:10px;" +
      "background:#e0685c;color:#fff;font-size:10.5px;font-weight:700;line-height:16px;text-align:center;font-family:'IBM Plex Mono',monospace}";
    var st = document.createElement("style");
    st.textContent = css;
    (document.head || document.documentElement).appendChild(st);
  }

  // ── review badge + notification ─────────────────────────────────────────────
  async function refreshBadge() {
    try {
      var r = await fetch(base() + "/review-queue", { headers: { Authorization: "Bearer " + token() } });
      if (!r.ok) return;
      var rows = await r.json();
      var n = rows.length;
      document.querySelectorAll('a[href$="otazky.html"]').forEach(function (a) {
        var b = a.querySelector(".majak-badge");
        if (n > 0) {
          if (!b) { b = document.createElement("span"); b.className = "majak-badge"; a.appendChild(b); }
          b.textContent = n;
        } else if (b) { b.remove(); }
      });
      var seen = parseInt(localStorage.getItem(LAST) || "0", 10);
      if (n > seen && "Notification" in g && Notification.permission === "granted") {
        new Notification("MAJÁK — nové otázky", { body: n + " otázok čaká na odpoveď." });
      }
      localStorage.setItem(LAST, String(n));
    } catch (e) { /* ignore */ }
  }

  function start() {
    injectStyle();
    if (!token()) { showLogin(""); return; }
    reveal();
    if ("Notification" in g && Notification.permission === "default") {
      try { Notification.requestPermission(); } catch (e) { /* ignore */ }
    }
    refreshBadge();
    setInterval(refreshBadge, 60000);
  }

  g.MajakAuth = { logout: function () { localStorage.removeItem(TOK); location.reload(); }, token: token };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})(typeof window !== "undefined" ? window : globalThis);
