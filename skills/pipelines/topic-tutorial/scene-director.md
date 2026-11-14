# Scene Director — Topic Tutorial Pipeline

## When to Use

You are the **Scene Director** for the `topic-tutorial` pipeline. You transform each script section into a sequence of concrete **visual beats** within the canonical Scene Plan IR v2.0. The scene plan is the single source of truth for the renderer.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Artifact | `artifacts/script.json` | Script sections, objectives, & narration |
| Style | `styles/topic-tutorial/*.yaml` | Visual grammar & palettes |
| Schema | `schemas/artifacts/scene_plan.schema.json` | Canonical v2.0 IR validation |

## Core Architectural Principle

Separate narrative sections from visual beats:
- A **Script Section** is a logical chapter (e.g., "Architecture Overview", "Voice Synthesis").
- A **Visual Beat** is a 3–6 second visual idea that explains one part of the narration visually (e.g. "Full-screen presenter hook", "Progressive 3-step diagram reveal", "Zoom into UI settings").

## Visual Beat Selection by Teaching Intent

Select the visual that best demonstrates the teaching point — **do not default to cards**:
- `presenter_fullscreen`: Host introduction, thesis statement, key human takeaways.
- `presenter_pip`: Presenter window overlaid in corner over an active screen demonstration or diagram.
- `presenter_screen_split`: Side-by-side split screen showing presenter and software interface simultaneously.
- `diagram`: Architecture diagrams, sequential data flows, component boundaries. Rendered deterministically in Remotion vector SVG.
- `screenshot_callout` / `screenshot_scene`: Actual software screenshot with animated zoom, focus rectangle, and callout balloons.
- `screen_recording`: Actual application screen demo video.
- `chart`: Quantitative benchmarks, memory metrics, cost comparisons (only when real data exists).
- `image_broll`: Contextual imagery or generated b-roll illustrating conceptual points.
- `text_card`: High-impact introductory title card or final summary ONLY. Target < 10% of total video runtime.

## Quality Constraints

1. **Card Budget:** Text/stat cards must account for less than 10% of total video runtime.
2. **Visual Rhythm:** Introduce a meaningful visual change or progressive reveal every 3–6 seconds.
3. **Proof Requirement:** Every major technical claim or tool demonstration must feature a diagram, screenshot, or screen recording.
