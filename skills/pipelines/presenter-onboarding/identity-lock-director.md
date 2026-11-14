# Identity Lock Director — presenter-onboarding  🛑

1. Show `identity/candidates/cand_*.png` and ask the owner to pick one (optionally with tweaks, e.g. "slightly warmer light"). Make tweaks by regenerating with `twin_identity` only after cost approval.
2. `pick_canonical` with the chosen candidate → `identity/canonical.png`, `picked_candidate`, `identity_transform: "beautified"`.
3. Identity is created once and then **fixed**. Per-topic variation later is simple wardrobe/hair only (generated from `canonical.png`, cached in `identity/wardrobe_catalog.json`).
4. Checkpoint `awaiting_human` and **end your turn** for the owner's confirmation.
