/**
 * Storyboard types matching renderer contract v1.0.0.
 *
 * Clean-room: built from the OpenAPI spec only.
 * No private tooling or naming conventions imported.
 */

export type OverlayKind = "text" | "figure";
export type ShotType = "hook" | "narration" | "figures" | "disclaimer";
export type ClipKind = "generative" | "stock" | "solid";

export interface Overlay {
  kind: OverlayKind;
  /** Display text for text overlays */
  text?: string;
  /** Label for figure overlays (e.g. "PER") */
  label?: string;
  /** Pre-verified financial value — MUST be reproduced verbatim */
  value?: string;
}

export interface ClipIntent {
  kind: ClipKind;
  /** CSS hex background for solid clips */
  color?: string;
  /** Generative clip prompt */
  prompt?: string;
  /** Stock footage search query */
  query?: string;
}

export interface Shot {
  id: string;
  type: ShotType;
  durationSec?: number;
  clip?: ClipIntent;
  overlays: Overlay[];
}

export interface Scene {
  id: string;
  durationSec?: number;
  shots: Shot[];
}

export interface Storyboard {
  title: string;
  ticker: string;
  scenes: Scene[];
}

export interface StoryboardVideoProps {
  storyboard: Storyboard;
}
