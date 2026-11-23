/** Normalized rectangle (0–1 of canvas width/height). Layout is aspect-aware, never hard-coded pixels. */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type PipPosition = "bottom-right" | "bottom-left" | "top-right" | "top-left";

export interface Canvas {
  width: number;
  height: number;
}

export interface Layout {
  aspect: "landscape" | "portrait";
  /** Presenter picture-in-picture window. `widthFraction` is a fraction of canvas width. */
  pip(position: PipPosition, widthFraction: number, canvas: Canvas): Rect;
  /** Presenter panel + content panel for presenter_screen_split. */
  split(side: "left" | "right", ratio: number): { presenter: Rect; content: Rect };
  /** Area captions may occupy (kept clear of the PIP window by the compositor). */
  captionSafe: Rect;
  /** Lower-third badge position. */
  lowerThird: Rect;
  /** Diagram grid: normalized card centers + card size for n nodes (max 7 per beat). */
  diagramGrid(n: number): { cols: number; rows: number; cardW: number; cardH: number; centers: Array<{ x: number; y: number }> };
}

export const toPx = (r: Rect, c: Canvas): Rect => ({
  x: Math.round(r.x * c.width),
  y: Math.round(r.y * c.height),
  w: Math.round(r.w * c.width),
  h: Math.round(r.h * c.height),
});
