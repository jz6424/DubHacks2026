import type { ReactNode } from "react";

/**
 * Minimal inline markdown for model-written text: **bold**, *italic*, [label](url) and bare URLs.
 * Builds React nodes (never innerHTML), so model output can't inject markup.
 */
const TOKEN = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)]+)/g;

export function Md({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(TOKEN)) {
    const t = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    if (t.startsWith("**")) out.push(<strong key={i++}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("[")) {
      const [, label, url] = t.match(/\[([^\]]+)\]\(([^)]+)\)/) ?? [];
      out.push(
        <a key={i++} href={url} target="_blank" rel="noreferrer">
          {label}
        </a>,
      );
    } else if (t.startsWith("http")) {
      const url = t.replace(/[.,;]+$/, "");
      out.push(
        <a key={i++} href={url} target="_blank" rel="noreferrer">
          {url.replace(/^https?:\/\/(www\.)?/, "")}
        </a>,
      );
      if (url.length < t.length) out.push(t.slice(url.length));
    } else out.push(<em key={i++}>{t.slice(1, -1)}</em>);
    last = at + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}
