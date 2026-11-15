"""Prompt builders for the digital-twin identity (Gemini image API, spec D5/D6, §5.5).

Beautification is deliberately subtle: better skin/light/grooming/framing, still clearly the owner.
"""

from __future__ import annotations

BEAUTIFY_PROMPT = (
    "Using the attached reference photos of the same person, create a photoreal head-and-shoulders studio portrait of "
    "this exact person. Keep the face clearly recognisable as them — same bone structure, eye shape, nose, mouth, "
    "age and ethnicity. Apply only subtle improvements: even healthy skin tone, flattering soft studio key light "
    "with gentle fill, tidy grooming, a relaxed confident posture, and clean framing. Neutral relaxed expression, "
    "mouth closed, eyes to camera, shoulders square, plain softly blurred neutral studio background, shallow depth of "
    "field, natural skin texture (no plastic smoothing, no filters). Variation {variation}: {variation_note}. "
    "16:9 frame with the subject centered, medium close-up, plenty of headroom."
)
BEAUTIFY_VARIATIONS = [
    "slightly warm key light, soft hair light",
    "neutral daylight-balanced light, subtle rim light",
    "slightly cooler modern light, gentle vignette",
    "soft window-style light from camera left",
    "balanced high-key light, very clean look",
    "slightly moody low-key light, still approachable",
]

# Strength dial (owner decision, gate 1): the twin starts from the owner's face but is deliberately
# changed so friends would not immediately recognise it, while staying a believable, attractive human.
STRENGTH_NOTES = {
    "strong": (
        "Make a clearly noticeable but natural improvement: a slightly more defined jawline and cheekbones, a refined "
        "nose bridge, brighter and more open eyes, tidier fuller brows, even healthy skin with natural pores, and an "
        "overall impression about five years younger. It should look like a more polished sibling of the reference."
    ),
    "very_strong": (
        "Make a strong, deliberate transformation: reshape the face to a slimmer, more V-shaped jaw with higher "
        "cheekbones, larger and more defined eyes, a slimmer straighter nose, fuller well-shaped brows, glowing even skin "
        "with natural texture, and an overall impression eight to ten years younger. The result should look like a "
        "different, strikingly attractive but entirely real person who only loosely resembles the reference, so that "
        "friends would not recognise them at first glance."
    ),
}
STRENGTH_GUARDRAILS = (
    "Keep the same sex, ethnicity, skin tone family and general hair colour, adult age, and a believable human look: "
    "natural proportions, visible skin texture, no plastic or airbrushed skin, no cartoon, anime, 3D-render or uncanny "
    "features, no exaggerated eyes, no extra or visible teeth, no jewellery, no text or logos."
)

STRONG_BEAUTIFY_PROMPT = (
    "Using the attached reference photos only as a loose starting point for the person's general look, create a photoreal "
    "head-and-shoulders studio portrait of an attractive adult. {strength_note} {guardrails} Neutral relaxed expression, "
    "mouth closed, eyes to camera, shoulders square, simple plain dark crew-neck top, soft flattering studio key light "
    "with gentle fill, plain softly blurred neutral studio background, shallow depth of field. Variation {variation}: "
    "{variation_note}. 16:9 frame with the subject centered, medium close-up, plenty of headroom."
)

WARDROBE_PROMPT = (
    "Edit the attached portrait: change ONLY the clothing{hair} to: {description}. Keep the face, identity, expression, "
    "pose, lighting, camera framing, background and image quality exactly the same. Photoreal, natural fabric detail, "
    "head-and-shoulders, mouth closed."
)

IDLE_LOOP_PROMPT = (
    "Locked-off camera, medium close-up of this exact person, seated or standing still. Subtle natural idle motion only: "
    "gentle breathing, occasional natural blinks, very slight head and shoulder movement. Mouth stays closed, no talking, "
    "no hand gestures, no camera movement, constant lighting. The final frame must match the first frame so the clip loops "
    "seamlessly."
)


def beautify_prompt(index: int, strength: str = "subtle") -> str:
    """``subtle`` = the original conservative prompt; ``strong`` / ``very_strong`` = deliberate, still photoreal change."""
    note = BEAUTIFY_VARIATIONS[index % len(BEAUTIFY_VARIATIONS)]
    if strength == "subtle":
        return BEAUTIFY_PROMPT.format(variation=index + 1, variation_note=note)
    if strength not in STRENGTH_NOTES:
        raise ValueError(f"unknown beautify strength {strength!r}; expected subtle, strong or very_strong")
    return STRONG_BEAUTIFY_PROMPT.format(strength_note=STRENGTH_NOTES[strength], guardrails=STRENGTH_GUARDRAILS,
                                         variation=index + 1, variation_note=note)


def wardrobe_prompt(description: str, change_hair: str | None = None) -> str:
    hair = f" and hair ({change_hair})" if change_hair else ""
    return WARDROBE_PROMPT.format(description=description, hair=hair)


STANDIN_PORTRAIT_PROMPT = (
    "Photoreal head-and-shoulders studio portrait of a FICTIONAL adult person — an invented face, not resembling any real "
    "individual, celebrity or public figure. Adult in their thirties, friendly neutral expression, mouth closed, eyes to "
    "camera, shoulders square, plain dark-grey t-shirt, soft flattering studio key light with gentle fill, plain softly "
    "blurred neutral studio background, shallow depth of field, natural skin texture, no text, no watermark, no logo. "
    "16:9 frame with the subject centered, medium close-up, plenty of headroom. Variation {variation}."
)


def standin_portrait_prompt(index: int = 0) -> str:
    return STANDIN_PORTRAIT_PROMPT.format(variation=index + 1)
