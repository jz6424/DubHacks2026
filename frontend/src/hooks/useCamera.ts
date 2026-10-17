import { useCallback, useEffect, useRef, useState } from "react";
import type { Frame } from "../types";

const WIDTH = 512;

/**
 * Starts the webcam and keeps a rolling buffer of the last `keep` JPEG frames,
 * sampled every `everyMs`. Frames are small (512px wide, q≈0.7) to keep checks fast.
 */
export function useCamera(keep = 4, everyMs = 700) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const frames = useRef<Frame[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let stream: MediaStream | undefined;
    let timer: number | undefined;
    const canvas = document.createElement("canvas");
    const t0 = performance.now();

    navigator.mediaDevices
      .getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false })
      .then((s) => {
        stream = s;
        const v = videoRef.current!;
        v.srcObject = s;
        v.onloadedmetadata = () => setReady(true);
        timer = window.setInterval(() => {
          if (!v.videoWidth) return;
          canvas.width = WIDTH;
          canvas.height = Math.round((WIDTH * v.videoHeight) / v.videoWidth);
          canvas.getContext("2d")!.drawImage(v, 0, 0, canvas.width, canvas.height);
          frames.current.push({
            data_url: canvas.toDataURL("image/jpeg", 0.7),
            t_ms: Math.round(performance.now() - t0),
          });
          if (frames.current.length > keep) frames.current.shift();
        }, everyMs);
      })
      .catch((e) => setError(e?.message ?? "Camera unavailable"));

    return () => {
      clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [keep, everyMs]);

  /** Snapshot of the buffer, timestamps rebased to start at 0. */
  const snapshot = useCallback((): Frame[] => {
    const f = frames.current;
    if (!f.length) return [];
    const base = f[0].t_ms;
    return f.map((x) => ({ ...x, t_ms: x.t_ms - base }));
  }, []);

  return { videoRef, snapshot, ready, error };
}
