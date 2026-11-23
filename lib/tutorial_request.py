"""Turn a free-form ``/tutorial`` request into a topic-tutorial project.

The ``/tutorial`` plugin command passes everything the owner typed (a folder, a
GitHub URL, a web page, a document, a plain-text topic, plus a few options) to
this module. It classifies each input, prepares it for the v3 inputs contract
(``topic`` / ``repos`` / ``urls`` / ``pdfs``), creates the project workspace and
writes:

- ``projects/<id>/inputs/inputs.yaml``   (validated against the inputs schema)
- ``projects/<id>/inputs/request.json``  (length, aspect, presenter, audience, raw request)

Preparation steps:
- a GitHub/GitLab/Bitbucket repo URL is shallow-cloned into ``inputs/repos/<name>``;
- a ``.md`` / ``.txt`` / ``.rst`` / ``.docx`` / ``.doc`` / ``.rtf`` / ``.html``
  document is converted to PDF (``textutil`` + ``cupsfilter``, both built into
  macOS) into ``inputs/docs/`` because the v3 contract reads only PDFs;
- local folders and PDFs are referenced in place (absolute paths), never copied
  or modified.

CLI (run from the OpenMontage repo root)::

    python -m lib.tutorial_request --cwd "$PWD" . https://docs.example.com "a topic" --length 5

Prints one JSON object describing the project (or the error) on stdout.
Exit code 0 = project created, 2 = bad request.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.inputs_contract import InputsError, check_inputs_exist, load_inputs  # noqa: E402

PIPELINE = "topic-tutorial"
ASPECTS = ("16:9", "9:16", "both")
CONVERTIBLE_DOCS = {".md", ".markdown", ".txt", ".rst", ".docx", ".doc", ".rtf", ".html", ".htm"}
TEXTUTIL_DOCS = {".docx", ".doc", ".rtf", ".html", ".htm"}
REPO_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
REPO_URL_RE = re.compile(r"^/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?(?:/(?:tree|blob|-/tree)/[^/]+(?P<sub>/.*)?)?/?$")


class RequestError(ValueError):
    """The request cannot be turned into a project."""


@dataclass
class Classified:
    repos: list[dict[str, Any]] = field(default_factory=list)  # {"path": str, "focus"?: [...]} or {"clone": url, "name": str, "focus"?}
    urls: list[str] = field(default_factory=list)
    pdfs: list[str] = field(default_factory=list)
    docs: list[Path] = field(default_factory=list)  # documents to convert to PDF
    topic_words: list[str] = field(default_factory=list)


def repo_url_parts(url: str) -> tuple[str, str, str | None] | None:
    """(clone_url, name, subpath) for a code-host repo URL, else None."""
    p = urlparse(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    if host not in REPO_HOSTS:
        return None
    m = REPO_URL_RE.match(p.path)
    if not m:
        return None
    name = m.group("name")
    sub = (m.group("sub") or "").strip("/") or None
    return f"https://{host}/{m.group('owner')}/{name}.git", name, sub


def classify(tokens: list[str], cwd: Path) -> Classified:
    """Sort raw request tokens into repos / urls / pdfs / docs / topic words."""
    out = Classified()
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if re.match(r"^https?://", tok, re.I):
            parts = repo_url_parts(tok)
            if parts:
                clone, name, sub = parts
                entry: dict[str, Any] = {"clone": clone, "name": name}
                if sub:
                    entry["focus"] = [sub]
                out.repos.append(entry)
            else:
                out.urls.append(tok)
            continue
        looks_like_path = tok.startswith(("./", "../", "/", "~")) or tok in (".", "..")
        candidate = (cwd / Path(tok).expanduser()).resolve() if not Path(tok).expanduser().is_absolute() else Path(tok).expanduser().resolve()
        if candidate.is_dir():
            out.repos.append({"path": str(candidate)})
        elif candidate.is_file():
            suffix = candidate.suffix.lower()
            if suffix == ".pdf":
                out.pdfs.append(str(candidate))
            elif suffix in CONVERTIBLE_DOCS:
                out.docs.append(candidate)
            else:
                raise RequestError(
                    f"unsupported file type {suffix or '(none)'}: {tok}. "
                    "Supported: folders, PDF, Markdown/text, Word (.docx/.doc), RTF, HTML, web and repo URLs, plain topics."
                )
        elif looks_like_path:
            raise RequestError(f"path not found: {tok} (looked in {cwd})")
        else:
            out.topic_words.append(tok)
    return out


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:max_len].rstrip("-")) or "tutorial"


def default_title(c: Classified) -> str:
    if c.topic_words:
        return " ".join(c.topic_words)
    if c.repos:
        r = c.repos[0]
        return r.get("name") or Path(r["path"]).name
    if c.urls:
        return urlparse(c.urls[0]).hostname or "web page"
    if c.pdfs:
        return Path(c.pdfs[0]).stem
    if c.docs:
        return c.docs[0].stem
    return "tutorial"


def unique_project_id(base: str, projects_dir: Path) -> str:
    stem = f"tutorial-{slugify(base)}-{date.today():%Y%m%d}"
    pid, n = stem, 2
    while (projects_dir / pid).exists():
        pid, n = f"{stem}-{n}", n + 1
    return pid


def convert_to_pdf(src: Path, dest_dir: Path) -> Path:
    """Convert a text-like document to PDF with macOS built-ins (textutil + cupsfilter)."""
    if not shutil.which("cupsfilter"):
        raise RequestError(f"cannot convert {src.name} to PDF: cupsfilter not found (macOS only). Export it to PDF and pass the PDF.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slugify(src.stem, 60)}.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        text_file = Path(tmp) / "doc.txt"
        if src.suffix.lower() in TEXTUTIL_DOCS:
            if not shutil.which("textutil"):
                raise RequestError(f"cannot read {src.name}: textutil not found (macOS only). Export it to PDF and pass the PDF.")
            subprocess.run(["textutil", "-convert", "txt", "-output", str(text_file), str(src)], check=True, capture_output=True)
        else:
            text_file.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        if not text_file.read_text(encoding="utf-8", errors="replace").strip():
            raise RequestError(f"document is empty: {src}")
        with open(dest, "wb") as fh:
            subprocess.run(["cupsfilter", "-m", "application/pdf", str(text_file)], check=True, stdout=fh, stderr=subprocess.DEVNULL)
    if dest.stat().st_size == 0:
        raise RequestError(f"PDF conversion produced an empty file for {src}")
    return dest


def clone_repo(clone_url: str, dest: Path) -> Path:
    if not shutil.which("git"):
        raise RequestError("git is not installed; cannot clone repo URLs")
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["git", "clone", "--depth", "1", "--quiet", clone_url, str(dest)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RequestError(f"git clone failed for {clone_url}: {proc.stderr.strip()[:300]}")
    return dest


def locked_profiles(profile_root: Path) -> list[str]:
    out = []
    if not profile_root.is_dir():
        return out
    for d in sorted(profile_root.iterdir()):
        pj = d / "profile.json"
        if not pj.is_file():
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("locked") and not data.get("standin"):
            out.append(d.name)
    return out


def resolve_presenter(requested: str | None, profile_root: Path) -> tuple[str | None, str]:
    """(profile_id or None, note)."""
    if requested and requested.lower() == "none":
        return None, "no presenter (owner asked)"
    locked = locked_profiles(profile_root)
    if requested:
        if requested not in locked:
            raise RequestError(f"presenter profile '{requested}' is not a locked profile (locked: {locked or 'none'})")
        return requested, f"presenter profile '{requested}'"
    if len(locked) == 1:
        return locked[0], f"presenter profile '{locked[0]}' (the only locked profile)"
    if not locked:
        return None, "no locked presenter profile found; run presenter-onboarding or continue without a presenter"
    raise RequestError(f"several locked presenter profiles {locked}; pass --presenter <id> or --presenter none")


def build_project(
    tokens: list[str],
    *,
    cwd: Path,
    length_min: float | None = None,
    aspect: str = "16:9",
    presenter: str | None = None,
    audience: str | None = None,
    title: str | None = None,
    project_id: str | None = None,
    projects_dir: Path | None = None,
    profile_root: Path | None = None,
) -> dict[str, Any]:
    """Create the project and return a summary. Raises RequestError on a bad request."""
    from lib.checkpoint import PROJECTS_DIR, init_project
    from lib.presenter_profile import profile_root as default_profile_root

    projects_dir = Path(projects_dir or PROJECTS_DIR)
    profile_root = Path(profile_root or default_profile_root())
    if aspect not in ASPECTS:
        raise RequestError(f"--aspect must be one of {ASPECTS}")
    if length_min is not None and not (0.5 <= length_min <= 30):
        raise RequestError("--length must be between 0.5 and 30 minutes")

    c = classify(tokens, cwd)
    if not (c.repos or c.urls or c.pdfs or c.docs or c.topic_words):
        raise RequestError("nothing to make a tutorial about: pass a folder, URL, document or topic")
    topic = " ".join(c.topic_words).strip()
    if topic and len(topic) < 3:
        raise RequestError(f"topic is too short: '{topic}'")

    presenter_id, presenter_note = resolve_presenter(presenter, profile_root)
    title = title or default_title(c)
    pid = project_id or unique_project_id(title, projects_dir)
    if project_id and (projects_dir / project_id).exists():
        raise RequestError(f"project already exists: {project_id}")

    project_dir = init_project(pid, title=title[:120], pipeline_type=PIPELINE, pipeline_dir=projects_dir)
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    try:
        repos: list[dict[str, Any]] = []
        for r in c.repos:
            if "clone" in r:
                path = clone_repo(r["clone"], inputs_dir / "repos" / slugify(r["name"], 60))
                entry = {"path": str(path)}
            else:
                entry = {"path": r["path"]}
            if r.get("focus"):
                entry["focus"] = r["focus"]
            repos.append(entry)
        pdfs = list(c.pdfs) + [str(convert_to_pdf(d, inputs_dir / "docs")) for d in c.docs]

        spec: dict[str, Any] = {}
        if topic:
            spec["topic"] = topic
        if repos:
            spec["repos"] = repos
        if c.urls:
            spec["urls"] = c.urls
        if pdfs:
            spec["pdfs"] = pdfs
        inputs_path = inputs_dir / "inputs.yaml"
        inputs_path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
        load_inputs(inputs_path)
        problems = check_inputs_exist(spec, project_dir)
        if problems:
            raise RequestError("; ".join(problems))
    except (RequestError, InputsError, subprocess.CalledProcessError) as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise RequestError(str(exc)) from exc

    request = {
        "version": "1.0",
        "pipeline": PIPELINE,
        "raw_tokens": tokens,
        "invoked_from": str(cwd),
        "length_min": length_min,
        "aspect": aspect,
        "presenter_profile": presenter_id,
        "presenter_note": presenter_note,
        "audience": audience,
        "converted_docs": [{"source": str(d), "pdf": p} for d, p in zip(c.docs, pdfs[len(c.pdfs):])],
    }
    (inputs_dir / "request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "project_id": pid,
        "project_dir": str(project_dir),
        "title": title,
        "inputs": spec,
        "request": {k: request[k] for k in ("length_min", "aspect", "presenter_profile", "presenter_note", "audience")},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lib.tutorial_request", description=__doc__.split("\n\n")[0])
    ap.add_argument("--cwd", default=".", help="folder the request was made from (relative paths resolve here)")
    ap.add_argument("--length", type=float, default=None, help="target length in minutes")
    ap.add_argument("--aspect", default="16:9", choices=ASPECTS)
    ap.add_argument("--presenter", default=None, help="locked presenter profile id, or 'none'")
    ap.add_argument("--audience", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--id", dest="project_id", default=None)
    ap.add_argument("inputs", nargs="*", help="folders, URLs, documents and/or topic words")
    args = ap.parse_intermixed_args(argv)
    try:
        summary = build_project(
            args.inputs,
            cwd=Path(args.cwd).expanduser().resolve(),
            length_min=args.length,
            aspect=args.aspect,
            presenter=args.presenter,
            audience=args.audience,
            title=args.title,
            project_id=args.project_id,
        )
    except RequestError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
