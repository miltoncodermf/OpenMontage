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


# ---- hairstyle variants of the LOCKED identity (hair only) -------------------------------------
HAIRSTYLE_PROMPT = (
    "Edit the attached portrait: change ONLY the hairstyle to: {description}. Keep the face, facial features, skin, "
    "expression, clothing, lighting, camera framing, background and image quality exactly the same, and keep the hair "
    "colour natural black unless the description says otherwise. Photoreal, natural hair texture and hairline, "
    "head-and-shoulders, mouth closed."
)

HAIRSTYLES = [
    {"id": "hair_neat_side_part", "description": "a short, neat, classic side-parted cut, clean tapered sides, tidy and professional"},
    {"id": "hair_textured_quiff", "description": "a short textured quiff swept up and slightly back at the front, tapered sides, modern and energetic"},
    {"id": "hair_medium_soft", "description": "a medium-length soft layered cut that falls loosely over the forehead and just covers the tops of the ears, relaxed and approachable"},
    {"id": "hair_close_crop", "description": "a very short close-cropped cut with a low skin fade on the sides, minimal and sharp"},
]


def hairstyle_prompt(description: str) -> str:
    return HAIRSTYLE_PROMPT.format(description=description)


EXPRESSION_PROMPT = (
    "Edit the attached portrait: change ONLY the facial expression to: {description}. Keep the person's face shape, "
    "facial features, skin, hairstyle, clothing, lighting, camera framing, background and image quality exactly the "
    "same, and keep the eyes looking straight into the camera. Photoreal, natural skin, head-and-shoulders."
)

EXPRESSIONS = [
    {"id": "expr_warm_smile", "description": "a gentle, relaxed, warm closed-mouth smile with softly lifted cheeks and relaxed brows, "
                                             "friendly and natural, like greeting a viewer you like (not a grin, no teeth)"},
]


def expression_prompt(description: str) -> str:
    return EXPRESSION_PROMPT.format(description=description)


# ---- person-free background plates (Remotion composites the matted presenter over them) ---------
PLATE_PROMPT = (
    "A photoreal, EMPTY background plate for a presenter video: {scene}. There must be NO person, no face, no hands and "
    "no text or logos anywhere. Shallow depth of field with a softly blurred background, gentle even lighting, calm "
    "uncluttered composition. Keep the central vertical third of the frame clean and low-contrast so a presenter can "
    "stand in front of it, and keep any interesting detail in the left and right thirds, with nothing important "
    "outside the centre 9:16 column being essential. 16:9 frame, camera at eye height."
)

BACKGROUND_PLATES = [
    {"id": "bg_modern_studio", "label": "Modern studio", "scene": "a modern minimal video studio wall in warm neutral grey with soft vertical LED light strips and a subtle textured acoustic panel"},
    {"id": "bg_home_office", "label": "Home office", "scene": "a tidy bright home office behind a desk, out-of-focus monitor glow, a green plant and a warm desk lamp, light wood and soft daylight from the left"},
    {"id": "bg_bookshelf", "label": "Bookshelf", "scene": "a warm, softly blurred wooden bookshelf filled with books and a few small objects, cosy evening light with a warm practical lamp"},
]


def plate_prompt(scene: str) -> str:
    return PLATE_PROMPT.format(scene=scene)
