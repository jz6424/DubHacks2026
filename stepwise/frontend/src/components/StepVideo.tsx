import YouTube, { YouTubePlayer } from "react-youtube";
import { useEffect, useRef } from "react";
import type { Step } from "../types";

/** Loops the current step's segment. Muted by default; user can unmute. */
export function StepVideo({ videoId, step }: { videoId: string; step: Step }) {
  const player = useRef<YouTubePlayer>();
  useEffect(() => {
    if (!player.current || step.video_start == null) return;
    player.current.seekTo(step.video_start, true);
    player.current.playVideo();
    const t = setInterval(async () => {          // manual loop: IFrame `end` doesn't loop
      if ((await player.current.getCurrentTime()) >= (step.video_end ?? Infinity))
        player.current.seekTo(step.video_start!, true);
    }, 250);
    return () => clearInterval(t);
  }, [step.index]);
  // TODO: scrubber showing all step segments as coloured ticks; current one highlighted
  return <YouTube videoId={videoId} onReady={e => { player.current = e.target; e.target.mute(); }}
    opts={{ playerVars: { start: Math.floor(step.video_start ?? 0), modestbranding: 1, rel: 0 } }} />;
}
