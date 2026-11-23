"""Universal Input Ingestor for OpenMontage topic-tutorial pipeline.

Normalizes the supported topic-tutorial inputs (code repositories, markdown/text,
PDFs with a text layer, and public URLs) into a provenance-aware source bundle with SHA-256 hashes, secret redaction,
and fact extraction.
"""

from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import json
import os
import re
import socket
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

# Secret file and pattern regexes
SECRET_FILE_PATTERNS = [
    ".env*",
    "*.pem",
    "*.key",
    "*credentials*",
    "*id_rsa*",
    "*id_ed25519*",
    "*.pfx",
    "*.p12",
    "*token*",
    "*.secret",
]

SECRET_CONTENT_REGEXES = [
    re.compile(r"([\"']?(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|bearer[_-]?token|private[_-]?key)[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9_\-\.]{8,})([\"']?)", re.IGNORECASE),
    re.compile(r"(AIzaSy[A-Za-z0-9_\-]{20,})"),  # Google API keys
    re.compile(r"(sk-[A-Za-z0-9_\-]{20,})"),  # OpenAI-style secret keys
    re.compile(r"(ghp_[A-Za-z0-9]{30,})"),  # GitHub personal access tokens
]

PROMPT_INJECTION_REGEX = re.compile(
    r"(?i)(ignore\s+all\s+previous|system\s+prompt\s+override|rm\s+-rf|call_api:)"
)


def _hash_file_stream(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_public_url(url: str) -> Optional[str]:
    """Return error string if URL targets a non-HTTP scheme or private/loopback/reserved IP."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Unsupported URL scheme: {parsed.scheme}"
    hostname = parsed.hostname
    if not hostname:
        return "URL missing hostname"
    if hostname.lower() in ("localhost", "ip6-localhost"):
        return "Loopback hostname is blocked (SSRF protection)"
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        for item in addr_info:
            ip_str = item[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                return f"URL resolves to restricted IP {ip_str} (SSRF protection)"
    except socket.gaierror as exc:
        return f"DNS resolution failed for {hostname}: {exc}"
    return None


def _is_secret_filename(name: str) -> bool:
    for pattern in SECRET_FILE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _redact_secrets(text: str) -> str:
    redacted = text
    for regex in SECRET_CONTENT_REGEXES:
        redacted = regex.sub(r"\1[REDACTED_SECRET]\3" if regex.groups >= 3 else r"[REDACTED_SECRET]", redacted)
    return redacted


class UniversalIngestor(BaseTool):
    name = "universal_ingestor"
    version = "1.1.0"
    tier = ToolTier.SOURCE
    capability = "ingestion"
    provider = "local"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = []
    agent_skills = ["video-understand"]

    capabilities = [
        "local_file_ingestion",
        "directory_scan",
        "code_repository_ingestion",
        "pdf_text_extraction",
        "secret_redaction",
        "provenance_tracking",
    ]

    supports = {
        "markdown": True,
        "text": True,
        "code": True,
        "pdf": True,
        "urls": True,
    }

    best_for = [
        "universal material intake for tutorial and explainer pipelines",
        "codebase and documentation extraction with secret redaction",
        "repo, URL and PDF research intake (no office/media formats in v3)",
    ]

    input_schema = {
        "type": "object",
        "properties": {
            "inputs_spec": {
                "type": "object",
                "description": "Parsed inputs.yaml: {topic?, repos:[{path,focus[]}], urls[], pdfs[]}",
            },
            "input_path": {
                "type": "string",
                "description": "Path to a file, directory, repository, or a web URL",
            },
            "project_dir": {
                "type": "string",
                "description": "Owning project directory for artifacts output",
            },
            "extract_claims": {
                "type": "boolean",
                "default": True,
                "description": "Whether to extract verifiable facts into fact_sheet.json",
            },
            "max_file_size_mb": {
                "type": "number",
                "default": 50.0,
                "description": "Maximum file size in MB to parse",
            },
            "max_files": {
                "type": "integer",
                "default": 100,
                "description": "Maximum files to ingest in directory scan",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=100, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, backoff_seconds=1.0)
    idempotency_key_fields = ["input_path", "max_file_size_mb"]
    side_effects = ["writes artifacts/input_manifest.json", "writes artifacts/fact_sheet.json"]
    user_visible_verification = [
        "Inspect artifacts/input_manifest.json for ingested sources and status",
        "Verify secrets were redacted from any ingested code or configs",
    ]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        """Ingest either a single ``input_path`` (legacy) or a full ``inputs_spec``
        (the parsed ``inputs.yaml``: topic / repos / urls / pdfs — spec D11)."""
        started = time.time()
        spec = inputs.get("inputs_spec")
        input_target = str(inputs.get("input_path", "")).strip()
        if not spec and not input_target:
            return ToolResult(success=False, error="provide input_path or inputs_spec (topic/repos/urls/pdfs)")

        project_dir_str = inputs.get("project_dir")
        project_dir = Path(project_dir_str) if project_dir_str else Path.cwd()
        max_file_size_bytes = int(inputs.get("max_file_size_mb", 50.0) * 1024 * 1024)
        max_files = int(inputs.get("max_files", 100))
        extract_claims = bool(inputs.get("extract_claims", True))

        artifacts_dir = project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        sources: list[dict[str, Any]] = []
        topic: Optional[str] = None
        retrieved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        def next_id() -> str:
            return f"src_{len(sources) + 1:03d}"

        def add(src: dict[str, Any], mode: str) -> None:
            src["mode"] = mode
            src["retrieved_at"] = retrieved_at
            sources.append(src)

        if spec:
            topic = (spec.get("topic") or "").strip() or None
            for repo in spec.get("repos") or []:
                root = Path(str(repo["path"])).expanduser()
                if not root.is_dir():
                    add({"source_id": next_id(), "file_path": str(root), "filename": root.name, "status": "unsupported",
                         "error": "Repo path is not a directory", "sha256": None, "word_count": 0, "byte_size": 0, "content": ""}, "repo")
                    continue
                focus = [str(f).strip("/") for f in (repo.get("focus") or [])]
                # focus is applied while walking, so max_files counts focused files (not the first N of the whole repo)
                files = self._collect_directory_files(root, max_files, focus=focus or None)
                for fpath in files:
                    add(self._ingest_file(fpath, next_id(), max_file_size_bytes, allowed_root=root), "repo")
            for url in spec.get("urls") or []:
                add(self._ingest_url(str(url), next_id()), "url")
            for pdf in spec.get("pdfs") or []:
                pdf_path = Path(str(pdf)).expanduser()
                if not pdf_path.is_absolute():
                    pdf_path = project_dir / "inputs" / pdf_path if not (project_dir / pdf_path).exists() else project_dir / pdf_path
                if pdf_path.suffix.lower() != ".pdf":
                    add({"source_id": next_id(), "file_path": str(pdf_path), "filename": pdf_path.name, "status": "unsupported",
                         "error": "pdfs[] entries must be .pdf files", "sha256": None, "word_count": 0, "byte_size": 0, "content": ""}, "pdf")
                elif not pdf_path.is_file():
                    add({"source_id": next_id(), "file_path": str(pdf_path), "filename": pdf_path.name, "status": "unsupported",
                         "error": "PDF not found", "sha256": None, "word_count": 0, "byte_size": 0, "content": ""}, "pdf")
                else:
                    add(self._ingest_file(pdf_path, next_id(), max_file_size_bytes, allowed_root=pdf_path.parent), "pdf")
        elif input_target.startswith(("http://", "https://")):
            add(self._ingest_url(input_target, next_id()), "url")
        else:
            target_path = Path(input_target).expanduser()
            if not target_path.exists():
                return ToolResult(success=False, error=f"Target path does not exist: {target_path}")
            if target_path.is_file():
                add(self._ingest_file(target_path, next_id(), max_file_size_bytes, allowed_root=target_path.parent),
                    "pdf" if target_path.suffix.lower() == ".pdf" else "repo")
            elif target_path.is_dir():
                for fpath in self._collect_directory_files(target_path, max_files):
                    add(self._ingest_file(fpath, next_id(), max_file_size_bytes, allowed_root=target_path), "repo")

        # Fact sheet generation - only from prose documents, never raw code
        facts: list[dict[str, Any]] = []
        if extract_claims:
            fact_counter = 1
            for src in sources:
                if (
                    src.get("status") == "supported"
                    and src.get("content")
                    and src.get("file_type") in {"text", "pdf", "url"}
                ):
                    for fact in self._extract_facts(src["content"], src["source_id"], src):
                        fact["fact_id"] = f"fact_{fact_counter:03d}"
                        facts.append(fact)
                        fact_counter += 1

        total_words = sum(s.get("word_count", 0) for s in sources)
        supported_count = sum(1 for s in sources if s.get("status") == "supported")
        unsupported_count = len(sources) - supported_count
        modes = sorted({s["mode"] for s in sources} | ({"topic"} if topic else set()))

        input_manifest = {
            "schema_version": "1.0",
            "ingested_at": retrieved_at,
            "input_target": input_target or "inputs.yaml",
            "project_dir": str(project_dir),
            "topic": topic,
            "modes": modes,
            "summary": {
                "total_sources": len(sources),
                "supported_sources": supported_count,
                "unsupported_sources": unsupported_count,
                "total_word_count": total_words,
            },
            "sources": sources,
        }

        fact_sheet = {
            "schema_version": "1.0",
            "generated_at": retrieved_at,
            "total_facts": len(facts),
            "facts": facts,
        }

        manifest_path = artifacts_dir / "input_manifest.json"
        fact_sheet_path = artifacts_dir / "fact_sheet.json"

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(input_manifest, f, indent=2, ensure_ascii=False)

        with open(fact_sheet_path, "w", encoding="utf-8") as f:
            json.dump(fact_sheet, f, indent=2, ensure_ascii=False)

        elapsed = round(time.time() - started, 2)
        return ToolResult(
            success=True,
            data={
                "input_manifest": str(manifest_path),
                "fact_sheet": str(fact_sheet_path),
                "modes": modes,
                "total_sources": len(sources),
                "supported_sources": supported_count,
                "unsupported_sources": unsupported_count,
                "total_word_count": total_words,
                "total_facts": len(facts),
            },
            artifacts=[str(manifest_path), str(fact_sheet_path)],
            duration_seconds=elapsed,
            cost_usd=0.0,
        )

    def _collect_directory_files(self, root_dir: Path, max_files: int, focus: Optional[list[str]] = None) -> list[Path]:
        collected: list[Path] = []
        root_resolved = root_dir.resolve()
        git_ignore_patterns = [
            ".git",
            ".git/*",
            ".venv",
            ".venv/*",
            "node_modules",
            "node_modules/*",
            "__pycache__",
            "__pycache__/*",
            "*.pyc",
            "*.pyo",
            "dist",
            "dist/*",
            "build",
            "build/*",
            ".DS_Store",
        ]

        gitignore_file = root_dir / ".gitignore"
        if gitignore_file.is_file():
            try:
                with open(gitignore_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith(("#", "!")):
                            # ".gitignore" directory entries end with "/" (and may start with "/"); fnmatch needs the bare name
                            git_ignore_patterns.append(line.strip("/") or line)
            except Exception:
                pass

        def _ignored(rel: Path, name: str) -> bool:
            return any(fnmatch.fnmatch(str(rel), pat) or fnmatch.fnmatch(name, pat) for pat in git_ignore_patterns)

        # With a focus list, walk only those files/dirs (still under root, still honouring ignore patterns).
        starts: list[Path] = [root_dir]
        if focus:
            starts = []
            for fo in focus:
                cand = (root_dir / fo).resolve()
                if cand != root_resolved and root_resolved not in cand.parents:
                    continue  # focus entry escapes the repo root
                if cand.exists():
                    starts.append(cand)
            if not starts:
                return collected

        for start in starts:
            if start.is_file():
                if not _ignored(start.relative_to(root_resolved), start.name):
                    collected.append(start)
                    if len(collected) >= max_files:
                        return collected
                continue
            for root, dirs, files in os.walk(start):
                rel_root = Path(root).resolve().relative_to(root_resolved)
                dirs.sort()
                dirs[:] = [d for d in dirs if not _ignored(rel_root / d, d)]
                for file in sorted(files):
                    rel_path = rel_root / file
                    if _ignored(rel_path, file):
                        continue
                    collected.append(Path(root) / file)
                    if len(collected) >= max_files:
                        return collected
        return collected

    def _ingest_file(
        self,
        path: Path,
        source_id: str,
        max_file_size_bytes: int,
        allowed_root: Optional[Path] = None,
    ) -> dict[str, Any]:
        filename = path.name
        rel_str = str(path)

        # 1. Immediate filename secret check before any filesystem resolution
        if _is_secret_filename(filename):
            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "status": "redacted_sensitive",
                "sha256": None,
                "word_count": 0,
                "byte_size": 0,
                "summary": "Sensitive configuration or secret file excluded for safety",
                "content": "",
            }

        # 2. Symlink & workspace boundary verification
        try:
            resolved_target = path.resolve(strict=True)
        except Exception as exc:
            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "status": "unsupported",
                "error": f"Unresolvable path or broken symlink: {exc}",
                "sha256": None,
                "word_count": 0,
                "byte_size": 0,
                "content": "",
            }

        if _is_secret_filename(resolved_target.name):
            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "status": "redacted_sensitive",
                "sha256": None,
                "word_count": 0,
                "byte_size": 0,
                "summary": "Symlink to sensitive file excluded for safety",
                "content": "",
            }

        if allowed_root is not None and not resolved_target.is_relative_to(allowed_root.resolve()):
            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "status": "redacted_sensitive",
                "error": "Symlink escapes allowed input directory boundary",
                "sha256": None,
                "word_count": 0,
                "byte_size": 0,
                "summary": "External symlink blocked by workspace boundary check",
                "content": "",
            }

        # 3. Check existence
        if not path.is_file():
            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "status": "unsupported",
                "error": "File not found or not a regular file",
                "sha256": None,
                "word_count": 0,
                "byte_size": 0,
                "content": "",
            }

        suffix = path.suffix.lower()
        byte_size = path.stat().st_size

        # 4. Check size for documents and code
        if byte_size > max_file_size_bytes:
            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "status": "unsupported",
                "error": f"File size ({byte_size} bytes) exceeds limit ({max_file_size_bytes} bytes)",
                "sha256": None,
                "word_count": 0,
                "byte_size": byte_size,
                "content": "",
            }

        # Compute SHA256 in 64KB chunks
        try:
            sha256_hash = _hash_file_stream(path)
            raw_bytes = path.read_bytes()
        except Exception as exc:
            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "status": "unsupported",
                "error": f"Failed reading file bytes: {exc}",
                "sha256": None,
                "word_count": 0,
                "byte_size": byte_size,
                "content": "",
            }

        try:
            # Markdown & Plain text
            if suffix in [".md", ".markdown", ".txt", ".rst"]:
                text = raw_bytes.decode("utf-8", errors="replace")
                text = _redact_secrets(text)
                words = len(text.split())
                return {
                    "source_id": source_id,
                    "file_path": rel_str,
                    "filename": filename,
                    "file_type": "text",
                    "status": "supported",
                    "sha256": sha256_hash,
                    "word_count": words,
                    "byte_size": byte_size,
                    "summary": text[:200].replace("\n", " ") + "...",
                    "content": text,
                }

            # Code
            if suffix in [".py", ".ts", ".js", ".json", ".yaml", ".yml", ".sh", ".html", ".css", ".rs", ".go", ".cpp", ".c", ".h", ".sql"]:
                text = raw_bytes.decode("utf-8", errors="replace")
                text = _redact_secrets(text)
                words = len(text.split())
                return {
                    "source_id": source_id,
                    "file_path": rel_str,
                    "filename": filename,
                    "file_type": "code",
                    "language": suffix.lstrip("."),
                    "status": "supported",
                    "sha256": sha256_hash,
                    "word_count": words,
                    "byte_size": byte_size,
                    "summary": f"Code source ({suffix.lstrip('.')}, {len(text.splitlines())} lines)",
                    "content": text,
                }

            # PDF
            if suffix == ".pdf":
                try:
                    import pypdf
                    reader = pypdf.PdfReader(path)
                    pages_text = []
                    for page in reader.pages:
                        extracted = page.extract_text() or ""
                        if extracted:
                            pages_text.append(extracted)
                    full_text = "\f".join(pages_text)
                    if not full_text.strip():
                        return {
                            "source_id": source_id,
                            "file_path": rel_str,
                            "filename": filename,
                            "file_type": "pdf",
                            "status": "unsupported",
                            "error": "PDF has no extractable text (rasterized/scanned)",
                            "sha256": sha256_hash,
                            "word_count": 0,
                            "byte_size": byte_size,
                            "content": "",
                        }
                    full_text = _redact_secrets(full_text)
                    return {
                        "source_id": source_id,
                        "file_path": rel_str,
                        "filename": filename,
                        "file_type": "pdf",
                        "status": "supported",
                        "pages": len(reader.pages),
                        "sha256": sha256_hash,
                        "word_count": len(full_text.split()),
                        "byte_size": byte_size,
                        "summary": full_text[:200].replace("\n", " ") + "...",
                        "content": full_text,
                    }
                except Exception as exc:
                    return {
                        "source_id": source_id,
                        "file_path": rel_str,
                        "filename": filename,
                        "file_type": "pdf",
                        "status": "unsupported",
                        "error": f"PDF parse error: {exc}",
                        "sha256": sha256_hash,
                        "word_count": 0,
                        "byte_size": byte_size,
                        "content": "",
                    }

            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "file_type": suffix.lstrip("."),
                "status": "unsupported",
                "error": f"Unsupported file format '{suffix}'",
                "sha256": sha256_hash,
                "word_count": 0,
                "byte_size": byte_size,
                "content": "",
            }

        except Exception as exc:
            return {
                "source_id": source_id,
                "file_path": rel_str,
                "filename": filename,
                "status": "unsupported",
                "error": f"Unexpected ingestion error: {exc}",
                "sha256": sha256_hash,
                "word_count": 0,
                "byte_size": byte_size,
                "content": "",
            }

    def _ingest_url(self, url: str, source_id: str) -> dict[str, Any]:
        sha256_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()

        # SSRF Protection
        ssrf_err = _validate_public_url(url)
        if ssrf_err:
            return {
                "source_id": source_id,
                "file_path": url,
                "filename": url,
                "file_type": "url",
                "status": "unsupported",
                "error": ssrf_err,
                "sha256": sha256_hash,
                "word_count": 0,
                "byte_size": 0,
                "content": "",
            }

        try:
            import requests
            from bs4 import BeautifulSoup

            # Follow up to 5 redirects manually so every hop is SSRF-validated (requests would follow blindly).
            final_url = url
            resp = None
            for _hop in range(6):
                resp = requests.get(
                    final_url,
                    timeout=15,
                    headers={"User-Agent": "OpenMontage-UniversalIngestor/1.1"},
                    stream=True,
                    allow_redirects=False,
                )
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                    nxt = urllib.parse.urljoin(final_url, resp.headers["Location"])
                    resp.close()
                    hop_err = _validate_public_url(nxt)
                    if hop_err:
                        return {
                            "source_id": source_id, "file_path": url, "filename": url, "file_type": "url",
                            "status": "unsupported", "error": f"redirect to {nxt} refused: {hop_err}",
                            "sha256": sha256_hash, "word_count": 0, "byte_size": 0, "content": "",
                        }
                    final_url = nxt
                    continue
                break
            # Stream response and cap at 5MB
            with resp:
                if resp.status_code != 200:
                    return {
                        "source_id": source_id,
                        "file_path": url,
                        "filename": urllib.parse.urlparse(url).path.split("/")[-1] or "index.html",
                        "file_type": "url",
                        "status": "unsupported",
                        "error": f"HTTP {resp.status_code}: {resp.reason}",
                        "sha256": sha256_hash,
                        "word_count": 0,
                        "byte_size": 0,
                        "content": "",
                    }

                content_chunks = []
                curr_len = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    curr_len += len(chunk)
                    content_chunks.append(chunk)
                    if curr_len > 5 * 1024 * 1024:
                        break
                raw_bytes = b"".join(content_chunks)

            soup = BeautifulSoup(raw_bytes, "html.parser")
            for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
                tag.extract()
            text = soup.get_text(separator="\n")
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            clean_text = "\n".join(lines)
            clean_text = _redact_secrets(clean_text)

            title = soup.title.string.strip() if (soup.title and soup.title.string) else url
            return {
                "source_id": source_id,
                "file_path": url,
                "filename": title[:60],
                "file_type": "url",
                "status": "supported",
                "sha256": sha256_hash,
                "word_count": len(clean_text.split()),
                "byte_size": len(raw_bytes),
                "summary": f"Web document: {title} ({len(clean_text.split())} words)",
                "content": clean_text[:20000],
            }
        except Exception as exc:
            return {
                "source_id": source_id,
                "file_path": url,
                "filename": url,
                "file_type": "url",
                "status": "unsupported",
                "error": f"Failed fetching URL: {exc}",
                "sha256": sha256_hash,
                "word_count": 0,
                "byte_size": 0,
                "content": "",
            }

    def _extract_facts(
        self, text: str, source_id: str, source: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """Heuristic claim candidates with a precise source_ref (file+line, PDF page, or URL)."""
        source = source or {}
        file_type = source.get("file_type")
        origin = source.get("file_path", "")
        retrieved_at = source.get("retrieved_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        facts: list[dict[str, Any]] = []
        lineno = 0
        for page, page_text in enumerate(text.split("\f"), start=1):
            for line in page_text.split("\n"):
                lineno += 1
                clean = line
                line_str = clean.strip().lstrip("-*#0123456789. ")
                # Prompt injection defense
                if PROMPT_INJECTION_REGEX.search(line_str):
                    continue
                if not (25 < len(line_str) < 300):
                    continue
                if not re.search(r"(\d+%|\$\d+|\b\d{4}\b|\bcores\b|\bGB\b|\bMB\b|\bsec\b|\barchitecture\b|\bpipeline\b|\bmodule\b|\bstage\b)", line_str, re.IGNORECASE):
                    continue
                if file_type == "url":
                    source_ref: dict[str, Any] = {"kind": "url", "url": origin}
                elif file_type == "pdf":
                    source_ref = {"kind": "pdf", "file": origin, "page": page}
                else:
                    source_ref = {"kind": "file", "file": origin, "line": lineno}
                fact: dict[str, Any] = {
                    "claim": line_str,
                    "source_id": source_id,
                    "source_ref": source_ref,
                    "retrieved_at": retrieved_at,
                    "confidence": "low",
                    "corroborated_by": [],
                    "context": clean.strip()[:150],
                    "verified": False,
                    "untrusted_source": True,
                }
                if file_type == "url":
                    fact["source_url"] = origin
                facts.append(fact)
                if len(facts) >= 20:
                    return facts
        return facts
