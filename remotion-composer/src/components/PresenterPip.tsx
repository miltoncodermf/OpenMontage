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

export interface PresenterPipProps {
  presenterSrc: string;
  startFrom?: number;
  position?: "bottom-right" | "bottom-left" | "top-right" | "top-left";
  pipWidthPercent?: number; // 22 - 28%
  accentColor?: string;
  borderRadius?: number;
  label?: string;
  /** Presenter clip carries an alpha channel (ProRes 4444 / VP9): composite it as a separate layer. */
  alpha?: boolean;
  children?: React.ReactNode;
}

export const PresenterPip: React.FC<PresenterPipProps> = ({
  presenterSrc,
  startFrom = 0,
  position = "bottom-right",
  pipWidthPercent = 25,
  accentColor = "#22D3EE",
  borderRadius = 16,
  label,
  alpha = false,
  children,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  const canvas = { width: width || 1920, height: height || 1080 };
  // Normalized layout (aspect-aware) -> pixels from the active canvas.
  const rect = toPx(getLayout(canvas.width, canvas.height).pip(position, pipWidthPercent / 100, canvas), canvas);

  const posStyle: React.CSSProperties = {
    position: "absolute",
    left: rect.x,
    top: rect.y,
    width: rect.w,
    height: rect.h,
    borderRadius,
    overflow: "hidden",
    boxShadow: alpha ? "none" : `0 16px 36px rgba(0, 0, 0, 0.6), 0 0 20px ${accentColor}25`,
    border: alpha ? "none" : `2px solid ${accentColor}80`,
    zIndex: 40,
  };

  const entrance = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 100 },
  });

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {/* Background Main Canvas Content (diagram, screen demo, broll, etc.) */}
      {children}

      {/* Floating PIP Presenter Window */}
      <div
        style={{
          ...posStyle,
          opacity: entrance,
          transform: `scale(${interpolate(entrance, [0, 1], [0.85, 1])})`,
          willChange: "transform, opacity",
          backgroundColor: alpha ? "transparent" : "#0F172A",
        }}
      >
        <OffthreadVideo
          src={resolveAsset(presenterSrc)}
          startFrom={Math.round(startFrom * fps)}
          muted
          transparent={alpha}
          style={{
            width: "100%",
            height: "100%",
            objectFit: alpha ? "contain" : "cover",
          }}
        />

        {/* Presenter Name / Status Pill */}
        {label && (
          <div
            style={{
              position: "absolute",
              bottom: 8,
              left: 10,
              background: "rgba(15, 23, 42, 0.8)",
              padding: "2px 8px",
              borderRadius: 6,
              fontSize: Math.round(canvas.height * 0.016),
              fontWeight: 700,
              color: accentColor,
              fontFamily: "Space Grotesk, Inter, sans-serif",
              letterSpacing: 0.5,
              border: `1px solid ${accentColor}40`,
            }}
          >
            {label}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
