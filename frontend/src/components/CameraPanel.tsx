import type { RefObject } from "react";
import type { CheckStatus } from "../hooks/useStepChecker";

interface Props {
  videoRef: RefObject<HTMLVideoElement>;
  cameraError: string | null;
  status: CheckStatus;
  confidence: number | null;
  hint: string;
  checkError: string | null;
  latencyMs: number | null;
  celebrate: boolean;
}

const LABEL: Record<CheckStatus, string> = {
  idle: "Auto-check off",
  watching: "Watching",
  checking: "Checking…",
  almost: "Looks done, confirming…",
  done: "Done!",
};

export function CameraPanel({ videoRef, cameraError, status, confidence, hint, checkError, latencyMs, celebrate }: Props) {
  return (
    <div className={`camera status-${status} ${celebrate ? "celebrate" : ""}`}>
      <video ref={videoRef} autoPlay muted playsInline />
      {cameraError && <div className="camera-error">Camera unavailable: {cameraError}</div>}

      <div className="status-pill">
        <span className="pulse" />
        {LABEL[status]}
        {confidence != null && status !== "idle" && <b>{Math.round(confidence * 100)}%</b>}
      </div>

      {latencyMs != null && <div className="latency">{latencyMs} ms</div>}

      {celebrate && <div className="burst">✓</div>}

      {(hint || checkError) && !celebrate && (
        <div className={`hint ${checkError ? "error" : ""}`}>{checkError ? `Check failed: ${checkError}` : hint}</div>
      )}
    </div>
  );
}
