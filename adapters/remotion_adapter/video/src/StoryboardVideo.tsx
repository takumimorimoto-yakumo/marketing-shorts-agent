/**
 * StoryboardVideo — top-level Remotion composition.
 *
 * Renders each Shot from the Storyboard in sequence using a single
 * <Sequence> per shot. Figure values are passed verbatim to ShotFrame
 * and rendered without alteration (renderer contract immutability rule).
 *
 * Composition:
 *   - Width:  1080px (9:16 vertical)
 *   - Height: 1920px
 *   - FPS:    30
 *   - Duration: sum of all shot durations (capped at 60s)
 */

import React from "react";
import { Sequence } from "remotion";
import { ShotFrame } from "./ShotFrame";
import type { Shot, StoryboardVideoProps } from "./types";

const FPS = 30;
const DEFAULT_SHOT_DURATION_SEC = 5;
const MAX_DURATION_SEC = 60;

function shotDurationFrames(shot: Shot): number {
  const sec = shot.durationSec != null && shot.durationSec > 0
    ? shot.durationSec
    : DEFAULT_SHOT_DURATION_SEC;
  return Math.round(sec * FPS);
}

function collectShots(props: StoryboardVideoProps): Shot[] {
  return props.storyboard.scenes.flatMap((scene) => scene.shots);
}

export const StoryboardVideo: React.FC<StoryboardVideoProps> = (props) => {
  const shots = collectShots(props);
  let offset = 0;

  return (
    <>
      {shots.map((shot) => {
        const durationFrames = shotDurationFrames(shot);
        const from = offset;
        offset += durationFrames;
        return (
          <Sequence key={shot.id} from={from} durationInFrames={durationFrames}>
            <ShotFrame shot={shot} durationFrames={durationFrames} />
          </Sequence>
        );
      })}
    </>
  );
};

export function getTotalFrames(props: StoryboardVideoProps): number {
  const shots = collectShots(props);
  const totalSec = shots.reduce((acc, s) => {
    const sec = s.durationSec != null && s.durationSec > 0
      ? s.durationSec
      : DEFAULT_SHOT_DURATION_SEC;
    return acc + sec;
  }, 0);
  return Math.round(Math.min(totalSec, MAX_DURATION_SEC) * FPS);
}
