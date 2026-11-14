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

export interface PresenterPipProps {
  presenterSrc: string;
  startFrom?: number;
  position?: "bottom-right" | "bottom-left" | "top-right" | "top-left";
  pipWidthPercent?: number; // 22 - 28%
  accentColor?: string;
  borderRadius?: number;
  label?: string;
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
  children,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  const canvasWidth = width || 1920;
  const canvasHeight = height || 1080;

  const pipWidth = Math.round(canvasWidth * (pipWidthPercent / 100));
  const pipHeight = Math.round(pipWidth * (9 / 16)); // 16:9 ratio

  const marginX = Math.round(canvasWidth * 0.05); // 5% margin
  const marginY = Math.round(canvasHeight * 0.06); // 6% margin

  const posStyle: React.CSSProperties = {
    position: "absolute",
    width: pipWidth,
    height: pipHeight,
    borderRadius,
    overflow: "hidden",
    boxShadow: `0 16px 36px rgba(0, 0, 0, 0.6), 0 0 20px ${accentColor}25`,
    border: `2px solid ${accentColor}80`,
    zIndex: 40,
  };

  if (position === "bottom-right") {
    posStyle.right = marginX;
    posStyle.bottom = marginY + 60; // Keep slightly above caption zone
  } else if (position === "bottom-left") {
    posStyle.left = marginX;
    posStyle.bottom = marginY + 60;
  } else if (position === "top-right") {
    posStyle.right = marginX;
    posStyle.top = marginY;
  } else {
    posStyle.left = marginX;
    posStyle.top = marginY;
  }

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
          backgroundColor: "#0F172A",
        }}
      >
        <OffthreadVideo
          src={resolveAsset(presenterSrc)}
          startFrom={Math.round(startFrom * fps)}
          muted
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
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
              fontSize: 11,
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
