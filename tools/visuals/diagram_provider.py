"""Deterministic Diagram Provider for Technical Tutorials.

Generates structured node/edge graph specifications and vector diagram specifications
rendered deterministically in Remotion / SVG without text-in-video hallucinations.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

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


class DiagramProvider(BaseTool):
    name = "diagram_gen"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "diagram"
    provider = "diagram_gen"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    capabilities = [
        "architecture_diagram",
        "sequential_workflow",
        "system_boundary",
    ]

    best_for = [
        "generating deterministic technical diagrams for software tutorials",
        "vector flowcharts rendered cleanly in Remotion without text hallucination",
    ]

    input_schema = {
        "type": "object",
        "required": ["title", "nodes"],
        "properties": {
            "title": {"type": "string", "description": "Title of the diagram"},
            "subtitle": {"type": "string", "description": "Subtitle or context description"},
            "nodes": {
                "type": "array",
                "description": "List of node labels or node objects {id, label, sublabel}",
                "minItems": 2,
            },
            "edges": {
                "type": "array",
                "description": "List of connecting edges [from, to] or objects",
            },
            "build_order": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Progressive reveal order of nodes",
            },
            "output_spec_path": {
                "type": "string",
                "description": "Optional path to save JSON diagram specification",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=10, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = ["title", "nodes"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        title = str(inputs.get("title", "")).strip()
        nodes_raw = inputs.get("nodes", [])
        if not title or not nodes_raw:
            return ToolResult(success=False, error="title and at least two nodes must be provided")

        edges_raw = inputs.get("edges")
        if not edges_raw:
            # Default linear sequential connections
            edges_raw = []
            for i in range(len(nodes_raw) - 1):
                from_id = nodes_raw[i]["id"] if isinstance(nodes_raw[i], dict) else f"node_{i}"
                to_id = nodes_raw[i + 1]["id"] if isinstance(nodes_raw[i + 1], dict) else f"node_{i+1}"
                edges_raw.append([from_id, to_id])

        diagram_spec = {
            "title": title,
            "subtitle": inputs.get("subtitle", ""),
            "nodes": nodes_raw,
            "edges": edges_raw,
            "build_order": inputs.get("build_order", [n["id"] if isinstance(n, dict) else f"node_{i}" for i, n in enumerate(nodes_raw)]),
        }

        output_path_str = inputs.get("output_spec_path")
        artifacts = []
        if output_path_str:
            out_file = Path(output_path_str).resolve()
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(diagram_spec, f, indent=2)
            artifacts.append(str(out_file))

        elapsed = round(time.time() - started, 2)
        return ToolResult(
            success=True,
            data={"diagram_spec": diagram_spec},
            artifacts=artifacts,
            duration_seconds=elapsed,
            cost_usd=0.0,
        )
