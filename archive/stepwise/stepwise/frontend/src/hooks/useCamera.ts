import { useEffect, useRef } from "react";

/** Starts the webcam and calls onFrame(jpegBlob) at `fps`. Downscales to 512px wide. */
export function useCamera(onFrame: (b: Blob) => void, fps = 1.5) {
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    let stream: MediaStream, timer: number;
    const canvas = document.createElement("canvas");
    navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } }).then(s => {
      stream = s;
      videoRef.current!.srcObject = s;
      timer = window.setInterval(() => {
        const v = videoRef.current!;
        if (!v.videoWidth) return;
        canvas.width = 512; canvas.height = Math.round(512 * v.videoHeight / v.videoWidth);
        canvas.getContext("2d")!.drawImage(v, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(b => b && onFrame(b), "image/jpeg", 0.7);
      }, 1000 / fps);
    });
    return () => { clearInterval(timer); stream?.getTracks().forEach(t => t.stop()); };
  }, []);
  return videoRef;
}
