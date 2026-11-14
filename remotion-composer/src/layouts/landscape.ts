import { Canvas, Layout, PipPosition, Rect } from "./types";

const MARGIN_X = 0.05;
const MARGIN_Y = 0.06;
const CAPTION_CLEARANCE = 0.055; // keep the PIP slightly above the caption zone

/** 16:9 (and any landscape) layout. Everything is normalized; pixels are derived from the canvas. */
export const landscape: Layout = {
  aspect: "landscape",

  pip(position: PipPosition, widthFraction: number, canvas: Canvas): Rect {
    const w = widthFraction;
    // PIP window keeps a 16:9 shape in pixels, whatever the canvas.
    const h = (w * canvas.width * (9 / 16)) / canvas.height;
    const x = position.endsWith("right") ? 1 - MARGIN_X - w : MARGIN_X;
    const y = position.startsWith("bottom") ? 1 - MARGIN_Y - CAPTION_CLEARANCE - h : MARGIN_Y;
    return { x, y, w, h };
  },

  split(side, ratio) {
    const presenter: Rect = { x: side === "left" ? 0 : 1 - ratio, y: 0, w: ratio, h: 1 };
    const content: Rect = { x: side === "left" ? ratio : 0, y: 0, w: 1 - ratio, h: 1 };
    return { presenter, content };
  },

  captionSafe: { x: 0.08, y: 0.8, w: 0.84, h: 0.14 },
  lowerThird: { x: 0.04, y: 0.78, w: 0.4, h: 0.14 },

  diagramGrid(n: number) {
    const count = Math.max(1, Math.min(7, n));
    const cols = count <= 4 ? count : Math.ceil(count / 2);
    const rows = Math.ceil(count / cols);
    const padX = 0.07;
    const usableW = 1 - 2 * padX;
    const cardW = Math.min(0.2, (usableW / cols) * 0.82);
    const cardH = rows === 1 ? 0.2 : 0.17;
    const top = rows === 1 ? 0.52 : 0.42;
    const rowGap = 0.26;
    const centers = Array.from({ length: count }, (_, i) => {
      const r = Math.floor(i / cols);
      const c = i % cols;
      // snake order keeps arrows short on the second row
      const col = rows > 1 && r % 2 === 1 ? cols - 1 - c : c;
      const x = padX + (usableW / cols) * (col + 0.5);
      return { x, y: top + r * rowGap };
    });
    return { cols, rows, cardW, cardH, centers };
  },
};
