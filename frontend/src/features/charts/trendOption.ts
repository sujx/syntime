import type { EChartsOption } from "echarts";
import type { TrendData } from "@/api/types";
import { CHART_PALETTE, COMPARE_LINE_COLOR, UNASSIGNED_COLOR, toMoneyNumber } from "./palette";

export { toMoneyNumber };

const UNALLOCATED = "未分配成本";

function axisDates(trend: TrendData): string[] {
  return trend.current.map((p) => p.date.slice(5)); // MM-DD
}

function seriesNames(trend: TrendData): string[] {
  const seen: string[] = [];
  for (const point of trend.current) {
    for (const item of point.items) if (!seen.includes(item.projectTag)) seen.push(item.projectTag);
  }
  return seen;
}

function valuesFor(trend: TrendData, name: string): (number | null)[] {
  return trend.current.map((point) => {
    const hit = point.items.find((i) => i.projectTag === name);
    return hit ? toMoneyNumber(hit.amount) : null;
  });
}

function baseGrid(): EChartsOption["grid"] {
  return { left: 8, right: 8, top: 36, bottom: 4, containLabel: true };
}

function baseTooltip(): EChartsOption["tooltip"] {
  return {
    trigger: "axis",
    backgroundColor: "#FFFFFF",
    borderColor: "#E2E8F0",
    borderRadius: 8,
    textStyle: { color: "#0F172A", fontSize: 12 },
    valueFormatter: (v) =>
      v == null
        ? "--"
        : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  };
}

function baseXAxis(trend: TrendData): EChartsOption["xAxis"] {
  return {
    type: "category",
    boundaryGap: true,
    data: axisDates(trend),
    axisLine: { lineStyle: { color: "#E2E8F0" } },
    axisLabel: { color: "#94A3B8", fontSize: 12 },
  };
}

function baseYAxis(): EChartsOption["yAxis"] {
  return {
    type: "value",
    splitLine: { lineStyle: { color: "#F1F5F9" } },
    axisLabel: { color: "#94A3B8", fontSize: 12 },
  };
}

function compareSeries(trend: TrendData) {
  const totals = trend.compare.map((point) => {
    const sum = point.items.reduce((acc, i) => acc + (toMoneyNumber(i.amount) ?? 0), 0);
    return point.items.length > 0 ? Number(sum.toFixed(2)) : null;
  });
  return {
    name: `上期(${trend.compareRange.start}~${trend.compareRange.end})`,
    type: "line" as const,
    data: totals,
    symbol: "none" as const,
    lineStyle: { color: COMPARE_LINE_COLOR, type: "dashed" as const, width: 1.5 },
    itemStyle: { color: COMPARE_LINE_COLOR },
  };
}

/** 治理页：逐日按项目堆叠面积折线 + 可选上期总额虚线（ui-spec 5.6） */
export function buildProjectTrendOption(trend: TrendData, showCompare: boolean): EChartsOption {
  const names = seriesNames(trend);
  let colorIdx = 0;
  const series: EChartsOption["series"] = names.map((name) => {
    const color =
      name === UNALLOCATED ? UNASSIGNED_COLOR : CHART_PALETTE[colorIdx++ % CHART_PALETTE.length];
    return {
      name,
      type: "line" as const,
      stack: "total",
      smooth: true,
      symbol: "none" as const,
      data: valuesFor(trend, name),
      lineStyle: { color, width: 2 },
      itemStyle: { color },
      areaStyle: { color, opacity: 0.18 },
    };
  });
  if (showCompare) (series as object[]).push(compareSeries(trend));
  return {
    grid: baseGrid(),
    tooltip: baseTooltip(),
    legend: { top: 0, right: 0, textStyle: { fontSize: 12, color: "#475569" } },
    xAxis: baseXAxis(trend),
    yAxis: baseYAxis(),
    series,
  } as EChartsOption;
}

/** 仪表盘：近 30 天按资源类型堆叠柱 */
export function buildResourceTrendOption(trend: TrendData): EChartsOption {
  const names = seriesNames(trend);
  let colorIdx = 0;
  const series: EChartsOption["series"] = names.map((name) => {
    const color = CHART_PALETTE[colorIdx++ % CHART_PALETTE.length];
    return {
      name,
      type: "bar" as const,
      stack: "total",
      barMaxWidth: 18,
      data: valuesFor(trend, name),
      itemStyle: { color, borderRadius: [3, 3, 0, 0] },
    };
  });
  return {
    grid: baseGrid(),
    tooltip: { ...baseTooltip(), axisPointer: { type: "shadow" } },
    legend: { top: 0, right: 0, textStyle: { fontSize: 12, color: "#475569" } },
    xAxis: baseXAxis(trend),
    yAxis: baseYAxis(),
    series,
  } as EChartsOption;
}
