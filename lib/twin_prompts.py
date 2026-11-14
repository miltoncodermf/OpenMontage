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


def beautify_prompt(index: int) -> str:
    note = BEAUTIFY_VARIATIONS[index % len(BEAUTIFY_VARIATIONS)]
    return BEAUTIFY_PROMPT.format(variation=index + 1, variation_note=note)


def wardrobe_prompt(description: str, change_hair: str | None = None) -> str:
    hair = f" and hair ({change_hair})" if change_hair else ""
    return WARDROBE_PROMPT.format(description=description, hair=hair)
