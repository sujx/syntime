export const CHART_PALETTE = [
  "#6366F1",
  "#10B981",
  "#F59E0B",
  "#EF4444",
  "#8B5CF6",
  "#06B6D4",
  "#EC4899",
  "#14B8A6",
] as const;
export const UNASSIGNED_COLOR = "#94A3B8";
export const COMPARE_LINE_COLOR = "#CBD5E1";

export function toMoneyNumber(v: string): number | null {
  if (v === "--") return null;
  const n = Number(v.replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}
