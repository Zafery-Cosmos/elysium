// Real direct-download detection: fetches the latest GitHub release, figures
// out which asset matches the visitor's OS (and best-effort CPU arch on
// macOS), and points every download control straight at the matching
// browser_download_url — never just "here's the releases page, good luck".
(function () {
  "use strict";

  var REPO = "Zafery-Cosmos/elysium";
  var API_URL = "https://api.github.com/repos/" + REPO + "/releases/latest";
  var RELEASES_URL = "https://github.com/" + REPO + "/releases/latest";

  // name -> matcher, in priority order per OS. Only real installer assets;
  // .sig files and raw archives are excluded from the picks below.
  var MATCHERS = {
    "windows-msi": /\.msi$/i,
    "windows-exe": /-setup\.exe$/i,
    "macos-arm64": /aarch64\.dmg$/i,
    "macos-x64": /(x64|x86_64|intel)[^/]*\.dmg$/i,
    "linux-appimage": /\.AppImage$/i,
    "linux-deb": /\.deb$/i,
    "linux-rpm": /\.rpm$/i,
  };

  function detectOS() {
    var platform = (navigator.platform || "").toLowerCase();
    var ua = (navigator.userAgent || "").toLowerCase();
    if (platform.indexOf("win") !== -1 || ua.indexOf("windows") !== -1) return "windows";
    if (platform.indexOf("mac") !== -1 || ua.indexOf("macintosh") !== -1) return "macos";
    if (platform.indexOf("linux") !== -1 || ua.indexOf("linux") !== -1) return "linux";
    return "unknown";
  }

  // Best-effort only: browsers don't expose CPU architecture directly. This
  // reads the (unmasked) WebGL renderer string, which names the GPU and
  // reliably contains "Apple M<n>" on Apple Silicon. Returns null — not
  // false — when it can't tell, so callers don't silently assume Intel.
  function detectAppleSilicon() {
    try {
      var canvas = document.createElement("canvas");
      var gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      var info = gl && gl.getExtension("WEBGL_debug_renderer_info");
      var renderer = info && gl.getParameter(info.UNMASKED_RENDERER_WEBGL);
      if (!renderer) return null;
      if (/Apple M\d/i.test(renderer) || /Apple GPU/i.test(renderer)) return true;
      if (/Intel/i.test(renderer)) return false;
    } catch (e) {
      // WebGL unavailable/blocked — fall through to "unknown".
    }
    return null;
  }

  function bytesToLabel(bytes) {
    if (!bytes) return "";
    var mb = bytes / (1024 * 1024);
    return mb >= 1000 ? (mb / 1024).toFixed(1) + " Go" : Math.round(mb) + " Mo";
  }

  function pick(assets, key) {
    var pattern = MATCHERS[key];
    for (var i = 0; i < assets.length; i++) {
      if (pattern.test(assets[i].name) && !/\.sig$/i.test(assets[i].name)) {
        return assets[i];
      }
    }
    return null;
  }

  function recommendedKey(os, appleSilicon) {
    if (os === "windows") return "windows-msi";
    if (os === "linux") return "linux-appimage";
    if (os === "macos") return appleSilicon === false ? "macos-x64" : "macos-arm64";
    return null;
  }

  function fillCard(el, asset, fallbackNote) {
    if (!el) return;
    var link = el.querySelector("[data-role=link]");
    var size = el.querySelector("[data-role=size]");
    if (asset) {
      link.href = asset.browser_download_url;
      link.removeAttribute("aria-disabled");
      link.classList.remove("is-disabled");
      if (size) size.textContent = bytesToLabel(asset.size);
    } else {
      link.href = RELEASES_URL;
      link.target = "_blank";
      link.rel = "noopener";
      if (size) size.textContent = fallbackNote || "voir sur GitHub";
    }
  }

  function render(release) {
    var version = release.tag_name || "";
    var assets = release.assets || [];
    var versionEl = document.getElementById("dl-version");
    if (versionEl) {
      versionEl.textContent = version ? "Version " + version : "";
    }

    var os = detectOS();
    var appleSilicon = os === "macos" ? detectAppleSilicon() : null;
    var recKey = recommendedKey(os, appleSilicon);
    var recAsset = recKey ? pick(assets, recKey) : null;

    // Primary hero CTA — swaps from "detecting" to a real, OS-matched link.
    var hero = document.getElementById("dl-hero");
    var heroLabel = document.getElementById("dl-hero-label");
    var heroSub = document.getElementById("dl-hero-sub");
    if (hero) {
      if (recAsset) {
        hero.href = recAsset.browser_download_url;
        hero.classList.remove("is-disabled");
        heroLabel.textContent = "Télécharger pour " + osLabel(os) + " (" + extOf(recAsset.name) + ")";
        heroSub.textContent = bytesToLabel(recAsset.size) + " · " + version;
      } else {
        hero.href = RELEASES_URL;
        hero.target = "_blank";
        hero.rel = "noopener";
        hero.classList.remove("is-disabled");
        heroLabel.textContent = "Voir toutes les versions sur GitHub";
        heroSub.textContent =
          os === "unknown"
            ? "Système non détecté automatiquement."
            : "Aucun binaire correspondant trouvé pour cette version.";
      }
    }

    // Full grid: every platform, always populated with a real asset link.
    fillCard(document.getElementById("card-windows-msi"), pick(assets, "windows-msi"));
    fillCard(document.getElementById("card-windows-exe"), pick(assets, "windows-exe"));
    fillCard(
      document.getElementById("card-macos-arm64"),
      pick(assets, "macos-arm64"),
    );
    fillCard(
      document.getElementById("card-macos-x64"),
      pick(assets, "macos-x64"),
      "pas encore publié pour cette version",
    );
    fillCard(document.getElementById("card-linux-appimage"), pick(assets, "linux-appimage"));
    fillCard(document.getElementById("card-linux-deb"), pick(assets, "linux-deb"));
    fillCard(document.getElementById("card-linux-rpm"), pick(assets, "linux-rpm"));

    // Mark the recommended card so the honest "auto-detect" claim is visible,
    // not just implied by the hero button.
    var recCardId = {
      "windows-msi": "card-windows-msi",
      "macos-arm64": "card-macos-arm64",
      "macos-x64": "card-macos-x64",
      "linux-appimage": "card-linux-appimage",
    }[recKey];
    if (recCardId) {
      var recCard = document.getElementById(recCardId);
      if (recCard) recCard.classList.add("dlcard-rec");
    }
  }

  function osLabel(os) {
    if (os === "windows") return "Windows";
    if (os === "macos") return "macOS";
    if (os === "linux") return "Linux";
    return "votre système";
  }

  function extOf(name) {
    var m = /\.([a-z0-9]+)$/i.exec(name);
    return m ? "." + m[1] : "";
  }

  function fail() {
    var hero = document.getElementById("dl-hero");
    var heroLabel = document.getElementById("dl-hero-label");
    var heroSub = document.getElementById("dl-hero-sub");
    if (hero) {
      hero.href = RELEASES_URL;
      hero.target = "_blank";
      hero.rel = "noopener";
      hero.classList.remove("is-disabled");
      heroLabel.textContent = "Voir les téléchargements sur GitHub";
      heroSub.textContent = "Détection automatique indisponible pour le moment.";
    }
    document.querySelectorAll("[data-role=link]").forEach(function (link) {
      link.href = RELEASES_URL;
      link.target = "_blank";
      link.rel = "noopener";
      link.classList.remove("is-disabled");
    });
  }

  fetch(API_URL, { headers: { Accept: "application/vnd.github+json" } })
    .then(function (res) {
      if (!res.ok) throw new Error("GitHub API " + res.status);
      return res.json();
    })
    .then(render)
    .catch(fail);
})();
