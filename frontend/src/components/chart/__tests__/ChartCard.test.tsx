import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EChartsOption } from "echarts";

// jsdom 无 canvas：桩掉 echarts 初始化本体，本测试只约束 DOM 结构（§5.6-9 宿主节点稳定性）
const { initMock } = vi.hoisted(() => ({ initMock: vi.fn() }));
vi.mock("echarts/core", () => ({
  use: vi.fn(),
  init: initMock,
}));

import { ChartCard } from "@/components/chart/ChartCard";
import { zh } from "@/i18n/zh";

const option = { xAxis: { type: "category" }, yAxis: {}, series: [] } as EChartsOption;

// restoreMocks 会在每个用例后清空实现，故在 beforeEach 中重桩 init 返回值
beforeEach(() => {
  initMock.mockReturnValue({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() });
});

describe("ChartCard 空态与图表宿主节点（§5.6-9）", () => {
  it("option undefined → defined → undefined 全程宿主节点是同一个 DOM 元素", () => {
    const { rerender } = render(<ChartCard title="T" height={120} />);
    const hostEmpty = screen.getByTestId("chart:T");
    rerender(<ChartCard title="T" height={120} option={option} />);
    expect(screen.getByTestId("chart:T")).toBe(hostEmpty);
    rerender(<ChartCard title="T" height={120} />);
    expect(screen.getByTestId("chart:T")).toBe(hostEmpty);
  });

  it("空态以覆盖层呈现文案，且不替换宿主 div", () => {
    render(<ChartCard title="T" height={120} />);
    expect(screen.getByText(zh["chart.pending"] ?? "")).toBeInTheDocument();
    expect(screen.getByTestId("chart:T")).toBeInTheDocument();
  });

  it("有数据时不渲染空态覆盖层", () => {
    render(<ChartCard title="T" height={120} option={option} />);
    expect(screen.queryByText(zh["chart.pending"] ?? "")).not.toBeInTheDocument();
    expect(initMock).toHaveBeenCalled();
  });
});
