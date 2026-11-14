import { Canvas, Layout, PipPosition, Rect } from "./types";

/**
 * 9:16 SLOT — intentionally minimal. v3 delivers 16:9 only; this placeholder proves the seam
 * (same scene plan compiles for a portrait canvas) and is the one place a real 9:16 re-layout goes.
 */
export const portrait: Layout = {
  aspect: "portrait",

  pip(_position: PipPosition, widthFraction: number, canvas: Canvas): Rect {
    const w = Math.min(0.9, widthFraction * 2.2);
    const h = (w * canvas.width * (9 / 16)) / canvas.height;
    return { x: (1 - w) / 2, y: 0.62, w, h };
  },

  split(_side, ratio) {
    const presenterH = Math.min(0.45, ratio + 0.1);
    return {
      presenter: { x: 0, y: 1 - presenterH, w: 1, h: presenterH },
      content: { x: 0, y: 0, w: 1, h: 1 - presenterH },
    };
  },

  captionSafe: { x: 0.06, y: 0.7, w: 0.88, h: 0.12 },
  lowerThird: { x: 0.04, y: 0.55, w: 0.9, h: 0.1 },

  diagramGrid(n: number) {
    const count = Math.max(1, Math.min(7, n));
    const centers = Array.from({ length: count }, (_, i) => ({ x: 0.5, y: 0.2 + (0.6 / Math.max(1, count - 1 || 1)) * i }));
    return { cols: 1, rows: count, cardW: 0.8, cardH: Math.min(0.1, 0.55 / count), centers };
  },
};
