/* Live unread count for the notification bell, with no page refresh.
 *
 * Every element with [data-notif-count] shows the number; the bell link carries
 * the URL to poll in data-count-url. Polling pauses while the tab is hidden and
 * resumes at once when it is shown again. If the inbox page is open and a new
 * notification arrives, only the list is replaced.
 *
 * Any block marked data-live-key="name" on the current page (for example the
 * "Donors who offered" box on a request) is refreshed in place when a new
 * notification arrives, so a donor's "I can help" shows up without a reload.
 *
 * To go easy on a small shared server: one check every 30 seconds, and the
 * checks stop after 10 minutes without a click, key or scroll. They start again
 * at the next touch. Nothing here is needed for correctness: without JavaScript
 * the number is simply right on the next page load.
 */
(function () {
  "use strict";
  var bell = document.querySelector("[data-notif-bell]");
  if (!bell) { return; }
  var url = bell.getAttribute("data-count-url");
  /* Wording comes from the #bn-i18n table on Urdu and Sindhi pages; English pages have none. */
  var table = {};
  try { var holder = document.getElementById("bn-i18n"); if (holder) { table = JSON.parse(holder.textContent) || {}; } } catch (e) { table = {}; }
  var say = function (text, values) {
    var out = Object.prototype.hasOwnProperty.call(table, text) ? table[text] : text;
    return values ? out.replace(/%\((\w+)\)s/g, function (all, k) { return k in values ? values[k] : all; }) : out;
  };
  var every = 30000;
  var idleAfter = 10 * 60 * 1000;
  var lastLatest = null;
  var lastTouch = Date.now();
  var timer = null;
  var busy = false;

  function show(unread) {
    var holders = document.querySelectorAll("[data-notif-count]");
    for (var i = 0; i < holders.length; i++) {
      holders[i].textContent = unread > 99 ? "99+" : String(unread);
      holders[i].hidden = unread === 0;
    }
    bell.setAttribute("aria-label", unread ? say("Notifications, %(n)s unread", { n: unread }) : say("Notifications"));
  }

  function fetchPage() {
    return fetch(window.location.pathname + window.location.search, {
      credentials: "same-origin", headers: { "X-Requested-With": "fetch" }
    }).then(function (r) { return r.ok ? r.text() : ""; })
      .then(function (html) { return html ? new DOMParser().parseFromString(html, "text/html") : null; });
  }

  function refreshList() {
    var list = document.getElementById("notif-list");
    if (!list) { return; }
    fetchPage().then(function (doc) {
      var fresh = doc && doc.getElementById("notif-list");
      if (fresh) { list.innerHTML = fresh.innerHTML; }
    }).catch(function () {});
  }

  function refreshLiveRegions() {
    var regions = document.querySelectorAll("[data-live-key]");
    if (!regions.length) { return; }
    fetchPage().then(function (doc) {
      if (!doc) { return; }
      for (var i = 0; i < regions.length; i++) {
        var region = regions[i];
        var fresh = doc.querySelector('[data-live-key="' + region.getAttribute("data-live-key") + '"]');
        /* Never replace a block somebody is typing in. */
        if (!fresh || region.contains(document.activeElement) && /input|textarea|select/i.test(document.activeElement.tagName)) { continue; }
        var animated = fresh.querySelectorAll("[data-aos]");
        for (var j = 0; j < animated.length; j++) { animated[j].removeAttribute("data-aos"); }
        region.innerHTML = fresh.innerHTML;
        region.classList.remove("live-flash"); void region.offsetWidth; region.classList.add("live-flash");
      }
    }).catch(function () {});
  }

  function poll() {
    if (document.hidden || busy) { return; }
    if (Date.now() - lastTouch > idleAfter) { stop(); return; }
    busy = true;
    fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) { return; }
        show(data.unread);
        if (lastLatest !== null && data.latest !== lastLatest) {
          bell.classList.remove("is-new"); void bell.offsetWidth; bell.classList.add("is-new");
          refreshList();
          refreshLiveRegions();
        }
        lastLatest = data.latest;
      })
      .catch(function () {})
      .then(function () { busy = false; });
  }

  function start() { if (!timer) { timer = setInterval(poll, every); } }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  function touched() {
    var wasIdle = Date.now() - lastTouch > idleAfter;
    lastTouch = Date.now();
    if (wasIdle) { poll(); start(); }
  }
  ["click", "keydown", "scroll", "touchstart", "mousemove"].forEach(function (name) {
    document.addEventListener(name, throttledTouch, { passive: true });
  });
  var touchGate = 0;
  function throttledTouch() {
    var now = Date.now();
    if (now - touchGate < 5000) { return; }
    touchGate = now;
    touched();
  }

  document.addEventListener("visibilitychange", function () { if (!document.hidden) { touched(); poll(); } });
  poll();
  start();
})();
