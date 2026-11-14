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

export interface PresenterFullScreenProps {
  src: string;
  startFrom?: number;
  title?: string;
  subtitle?: string;
  accentColor?: string;
  textColor?: string;
}

export const PresenterFullScreen: React.FC<PresenterFullScreenProps> = ({
  src,
  startFrom = 0,
  title,
  subtitle,
  accentColor = "#22D3EE",
  textColor = "#F8FAFC",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // Gentle subtle camera push-in
  const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = 1.0 + progress * 0.04;

  const badgeSpring = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 100 },
  });

  return (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#0F172A" }}>
      {/* Presenter Video */}
      <OffthreadVideo
        src={resolveAsset(src)}
        startFrom={Math.round(startFrom * fps)}
        muted
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
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
            bottom: 70,
            left: 80,
            opacity: badgeSpring,
            transform: `translateY(${interpolate(badgeSpring, [0, 1], [20, 0])}px)`,
            background: "rgba(15, 23, 42, 0.85)",
            border: `1px solid ${accentColor}50`,
            borderRadius: 14,
            padding: "12px 24px",
            backdropFilter: "blur(12px)",
            boxShadow: "0 8px 24px rgba(0, 0, 0, 0.4)",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            fontFamily: "Space Grotesk, Inter, system-ui, sans-serif",
            maxWidth: 600,
          }}
        >
          <div style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: 1.2, color: accentColor, fontWeight: 700 }}>
            Presenter Guide
          </div>
          <div style={{ fontSize: 24, fontWeight: 700, color: textColor }}>
            {title}
          </div>
          {subtitle && (
            <div style={{ fontSize: 16, color: `${textColor}99` }}>
              {subtitle}
            </div>
          )}
        </div>
      )}
    </AbsoluteFill>
  );
};
