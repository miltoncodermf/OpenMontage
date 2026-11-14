"""inputs.yaml contract for topic-tutorial (spec D11 / §5.3).

Supported, combinable inputs: ``topic``, ``repos``, ``urls``, ``pdfs``. Nothing else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from schemas.artifacts import validate_artifact

SUPPORTED_KEYS = ("topic", "repos", "urls", "pdfs")


class InputsError(ValueError):
    """inputs.yaml is invalid."""


def load_inputs(path: Path) -> dict[str, Any]:
    """Parse and schema-validate an inputs.yaml file."""
    path = Path(path)
    if not path.is_file():
        raise InputsError(f"inputs file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise InputsError("inputs.yaml must be a mapping")
    unknown = sorted(set(data) - set(SUPPORTED_KEYS))
    if unknown:
        raise InputsError(
            f"unsupported input keys {unknown}; v3 supports only {list(SUPPORTED_KEYS)} "
            "(docx/pptx/xlsx/csv/media inputs were removed)"
        )
    try:
        validate_artifact("inputs", data)
    except Exception as exc:  # jsonschema.ValidationError
        raise InputsError(str(getattr(exc, "message", exc))) from exc
    return data


def check_inputs_exist(data: dict[str, Any], project_dir: Path) -> list[str]:
    """Return problems with referenced local paths (empty list = fine)."""
    problems: list[str] = []
    for repo in data.get("repos") or []:
        if not Path(repo["path"]).expanduser().is_dir():
            problems.append(f"repo path is not a directory: {repo['path']}")
    for pdf in data.get("pdfs") or []:
        p = Path(pdf).expanduser()
        if not p.is_absolute():
            p = Path(project_dir) / p
        if not p.is_file():
            problems.append(f"pdf not found: {pdf}")
    return problems


def ingest_inputs(project_dir: Path, inputs_path: Path | None = None) -> dict[str, Any]:
    """Run ``universal_ingestor`` over ``projects/<id>/inputs/inputs.yaml``.

    Writes ``artifacts/input_manifest.json`` and ``artifacts/fact_sheet.json``;
    returns the tool result data. Raises ``InputsError`` on a bad contract or failed ingest.
    """
    from tools.ingestion.universal_ingestor import UniversalIngestor

    project_dir = Path(project_dir)
    spec = load_inputs(inputs_path or project_dir / "inputs" / "inputs.yaml")
    result = UniversalIngestor().execute({"inputs_spec": spec, "project_dir": str(project_dir)})
    if not result.success:
        raise InputsError(result.error or "ingestion failed")
    return result.data
