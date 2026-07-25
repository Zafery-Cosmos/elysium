// Typewriter of example ideas + theme toggle (persisted, respects system pref).
(function () {
  "use strict";

  // ---- Typewriter ----
  var phrases = [
    "une application de réservation de restaurants",
    "un CRM pour gérer mes clients",
    "un site e-commerce avec paiement",
    "une API REST avec base de données",
    "un tableau de bord d'analytics",
    "un clone de Netflix",
  ];
  var el = document.getElementById("tw");
  var reduced =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (el) {
    if (reduced) {
      var i = 0;
      el.textContent = phrases[0];
      setInterval(function () {
        i = (i + 1) % phrases.length;
        el.textContent = phrases[i];
      }, 2500);
    } else {
      var p = 0,
        c = 0,
        deleting = false;
      var tick = function () {
        var word = phrases[p];
        el.textContent = word.slice(0, c);
        var delay;
        if (!deleting) {
          c++;
          delay = 45;
          if (c > word.length) {
            deleting = true;
            delay = 1500;
          }
        } else {
          c--;
          delay = 25;
          if (c === 0) {
            deleting = false;
            p = (p + 1) % phrases.length;
            delay = 350;
          }
        }
        setTimeout(tick, delay);
      };
      tick();
    }
  }

  // ---- Theme toggle ----
  var root = document.documentElement;
  var stored = null;
  try {
    stored = localStorage.getItem("elysium-site-theme");
  } catch (e) {}
  var systemDark =
    window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  root.setAttribute("data-theme", stored || (systemDark ? "dark" : "light"));

  var btn = document.getElementById("themeToggle");
  if (btn) {
    btn.addEventListener("click", function () {
      var next =
        root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        localStorage.setItem("elysium-site-theme", next);
      } catch (e) {}
    });
  }
})();
