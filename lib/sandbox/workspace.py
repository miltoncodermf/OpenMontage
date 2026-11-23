"""Host-side workspace preparation for sandbox captures (spec §5.7).

Copies a repo subset to ``projects/<id>/.sandbox/<capture_id>/workspace`` excluding
secrets and VCS credentials, and redacts secret-looking content in text files. The
container only ever sees this copy — never ``$HOME``, ``~/.ssh``, the repo root, or ``.env``.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any

from tools.ingestion.universal_ingestor import _is_secret_filename, _redact_secrets

# Directories never copied.
EXCLUDED_DIRS = {".git", ".hg", ".svn", ".ssh", ".aws", ".gnupg", "node_modules", ".venv", "venv", "__pycache__", ".cache"}
# Extra file patterns beyond the ingestor's secret filename filter.
EXTRA_SECRET_PATTERNS = ["*.keystore", "*.jks", "*.kdbx", ".netrc", ".npmrc", ".pypirc", ".git-credentials", "*.tfstate", "*.tfvars"]
TEXT_SUFFIXES = {
    ".md", ".txt", ".rst", ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sh", ".html", ".css", ".rs", ".go", ".c", ".cpp", ".h", ".sql", ".rb", ".java", ".kt", ".swift",
}
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024


def is_excluded_file(name: str) -> bool:
    return _is_secret_filename(name) or any(fnmatch.fnmatch(name, p) for p in EXTRA_SECRET_PATTERNS)


def prepare_workspace(
    source: Path,
    dest: Path,
    focus: list[str] | None = None,
) -> dict[str, Any]:
    """Copy ``source`` (optionally limited to ``focus`` sub-paths) into ``dest``.

    Returns a report: ``copied``, ``excluded`` (path -> reason), ``redacted`` files.
    Symlinks are never followed or copied.
    """
    source = Path(source).resolve()
    dest = Path(dest)
    if not source.is_dir():
        raise ValueError(f"workspace source is not a directory: {source}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    dest_resolved = dest.resolve()
    if dest_resolved == source:
        raise ValueError("dest must not equal source")
    # If dest lives inside source (e.g. projects/<id>/.sandbox inside the repo), never copy
    # the directories on the path to it — that would recurse into the sandbox itself.
    dest_ancestors = {a for a in [dest_resolved, *dest_resolved.parents] if a != source and a.is_relative_to(source)}

    report: dict[str, Any] = {"copied": [], "excluded": {}, "redacted": []}
    total = 0
    focus_norm = [f.strip("/") for f in (focus or [])]

    def in_focus(rel: str) -> bool:
        return not focus_norm or any(rel == f or rel.startswith(f + "/") or f.startswith(rel + "/") for f in focus_norm)

    for root, dirs, files in os.walk(source, followlinks=False):
        rel_root = Path(root).relative_to(source)
        keep = []
        for d in sorted(dirs):
            rel = (rel_root / d).as_posix()
            full = Path(root) / d
            if full.resolve() in dest_ancestors:
                report["excluded"][rel + "/"] = "contains the sandbox destination"
            elif d in EXCLUDED_DIRS:
                report["excluded"][rel + "/"] = "excluded directory"
            elif full.is_symlink():
                report["excluded"][rel + "/"] = "symlinked directory"
            elif not in_focus(rel):
                continue
            else:
                keep.append(d)
        dirs[:] = keep
        for name in sorted(files):
            rel = (rel_root / name).as_posix() if str(rel_root) != "." else name
            src = Path(root) / name
            if src.is_symlink():
                report["excluded"][rel] = "symlink"
                continue
            if not in_focus(rel):
                continue
            if is_excluded_file(name):
                report["excluded"][rel] = "secret filename"
                continue
            size = src.stat().st_size
            if size > MAX_FILE_BYTES:
                report["excluded"][rel] = f"larger than {MAX_FILE_BYTES} bytes"
                continue
            if total + size > MAX_TOTAL_BYTES:
                report["excluded"][rel] = "workspace size ceiling reached"
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix.lower() in TEXT_SUFFIXES:
                text = src.read_text(encoding="utf-8", errors="replace")
                redacted = _redact_secrets(text)
                out.write_text(redacted, encoding="utf-8")
                if redacted != text:
                    report["redacted"].append(rel)
            else:
                shutil.copy2(src, out)
            total += size
            report["copied"].append(rel)
    report["total_bytes"] = total
    return report
