/**
 * Remotion entry point — registers the StoryboardVideo composition.
 *
 * Composition settings:
 *   - id:     "StoryboardVideo"
 *   - width:  1080  (9:16 vertical)
 *   - height: 1920
 *   - fps:    30
 *   - durationInFrames: derived from input props (default covers all 4 shot types)
 *
 * Input props (passed via --props JSON by the Python adapter wrapper):
 *   { "storyboard": <Storyboard JSON per renderer contract v1.0.0> }
 *
 * Default props include all 4 shot types (hook / narration / figures / disclaimer)
 * so that `npx remotion still` can target each type for visual QA.
 */

import React from "react";
import { Composition, registerRoot } from "remotion";
import { StoryboardVideo, getTotalFrames } from "./StoryboardVideo";
import type { StoryboardVideoProps, Storyboard } from "./types";

// Default storyboard covers all 4 shot types for visual QA via `npx remotion still`.
// Frame map (30fps):
//   0..89   — hook shot (durationSec=3)
//   90..269 — narration shot (durationSec=6)
//   270..449 — figures shot (durationSec=6)
//   450..509 — disclaimer shot (durationSec=2)
const _defaultStoryboard: Storyboard = {
  title: "銘柄解説プレビュー",
  ticker: "7203",
  scenes: [
    {
      id: "hook-scene",
      shots: [
        {
          id: "hook-0",
          type: "hook",
          durationSec: 3,
          overlays: [
            {
              kind: "text",
              text: "トヨタ自動車を\n30秒で把握する",
            },
          ],
        },
      ],
    },
    {
      id: "narration-scene",
      shots: [
        {
          id: "narr-0",
          type: "narration",
          durationSec: 6,
          overlays: [
            {
              kind: "text",
              text: "世界最大級の自動車メーカー。EV シフトと水素戦略を並走させながら、北米・アジアでの販売が堅調に推移しています。",
            },
            {
              kind: "figure",
              label: "売上高",
              value: "45.1兆円",
            },
          ],
        },
      ],
    },
    {
      id: "figures-scene",
      shots: [
        {
          id: "figures-0",
          type: "figures",
          durationSec: 6,
          overlays: [
            {
              kind: "text",
              text: "主要指標",
            },
            {
              kind: "figure",
              label: "PER",
              value: "8.4x",
            },
            {
              kind: "figure",
              label: "PBR",
              value: "1.02x",
            },
            {
              kind: "figure",
              label: "配当利回り",
              value: "2.8%",
            },
          ],
        },
      ],
    },
    {
      id: "disclaimer-scene",
      shots: [
        {
          id: "disclaimer-0",
          type: "disclaimer",
          durationSec: 2,
          overlays: [
            {
              kind: "text",
              text: "この動画は情報提供を目的としており、投資助言ではありません。投資判断はご自身の責任で行ってください。",
            },
          ],
        },
      ],
    },
  ],
};

const _defaultProps: StoryboardVideoProps = { storyboard: _defaultStoryboard };

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="StoryboardVideo"
      component={StoryboardVideo as unknown as React.FC<Record<string, unknown>>}
      durationInFrames={getTotalFrames(_defaultProps)}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={_defaultProps as unknown as Record<string, unknown>}
      calculateMetadata={async ({ props }: { props: Record<string, unknown> }) => ({
        durationInFrames: getTotalFrames(props as unknown as StoryboardVideoProps),
      })}
    />
  );
};

registerRoot(RemotionRoot);
