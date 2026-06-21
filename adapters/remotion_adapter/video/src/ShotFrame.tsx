/**
 * ShotFrame — renders a single Shot as a full-screen frame.
 *
 * Layout:
 *   - Black background (solid clips) or placeholder gradient
 *   - Shot type badge at top
 *   - Text overlays in sequence
 *   - Figure overlays: label + verbatim value (immutability contract)
 *   - Disclaimer shots get a distinct yellow border + "DISCLAIMER" label
 *
 * No private tooling, naming conventions, or external UI libraries.
 */

import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";
import type { Shot, Overlay } from "./types";

// ── Design constants (SSOT for this adapter) ─────────────────────────────────
const FONT_FAMILY = "sans-serif";
const COLOR_BG = "#000000";
const COLOR_TEXT = "#ffffff";
const COLOR_FIGURE = "#ffe066";
const COLOR_DISCLAIMER = "#aaaaaa";
const COLOR_DISCLAIMER_BORDER = "#ffe066";
const FONT_SIZE_TYPE_BADGE = 22;
const FONT_SIZE_TEXT = 28;
const FONT_SIZE_FIGURE_LABEL = 24;
const FONT_SIZE_FIGURE_VALUE = 36;
const FONT_SIZE_DISCLAIMER = 22;
const PADDING_H = 40;
const PADDING_V = 80;

interface ShotFrameProps {
  shot: Shot;
  /** Duration in frames for fade-in animation */
  durationFrames: number;
}

export const ShotFrame: React.FC<ShotFrameProps> = ({ shot, durationFrames }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, Math.min(8, durationFrames - 1)], [0, 1], {
    extrapolateRight: "clamp",
  });

  const isDisclaimer = shot.type === "disclaimer";
  const bgColor = shot.clip?.color ?? COLOR_BG;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: bgColor,
        opacity,
        fontFamily: FONT_FAMILY,
        color: COLOR_TEXT,
        padding: `${PADDING_V}px ${PADDING_H}px`,
        flexDirection: "column",
        justifyContent: "flex-start",
        alignItems: "flex-start",
        border: isDisclaimer ? `4px solid ${COLOR_DISCLAIMER_BORDER}` : "none",
        boxSizing: "border-box",
      }}
    >
      {/* Shot type badge */}
      <div
        style={{
          fontSize: FONT_SIZE_TYPE_BADGE,
          color: isDisclaimer ? COLOR_DISCLAIMER : COLOR_FIGURE,
          textTransform: "uppercase",
          letterSpacing: 4,
          marginBottom: 24,
          opacity: 0.8,
        }}
      >
        {shot.type}
      </div>

      {/* Overlays */}
      {shot.overlays.map((overlay, idx) => (
        <OverlayBlock key={idx} overlay={overlay} isDisclaimer={isDisclaimer} />
      ))}
    </AbsoluteFill>
  );
};

interface OverlayBlockProps {
  overlay: Overlay;
  isDisclaimer: boolean;
}

const OverlayBlock: React.FC<OverlayBlockProps> = ({ overlay, isDisclaimer }) => {
  if (overlay.kind === "text" && overlay.text) {
    return (
      <div
        style={{
          fontSize: isDisclaimer ? FONT_SIZE_DISCLAIMER : FONT_SIZE_TEXT,
          color: isDisclaimer ? COLOR_DISCLAIMER : COLOR_TEXT,
          marginBottom: 20,
          lineHeight: 1.5,
          wordBreak: "break-word",
        }}
      >
        {overlay.text}
      </div>
    );
  }

  if (overlay.kind === "figure" && overlay.label != null && overlay.value != null) {
    // Figure values MUST be reproduced verbatim (renderer contract immutability rule)
    return (
      <div
        style={{
          marginBottom: 32,
          borderLeft: `4px solid ${COLOR_FIGURE}`,
          paddingLeft: 16,
        }}
      >
        <div
          style={{
            fontSize: FONT_SIZE_FIGURE_LABEL,
            color: COLOR_TEXT,
            opacity: 0.7,
            textTransform: "uppercase",
            letterSpacing: 2,
            marginBottom: 4,
          }}
        >
          {overlay.label}
        </div>
        {/* Value rendered verbatim — no rounding, abbreviation, or translation */}
        <div
          style={{
            fontSize: FONT_SIZE_FIGURE_VALUE,
            color: COLOR_FIGURE,
            fontWeight: "bold",
          }}
        >
          {overlay.value}
        </div>
      </div>
    );
  }

  return null;
};
