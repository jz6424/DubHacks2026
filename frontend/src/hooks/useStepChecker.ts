import { useEffect, useRef, useState } from "react";
import { checkStep } from "../api";
import type { CheckResult, Frame, Step } from "../types";

export type CheckStatus = "idle" | "watching" | "checking" | "almost" | "done";

interface Options {
  planId: string;
  step: Step | undefined;
  enabled: boolean;
  snapshot: () => Frame[];
  onComplete: () => void;
  intervalMs?: number;
  /** Consecutive confident "done" verdicts required before checking off. */
  need?: number;
  threshold?: number;
}

/**
 * Polls Mk1.5 with the latest frames for the current step. A step is checked off
 * only after `need` confident positives in a row, so one lucky frame can't do it.
 * Never queues: if a check is in flight, the tick is skipped (fresh > complete).
 */
export function useStepChecker({
  planId, step, enabled, snapshot, onComplete,
  intervalMs = 1800, need = 2, threshold = 0.7,
}: Options) {
  const [status, setStatus] = useState<CheckStatus>("idle");
  const [last, setLast] = useState<CheckResult | null>(null);
  const [hint, setHint] = useState("");
  const [error, setError] = useState<string | null>(null);
  const streak = useRef(0);
  const inflight = useRef(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  // Reset whenever the step changes.
  useEffect(() => {
    streak.current = 0;
    setLast(null);
    setHint("");
    setStatus(enabled && step?.verifiable ? "watching" : "idle");
  }, [step?.index, enabled, step?.verifiable]);

  useEffect(() => {
    if (!enabled || !step || !step.verifiable) return;
    const ctrl = new AbortController();
    const stepIndex = step.index;

    const tick = async () => {
      if (inflight.current) return;
      const frames = snapshot();
      if (frames.length < 2) return;
      inflight.current = true;
      setStatus((s) => (s === "almost" ? s : "checking"));
      try {
        const r = await checkStep(planId, stepIndex, frames, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setError(null);
        setLast(r);
        const positive = r.done && r.confidence >= threshold;
        streak.current = positive ? streak.current + 1 : 0;
        if (!positive && r.hint) setHint(r.hint);
        if (streak.current >= need) {
          setStatus("done");
          setHint("");
          onCompleteRef.current();
        } else {
          setStatus(streak.current > 0 ? "almost" : "watching");
        }
      } catch (e: any) {
        if (e?.name !== "AbortError") {
          setError(e?.message ?? "Check failed");
          setStatus("watching");
        }
      } finally {
        inflight.current = false;
      }
    };

    const id = window.setInterval(tick, intervalMs);
    return () => {
      clearInterval(id);
      ctrl.abort();
      inflight.current = false;
    };
  }, [planId, step?.index, step?.verifiable, enabled, intervalMs, need, threshold, snapshot]);

  return { status, last, hint, error };
}
