import { describe, expect, it } from "vitest";
import {
  buildProjectTrendOption,
  buildResourceTrendOption,
  toMoneyNumber,
} from "@/features/charts/trendOption";
import type { TrendData } from "@/api/types";

const trend: TrendData = {
  current: [
    {
      date: "2026-09-01",
      items: [
        { projectTag: "A", tagStatus: "normal", amount: "100.00" },
        { projectTag: "未分配成本", tagStatus: null, amount: "--" },
      ],
    },
    { date: "2026-09-02", items: [{ projectTag: "A", tagStatus: "normal", amount: "250.50" }] },
  ],
  compare: [
    { date: "2026-08-01", items: [{ projectTag: "A", tagStatus: "normal", amount: "50.00" }] },
  ],
  statRange: { start: "2026-09-01", end: "2026-09-02" },
  compareRange: { start: "2026-08-01", end: "2026-08-01" },
  billMonthIncomplete: false,
};

describe("toMoneyNumber", () => {
  it("口径 -- 转 null，金额串转数值", () => {
    expect(toMoneyNumber("--")).toBeNull();
    expect(toMoneyNumber("250.50")).toBe(250.5);
  });
});

describe("buildProjectTrendOption", () => {
  it("项目序列取色，未分配成本固定灰", () => {
    const opt = buildProjectTrendOption(trend, false);
    const names = opt.series as { name: string }[];
    expect(names.map((s) => s.name)).toEqual(["A", "未分配成本"]);
    const series = opt.series as {
      itemStyle?: { color?: string };
      lineStyle?: { color?: string };
    }[];
    expect(series[1]?.lineStyle?.color).toBe("#94A3B8");
    expect((opt.xAxis as { data: string[] }).data).toEqual(["09-01", "09-02"]);
  });
  it("showCompare 时追加比较区间总额虚线", () => {
    const withCmp = buildProjectTrendOption(trend, true).series as {
      name: string;
      lineStyle?: { type?: string };
    }[];
    expect(withCmp.some((s) => s.lineStyle?.type === "dashed")).toBe(true);
    const noCmp = buildProjectTrendOption(trend, false).series as {
      lineStyle?: { type?: string };
    }[];
    expect(noCmp.some((s) => s.lineStyle?.type === "dashed")).toBe(false);
  });
});

describe("buildResourceTrendOption", () => {
  it("堆叠柱：projectTag 承载资源类型码，序列按首现顺序", () => {
    const t: TrendData = {
      ...trend,
      current: [
        {
          date: "2026-09-01",
          items: [
            { projectTag: "ecs", tagStatus: null, amount: "1.00" },
            { projectTag: "rds", tagStatus: null, amount: "2.00" },
          ],
        },
      ],
    };
    const series = buildResourceTrendOption(t).series as {
      name: string;
      type: string;
      stack?: string;
    }[];
    expect(series.map((s) => s.name)).toEqual(["ecs", "rds"]);
    expect(series[0]?.type).toBe("bar");
    expect(series[0]?.stack).toBe("total");
  });
});
