/**
 * Remotion entry point — registers the StoryboardVideo composition.
 *
 * Composition settings:
 *   - id:     "StoryboardVideo"
 *   - width:  1080  (9:16 vertical)
 *   - height: 1920
 *   - fps:    30
 *   - durationInFrames: derived from input props (default 150 = 5s)
 *
 * Input props (passed via --props JSON by the Python adapter wrapper):
 *   { "storyboard": <Storyboard JSON per renderer contract v1.0.0> }
 */

import React from "react";
import { Composition } from "remotion";
import { StoryboardVideo, getTotalFrames } from "./StoryboardVideo";
import type { StoryboardVideoProps, Storyboard } from "./types";

const _defaultStoryboard: Storyboard = {
  title: "Preview",
  ticker: "0000",
  scenes: [
    {
      id: "intro",
      shots: [
        {
          id: "hook-0",
          type: "hook",
          durationSec: 3,
          overlays: [{ kind: "text", text: "Storyboard Video" }],
        },
      ],
    },
    {
      id: "close",
      shots: [
        {
          id: "disclaimer-0",
          type: "disclaimer",
          durationSec: 2,
          overlays: [
            {
              kind: "text",
              text: "This video is for informational purposes only and is not investment advice.",
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
      component={StoryboardVideo}
      durationInFrames={getTotalFrames(_defaultProps)}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={_defaultProps}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: getTotalFrames(props as StoryboardVideoProps),
      })}
    />
  );
};
