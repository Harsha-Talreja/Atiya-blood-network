/* Site-wide behaviour. No external services: everything here works offline. */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Wording for Urdu and Sindhi pages. The server puts a JSON table in #bn-i18n; on an
     English page there is none and every sentence below simply stays as written here.
     t("English text") returns the translation; fill() swaps %(name)s placeholders. */
  var strings = {};
  try {
    var table = document.getElementById("bn-i18n");
    if (table) { strings = JSON.parse(table.textContent) || {}; }
  } catch (e) { strings = {}; }
  var t = function (text) { return Object.prototype.hasOwnProperty.call(strings, text) ? strings[text] : text; };
  var fill = function (text, values) {
    return text.replace(/%\((\w+)\)s/g, function (all, name) { return name in values ? values[name] : all; });
  };

  /* Home sections reveal in both directions. AOS plays each block once, so scrolling
     back up showed nothing. Here every block animates in whenever it enters the
     screen, coming from the side it entered: from below when scrolling down, from
     above when scrolling up. These blocks are taken out of AOS so the two never
     fight over the same element. Reduced motion skips all of it. */
  if (!reduceMotion && "IntersectionObserver" in window) {
    var rvIo = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var el = entry.target;
        if (entry.isIntersecting) {
          el.classList.remove("rv-above");
          el.classList.add("rv-in");
        } else {
          el.classList.remove("rv-in");
          el.classList.toggle("rv-above", entry.boundingClientRect.top < 0);
        }
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.1 });
    document.querySelectorAll(".home-body [data-aos], .rq-page [data-aos], .dd-page [data-aos]").forEach(function (el) {
      var delay = el.getAttribute("data-aos-delay");
      el.removeAttribute("data-aos");
      el.removeAttribute("data-aos-delay");
      el.classList.add("rv");
      if (delay) { el.style.setProperty("--rd", delay + "ms"); }
      rvIo.observe(el);
    });
  }

  /* Scroll-reveal animations (AOS) for the other pages. Disabled for people who prefer reduced motion. */
  if (window.AOS) {
    AOS.init({ duration: 450, easing: "ease-out-cubic", once: true, offset: 70, disable: reduceMotion });
    /* Once a block has finished revealing, let go of it. Otherwise the long reveal
       transition would also slow down its hover lift. */
    document.addEventListener("transitionend", function (e) {
      var el = e.target;
      if (e.propertyName === "opacity" && el.hasAttribute && el.hasAttribute("data-aos") && el.classList.contains("aos-animate")) {
        el.removeAttribute("data-aos");
        el.removeAttribute("data-aos-delay");
      }
    });
    /* AOS measures where everything sits when it starts. Fonts, images and the
       counters settle after that, so measure again once the page has loaded;
       otherwise some blocks wait for a trigger point that has since moved. */
    window.addEventListener("load", function () { AOS.refreshHard(); });
  }

  /* The floating navbar hides as soon as the page scrolls down and comes back when the
     page scrolls up, or at the top. A trackpad or a smooth-scrolling mouse sends small
     back-and-forth movements, and a layout shift can nudge the scroll position, so the
     direction is judged by distance travelled, not by single events: about 6px down
     hides it, but it takes a real 60px back up to show it again. It also stays visible
     while the mobile menu or a dropdown is open, or while keyboard focus is inside it. */
  var header = document.querySelector(".site-header");
  if (header) {
    var lastY = window.scrollY, travel = 0, HIDE_AFTER = 6, SHOW_AFTER = 60;
    var navBusy = function () {
      return header.querySelector(":focus-visible, .navbar-collapse.show, .dropdown-menu.show");
    };
    var onScroll = function () {
      var y = window.scrollY, dy = y - lastY;
      lastY = y;
      header.classList.toggle("is-scrolled", y > 8);
      if (y <= 10 || navBusy()) { header.classList.remove("is-hidden"); travel = 0; return; }
      if (dy === 0) { return; }
      travel = (dy > 0) === (travel > 0) ? travel + dy : dy;
      if (travel > HIDE_AFTER) { header.classList.add("is-hidden"); }
      else if (travel < -SHOW_AFTER) { header.classList.remove("is-hidden"); }
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  /* Toasts. Django's own messages are already in the stack when the page
     arrives; this handles dismissing those and raising new ones from script.
     Text is set with textContent, never innerHTML, so a message that contains
     a stray < cannot become markup. */
  var TOAST_LOOK = {
    success: ["is-good", "bi-check-circle-fill"],
    error: ["is-bad", "bi-exclamation-octagon-fill"],
    danger: ["is-bad", "bi-exclamation-octagon-fill"],
    warning: ["is-warn", "bi-exclamation-triangle-fill"],
    info: ["is-info", "bi-info-circle-fill"]
  };

  function dismissToast(el) {
    if (!el || el.classList.contains("is-leaving")) { return; }
    el.classList.add("is-leaving");
    window.setTimeout(function () { el.remove(); }, 320);
  }

  function watchToast(el) {
    var life = Number(el.getAttribute("data-toast-life")) || 5000;
    var timer = window.setTimeout(function () { dismissToast(el); }, life);
    /* Reading a long message should not be cut short, so hovering pauses it. */
    el.addEventListener("pointerenter", function () { window.clearTimeout(timer); });
    el.addEventListener("pointerleave", function () {
      timer = window.setTimeout(function () { dismissToast(el); }, 2500);
    });
  }

  document.addEventListener("click", function (event) {
    var close = event.target.closest("[data-toast-close]");
    if (close) { dismissToast(close.closest("[data-toast]")); }
  });
  document.querySelectorAll("[data-toast]").forEach(watchToast);

  window.showToast = function (message, variant) {
    var container = document.getElementById("toast-container");
    if (!container) { return; }
    var look = TOAST_LOOK[variant] || TOAST_LOOK.info;
    var el = document.createElement("div");
    el.className = "toast-item " + look[0];
    el.setAttribute("data-toast", "");
    var icon = document.createElement("i");
    icon.className = "bi " + look[1];
    icon.setAttribute("aria-hidden", "true");
    var text = document.createElement("span");
    text.textContent = message;
    var close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("data-toast-close", "");
    close.setAttribute("aria-label", t("Dismiss this message"));
    close.textContent = "×";
    el.append(icon, text, close);
    container.appendChild(el);
    watchToast(el);
  };

  /* Links for pages that are built in later milestones. */
  document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-soon]");
    if (!link) { return; }
    event.preventDefault();
    window.showToast(link.getAttribute("data-soon") + " is coming in the next build step.");
  });

  /* Count-up numbers: <span data-count="120">0</span> */
  function formatNumber(n) { return Number(n).toLocaleString("en-US"); }

  function countUp(el) {
    var target = parseInt(el.getAttribute("data-count"), 10) || 0;
    if (reduceMotion || target === 0) { el.textContent = formatNumber(target); return; }
    var duration = 1200;
    var start = null;
    function step(ts) {
      if (start === null) { start = ts; }
      var progress = Math.min((ts - start) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = formatNumber(Math.round(target * eased));
      if (progress < 1) { window.requestAnimationFrame(step); }
    }
    window.requestAnimationFrame(step);
  }

  var counters = document.querySelectorAll("[data-count]");
  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { countUp(entry.target); observer.unobserve(entry.target); }
      });
    }, { threshold: 0.4 });
    counters.forEach(function (el) { observer.observe(el); });
  } else {
    counters.forEach(countUp);
  }


  /* Reading-progress line */
  var progress = document.querySelector(".scroll-progress");
  if (progress) {
    var ticking = false;
    var updateProgress = function () {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      var ratio = max > 0 ? Math.min(window.scrollY / max, 1) : 0;
      progress.style.setProperty("--p", ratio.toFixed(4));
      ticking = false;
    };
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; window.requestAnimationFrame(updateProgress); }
    }, { passive: true });
    updateProgress();
  }

  /* Tabs on the home page ("I need blood" / "I can donate"). Without script both
     panels simply sit one under the other. Arrow keys, Home and End move between
     tabs, and only the selected tab is reachable with Tab, as the ARIA pattern asks. */
  document.querySelectorAll("[data-tabs]").forEach(function (box) {
    var tabs = Array.prototype.slice.call(box.querySelectorAll('[role="tab"]'));
    var panes = tabs.map(function (tab) { return document.getElementById(tab.getAttribute("aria-controls")); });
    var select = function (index, focus) {
      tabs.forEach(function (tab, i) {
        var on = i === index;
        tab.setAttribute("aria-selected", on ? "true" : "false");
        tab.tabIndex = on ? 0 : -1;
        if (panes[i]) {
          panes[i].hidden = !on;
          panes[i].classList.toggle("is-entering", on && !reduceMotion);
        }
      });
      if (focus) { tabs[index].focus(); }
    };
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { select(i, false); });
      tab.addEventListener("keydown", function (event) {
        var next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[event.key];
        if (next === undefined) { return; }
        event.preventDefault();
        select((next + tabs.length) % tabs.length, true);
      });
    });
    select(0, false);
    panes[0] && panes[0].classList.remove("is-entering");
  });

  /* Hero scroll motion. --sy follows the scroll position through a short ease, so
     the hero and the glows behind the home sections glide instead of stepping with
     every wheel tick. The values are set on those small elements only (not on the
     page root, which would restyle everything on every frame), and the loop stops
     by itself once it has caught up. Reduced motion leaves everything still. */
  var heroEl = document.querySelector(".hero-premium");
  var glowEl = null; // the home glows no longer follow the scroll (see theme.css 65)
  if ((heroEl || glowEl) && !reduceMotion) {
    var nowY = window.scrollY, targetY = nowY, running = false;
    var tick = function () {
      nowY += (targetY - nowY) * 0.12;
      if (Math.abs(targetY - nowY) < 0.1) { nowY = targetY; running = false; }
      if (heroEl) { heroEl.style.setProperty("--sy", Math.min(nowY, 900).toFixed(2)); }
      if (glowEl) { glowEl.style.setProperty("--bs", Math.min(nowY, 6000).toFixed(2)); }
      if (running) { window.requestAnimationFrame(tick); }
    };
    var kick = function () {
      targetY = window.scrollY;
      if (!running) { running = true; window.requestAnimationFrame(tick); }
    };
    window.addEventListener("scroll", kick, { passive: true });
    kick();
  }

  /* Live strip under the hero buttons: show the next request every few seconds.
     Left alone with reduced motion on, so nothing changes under the reader. */
  var strip = document.querySelector("[data-live-strip]");
  if (strip && !reduceMotion) {
    var slides = strip.querySelectorAll(".live-slide");
    if (slides.length > 1) {
      var current = 0, timer = null;
      var show = function (index) {
        slides[current].classList.remove("is-on");
        current = index;
        slides[current].classList.add("is-on");
      };
      var start = function () { timer = window.setInterval(function () { show((current + 1) % slides.length); }, 3600); };
      var stop = function () { window.clearInterval(timer); };
      strip.addEventListener("pointerenter", stop);
      strip.addEventListener("pointerleave", start);
      strip.addEventListener("focusin", stop);
      strip.addEventListener("focusout", start);
      start();
    }
  }

  /* Navbar: highlight the section being read on the home page. */
  var spyLinks = document.querySelectorAll("[data-spy]");
  if (spyLinks.length && "IntersectionObserver" in window) {
    var homeLink = document.querySelector(".navbar .nav-link[aria-current='page']");
    var seen = {};
    var spyObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) { seen[entry.target.id] = entry.isIntersecting; });
      var current = null;
      spyLinks.forEach(function (link) {
        var on = !current && seen[link.getAttribute("data-spy")];
        if (on) { current = link; }
        link.classList.toggle("active", !!on);
      });
      if (homeLink) { homeLink.classList.toggle("active", !current); }
    }, { rootMargin: "-30% 0px -55% 0px" });
    spyLinks.forEach(function (link) {
      var section = document.getElementById(link.getAttribute("data-spy"));
      if (section) { spyObserver.observe(section); }
    });
  }

  /* Hero: cursor spotlight and card tilt (mouse devices only, never with reduced motion) */
  var hero = document.querySelector("[data-hero]");
  if (hero && !reduceMotion && window.matchMedia("(hover: hover)").matches) {
    var frame = null, px = 0, py = 0;
    hero.addEventListener("pointermove", function (event) {
      var box = hero.getBoundingClientRect();
      px = event.clientX - box.left;
      py = event.clientY - box.top;
      if (!frame) {
        frame = window.requestAnimationFrame(function () {
          hero.style.setProperty("--mx", px + "px");
          hero.style.setProperty("--my", py + "px");
          frame = null;
        });
      }
    });
    var tilt = hero.querySelector("[data-tilt]");
    if (tilt) {
      hero.addEventListener("pointermove", function (event) {
        var r = tilt.getBoundingClientRect();
        var x = (event.clientX - (r.left + r.width / 2)) / window.innerWidth;
        var y = (event.clientY - (r.top + r.height / 2)) / window.innerHeight;
        tilt.classList.add("is-tilting");
        tilt.style.transform = "perspective(900px) rotateY(" + (x * 14).toFixed(2) + "deg) rotateX(" + (-y * 14).toFixed(2) + "deg)";
      });
      hero.addEventListener("pointerleave", function () {
        tilt.classList.remove("is-tilting");
        tilt.style.transform = "";
      });
    }
  }

  /* Bar charts fill in when they scroll into view */
  var barCharts = document.querySelectorAll("[data-bars]");
  if (barCharts.length) {
    if (reduceMotion || !("IntersectionObserver" in window)) {
      barCharts.forEach(function (chart) { chart.classList.add("is-in"); });
    } else {
      var barObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) { entry.target.classList.add("is-in"); barObserver.unobserve(entry.target); }
        });
      }, { threshold: 0.25 });
      barCharts.forEach(function (chart) { barObserver.observe(chart); });
    }
  }

  /* Light / dark theme. The saved choice is applied before first paint (see base.html). */
  var themeButton = document.querySelector("[data-theme-toggle]");
  var applyTheme = function (theme, persist) {
    var root = document.documentElement;
    root.setAttribute("data-bs-theme", theme);
    if (persist) { try { localStorage.setItem("theme", theme); } catch (e) { /* private mode: ignore */ } }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) { meta.setAttribute("content", theme === "dark" ? "#0C1014" : "#C7192D"); }
    if (themeButton) {
      themeButton.querySelector("i").className = "bi " + (theme === "dark" ? "bi-sun" : "bi-moon-stars");
      themeButton.setAttribute("aria-label", theme === "dark" ? t("Switch to light mode") : t("Switch to dark mode"));
    }
  };
  applyTheme(document.documentElement.getAttribute("data-bs-theme") || "light", false);
  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var root = document.documentElement;
      var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      root.classList.add("theme-fade");
      applyTheme(next, true);
      window.setTimeout(function () { root.classList.remove("theme-fade"); }, 450);
    });
  }

  /* Language box: choosing a language sends the little form at once. */
  document.querySelectorAll("[data-lang-select]").forEach(function (box) {
    box.addEventListener("change", function () { if (box.form) { box.form.submit(); } });
  });

  /* Live countdowns: <time data-countdown="2026-09-21T12:00:00+05:00"> */
  var countdowns = document.querySelectorAll("[data-countdown]");
  if (countdowns.length) {
    var two = function (n) { return n < 10 ? "0" + n : String(n); };
    var renderCountdowns = function () {
      var now = Date.now();
      countdowns.forEach(function (el) {
        var end = Date.parse(el.getAttribute("data-countdown"));
        if (isNaN(end)) { return; }
        var seconds = Math.floor((end - now) / 1000);
        var text, soon = false, expired = false;
        // Defaults suit a request's closing time; a deadline of another kind sets its own words.
        var prefix = el.hasAttribute("data-countdown-prefix") ? el.getAttribute("data-countdown-prefix") : t("Closes in ");
        var doneText = el.hasAttribute("data-countdown-done") ? el.getAttribute("data-countdown-done") : t("Closed");
        if (seconds <= 0) {
          text = doneText;
          expired = true;
        } else {
          var d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600);
          var m = Math.floor((seconds % 3600) / 60), sec = seconds % 60;
          if (d > 0) { text = fill(t("%(d)sd %(h)sh"), { d: d, h: h }); }
          else if (h > 0) { text = fill(t("%(h)sh %(m)sm"), { h: h, m: two(m) }); }
          else { text = fill(t("%(m)sm %(s)ss"), { m: m, s: two(sec) }); soon = true; }
          text = prefix + text;
        }
        if (el.textContent !== text) { el.textContent = text; }
        el.classList.toggle("is-soon", soon);
        el.classList.toggle("is-expired", expired);
      });
    };
    renderCountdowns();
    window.setInterval(renderCountdowns, 1000);
  }

  /* Success dialog: showSuccess({ title: "Request posted", text: "..." }) */
  window.showSuccess = function (options) {
    var modalEl = document.getElementById("successModal");
    if (!modalEl || !window.bootstrap) { return; }
    modalEl.querySelector("#successTitle").textContent = (options && options.title) || t("Done");
    modalEl.querySelector("#successText").textContent = (options && options.text) || "";
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  };

  /* Auto-fire the success dialog when the server queued one (core.flash.success_dialog). */
  var flashDialog = document.querySelector("[data-flash-dialog]");
  if (flashDialog) {
    window.showSuccess({ title: flashDialog.dataset.title, text: flashDialog.dataset.text });
  }

  /* ---------- Forms ---------- */
  var SPINNER = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>';

  /* Phone fields keep only digits and a leading + */
  document.querySelectorAll("input[data-phone]").forEach(function (input) {
    input.addEventListener("input", function () {
      var v = input.value.replace(/[^\d+]/g, "");
      v = v.charAt(0) === "+" ? "+" + v.slice(1).replace(/\+/g, "") : v.replace(/\+/g, "");
      if (v !== input.value) { input.value = v; }
    });
  });

  /* Fixed-length number fields (mobile 11 digits, CNIC 13): digits only, and no digit past the length.
     A small "7/11" counter shows how far along it is. The server checks the same rule again. */
  document.querySelectorAll("input[data-digits]").forEach(function (input) {
    var max = parseInt(input.getAttribute("data-digits"), 10);
    if (!max) { return; }
    var counter = document.createElement("div");
    counter.className = "digit-count";
    counter.setAttribute("aria-hidden", "true");
    input.insertAdjacentElement("afterend", counter);
    /* data-format="cnic" shows the digits as 12345-1234567-1. The count is always of digits. */
    var dashed = input.getAttribute("data-format") === "cnic";
    /* The browser's length limit would cut a pasted "+92 4210112345671" before the digits are picked
       out, so with this script running the digits are capped here instead (the limit stays without it). */
    if (dashed) { input.removeAttribute("maxlength"); }
    function shape(digits) {
      if (!dashed) { return digits; }
      var out = digits.slice(0, 5);
      if (digits.length > 5) { out += "-" + digits.slice(5, 12); }
      if (digits.length > 12) { out += "-" + digits.slice(12, 13); }
      return out;
    }
    function clean() {
      var raw = input.value;
      var caret = input.selectionStart;
      var before = raw.slice(0, caret === null || caret === undefined ? raw.length : caret).replace(/\D/g, "").length;
      var v = raw.replace(/\D/g, "").slice(0, max);
      var shown = shape(v);
      if (shown !== raw) {
        input.value = shown;
        /* Keep the cursor after the same digit, so typing in the middle does not jump to the end. */
        if (document.activeElement === input) {
          var seen = 0, pos = 0;
          for (; pos < shown.length && seen < Math.min(before, v.length); pos++) {
            if (/\d/.test(shown.charAt(pos))) { seen++; }
          }
          try { input.setSelectionRange(pos, pos); } catch (e) { /* some inputs do not allow it */ }
        }
      }
      counter.textContent = v.length + "/" + max;
      counter.classList.toggle("is-full", v.length === max);
    }
    input.addEventListener("input", clean);
    input.addEventListener("paste", function () { setTimeout(clean, 0); });
    clean();
  });

  /* "I have never donated": the last-donation date is switched off and cleared while it is ticked */
  var neverBox = document.getElementById("id_never_donated");
  var lastDate = document.getElementById("id_last_donation_date");
  if (neverBox && lastDate) {
    var syncNever = function () {
      lastDate.disabled = neverBox.checked;
      if (neverBox.checked) { lastDate.value = ""; }
    };
    neverBox.addEventListener("change", syncNever);
    syncNever();
  }

  /* A box that only shows while its checkbox is ticked (the other-condition box) */
  document.querySelectorAll("[data-reveal-when]").forEach(function (box) {
    var check = document.getElementById(box.getAttribute("data-reveal-when"));
    if (!check) { return; }
    function sync() {
      if (check.checked) {
        if (box.hidden) { box.hidden = false; box.classList.add("reveal-in"); }
      } else {
        box.hidden = true;
        box.classList.remove("reveal-in");
      }
    }
    check.addEventListener("change", sync);
    sync();
  });

  /* Medical conditions: "None" cancels the others, any other choice cancels "None",
     and "Other" shows the box where the donor types the condition. */
  var conditions = document.querySelector("[data-conditions]");
  if (conditions) {
    var condBoxes = conditions.querySelectorAll("input[type=checkbox]");
    var otherBox = document.querySelector("[data-other-condition]");
    var syncOther = function () {
      var otherOn = false;
      condBoxes.forEach(function (b) { if (b.value === "other" && b.checked) { otherOn = true; } });
      if (otherBox) {
        if (otherOn && otherBox.hidden) { otherBox.hidden = false; otherBox.classList.add("reveal-in"); }
        if (!otherOn) { otherBox.hidden = true; otherBox.classList.remove("reveal-in"); }
      }
    };
    condBoxes.forEach(function (box) {
      box.addEventListener("change", function () {
        if (box.checked) {
          condBoxes.forEach(function (other) {
            if (other !== box && (box.value === "none" || other.value === "none")) { other.checked = false; }
          });
        }
        syncOther();
      });
    });
    syncOther();
  }

  /* Show / hide password */
  document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
    button.addEventListener("click", function () {
      var input = button.parentElement.querySelector("input");
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-label", show ? t("Hide password") : t("Show password"));
      button.querySelector("i").className = "bi " + (show ? "bi-eye-slash" : "bi-eye");
    });
  });

  /* Inline validation for forms marked data-guard. The server still checks everything again. */
  var holderOf = function (input) { return input.closest(".mb-3") || input.parentElement; };
  var validateField = function (input) {
    var holder = holderOf(input);
    var box = holder.querySelector(".field-error[data-client]");
    if (input.checkValidity()) {
      input.classList.remove("is-invalid");
      input.removeAttribute("aria-invalid");
      if (box) { box.remove(); }
      return true;
    }
    input.classList.add("is-invalid");
    input.setAttribute("aria-invalid", "true");
    if (!box) {
      box = document.createElement("div");
      box.className = "field-error";
      box.setAttribute("data-client", "");
      box.innerHTML = '<i class="bi bi-exclamation-circle-fill" aria-hidden="true"></i><span></span>';
      holder.appendChild(box);
    }
    box.lastElementChild.textContent = (input.validity.patternMismatch && input.title) ? input.title : input.validationMessage;
    return false;
  };
  var resetForm = function (form) {
    delete form.dataset.submitting;
    var button = form.querySelector("[data-submit]");
    if (button && button.dataset.label) {
      button.innerHTML = button.dataset.label;
      button.classList.remove("btn-loading");
      button.removeAttribute("aria-busy");
      delete button.dataset.label;
    }
  };

  /* Three-step wizard for the request form.
     The form is written as one plain form with <h2 class="form-section-title">
     headings. Without JavaScript that is exactly what you get: every field on
     one page, one submit button, nothing hidden. With JavaScript the headings
     become steps, so the person answers four questions at a time instead of
     nine. Nothing is removed from the DOM, so a required field that is out of
     view is still submitted with the rest. */
  document.querySelectorAll("form[data-wizard]").forEach(function (form) {
    var titles = form.querySelectorAll(".form-section-title");
    if (titles.length < 2) { return; }

    /* Group each heading with everything that follows it, up to the next one. */
    var steps = [];
    titles.forEach(function (title) {
      var group = document.createElement("div");
      group.className = "wizard-panel";
      title.before(group);
      var node = title;
      while (node && !(node !== title && node.classList && node.classList.contains("form-section-title"))) {
        var next = node.nextElementSibling;
        if (node.hasAttribute("data-wizard-end")) { break; }
        group.appendChild(node);
        node = next;
      }
      var desc = title.getAttribute("data-desc") || "";
      steps.push({ panel: group, label: title.textContent.trim(), desc: desc });
      /* The heading stays visible as the title of its step. A short line under
         it says what the step is for, as the side list does. */
      if (desc) {
        var note = document.createElement("p");
        note.className = "wizard-desc";
        note.textContent = desc;
        title.after(note);
      }
    });

    var current = 0;

    var nav = document.createElement("ol");
    nav.className = "wizard-steps";
    nav.setAttribute("aria-label", t("Steps"));
    steps.forEach(function (step, i) {
      if (i) {
        var line = document.createElement("li");
        line.className = "wz-line";
        line.setAttribute("aria-hidden", "true");
        nav.appendChild(line);
      }
      var li = document.createElement("li");
      li.className = "wz-step";
      var num = document.createElement("span");
      num.className = "wz-num";
      num.textContent = String(i + 1);
      var label = document.createElement("span");
      label.className = "wz-text";
      var name = document.createElement("b");
      name.textContent = step.label;
      label.appendChild(name);
      if (step.desc) {
        var sub = document.createElement("small");
        sub.textContent = step.desc;
        label.appendChild(sub);
      }
      li.append(num, label);
      nav.appendChild(li);
      step.chip = li;
      step.num = num;
    });
    form.prepend(nav);
    form.classList.add("wizard-on");

    var controls = document.createElement("div");
    controls.className = "wizard-controls";
    var back = document.createElement("button");
    back.type = "button";
    back.className = "btn btn-ghost";
    back.innerHTML = '<i class="bi bi-arrow-left" aria-hidden="true"></i> ' + t("Back");
    var next = document.createElement("button");
    next.type = "button";
    next.className = "btn btn-brand";
    next.innerHTML = t("Next") + ' <i class="bi bi-arrow-right" aria-hidden="true"></i>';
    controls.append(back, next);

    var submitButton = form.querySelector("[data-submit]");
    var submitHolder = submitButton ? (submitButton.closest("[data-wizard-end]") || submitButton) : null;
    if (submitHolder) { submitHolder.before(controls); }
    else { form.appendChild(controls); }

    function show(i) {
      current = i;
      steps.forEach(function (step, n) {
        step.panel.hidden = n !== i;
        step.chip.className = "wz-step" + (n === i ? " is-active" : (n < i ? " is-done" : ""));
        step.num.innerHTML = n < i ? '<i class="bi bi-check-lg"></i>' : String(n + 1);
        step.chip.setAttribute("aria-current", n === i ? "step" : "false");
      });
      var last = i === steps.length - 1;
      back.hidden = i === 0;
      next.hidden = last;
      if (submitHolder) { submitHolder.hidden = !last; }
      /* Move focus to the first field of the step so a keyboard user is not
         left at the bottom of the page after pressing Next. */
      var first = steps[i].panel.querySelector("input, select, textarea");
      if (first && document.activeElement !== document.body) { first.focus({ preventScroll: true }); }
      nav.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    next.addEventListener("click", function () {
      var bad = null;
      steps[current].panel.querySelectorAll("input, select, textarea").forEach(function (f) {
        if (f.type !== "hidden" && f.willValidate && !validateField(f) && !bad) { bad = f; }
      });
      if (bad) { bad.focus(); return; }
      show(Math.min(current + 1, steps.length - 1));
    });
    back.addEventListener("click", function () { show(Math.max(current - 1, 0)); });

    /* Submitting from the last step can still fail on a field two steps back.
       The guard below calls this so the person is shown the field it is
       complaining about instead of an error they cannot see. */
    form.wizardReveal = function (field) {
      var panel = field.closest(".wizard-panel");
      steps.forEach(function (step, n) { if (step.panel === panel) { show(n); } });
    };

    /* If the server sent the form back with errors, open the step that holds
       the first one rather than starting again from step one. */
    var firstServerError = form.querySelector(".field-error, .is-invalid");
    var startAt = 0;
    if (firstServerError) {
      steps.forEach(function (step, n) {
        if (step.panel.contains(firstServerError) && !startAt) { startAt = n; }
      });
    }
    show(startAt);
  });

  document.querySelectorAll("form[data-guard]").forEach(function (form) {
    form.noValidate = true;
    var fields = form.querySelectorAll("input, select, textarea");
    fields.forEach(function (field) {
      field.addEventListener("blur", function () { if (field.value !== "") { validateField(field); } });
      field.addEventListener("input", function () {
        var serverError = holderOf(field).querySelector('[id$="-error"]');
        if (serverError) { serverError.remove(); }
        if (field.classList.contains("is-invalid")) { validateField(field); }
      });
    });
    form.addEventListener("submit", function (event) {
      if (form.dataset.submitting === "1") { event.preventDefault(); return; }
      var firstBad = null;
      fields.forEach(function (field) {
        if (field.type !== "hidden" && field.willValidate && !validateField(field) && !firstBad) { firstBad = field; }
      });
      if (firstBad) {
        event.preventDefault();
        if (form.wizardReveal) { form.wizardReveal(firstBad); }
        firstBad.focus();
        return;
      }
      form.dataset.submitting = "1";
      var button = form.querySelector("[data-submit]");
      if (button) {
        button.dataset.label = button.innerHTML;
        button.classList.add("btn-loading");
        button.setAttribute("aria-busy", "true");
        button.innerHTML = SPINNER + (button.getAttribute("data-loading-text") || t("Please wait..."));
      }
      if (form.hasAttribute("data-demo")) {   /* style guide only: pretend to save */
        event.preventDefault();
        window.setTimeout(function () {
          resetForm(form);
          window.showSuccess({ title: "Account created", text: "This is only a demo, nothing was saved." });
        }, 1200);
      }
    });
  });
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) { document.querySelectorAll("form[data-guard]").forEach(resetForm); }
  });

  /* Home page glass cards: a soft spotlight follows the pointer (mouse devices only). */
  var homeBody = document.querySelector(".home-body");
  if (homeBody && !reduceMotion && window.matchMedia("(hover: hover)").matches) {
    homeBody.addEventListener("pointermove", function (event) {
      var card = event.target.closest && event.target.closest(".card-soft, .flow-card");
      if (!card) { return; }
      var box = card.getBoundingClientRect();
      card.style.setProperty("--mx", (event.clientX - box.left) + "px");
      card.style.setProperty("--my", (event.clientY - box.top) + "px");
    }, { passive: true });
  }

  /* Blood compatibility checker on the home page. */
  var widget = document.querySelector("[data-compat]");
  var dataEl = document.getElementById("compat-data");
  if (widget && dataEl) {
    var compat = JSON.parse(dataEl.textContent);
    /* Each blood type is wrapped in left-to-right isolate marks so "A+" and "O\u2212" keep their
       shape and their commas stay in place inside right-to-left sentences. */
    var pretty = function (t) { return "\u2066" + t.replace(/-$/, "\u2212") + "\u2069"; };
    var recipientButtons = widget.querySelectorAll("button[data-type]");
    var donorChips = widget.querySelectorAll("[data-donor]");
    var result = widget.querySelector("#compat-result");

    var select = function (type) {
      var allowed = compat[type] || [];
      recipientButtons.forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-type") === type ? "true" : "false");
      });
      widget.classList.add("has-selection");
      donorChips.forEach(function (chip, index) {
        chip.style.transitionDelay = reduceMotion ? "0ms" : (index * 25) + "ms";
        chip.classList.toggle("is-match", allowed.indexOf(chip.getAttribute("data-donor")) !== -1);
      });
      var text = fill(t("A patient with %(type)s blood can receive red blood cells from: %(list)s."),
                      { type: pretty(type), list: allowed.map(pretty).join(", ") });
      text += fill(t(" (%(n)s of %(total)s types)"), { n: allowed.length, total: donorChips.length });
      if (type === "O-") { text += t(" O\u2212 patients can only receive O\u2212."); }
      if (type === "AB+") { text += t(" AB+ is the universal recipient."); }
      result.textContent = text;
    };

    recipientButtons.forEach(function (b) {
      b.addEventListener("click", function () { select(b.getAttribute("data-type")); });
    });
  }

  /* Request form: asking for more units than the standard limit makes the reason
     required. The server enforces this too; this only makes it visible early. */
  var unitsInput = document.querySelector("input[data-unit-limit]");
  var reasonInput = document.querySelector("textarea[data-extra-reason]");
  if (unitsInput && reasonInput) {
    var unitLimit = parseInt(unitsInput.getAttribute("data-unit-limit"), 10);
    var reasonBlock = reasonInput.closest(".mb-3");
    var optionalTag = reasonBlock ? reasonBlock.querySelector(".optional") : null;
    var notice = document.createElement("div");
    notice.className = "extra-notice";
    notice.setAttribute("role", "status");
    notice.hidden = true;
    reasonBlock.insertBefore(notice, reasonInput.nextSibling);
    var syncReason = function () {
      var units = parseInt(unitsInput.value, 10);
      var over = !isNaN(units) && units > unitLimit;
      reasonInput.required = over;
      /* Hidden until it is needed, unless it already holds a reason or an error from the server. */
      reasonBlock.hidden = !over && !reasonInput.value.trim() && !reasonBlock.querySelector(".field-error");
      reasonBlock.classList.toggle("is-needed", over);
      if (optionalTag) { optionalTag.textContent = over ? t("(required)") : t("(optional)"); }
      notice.hidden = !over;
      if (over) {
        notice.textContent = fill(t("%(units)s units is more than %(limit)s. An admin has to approve this request before donors can see it, so please explain why this much blood is needed."),
          { units: units, limit: unitLimit });
      }
    };
    unitsInput.addEventListener("input", syncReason);
    syncReason();
  }

  /* Dashboard side panel: the fold button turns it into a thin icon strip and the
     choice is remembered in this browser. Without JavaScript the panel is simply open. */
  var dashToggle = document.querySelector("[data-dash-toggle]");
  var dashShell = document.querySelector(".dshell");
  if (dashToggle && dashShell) {
    var setFolded = function (folded, remember) {
      dashShell.classList.toggle("is-collapsed", folded);
      dashToggle.setAttribute("aria-expanded", folded ? "false" : "true");
      var label = folded ? t("Open the side panel") : t("Fold the side panel");
      dashToggle.setAttribute("title", label);
      dashToggle.setAttribute("aria-label", label);
      if (remember) { try { localStorage.setItem("bn-dash-folded", folded ? "1" : "0"); } catch (e) {} }
    };
    setFolded(dashShell.classList.contains("is-collapsed"), false);
    dashToggle.addEventListener("click", function () { setFolded(!dashShell.classList.contains("is-collapsed"), true); });
  }
  /* Confirm before the actions that cannot be taken back easily. A form marked
     data-confirm="..." asks first; Cancel leaves the page as it was. The question
     is set as text, never as HTML. Without Bootstrap's modal it falls back to the
     browser's own confirm box. */
  var confirmModal = null;
  var askToConfirm = function (message, onYes) {
    if (!window.bootstrap || !window.bootstrap.Modal) { if (window.confirm(message)) { onYes(); } return; }
    if (!confirmModal) {
      var holder = document.createElement("div");
      holder.className = "modal fade";
      holder.tabIndex = -1;
      holder.setAttribute("aria-labelledby", "confirmTitle");
      holder.setAttribute("aria-hidden", "true");
      holder.innerHTML =
        '<div class="modal-dialog modal-dialog-centered modal-sm"><div class="modal-content">' +
        '<div class="modal-header"><h2 class="modal-title h5" id="confirmTitle">' + t("Please confirm") + '</h2>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="' + t("Close") + '"></button></div>' +
        '<div class="modal-body"><p class="mb-0" data-confirm-text></p></div>' +
        '<div class="modal-footer"><button type="button" class="btn btn-ghost" data-bs-dismiss="modal">' + t("Cancel") + '</button>' +
        '<button type="button" class="btn btn-brand" data-confirm-yes>' + t("Yes, continue") + '</button></div></div></div>';
      document.body.appendChild(holder);
      confirmModal = { el: holder, modal: new window.bootstrap.Modal(holder), yes: null };
      holder.querySelector("[data-confirm-yes]").addEventListener("click", function () {
        var go = confirmModal.yes; confirmModal.yes = null; confirmModal.modal.hide();
        if (go) { go(); }
      });
    }
    confirmModal.el.querySelector("[data-confirm-text]").textContent = message;
    confirmModal.yes = onYes;
    confirmModal.modal.show();
  };
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.getAttribute || !form.getAttribute("data-confirm") || form.dataset.confirmed === "1") { return; }
    event.preventDefault();
    var submitter = event.submitter;
    askToConfirm(form.getAttribute("data-confirm"), function () {
      form.dataset.confirmed = "1";
      if (form.requestSubmit) { form.requestSubmit(submitter || undefined); } else { form.submit(); }
    });
  }, true);
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) { document.querySelectorAll("form[data-confirm]").forEach(function (f) { delete f.dataset.confirmed; }); }
  });
})();
