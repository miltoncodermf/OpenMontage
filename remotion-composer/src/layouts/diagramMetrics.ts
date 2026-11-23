/**
 * Diagram legibility metrics (spec §5.9) — single source of truth for the Remotion components.
 * Pixel sizes are defined at 1080p canvas height and scale with canvas height.
 * MUST match lib/diagram_legibility.py (a fast test compares them).
 */
export const BASE_HEIGHT = 1080;
export const MIN_LABEL_PX = 28;
export const MIN_TITLE_PX = 44;
export const MIN_SUBLABEL_PX = 22;
export const MIN_EDGE_LABEL_PX = 22;
export const MAX_NODES_PER_BEAT = 7;
export const MIN_CONTRAST = 4.5;

export const diagramFontSizes = (canvasHeight: number) => {
  const s = canvasHeight / BASE_HEIGHT;
  return {
    label: Math.round(MIN_LABEL_PX * s),
    title: Math.round(MIN_TITLE_PX * s),
    sublabel: Math.round(MIN_SUBLABEL_PX * s),
    edgeLabel: Math.round(MIN_EDGE_LABEL_PX * s),
  };
};
