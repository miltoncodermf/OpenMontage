"""Paid-call guard (spec D18 / §5.11).

Proposal approval covers every itemized paid call up to estimate + 20 %. A call that is
not itemized, or that would push actual spend past 1.2x the approved total, must pause and
ask the owner. Pure decision function — the agent does the asking.
"""

from __future__ import annotations

from typing import Any

OVERRUN_FACTOR = 1.2


def _paid_calls(proposal_packet: dict[str, Any]) -> list[dict[str, Any]]:
    return list((proposal_packet.get("cost_estimate") or {}).get("paid_calls") or [])


def approved_total(proposal_packet: dict[str, Any]) -> float:
    ce = proposal_packet.get("cost_estimate") or {}
    if "total_est_usd" in ce:
        return float(ce["total_est_usd"])
    return round(sum(float(c.get("est_usd", 0.0)) for c in _paid_calls(proposal_packet)), 6)


def check_paid_call(
    proposal_packet: dict[str, Any],
    *,
    tool: str,
    provider: str,
    model: str | None,
    est_usd: float,
    actual_spent_usd: float,
) -> dict[str, Any]:
    """Return {allowed: bool, reason: str}. ``allowed=False`` means pause and ask the owner."""
    approval = (proposal_packet.get("approval") or {}).get("status")
    if approval not in {"approved", "approved_with_changes"}:
        return {"allowed": False, "reason": "proposal not approved"}

    listed = [
        c for c in _paid_calls(proposal_packet)
        if c.get("tool") == tool and c.get("provider") == provider
        and (model is None or c.get("model") in (None, model))
    ]
    if not listed:
        return {"allowed": False, "reason": f"paid call {tool}/{provider}/{model} is not in the approved paid_calls list"}

    ceiling = approved_total(proposal_packet) * OVERRUN_FACTOR
    if actual_spent_usd + est_usd > ceiling + 1e-9:
        return {
            "allowed": False,
            "reason": f"actual {actual_spent_usd:.2f} + next {est_usd:.2f} exceeds 1.2x approved total ({ceiling:.2f})",
        }
    return {"allowed": True, "reason": "within approved paid_calls and 1.2x ceiling"}
