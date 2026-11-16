import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  useVideoConfig,
} from "remotion";
import { resolveAsset } from "../lib/resolveAsset";
import { getLayout, toPx } from "../layouts";
import { PresenterBackdrop, PresenterBackdropSpec } from "./PresenterBackdrop";

export interface PresenterScreenSplitProps {
  presenterSrc: string;
  startFrom?: number;
  presenterSide?: "left" | "right";
  splitRatio?: number; // default 0.35 (35% presenter, 65% screen)
  accentColor?: string;
  alpha?: boolean;
  backdrop?: PresenterBackdropSpec;
  children?: React.ReactNode;
}

export const PresenterScreenSplit: React.FC<PresenterScreenSplitProps> = ({
  presenterSrc,
  startFrom = 0,
  presenterSide = "left",
  splitRatio = 0.35,
  accentColor = "#22D3EE",
  alpha = false,
  backdrop,
  children,
}) => {
  const { fps, width, height } = useVideoConfig();
  const canvas = { width: width || 1920, height: height || 1080 };
  const panels = getLayout(canvas.width, canvas.height).split(presenterSide, splitRatio);
  const pr = toPx(panels.presenter, canvas);
  const cr = toPx(panels.content, canvas);

  return (
    <AbsoluteFill style={{ backgroundColor: "#0F172A", overflow: "hidden" }}>
      {/* Presenter Panel (alpha layer composited over the panel backdrop) */}
      <div
        style={{
          position: "absolute", left: pr.x, top: pr.y, width: pr.w, height: pr.h,
          borderRight: presenterSide === "left" ? `2px solid ${accentColor}40` : undefined,
          borderLeft: presenterSide === "right" ? `2px solid ${accentColor}40` : undefined,
          overflow: "hidden",
          backgroundColor: "#0B1120",
        }}
      >
        {alpha && backdrop && <PresenterBackdrop spec={backdrop} />}
        <OffthreadVideo
          src={resolveAsset(presenterSrc)}
          startFrom={Math.round(startFrom * fps)}
          muted
          transparent={alpha}
          style={{ width: "100%", height: "100%", objectFit: alpha ? "contain" : "cover" }}
        />
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "linear-gradient(to top, rgba(11,17,32,0.6) 0%, transparent 20%)",
            pointerEvents: "none",
          }}
        />
      </div>

      {/* Screen / Diagram Panel */}
      <div style={{ position: "absolute", left: cr.x, top: cr.y, width: cr.w, height: cr.h, overflow: "hidden" }}>
        {children}
      </div>
    </AbsoluteFill>
  );
};
