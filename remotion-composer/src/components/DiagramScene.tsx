import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { diagramFontSizes, getLayout, MAX_NODES_PER_BEAT } from "../layouts";

export interface DiagramNode {
  id: string;
  label: string;
  sublabel?: string;
  icon?: string;
}

export interface DiagramEdge {
  from: string;
  to: string;
  label?: string;
}

export interface DiagramSpec {
  title?: string;
  subtitle?: string;
  nodes: Array<DiagramNode | string>;
  edges?: Array<DiagramEdge | [string, string]>;
  buildOrder?: string[];
  activeIndex?: number;
}

export interface DiagramSceneProps {
  diagramSpec: DiagramSpec;
  accentColor?: string;
  textColor?: string;
  backgroundColor?: string;
}

export const DiagramScene: React.FC<DiagramSceneProps> = ({
  diagramSpec,
  accentColor = "#22D3EE",
  textColor = "#F8FAFC",
  backgroundColor = "transparent",
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const canvas = { width: width || 1920, height: height || 1080 };
  // Legibility (spec §5.9): sizes are defined at 1080p and scale with canvas height.
  const font = diagramFontSizes(canvas.height);
  const scale = canvas.height / 1080;

  const title = diagramSpec.title || "System Architecture";
  const subtitle = diagramSpec.subtitle || "";

  const nodes: DiagramNode[] = (diagramSpec.nodes || [])
    .map((n, i) => (typeof n === "string" ? { id: `node_${i}`, label: n } : n))
    .slice(0, MAX_NODES_PER_BEAT); // >7 nodes must be split across beats (progressive reveal) upstream

  const edges: DiagramEdge[] = (diagramSpec.edges || []).map((e) => (Array.isArray(e) ? { from: e[0], to: e[1] } : e));

  const grid = getLayout(canvas.width, canvas.height).diagramGrid(nodes.length);
  const cardW = grid.cardW * canvas.width;
  const cardH = grid.cardH * canvas.height;
  const nodePositions = grid.centers.map((c) => ({ x: c.x * canvas.width, y: c.y * canvas.height }));

  const titleSpring = spring({ frame, fps, config: { damping: 18, stiffness: 100 } });

  return (
    <AbsoluteFill
      style={{
        backgroundColor,
        padding: `${Math.round(48 * scale)}px ${Math.round(80 * scale)}px`,
        fontFamily: "Space Grotesk, Inter, system-ui, sans-serif",
      }}
    >
      <div
        style={{
          opacity: titleSpring,
          transform: `translateY(${interpolate(titleSpring, [0, 1], [-20, 0])}px)`,
          textAlign: "left",
          zIndex: 10,
        }}
      >
        <h2 style={{ fontSize: font.title, fontWeight: 700, color: textColor, margin: "4px 0", letterSpacing: -0.5, lineHeight: 1.1 }}>
          {title}
        </h2>
        {subtitle && (
          <p style={{ fontSize: font.sublabel, color: textColor, opacity: 0.85, margin: "4px 0 0 0" }}>{subtitle}</p>
        )}
      </div>

      <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
        <svg style={{ width: "100%", height: "100%", position: "absolute", inset: 0 }} viewBox={`0 0 ${canvas.width} ${canvas.height}`}>
          <defs>
            <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
              <polygon points="0 0, 10 3.5, 0 7" fill={accentColor} opacity="0.9" />
            </marker>
          </defs>
          {edges.map((edge, idx) => {
            const fromIdx = nodes.findIndex((n) => n.id === edge.from || n.label === edge.from);
            const toIdx = nodes.findIndex((n) => n.id === edge.to || n.label === edge.to);
            if (fromIdx === -1 || toIdx === -1) return null;
            const a = nodePositions[fromIdx];
            const b = nodePositions[toIdx];
            // connect the facing sides when on the same row, otherwise centre-to-centre edges of the cards
            const sameRow = Math.abs(a.y - b.y) < 1;
            const dir = b.x >= a.x ? 1 : -1;
            const startX = sameRow ? a.x + (dir * cardW) / 2 : a.x;
            const startY = sameRow ? a.y : a.y + cardH / 2;
            const endX = sameRow ? b.x - (dir * cardW) / 2 : b.x;
            const endY = sameRow ? b.y : b.y - cardH / 2;
            const delay = 10 + Math.min(fromIdx, toIdx) * 8;
            const arrowProgress = spring({ frame: Math.max(0, frame - delay), fps, config: { damping: 20, stiffness: 80 } });
            const curX = interpolate(arrowProgress, [0, 1], [startX, endX]);
            const curY = interpolate(arrowProgress, [0, 1], [startY, endY]);
            return (
              <g key={`edge_${idx}`}>
                <line
                  x1={startX} y1={startY} x2={curX} y2={curY}
                  stroke={accentColor} strokeWidth={Math.max(3, 4 * scale)} strokeDasharray="8 5"
                  opacity={arrowProgress * 0.9}
                  markerEnd={arrowProgress > 0.8 ? "url(#arrowhead)" : undefined}
                />
                {edge.label && arrowProgress > 0.6 && (
                  <text
                    x={(startX + endX) / 2} y={(startY + endY) / 2 - 14 * scale}
                    fill={textColor} fontSize={font.edgeLabel} textAnchor="middle"
                    fontFamily="Space Grotesk, sans-serif" fontWeight={600}
                  >
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {nodes.map((node, i) => {
          const pos = nodePositions[i];
          const nodeSpring = spring({ frame: Math.max(0, frame - (6 + i * 8)), fps, config: { damping: 16, stiffness: 120 } });
          const isActive = diagramSpec.activeIndex !== undefined ? diagramSpec.activeIndex === i : true;
          return (
            <div
              key={node.id}
              style={{
                position: "absolute",
                left: pos.x - cardW / 2,
                top: pos.y - cardH / 2,
                width: cardW,
                height: cardH,
                opacity: nodeSpring,
                transform: `scale(${interpolate(nodeSpring, [0, 1], [0.85, 1])}) translateY(${interpolate(nodeSpring, [0, 1], [30, 0])}px)`,
                // dark card behind light text: >= 4.5:1 (checked by lib/diagram_legibility.py)
                background: isActive ? "linear-gradient(135deg, #1E293B, #0F172A)" : "#0F172A",
                border: `${Math.max(2, 3 * scale)}px solid ${isActive ? accentColor : "rgba(148, 163, 184, 0.35)"}`,
                borderRadius: 16 * scale,
                boxShadow: isActive ? `0 12px 32px rgba(0, 0, 0, 0.45), 0 0 24px ${accentColor}30` : "0 8px 24px rgba(0, 0, 0, 0.3)",
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                alignItems: "center",
                padding: `${Math.round(12 * scale)}px`,
                textAlign: "center",
                overflow: "hidden",
              }}
            >
              <div style={{ fontSize: font.label, fontWeight: 700, color: textColor, lineHeight: 1.15, wordBreak: "break-word" }}>
                {node.label}
              </div>
              {node.sublabel && (
                <div style={{ fontSize: font.sublabel, color: textColor, opacity: 0.85, marginTop: 6 * scale, lineHeight: 1.2 }}>
                  {node.sublabel}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
