"""Static file graph of a project: what each file is, and what it imports.

No model is involved: files are analysed with plain parsing (``ast`` for Python,
patterns for the JS/TS family, CSS and HTML) into a one-line summary, the public
symbols, and the project-internal files they import.  A file whose size and
modification time did not change is **not read again** — that is the point of the
memory: agents get this map instead of re-reading the sources.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from elysium_engine.importer import SKIP_DIRS, detect_language
from elysium_engine.preview.paths import is_inside

MAX_FILE_BYTES = 200_000
MAX_FILES = 3_000
SUMMARY_CHARS = 240

_TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte", ".astro",
    ".html", ".htm", ".css", ".scss", ".md", ".rs", ".go", ".java", ".rb", ".php", ".sh", ".json", ".toml", ".yml", ".yaml",
}  # fmt: skip
_JS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro", ".json")
_SKIP_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock", "poetry.lock"}

_JS_IMPORT = re.compile(
    r"""(?:import\s+(?:[\w*\s{},$]+?\s+from\s+)?|export\s+(?:[\w*\s{},$]+?\s+from\s+)|require\(\s*|import\(\s*)['"]([^'"\n]+)['"]"""
)
_JS_EXPORT = re.compile(
    r"export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"
)
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?['"]?([^'")\s;]+)""")
_HTML_REF = re.compile(r"""(?:src|href)\s*=\s*['"]([^'":#?]+\.(?:js|mjs|css|ts))['"]""")
_RS_ITEM = re.compile(r"pub\s+(?:async\s+)?(?:fn|struct|enum|trait|mod)\s+(\w+)")


@dataclass(slots=True)
class Analysis:
    language: str | None
    summary: str
    symbols: list[str]
    raw_imports: list[str]  # specifiers exactly as written
    python_imports: list[tuple[int, str]] = field(default_factory=list)  # (level, module)


@dataclass(slots=True)
class ScannedFile:
    path: str
    size: int
    mtime_ns: int
    sha1: str
    analysis: Analysis


@dataclass(slots=True)
class ScanResult:
    changed: list[ScannedFile]
    unchanged: list[str]
    removed: list[str]
    skipped: int
    truncated: bool
    bytes_covered: int  # total size of every file in the map (what re-reading would cost)


def _first_comment(text: str) -> str:
    stripped = text.lstrip()
    match = re.match(r"/\*\*?\s*(.*?)\*/", stripped, re.S)
    if match:
        body = " ".join(line.strip(" *\t") for line in match.group(1).splitlines()).strip()
        if body:
            return body
    lines = []
    for line in stripped.splitlines()[:6]:
        if line.startswith(("//", "#!")) and not line.startswith("#!/"):
            lines.append(line.lstrip("/ !").strip())
        elif line.startswith("#") and not line.startswith("#!"):
            lines.append(line.lstrip("# ").strip())
        elif lines or line.strip():
            break
    return " ".join(x for x in lines if x)


def _compose(lead: str, symbols: list[str]) -> str:
    lead = " ".join(lead.split())
    parts = [lead[:140]] if lead else []
    if symbols:
        shown = ", ".join(symbols[:6]) + (f" (+{len(symbols) - 6})" if len(symbols) > 6 else "")
        parts.append(f"exports: {shown}")
    return " · ".join(parts)[:SUMMARY_CHARS]


def analyze(rel_path: str, text: str) -> Analysis:
    suffix = Path(rel_path).suffix.lower()
    language = detect_language(rel_path)
    if suffix == ".py":
        symbols: list[str] = []
        imports: list[tuple[int, str]] = []
        doc = ""
        try:
            tree = ast.parse(text)
            doc = (ast.get_docstring(tree) or "").strip().splitlines()[0] if ast.get_docstring(tree) else ""
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
                    symbols.append(node.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports += [(0, alias.name) for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports.append((node.level, node.module or ""))
                    if node.module is None or node.level:
                        imports += [(node.level, alias.name) for alias in node.names]
        except (SyntaxError, ValueError):
            doc = _first_comment(text)
        return Analysis(language, _compose(doc, symbols), symbols, [], imports)
    if suffix in _JS_SUFFIXES or suffix in {".astro"}:
        symbols = list(dict.fromkeys(_JS_EXPORT.findall(text)))
        return Analysis(language, _compose(_first_comment(text), symbols), symbols, list(dict.fromkeys(_JS_IMPORT.findall(text))))
    if suffix in {".css", ".scss"}:
        return Analysis(language, _compose(_first_comment(text), []), [], list(dict.fromkeys(_CSS_IMPORT.findall(text))))
    if suffix in {".html", ".htm"}:
        title = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        return Analysis(language, (title.group(1).strip() if title else "")[:SUMMARY_CHARS], [], list(dict.fromkeys(_HTML_REF.findall(text))))
    if suffix == ".md":
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        heading = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), "")
        body = next((ln for ln in lines if not ln.startswith("#")), "")
        return Analysis(language, _compose(f"{heading} — {body}" if heading and body else heading or body, []), [], [])
    if suffix == ".rs":
        symbols = list(dict.fromkeys(_RS_ITEM.findall(text)))
        return Analysis(language, _compose(_first_comment(text).lstrip("/! "), symbols), symbols, [])
    return Analysis(language, _compose(_first_comment(text), []), [], [])


def _py_candidates(base: Path, parts: list[str]) -> list[Path]:
    target = base.joinpath(*parts) if parts else base
    return [target.with_suffix(".py"), target / "__init__.py"]


def resolve_imports(root: Path, rel_path: str, analysis: Analysis, known: set[str]) -> tuple[list[str], list[str]]:
    """Project-internal files imported by ``rel_path`` and the external packages."""
    here = Path(rel_path).parent
    internal: list[str] = []
    external: list[str] = []

    def add_internal(path: Path) -> bool:
        posix = path.as_posix()
        if posix in known and posix != rel_path:
            if posix not in internal:
                internal.append(posix)
            return True
        return False

    for level, module in analysis.python_imports:
        parts = [p for p in module.split(".") if p]
        if not parts:
            continue
        if level:  # relative: one dot = this folder, two = its parent, ...
            base = here
            for _ in range(level - 1):
                base = base.parent
            bases = [base]
        else:
            bases = [Path("."), Path("src")]
        hit = False
        for base in bases:
            for cand in _py_candidates(base, parts):
                hit = add_internal(Path(os.path.normpath(cand))) or hit
        if not hit and level == 0 and parts:
            external.append(parts[0])

    for spec in analysis.raw_imports:
        if spec.startswith((".", "/")) or spec.startswith("@/") or spec.startswith("~/"):
            if spec.startswith("@/") or spec.startswith("~/"):
                base_candidates = [Path("src") / spec[2:], Path(spec[2:])]
            elif spec.startswith("/"):
                base_candidates = [Path(spec.lstrip("/"))]
            else:
                base_candidates = [here / spec]
            hit = False
            for base in base_candidates:
                norm = Path(os.path.normpath(base))
                options = [norm, *[norm.with_name(norm.name + s) for s in _JS_SUFFIXES], *[norm / f"index{s}" for s in _JS_SUFFIXES]]
                options += [norm.with_suffix(s) for s in (".ts", ".tsx")] if norm.suffix == ".js" else []
                for option in options:
                    if add_internal(option):
                        hit = True
                        break
                if hit:
                    break
        else:
            name = spec.split("/")[0] if not spec.startswith("@") else "/".join(spec.split("/")[:2])
            if name and name not in external:
                external.append(name)
    return internal, external


def _walk(root: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if name in _SKIP_NAMES or name.startswith("."):
                continue
            path = Path(current) / name
            if path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            found.append((path.relative_to(root).as_posix(), path))
    return found


def scan_folder(root: Path, existing: dict[str, tuple[int, int, str]], max_files: int = MAX_FILES) -> ScanResult:
    """Scan ``root`` (a validated real path). ``existing`` maps path -> (size, mtime_ns, sha1)."""
    changed: list[ScannedFile] = []
    unchanged: list[str] = []
    skipped = 0
    covered = 0
    truncated = False
    seen: set[str] = set()
    for count, (rel, path) in enumerate(_walk(root)):
        if count >= max_files:
            truncated = True
            break
        if not is_inside(root, path):  # a symlink leaving the project is not indexed
            skipped += 1
            continue
        try:
            stat = path.stat()
        except OSError:
            skipped += 1
            continue
        if stat.st_size > MAX_FILE_BYTES:
            skipped += 1
            continue
        seen.add(rel)
        covered += stat.st_size
        old = existing.get(rel)
        if old is not None and old[0] == stat.st_size and old[1] == stat.st_mtime_ns:
            unchanged.append(rel)  # not read: nothing changed
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            skipped += 1
            seen.discard(rel)
            covered -= stat.st_size
            continue
        digest = hashlib.sha1(raw).hexdigest()  # noqa: S324 - change detection, not security
        text = raw.decode("utf-8", errors="replace")
        changed.append(ScannedFile(rel, stat.st_size, stat.st_mtime_ns, digest, analyze(rel, text)))
    removed = [p for p in existing if p not in seen] if not truncated else []
    return ScanResult(changed, unchanged, removed, skipped, truncated, covered)
