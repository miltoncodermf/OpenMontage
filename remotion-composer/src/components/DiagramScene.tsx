import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

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

  const title = diagramSpec.title || "System Architecture";
  const subtitle = diagramSpec.subtitle || "";

  // Normalize nodes
  const rawNodes = diagramSpec.nodes || [];
  const nodes: DiagramNode[] = rawNodes.map((n, i) => {
    if (typeof n === "string") {
      return { id: `node_${i}`, label: n };
    }
    return n;
  });

  // Normalize edges
  const rawEdges = diagramSpec.edges || [];
  const edges: DiagramEdge[] = rawEdges.map((e) => {
    if (Array.isArray(e)) {
      return { from: e[0], to: e[1] };
    }
    return e;
  });

  const nodeCount = Math.max(1, nodes.length);
  // Compute horizontal layout coordinates
  const canvasWidth = width || 1920;
  const canvasHeight = height || 1080;
  const paddingX = 140;
  const usableWidth = canvasWidth - paddingX * 2;
  const cardWidth = Math.min(320, Math.floor(usableWidth / (nodeCount * 1.25)));
  const cardHeight = 160;
  const centerY = canvasHeight * 0.52;

  const spacing = nodeCount > 1 ? (usableWidth - cardWidth * nodeCount) / (nodeCount - 1) : 0;

  const nodePositions = nodes.map((_, i) => {
    const x = paddingX + i * (cardWidth + spacing) + cardWidth / 2;
    return { x, y: centerY };
  });

  // Staggered node entrance
  const titleSpring = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 100 },
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor,
        padding: "60px 100px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        fontFamily: "Space Grotesk, Inter, system-ui, sans-serif",
      }}
    >
      {/* Title Section */}
      <div
        style={{
          opacity: titleSpring,
          transform: `translateY(${interpolate(titleSpring, [0, 1], [-20, 0])}px)`,
          textAlign: "left",
          zIndex: 10,
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            background: "rgba(34, 211, 238, 0.12)",
            border: `1px solid ${accentColor}40`,
            borderRadius: 20,
            padding: "6px 16px",
            marginBottom: 12,
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: accentColor }} />
          <span style={{ fontSize: 16, fontWeight: 700, color: accentColor, textTransform: "uppercase", letterSpacing: 1.5 }}>
            Architecture Flow
          </span>
        </div>
        <h2 style={{ fontSize: 44, fontWeight: 700, color: textColor, margin: "4px 0", letterSpacing: -0.5 }}>
          {title}
        </h2>
        {subtitle && (
          <p style={{ fontSize: 22, color: `${textColor}99`, margin: "4px 0 0 0" }}>
            {subtitle}
          </p>
        )}
      </div>

      {/* Diagram Canvas with SVG Connections & Node Cards */}
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
        <svg
          style={{ width: "100%", height: "100%", position: "absolute", inset: 0 }}
          viewBox={`0 0 ${canvasWidth} ${canvasHeight}`}
        >
          <defs>
            <marker
              id="arrowhead"
              markerWidth="10"
              markerHeight="7"
              refX="9"
              refY="3.5"
              orient="auto"
            >
              <polygon points="0 0, 10 3.5, 0 7" fill={accentColor} opacity="0.9" />
            </marker>
          </defs>

          {/* Render Connections */}
          {edges.map((edge, idx) => {
            const fromIdx = nodes.findIndex((n) => n.id === edge.from || n.label === edge.from);
            const toIdx = nodes.findIndex((n) => n.id === edge.to || n.label === edge.to);
            if (fromIdx === -1 || toIdx === -1) return null;

            const startX = nodePositions[fromIdx].x + cardWidth / 2;
            const startY = nodePositions[fromIdx].y;
            const endX = nodePositions[toIdx].x - cardWidth / 2;
            const endY = nodePositions[toIdx].y;

            // Animate arrow draw
            const delay = 10 + Math.min(fromIdx, toIdx) * 8;
            const arrowProgress = spring({
              frame: Math.max(0, frame - delay),
              fps,
              config: { damping: 20, stiffness: 80 },
            });

            const currentEndX = interpolate(arrowProgress, [0, 1], [startX, endX]);

            return (
              <g key={`edge_${idx}`}>
                <line
                  x1={startX}
                  y1={startY}
                  x2={currentEndX}
                  y2={endY}
                  stroke={accentColor}
                  strokeWidth={3}
                  strokeDasharray="6 4"
                  opacity={arrowProgress * 0.8}
                  markerEnd={arrowProgress > 0.8 ? "url(#arrowhead)" : undefined}
                />
                {edge.label && arrowProgress > 0.6 && (
                  <text
                    x={(startX + endX) / 2}
                    y={startY - 14}
                    fill={`${textColor}99`}
                    fontSize={15}
                    textAnchor="middle"
                    fontFamily="Space Grotesk, sans-serif"
                  >
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {/* Node Cards */}
        {nodes.map((node, i) => {
          const pos = nodePositions[i];
          const delay = 6 + i * 8;
          const nodeSpring = spring({
            frame: Math.max(0, frame - delay),
            fps,
            config: { damping: 16, stiffness: 120 },
          });

          const isActive = diagramSpec.activeIndex !== undefined ? diagramSpec.activeIndex === i : true;

          return (
            <div
              key={node.id}
              style={{
                position: "absolute",
                left: pos.x - cardWidth / 2,
                top: pos.y - cardHeight / 2,
                width: cardWidth,
                height: cardHeight,
                opacity: nodeSpring,
                transform: `scale(${interpolate(nodeSpring, [0, 1], [0.85, 1])}) translateY(${interpolate(
                  nodeSpring,
                  [0, 1],
                  [30, 0]
                )}px)`,
                background: isActive
                  ? "linear-gradient(135deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.95))"
                  : "rgba(15, 23, 42, 0.7)",
                border: `2px solid ${isActive ? accentColor : "rgba(148, 163, 184, 0.2)"}`,
                borderRadius: 16,
                boxShadow: isActive
                  ? `0 12px 32px rgba(0, 0, 0, 0.45), 0 0 24px ${accentColor}30`
                  : "0 8px 24px rgba(0, 0, 0, 0.3)",
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                alignItems: "center",
                padding: "20px",
                textAlign: "center",
                backdropFilter: "blur(12px)",
              }}
            >
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 10,
                  background: `${accentColor}20`,
                  border: `1px solid ${accentColor}50`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: accentColor,
                  fontWeight: 700,
                  fontSize: 18,
                  marginBottom: 10,
                }}
              >
                {i + 1}
              </div>
              <div
                style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: textColor,
                  lineHeight: 1.25,
                }}
              >
                {node.label}
              </div>
              {node.sublabel && (
                <div
                  style={{
                    fontSize: 14,
                    color: `${textColor}99`,
                    marginTop: 6,
                    lineHeight: 1.3,
                  }}
                >
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
