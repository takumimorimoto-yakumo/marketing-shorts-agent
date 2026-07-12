/**
 * ShotFrame — renders a single Shot as a full-screen frame.
 *
 * Design: meigara 計器盤美学
 *   - Sharp / low density / tabular-nums / line-based structure
 *   - 3-tier text hierarchy: textHigh / textMid / textLow
 *   - Amber accent for financial figures
 *   - Subtle gradient background (no flat black)
 *   - Spring + interpolate entrance (slide-up + fade); NO CSS animations
 *
 * ALL design values come from theme.ts (SSOT). No raw values here.
 *
 * Storyboard JSON schema (types.ts) is NOT modified.
 * Figure values are reproduced verbatim (renderer contract v1.0.0).
 */

import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Sequence,
} from "remotion";
import type { Shot, Overlay, ShotType } from "./types";
import {
  COLOR,
  FONT,
  FONT_SIZE,
  SPACE,
  RADIUS,
  MOTION,
  GRADIENT,
  EASE,
  entranceBounds,
  exitBounds,
  buildGradient,
} from "./theme";

// ── Types ─────────────────────────────────────────────────────────────────────
interface ShotFrameProps {
  shot: Shot;
  /** Duration of this shot in frames (from Sequence) */
  durationFrames: number;
}

// ── ShotFrame (top-level) ──────────────────────────────────────────────────────
export const ShotFrame: React.FC<ShotFrameProps> = ({ shot, durationFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = entranceBounds(durationFrames);
  const exit = exitBounds(durationFrames);

  // Whole-frame fade-in (very short, frames 0→enter.end)
  const frameOpacity = interpolate(
    frame,
    [enter.start, enter.end],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.outQuad },
  );

  // Whole-frame fade-out at end
  const frameOpacityOut = interpolate(
    frame,
    [exit.start, exit.end],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.inOutQuad },
  );

  const compositeOpacity = Math.min(frameOpacity, frameOpacityOut);

  const isDisclaimer = shot.type === "disclaimer";
  const background = buildGradient(GRADIENT[shot.type as keyof typeof GRADIENT] ?? GRADIENT.narration);

  return (
    <AbsoluteFill
      style={{
        background,
        fontFamily: FONT.sans,
        opacity: compositeOpacity,
        boxSizing: "border-box",
        overflow: "hidden",
      }}
    >
      {/* Vignette overlay — subtle radial darkness around edges */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at 50% 50%, transparent 40%, rgba(0,0,0,0.45) 100%)",
          pointerEvents: "none",
        }}
      />

      {/* Disclaimer: amber top/bottom border lines */}
      {isDisclaimer && (
        <>
          <div style={hairlineBarStyle("top")} />
          <div style={hairlineBarStyle("bottom")} />
        </>
      )}

      {/* Content router by shot type */}
      {shot.type === "hook" && (
        <HookLayout shot={shot} durationFrames={durationFrames} frame={frame} fps={fps} />
      )}
      {shot.type === "narration" && (
        <NarrationLayout shot={shot} durationFrames={durationFrames} frame={frame} fps={fps} />
      )}
      {shot.type === "figures" && (
        <FiguresLayout shot={shot} durationFrames={durationFrames} frame={frame} fps={fps} />
      )}
      {shot.type === "disclaimer" && (
        <DisclaimerLayout shot={shot} durationFrames={durationFrames} frame={frame} fps={fps} />
      )}

      {/* Shot type badge — bottom-left corner structural label */}
      <ShotBadge type={shot.type} frame={frame} durationFrames={durationFrames} fps={fps} />
    </AbsoluteFill>
  );
};

// ── Shared helpers ────────────────────────────────────────────────────────────
function hairlineBarStyle(position: "top" | "bottom"): React.CSSProperties {
  return {
    position: "absolute",
    [position]: 0,
    left: 0,
    right: 0,
    height: 3,
    background: `linear-gradient(to right, transparent, ${COLOR.disclaimerBorder}, transparent)`,
  };
}

interface LayoutProps {
  shot: Shot;
  durationFrames: number;
  frame: number;
  fps: number;
}

// ── useEntranceSpring ─────────────────────────────────────────────────────────
// Returns a 0→1 spring progress clamped to durationFrames.
function useEntranceSpring(frame: number, fps: number, durationFrames: number, delayFrames = 0) {
  const enterEnd = entranceBounds(durationFrames).end;
  return spring({
    frame: frame - delayFrames,
    fps,
    config: MOTION.springConfig,
    durationInFrames: enterEnd,
  });
}

// ── Hook Layout ───────────────────────────────────────────────────────────────
// Visually dominant. Large typography centered vertically.
// Single most-important message — grabs viewer in first 3s.
const HookLayout: React.FC<LayoutProps> = ({ shot, durationFrames, frame, fps }) => {
  const enter = entranceBounds(durationFrames);

  // headline: spring slide-up + fade
  const headProgress = useEntranceSpring(frame, fps, durationFrames, 0);
  const headY = interpolate(headProgress, [0, 1], [MOTION.slideYEntrance, 0]);
  const headOpacity = interpolate(frame, [0, enter.end], [0, 1], {
    extrapolateRight: "clamp",
    easing: EASE.outQuad,
  });

  // sub text: slightly delayed
  const subDelayFrames = Math.round(enter.end * 0.4);
  const subProgress = useEntranceSpring(frame, fps, durationFrames, subDelayFrames);
  const subY = interpolate(subProgress, [0, 1], [MOTION.slideYEntrance * 0.6, 0]);
  const subOpacity = interpolate(frame, [subDelayFrames, enter.end + subDelayFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE.outQuad,
  });

  // Separate text overlays into headline (first text) and rest
  const textOverlays = shot.overlays.filter((o) => o.kind === "text" && o.text);
  const headlineOverlay = textOverlays[0];
  const subOverlays = textOverlays.slice(1);

  return (
    <AbsoluteFill
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-start",
        alignItems: "flex-start",
        padding: `${SPACE.paddingV}px ${SPACE.paddingH}px`,
        paddingTop: Math.round(1920 * 0.32), // 32% from top — visual center slightly above mid
      }}
    >
      {/* Vertical accent line — left structural element (inside padding zone) */}
      <div
        style={{
          position: "absolute",
          left: SPACE.paddingH - 24,
          top: "25%",
          bottom: "30%",
          width: 3,
          borderRadius: RADIUS.sm,
          background: `linear-gradient(to bottom, transparent, ${COLOR.cobalt} 30%, ${COLOR.cobalt} 70%, transparent)`,
          opacity: headOpacity,
        }}
      />

      {/* Headline text */}
      {headlineOverlay?.text && (
        <div
          style={{
            fontFamily: FONT.sans,
            fontSize: FONT_SIZE.hookHead,
            fontWeight: 700,
            color: COLOR.textHigh,
            lineHeight: 1.12,
            letterSpacing: "-1px",
            transform: `translateY(${headY}px)`,
            opacity: headOpacity,
            paddingLeft: SPACE.lg,
            marginBottom: SPACE.lg,
            maxWidth: "100%",
          }}
        >
          {headlineOverlay.text}
        </div>
      )}

      {/* Sub-text overlays */}
      {subOverlays.map((ov, idx) => (
        <div
          key={idx}
          style={{
            fontFamily: FONT.sans,
            fontSize: FONT_SIZE.hookSub,
            fontWeight: 400,
            color: COLOR.textMid,
            lineHeight: 1.4,
            transform: `translateY(${subY}px)`,
            opacity: subOpacity,
            paddingLeft: SPACE.lg,
            marginBottom: SPACE.md,
            maxWidth: "88%",
          }}
        >
          {ov.text}
        </div>
      ))}

      {/* Figure overlays in hook (rare but supported) */}
      {shot.overlays
        .filter((o) => o.kind === "figure")
        .map((ov, idx) => (
          <InlineFigure key={idx} overlay={ov} frame={frame} fps={fps} durationFrames={durationFrames} />
        ))}
    </AbsoluteFill>
  );
};

// ── Narration Layout ──────────────────────────────────────────────────────────
// Readable mid-size text. Left-aligned, controlled line length.
const NarrationLayout: React.FC<LayoutProps> = ({ shot, durationFrames, frame, fps }) => {
  const enter = entranceBounds(durationFrames);
  const staggerBase = Math.round(enter.end * MOTION.staggerRatio);

  return (
    <AbsoluteFill
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        padding: `${SPACE.paddingV}px ${SPACE.paddingH}px`,
      }}
    >
      {shot.overlays.map((overlay, idx) => {
        const delayFrames = idx * staggerBase;

        if (overlay.kind === "text" && overlay.text) {
          const progress = useEntranceSpring(frame, fps, durationFrames, delayFrames);
          const yOffset = interpolate(progress, [0, 1], [MOTION.slideYEntrance, 0]);
          const opacity = interpolate(
            frame,
            [delayFrames, delayFrames + enter.end],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.outQuad },
          );

          return (
            <div
              key={idx}
              style={{
                fontFamily: FONT.sans,
                fontSize: FONT_SIZE.narrBody,
                fontWeight: 400,
                color: COLOR.textHigh,
                lineHeight: 1.65,
                transform: `translateY(${yOffset}px)`,
                opacity,
                marginBottom: SPACE.xl,
                // Limit line length for readability (~28 chars/line at this size)
                maxWidth: "90%",
              }}
            >
              {overlay.text}
            </div>
          );
        }

        if (overlay.kind === "figure") {
          const progress = useEntranceSpring(frame, fps, durationFrames, delayFrames);
          return (
            <NarrationFigureBlock
              key={idx}
              overlay={overlay}
              slideProgress={progress}
              frame={frame}
              delayFrames={delayFrames}
              enterEnd={enter.end}
            />
          );
        }

        return null;
      })}
    </AbsoluteFill>
  );
};

// ── Figures Layout ────────────────────────────────────────────────────────────
// KPI card-centric. Numbers as protagonists with label small / value large.
// "線で構造" — thin borders define card boundaries.
const FiguresLayout: React.FC<LayoutProps> = ({ shot, durationFrames, frame, fps }) => {
  const enter = entranceBounds(durationFrames);
  const figureOverlays = shot.overlays.filter(
    (o) => o.kind === "figure" && o.label != null && o.value != null,
  );
  const textOverlays = shot.overlays.filter((o) => o.kind === "text" && o.text);
  const staggerBase = Math.round(enter.end * MOTION.staggerRatio);

  return (
    <AbsoluteFill
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        padding: `${SPACE.paddingV}px ${SPACE.paddingH}px`,
      }}
    >
      {/* Section heading (text overlays at top) */}
      {textOverlays.map((ov, idx) => {
        const delayFrames = idx * staggerBase;
        const opacity = interpolate(
          frame,
          [delayFrames, delayFrames + enter.end],
          [0, 1],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.outQuad },
        );
        const progress = spring({
          frame: frame - delayFrames,
          fps,
          config: MOTION.springConfig,
          durationInFrames: enter.end,
        });
        const yOffset = interpolate(progress, [0, 1], [MOTION.slideYEntrance * 0.5, 0]);

        return (
          <div
            key={idx}
            style={{
              fontFamily: FONT.sans,
              fontSize: FONT_SIZE.figureLabel + 4,
              fontWeight: 500,
              color: COLOR.textMid,
              letterSpacing: "0.12em",
              textTransform: "uppercase" as const,
              opacity,
              transform: `translateY(${yOffset}px)`,
              marginBottom: SPACE.xl,
            }}
          >
            {ov.text}
          </div>
        );
      })}

      {/* KPI figure cards */}
      {figureOverlays.map((ov, idx) => {
        const delayFrames = (textOverlays.length + idx) * staggerBase;
        const progress = spring({
          frame: frame - delayFrames,
          fps,
          config: MOTION.springConfig,
          durationInFrames: enter.end,
        });
        const xOffset = interpolate(progress, [0, 1], [Math.abs(MOTION.slideXFigure), 0]);
        const opacity = interpolate(
          frame,
          [delayFrames, delayFrames + enter.end],
          [0, 1],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.outQuad },
        );

        return (
          <div
            key={idx}
            style={{
              display: "flex",
              flexDirection: "column",
              marginBottom: SPACE.xl,
              transform: `translateX(${xOffset}px)`,
              opacity,
              // KPI card with amber accent border
              background: COLOR.figureCardBg,
              border: `1px solid ${COLOR.figureCardBorder}`,
              borderLeft: `4px solid ${COLOR.figureAccentBar}`,
              borderRadius: RADIUS.md,
              padding: `${SPACE.md}px ${SPACE.lg}px`,
            }}
          >
            {/* Label */}
            <div
              style={{
                fontFamily: FONT.mono,
                fontSize: FONT_SIZE.figureLabel,
                fontWeight: 400,
                color: COLOR.textMid,
                letterSpacing: "0.14em",
                textTransform: "uppercase" as const,
                marginBottom: SPACE.sm,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {ov.label}
            </div>
            {/* Value — reproduced verbatim (renderer contract) */}
            <div
              style={{
                fontFamily: FONT.mono,
                fontSize: FONT_SIZE.figureValue,
                fontWeight: 700,
                color: COLOR.amber,
                lineHeight: 1,
                fontVariantNumeric: "tabular-nums",
                letterSpacing: "-1px",
              }}
            >
              {ov.value}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

// ── Disclaimer Layout ─────────────────────────────────────────────────────────
// Footer-like, clearly de-emphasized. Small text, amber accent maintained
// for brand continuity but muted. Yellow border intent preserved.
const DisclaimerLayout: React.FC<LayoutProps> = ({ shot, durationFrames, frame, fps }) => {
  const enter = entranceBounds(durationFrames);
  const staggerBase = Math.round(enter.end * MOTION.staggerRatio);

  return (
    <AbsoluteFill
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-end",
        padding: `${SPACE.paddingV}px ${SPACE.paddingH}px`,
        paddingBottom: SPACE.paddingV + SPACE.xxxl,
      }}
    >
      {/* "免責事項" label */}
      <DisclaimerLabel frame={frame} enter={enter} fps={fps} durationFrames={durationFrames} />

      {/* Thin separator line */}
      <div
        style={{
          height: 1,
          background: `linear-gradient(to right, ${COLOR.disclaimerBorder}, transparent)`,
          marginBottom: SPACE.lg,
          opacity: interpolate(frame, [0, enter.end], [0, 1], {
            extrapolateRight: "clamp",
          }),
        }}
      />

      {/* Disclaimer body text */}
      {shot.overlays.map((overlay, idx) => {
        if (overlay.kind !== "text" || !overlay.text) return null;
        const delayFrames = (idx + 1) * staggerBase;
        const opacity = interpolate(
          frame,
          [delayFrames, delayFrames + enter.end],
          [0, 1],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.outQuad },
        );
        const progress = spring({
          frame: frame - delayFrames,
          fps,
          config: MOTION.springConfig,
          durationInFrames: enter.end,
        });
        const yOffset = interpolate(progress, [0, 1], [MOTION.slideYEntrance * 0.4, 0]);

        return (
          <div
            key={idx}
            style={{
              fontFamily: FONT.sans,
              fontSize: FONT_SIZE.disclaimerBody,
              fontWeight: 400,
              color: COLOR.textLow,
              lineHeight: 1.7,
              opacity,
              transform: `translateY(${yOffset}px)`,
              marginBottom: SPACE.sm,
            }}
          >
            {overlay.text}
          </div>
        );
      })}

      {/* Figure overlays in disclaimer (rare) */}
      {shot.overlays
        .filter((o) => o.kind === "figure")
        .map((ov, idx) => (
          <div
            key={idx}
            style={{
              fontFamily: FONT.mono,
              fontSize: FONT_SIZE.disclaimerBody,
              color: COLOR.textLow,
              opacity: interpolate(frame, [0, enter.end], [0, 0.7], {
                extrapolateRight: "clamp",
              }),
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {ov.label}: {ov.value}
          </div>
        ))}
    </AbsoluteFill>
  );
};

// ── Sub-components ────────────────────────────────────────────────────────────

interface DisclaimerLabelProps {
  frame: number;
  enter: { start: number; end: number };
  fps: number;
  durationFrames: number;
}

const DisclaimerLabel: React.FC<DisclaimerLabelProps> = ({ frame, enter }) => {
  const opacity = interpolate(frame, [0, enter.end], [0, 1], {
    extrapolateRight: "clamp",
    easing: EASE.outQuad,
  });

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: SPACE.sm,
        marginBottom: SPACE.md,
        opacity,
      }}
    >
      {/* Small amber dot */}
      <div
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: COLOR.disclaimerAccent,
          opacity: 0.7,
          flexShrink: 0,
        }}
      />
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: FONT_SIZE.badge,
          fontWeight: 500,
          color: COLOR.textLow,
          letterSpacing: "0.18em",
          textTransform: "uppercase" as const,
        }}
      >
        免責事項
      </div>
    </div>
  );
};

// Inline figure for use within Hook layout (compact format)
interface InlineFigureProps {
  overlay: Overlay;
  frame: number;
  fps: number;
  durationFrames: number;
}

const InlineFigure: React.FC<InlineFigureProps> = ({ overlay, frame, fps, durationFrames }) => {
  const enter = entranceBounds(durationFrames);
  const progress = spring({
    frame,
    fps,
    config: MOTION.springConfig,
    durationInFrames: enter.end,
  });
  const yOffset = interpolate(progress, [0, 1], [MOTION.slideYEntrance, 0]);
  const opacity = interpolate(frame, [enter.end * 0.3, enter.end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: SPACE.sm,
        opacity,
        transform: `translateY(${yOffset}px)`,
        marginBottom: SPACE.lg,
        paddingLeft: SPACE.lg,
      }}
    >
      <span
        style={{
          fontFamily: FONT.mono,
          fontSize: FONT_SIZE.figureLabel,
          color: COLOR.textMid,
          letterSpacing: "0.1em",
          textTransform: "uppercase" as const,
        }}
      >
        {overlay.label}
      </span>
      <span
        style={{
          fontFamily: FONT.mono,
          fontSize: FONT_SIZE.hookSub,
          fontWeight: 700,
          color: COLOR.amber,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {overlay.value}
      </span>
    </div>
  );
};

// Figure block within Narration layout (compact, left-bordered)
interface NarrationFigureBlockProps {
  overlay: Overlay;
  slideProgress: number;
  frame: number;
  delayFrames: number;
  enterEnd: number;
}

const NarrationFigureBlock: React.FC<NarrationFigureBlockProps> = ({
  overlay,
  slideProgress,
  frame,
  delayFrames,
  enterEnd,
}) => {
  const yOffset = interpolate(slideProgress, [0, 1], [MOTION.slideYEntrance, 0]);
  const opacity = interpolate(
    frame,
    [delayFrames, delayFrames + enterEnd],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.outQuad },
  );

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        marginBottom: SPACE.lg,
        borderLeft: `3px solid ${COLOR.amber}`,
        paddingLeft: SPACE.md,
        opacity,
        transform: `translateY(${yOffset}px)`,
      }}
    >
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: FONT_SIZE.figureLabel,
          color: COLOR.textMid,
          letterSpacing: "0.12em",
          textTransform: "uppercase" as const,
          marginBottom: SPACE.xs,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {overlay.label}
      </div>
      {/* Value reproduced verbatim */}
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: FONT_SIZE.figureUnit + 12,
          fontWeight: 700,
          color: COLOR.amber,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1.1,
        }}
      >
        {overlay.value}
      </div>
    </div>
  );
};

// ── Shot type badge ───────────────────────────────────────────────────────────
// Bottom-left structural label. Uses spring for snappy entrance.
interface ShotBadgeProps {
  type: ShotType;
  frame: number;
  durationFrames: number;
  fps: number;
}

const BADGE_LABEL: Record<ShotType, string> = {
  hook:        "HOOK",
  narration:   "NARRATION",
  figures:     "FIGURES",
  disclaimer:  "DISCLAIMER",
};

const BADGE_BG: Record<ShotType, string> = {
  hook:       COLOR.cobaltDim,
  narration:  COLOR.hairline,
  figures:    COLOR.amberDim,
  disclaimer: "rgba(255,255,255,0.04)",
};

const BADGE_COLOR: Record<ShotType, string> = {
  hook:       COLOR.cobalt,
  narration:  COLOR.textMid,
  figures:    COLOR.amber,
  disclaimer: COLOR.textLow,
};

const ShotBadge: React.FC<ShotBadgeProps> = ({ type, frame, durationFrames, fps }) => {
  const enter = entranceBounds(durationFrames);
  const badgeProgress = spring({
    frame,
    fps,
    config: MOTION.springSnappy,
    durationInFrames: enter.end,
  });
  const badgeOpacity = interpolate(badgeProgress, [0, 1], [0, 0.85]);
  const badgeY = interpolate(badgeProgress, [0, 1], [12, 0]);

  return (
    <div
      style={{
        position: "absolute",
        bottom: SPACE.paddingV,
        left: SPACE.paddingH,
        display: "flex",
        alignItems: "center",
        gap: SPACE.xs,
        opacity: badgeOpacity,
        transform: `translateY(${badgeY}px)`,
      }}
    >
      {/* Dot indicator */}
      <div
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: BADGE_COLOR[type],
          flexShrink: 0,
        }}
      />
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: FONT_SIZE.badge,
          fontWeight: 500,
          color: BADGE_COLOR[type],
          letterSpacing: "0.2em",
          background: BADGE_BG[type],
          padding: `${SPACE.xs}px ${SPACE.sm}px`,
          borderRadius: RADIUS.sm,
          border: `1px solid ${BADGE_COLOR[type]}28`,
        }}
      >
        {BADGE_LABEL[type]}
      </div>
    </div>
  );
};
