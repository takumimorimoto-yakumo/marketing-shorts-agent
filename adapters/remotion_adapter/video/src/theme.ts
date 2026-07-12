/**
 * theme.ts — Design token SSOT for StoryboardVideo.
 *
 * ALL visual values originate here. ShotFrame and sub-components
 * must import from this file and never hard-code raw values.
 *
 * Design reference: meigara計器盤美学
 *   - Sharp / low border-radius / tabular-nums / low density
 *   - 3-tier text hierarchy (high / mid / low)
 *   - Amber accent for financial figures (AI/data専用)
 *   - Cobalt blue for structural accents
 *   - Line-based structure (border as structure, not decoration)
 *   - Subtle depth from gradient, not shadows
 */

import { Easing } from "remotion";

// ── Fonts ─────────────────────────────────────────────────────────────────────
// loadFont must NOT be called inside individual components.
// Declare the font stack here as the single source of truth.
export const FONT = {
  sans: "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, system-ui, sans-serif",
  mono: "ui-monospace, 'SF Mono', 'Cascadia Code', 'Fira Mono', monospace",
} as const;

// ── Colors ────────────────────────────────────────────────────────────────────
export const COLOR = {
  // Background layers
  bgBase: "#07090E",          // near-black — deepest background
  bgHook: "#07090E",          // hook: same deep bg, gradient adds blue tint
  bgNarration: "#08090D",     // narration: neutral dark
  bgFigures: "#07090E",       // figures: same dark
  bgDisclaimer: "#080808",    // disclaimer: slightly warmer dark

  // Vignette overlay color (semi-transparent)
  vignette: "rgba(0, 0, 0, 0.55)",

  // Text hierarchy (3 tiers — strict)
  textHigh: "rgba(255, 255, 255, 0.92)",   // primary text / headlines
  textMid:  "rgba(255, 255, 255, 0.58)",   // secondary / labels
  textLow:  "rgba(255, 255, 255, 0.34)",   // caption / disclaimer body

  // Accent colors
  amber: "#E8AB32",            // financial figures, AI-data accent (meigara brand-accent)
  amberMuted: "#C47F0A",       // amber darker for borders
  amberDim: "rgba(232, 171, 50, 0.15)",    // amber tint background
  cobalt: "#2A7CF6",           // structural accent (meigara brand-primary)
  cobaltDim: "rgba(42, 124, 246, 0.12)",   // cobalt tint

  // Disclaimer specific
  disclaimerBorder: "rgba(232, 171, 50, 0.35)",  // subtle amber border
  disclaimerAccent: "#E8AB32",

  // Shot type badge
  badgeHook:        "rgba(42, 124, 246, 0.18)",   // cobalt tint
  badgeNarration:   "rgba(255, 255, 255, 0.08)",
  badgeFigures:     "rgba(232, 171, 50, 0.18)",   // amber tint
  badgeDisclaimer:  "rgba(255, 255, 255, 0.06)",

  // Hairline borders (structure, not decoration)
  hairline: "rgba(255, 255, 255, 0.08)",
  hairlineStrong: "rgba(255, 255, 255, 0.14)",

  // Figure card
  figureCardBg: "rgba(232, 171, 50, 0.06)",
  figureCardBorder: "rgba(232, 171, 50, 0.22)",
  figureAccentBar: "#E8AB32",
} as const;

// ── Typography scale (px — 1080×1920 vertical canvas) ────────────────────────
// Scaled up from meigara's web scale (14px base → 32px base for video)
// Ratio is approximately 2.3× to account for video rendering at 1080px width
export const FONT_SIZE = {
  // Hook shot — screen-dominating headline
  hookDisplay:   148,   // hero number / single word impact
  hookHead:      108,   // hook main headline (large — grabs viewer)
  hookSub:        52,   // hook subtitle / supporting copy

  // Narration shot
  narrBody:       44,   // comfortable reading size for narration
  narrEmphasis:   54,   // emphasized phrase within narration

  // Figures shot
  figureValue:    96,   // KPI value — largest and most prominent
  figureLabel:    30,   // KPI label — small caps
  figureUnit:     36,   // unit suffix alongside value

  // Disclaimer shot
  disclaimerBody: 28,   // small, clearly de-emphasized

  // Structural UI
  badge:          24,   // shot type badge
  ticker:         26,   // company ticker
} as const;

// ── Spacing (8px grid base, scaled for 1080px canvas) ────────────────────────
export const SPACE = {
  xs:   12,
  sm:   20,
  md:   32,
  lg:   48,
  xl:   64,
  xxl:  96,
  xxxl: 128,

  // Layout
  paddingH:     72,    // horizontal padding for content area
  paddingV:     120,   // vertical padding top/bottom
  safeAreaTop:  80,    // safe zone below badge
  safeAreaBot:  80,    // safe zone above bottom edge
} as const;

// ── Border radius (sharp — 計器盤美学) ───────────────────────────────────────
export const RADIUS = {
  none: 0,
  sm:   4,    // badge, chip
  md:   8,    // card
  lg:   12,   // panel (upper limit)
} as const;

// ── Motion tokens ─────────────────────────────────────────────────────────────
// All timing expressed as RATIOS of shot duration, not absolute frame counts.
// Usage pattern:
//   const enterEnd = Math.round(durationFrames * MOTION.enterRatio);
//   const exitStart = Math.round(durationFrames * MOTION.exitStartRatio);
export const MOTION = {
  // Fraction of shot duration for entrance animation
  enterRatio: 0.18,      // entrance completes in first 18% of shot
  enterMinFrames: 6,     // minimum entrance frames (for very short shots)
  enterMaxFrames: 24,    // maximum entrance frames (for very long shots)

  // Fraction of shot duration when exit animation begins
  exitStartRatio: 0.85,  // exit begins at 85% of shot duration
  exitMinStart: 8,       // minimum frames before shot end to start exit

  // Stagger between overlay blocks (as fraction of enterDuration)
  staggerRatio: 0.25,    // each block staggers by 25% of enterDuration

  // Spring config for entrance motion
  springConfig: { damping: 200 } as const,  // smooth, no bounce (meigara base)
  springSnappy: { damping: 20, stiffness: 200 } as const,  // snappy for badges

  // Slide distances (px on 1080w canvas)
  slideYEntrance:  28,   // elements slide up this many px on entrance
  slideXFigure:    -20,  // figure cards slide from left
} as const;

// ── Gradient definitions (background) ────────────────────────────────────────
// Expressed as CSS gradient strings keyed by shot type.
// Subtle depth — text readability is paramount.
export const GRADIENT = {
  hook: [
    { stop: "0%",   color: "#07090E" },  // dark base
    { stop: "40%",  color: "#060A10" },  // subtle blue-black mid
    { stop: "100%", color: "#050709" },  // darker bottom
  ],
  narration: [
    { stop: "0%",   color: "#08090D" },
    { stop: "60%",  color: "#070810" },
    { stop: "100%", color: "#060709" },
  ],
  figures: [
    { stop: "0%",   color: "#070910" },  // faint blue-black top
    { stop: "35%",  color: "#07090E" },
    { stop: "100%", color: "#050608" },
  ],
  disclaimer: [
    { stop: "0%",   color: "#080808" },
    { stop: "100%", color: "#060607" },
  ],
} as const;

// Easing functions (pre-composed for reuse)
export const EASE = {
  outExpo:   Easing.out(Easing.exp),    // entrance: enters fast, settles
  inOutQuad: Easing.inOut(Easing.quad), // exit: symmetrical smooth
  outQuad:   Easing.out(Easing.quad),   // generic smooth decel
} as const;

// ── Helper: compute entrance frame bounds from durationFrames ─────────────────
export function entranceBounds(durationFrames: number): { start: number; end: number } {
  const raw = Math.round(durationFrames * MOTION.enterRatio);
  const clamped = Math.max(
    MOTION.enterMinFrames,
    Math.min(MOTION.enterMaxFrames, raw),
  );
  return { start: 0, end: clamped };
}

// ── Helper: compute exit frame bounds from durationFrames ─────────────────────
export function exitBounds(durationFrames: number): { start: number; end: number } {
  const exitStart = Math.max(
    durationFrames - MOTION.exitMinStart,
    Math.round(durationFrames * MOTION.exitStartRatio),
  );
  return { start: exitStart, end: durationFrames };
}

// ── Helper: build CSS linear-gradient string from stop array ─────────────────
export function buildGradient(
  stops: ReadonlyArray<{ stop: string; color: string }>,
  direction = "to bottom",
): string {
  const stopStr = stops.map((s) => `${s.color} ${s.stop}`).join(", ");
  return `linear-gradient(${direction}, ${stopStr})`;
}
