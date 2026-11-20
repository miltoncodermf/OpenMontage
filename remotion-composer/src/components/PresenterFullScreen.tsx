import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { resolveAsset } from "../lib/resolveAsset";
import { getLayout, toPx } from "../layouts";
import { PresenterBackdrop, PresenterBackdropSpec } from "./PresenterBackdrop";

export interface PresenterFullScreenProps {
  src: string;
  startFrom?: number;
  title?: string;
  subtitle?: string;
  accentColor?: string;
  textColor?: string;
  /** Presenter clip has alpha: draw a backdrop under it (layer stack: backdrop -> presenter -> captions). */
  alpha?: boolean;
  backdropColor?: string;
  /** Owner's background catalog entry (procedural spec or plate image); drawn under the alpha presenter. */
  backdrop?: PresenterBackdropSpec;
}

export const PresenterFullScreen: React.FC<PresenterFullScreenProps> = ({
  src,
  startFrom = 0,
  title,
  subtitle,
  accentColor = "#22D3EE",
  textColor = "#F8FAFC",
  alpha = false,
  backdropColor = "#0F172A",
  backdrop,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const canvas = { width: width || 1920, height: height || 1080 };
  const lt = toPx(getLayout(canvas.width, canvas.height).lowerThird, canvas);
  const fs = canvas.height / 1080;

  // Gentle subtle camera push-in, but never on a matted (alpha) presenter: the backdrop does not move, so the person
  // would visibly grow over the clip (owner feedback: "head resizing towards the end").
  const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = alpha ? 1.0 : 1.0 + progress * 0.04;

  const badgeSpring = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 100 },
  });

  return (
    <AbsoluteFill
      style={{
        overflow: "hidden",
        background: alpha ? backdropColor : "#0F172A",
      }}
    >
      {alpha && backdrop && <PresenterBackdrop spec={backdrop} />}
      {/* Presenter Video */}
      <OffthreadVideo
        src={resolveAsset(src)}
        startFrom={Math.round(startFrom * fps)}
        muted
        transparent={alpha}
        style={{
          width: "100%",
          height: "100%",
          objectFit: alpha ? "contain" : "cover",
          transform: `scale(${scale})`,
          willChange: "transform",
        }}
      />

      {/* Subtle vignette for cinematic depth */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 60%, rgba(15, 23, 42, 0.55) 100%), linear-gradient(to top, rgba(15,23,42,0.7) 0%, transparent 25%)",
          pointerEvents: "none",
        }}
      />

      {/* Optional Presenter / Topic Lower Third Badge */}
      {title && (
        <div
          style={{
            position: "absolute",
            left: lt.x,
            top: lt.y,
            opacity: badgeSpring,
            transform: `translateY(${interpolate(badgeSpring, [0, 1], [20, 0])}px)`,
            background: "rgba(15, 23, 42, 0.85)",
            border: `1px solid ${accentColor}50`,
            borderRadius: 14,
            padding: `${Math.round(12 * fs)}px ${Math.round(24 * fs)}px`,
            backdropFilter: "blur(12px)",
            boxShadow: "0 8px 24px rgba(0, 0, 0, 0.4)",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            fontFamily: "Space Grotesk, Inter, system-ui, sans-serif",
            maxWidth: lt.w,
          }}
        >
          <div style={{ fontSize: Math.round(20 * fs), textTransform: "uppercase", letterSpacing: 1.2, color: accentColor, fontWeight: 700 }}>
            Presenter Guide
          </div>
          <div style={{ fontSize: Math.round(34 * fs), fontWeight: 700, color: textColor }}>
            {title}
          </div>
          {subtitle && (
            <div style={{ fontSize: Math.round(24 * fs), color: `${textColor}99` }}>
              {subtitle}
            </div>
          )}
        </div>
      )}
    </AbsoluteFill>
  );
};
