"""Tiny loopback-only static server with live reload, for plain HTML projects.

* Binds 127.0.0.1 on an OS-assigned port (no port guessing, no race).
* Serves only files whose *real* path is inside the project folder, and never
  dotfiles (``.env``, ``.git``...) or ``node_modules``.
* Injects a small script into HTML pages that polls ``/__elysium/version`` and
  reloads the page when a file in the project changed.
"""

from __future__ import annotations

import json
import os
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from elysium_engine.preview.paths import is_inside

VERSION_PATH = "/__elysium/version"
_SKIP = {"node_modules", ".git"}

_RELOAD_SNIPPET = (
    "<script>(function(){var v=null;function t(){fetch('"
    + VERSION_PATH
    + "',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){"
    "if(v!==null&&d.v!==v){location.reload();return}v=d.v}).catch(function(){})}"
    "setInterval(t,700);t()})();</script>"
)


def tree_signature(root: Path, limit: int = 5000) -> str:
    """Cheap change detector: file count + newest mtime (+ total size)."""
    count = 0
    newest = 0
    size = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            try:
                stat = os.stat(os.path.join(current, name))
            except OSError:
                continue
            count += 1
            size += stat.st_size
            newest = max(newest, stat.st_mtime_ns)
            if count >= limit:
                return f"{count}:{newest}:{size}"
    return f"{count}:{newest}:{size}"


class _Handler(SimpleHTTPRequestHandler):
    server_version = "ElysiumPreview"

    def __init__(self, *args, root: Path, signature, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._root = root
        self._signature = signature
        super().__init__(*args, directory=str(root), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # keep the engine log free of per-request noise

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _allowed(self, translated: str) -> bool:
        path = Path(translated)
        if not is_inside(self._root, path):
            return False
        try:
            relative = path.resolve().relative_to(self._root)
        except ValueError:
            return False
        return not any(part.startswith(".") or part in _SKIP for part in relative.parts)

    def _safe_index(self, folder: Path) -> Path | None:
        """The folder's index page, unless it is a link leading out of the project."""
        for name in ("index.html", "index.htm"):
            candidate = folder / name
            if candidate.is_file():
                return candidate if self._allowed(str(candidate)) else None
        return None

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == VERSION_PATH:
            body = json.dumps({"v": self._signature()}).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        translated = self.translate_path(self.path)
        if not self._allowed(translated):
            self.send_error(HTTPStatus.FORBIDDEN, "Not available in the preview")
            return
        target = Path(translated)
        if target.is_dir():
            index = self._safe_index(target)
            if index is None:  # never list a folder: the names may be sensitive
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not urlsplit(self.path).path.endswith("/"):
                super().do_GET()  # redirects to "/sub/" so relative assets resolve
                return
            target = index
        if target.suffix.lower() in {".html", ".htm"} and target.is_file():
            try:
                html = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            lowered = html.lower()
            at = lowered.rfind("</body>")
            html = html[:at] + _RELOAD_SNIPPET + html[at:] if at != -1 else html + _RELOAD_SNIPPET
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        translated = self.translate_path(self.path)
        if not self._allowed(translated):
            self.send_error(HTTPStatus.FORBIDDEN)
        elif Path(translated).is_dir() and self._safe_index(Path(translated)) is None:
            self.send_error(HTTPStatus.NOT_FOUND)
        else:
            super().do_HEAD()


class StaticPreviewServer:
    """Runs :class:`_Handler` in a daemon thread."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: tuple[float, str] = (0.0, "")
        self._lock = threading.Lock()
        handler = partial(_Handler, root=root, signature=self._signature)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="static-preview")

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    def _signature(self) -> str:
        with self._lock:
            now = time.monotonic()
            if now - self._cache[0] > 0.4:
                self._cache = (now, tree_signature(self.root))
            return self._cache[1]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
