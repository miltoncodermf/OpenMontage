import React from "react";
import { AbsoluteFill, Img } from "remotion";
import { resolveAsset } from "../lib/resolveAsset";

/**
 * Backdrop drawn *behind* the presenter's alpha layer (stack: backdrop -> presenter -> captions).
 * Mirrors `lib/backdrops.py` (the owner's background catalog):
 *   procedural: gradient `angle` + `stops` (+ optional `overlay`), $0, drawn here at render time
 *   plate:      a person-free 16:9 image stored in the profile, shown cover-fit
 */
export type PresenterBackdropSpec =
  | {
      kind: "procedural";
      id?: string;
      angle?: number;
      stops: [number, string][];
      overlay?: "grid_glow" | "vignette" | null;
    }
  | { kind: "plate"; id?: string; src: string };

export const gradientCss = (angle: number, stops: [number, string][]): string =>
  // CSS angle 0deg = to top, 90deg = to right: the same convention as the PIL preview in lib/backdrops.py
  `linear-gradient(${angle}deg, ${stops.map(([p, c]) => `${c} ${(p * 100).toFixed(1)}%`).join(", ")})`;

export const PresenterBackdrop: React.FC<{ spec: PresenterBackdropSpec }> = ({ spec }) => {
  if (spec.kind === "plate") {
    return (
      <AbsoluteFill>
        <Img src={resolveAsset(spec.src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </AbsoluteFill>
    );
  }
  const base = gradientCss(spec.angle ?? 180, spec.stops);
  return (
    <AbsoluteFill style={{ background: base }}>
      {spec.overlay === "grid_glow" && (
        <>
          <AbsoluteFill
            style={{
              backgroundImage:
                "linear-gradient(rgba(120,170,255,0.055) 1px, transparent 1px), linear-gradient(90deg, rgba(120,170,255,0.055) 1px, transparent 1px)",
              backgroundSize: "60px 60px",
            }}
          />
          <AbsoluteFill
            style={{ background: "radial-gradient(ellipse 30% 45% at 88% 18%, rgba(40,120,255,0.28), transparent 70%)" }}
          />
        </>
      )}
      {spec.overlay === "vignette" && (
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.12) 100%)" }} />
      )}
    </AbsoluteFill>
  );
};
