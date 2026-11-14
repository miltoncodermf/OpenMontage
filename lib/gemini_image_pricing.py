"""Gemini image-generation price table for topic-tutorial proposals (decision D18).

The stock ``google_imagen`` tool raises PriceQuoteRequired for Gemini 3.x image models because
their price depends on resolution/tokens. Topic-tutorial must itemize identity/wardrobe calls in the
proposal, so we keep our own dated per-image table here (the stock tool stays untouched).

Source: Google AI Studio pricing page. Re-check before each real run — prices change.
"""

from __future__ import annotations

SOURCE_URL = "https://aistudio.google.com/docs/pricing"  # ai.google.dev/gemini-api/docs/pricing redirects here
AS_OF = "2026-11-14"

# USD per generated image, standard tier, by output resolution. Image *input* tokens add a little more
# (gemini-3-pro-image: $0.0011/input image; flash: $0.50/1M input tokens) — covered by INPUT_PAD_USD.
PER_IMAGE_USD: dict[str, dict[str, float]] = {
    "gemini-nano-banana-2.1": {"1K": 0.0336, "2K": 0.0504, "4K": 0.113},
    "gemini-3.1-flash-image": {"0.5K": 0.045, "1K": 0.067, "2K": 0.101, "4K": 0.151},
    "gemini-3.1-flash-lite-image": {"1K": 0.0336},
    "gemini-3-pro-image": {"1K": 0.134, "2K": 0.134, "4K": 0.24},
    "gemini-2.5-flash-image": {"1K": 0.039},
}
# Reference-image input + text/thinking output allowance per call (conservative).
INPUT_PAD_USD = 0.01


def per_image_usd(model: str, resolution: str = "1K") -> float:
    table = PER_IMAGE_USD.get(model)
    if table is None:
        raise KeyError(f"no price on file for Gemini image model {model!r} (known: {sorted(PER_IMAGE_USD)})")
    return table.get(resolution) or table["1K"]


def estimate_calls_usd(model: str, n_calls: int, resolution: str = "1K") -> float:
    """Upper-ish estimate for ``n_calls`` image generations including input/thinking padding."""
    return round(n_calls * (per_image_usd(model, resolution) + INPUT_PAD_USD), 4)


def price_note(model: str, resolution: str = "1K") -> dict[str, str | float]:
    return {"model": model, "resolution": resolution, "per_image_usd": per_image_usd(model, resolution),
            "input_pad_usd": INPUT_PAD_USD, "source_url": SOURCE_URL, "as_of": AS_OF}
