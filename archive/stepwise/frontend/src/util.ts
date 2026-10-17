export const fmt = (s: number | null | undefined) => {
  if (s == null || Number.isNaN(s)) return "–";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
};
