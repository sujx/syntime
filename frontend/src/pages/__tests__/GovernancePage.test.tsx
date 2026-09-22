import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntdApp } from "antd";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("@/api/client", () => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/components/chart/ChartCard", () => ({
  ChartCard: ({ title }: { title: string }) => <div data-testid={`chart:${title}`} />,
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    username: "alice",
    role: "成本管理员",
    status: "authenticated",
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

import { get } from "@/api/client";
import GovernancePage from "@/pages/GovernancePage";
import { zh } from "@/i18n/zh";

// jsdom 未实现 matchMedia，antd Table 响应式观察器依赖它
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// jsdom 的 getComputedStyle 极慢且 rc-table scroll.x 触发的伪元素测量未实现，
// 用轻量桩替换：role 查询的隐藏元素计算与滚动条测量均走此函数
const fakeStyle = {
  getPropertyValue: () => "",
  display: "block",
  visibility: "visible",
  width: "0px",
  height: "0px",
  overflow: "visible",
};
window.getComputedStyle = (() => fakeStyle) as unknown as typeof window.getComputedStyle;

const summaryData = {
  total: 2,
  page: 1,
  pageSize: 20,
  resourceTypes: [
    { code: "ecs", displayName: "云服务器 ECS" },
    { code: "rds", displayName: "云数据库 RDS" },
  ],
  summary: {
    amountByResourceType: { ecs: "700.00", rds: "300.00" },
    totalAmount: "1000.00",
  },
  list: [
    {
      projectTag: "项目A",
      tagStatus: "normal",
      amountByResourceType: { ecs: "100.00", rds: "50.00" },
      totalAmount: "150.00",
      lastPeriodAmount: "100.00",
      lastPeriodRange: { start: "2026-08-01", end: "2026-08-31" },
      rate: "50.00",
      budgetAmount: "120.00",
      budgetRate: "125.00",
      overBudget: true,
      budgetIncomplete: false,
      statRange: { start: "2026-09-01", end: "2026-09-21" },
    },
    {
      projectTag: "未分配成本",
      tagStatus: null,
      amountByResourceType: {},
      totalAmount: "850.00",
      lastPeriodAmount: "--",
      lastPeriodRange: { start: "2026-08-01", end: "2026-08-31" },
      rate: "--",
      budgetAmount: "--",
      budgetRate: "--",
      overBudget: false,
      budgetIncomplete: false,
      statRange: { start: "2026-09-01", end: "2026-09-21" },
    },
  ],
};

function setup(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AntdApp>{ui}</AntdApp>
    </QueryClientProvider>,
  );
}

describe("GovernancePage 汇总", () => {
  it("首查默认本月区间并渲染动态列与合计标题区", async () => {
    vi.mocked(get).mockResolvedValue(summaryData);
    setup(<GovernancePage />);
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ startDate: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) }),
      ),
    );
    // 使用 role 查询避免 MeasureRow 中重复的 th
    expect(
      await screen.findByRole("columnheader", { name: "云服务器 ECS费用" }),
    ).toBeInTheDocument();
    expect(screen.getByText(zh["gov.totalPrefix"] ?? "")).toBeInTheDocument();
    expect(await screen.findByText(/1000\.00/)).toBeInTheDocument();
    expect(screen.getByText("150.00")).toBeInTheDocument();
    // 未分配行金额为空字典 → 动态列显示 --
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
  });
  it("排序三态：升序→降序→取消", async () => {
    vi.mocked(get).mockResolvedValue(summaryData);
    setup(<GovernancePage />);
    await screen.findByText("150.00");
    vi.mocked(get).mockClear();

    // 第一次点击：升序
    await userEvent.click(screen.getByRole("columnheader", { name: /项目总支出/ }));
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ sortField: "totalAmount", sortOrder: "asc" }),
      ),
    );
    vi.mocked(get).mockClear();

    // 第二次点击：降序
    await userEvent.click(screen.getByRole("columnheader", { name: /项目总支出/ }));
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ sortField: "totalAmount", sortOrder: "desc" }),
      ),
    );
    vi.mocked(get).mockClear();

    // 第三次点击：取消排序（无 sortField/sortOrder）
    await userEvent.click(screen.getByRole("columnheader", { name: /项目总支出/ }));
    await waitFor(() => expect(vi.mocked(get)).toHaveBeenCalled());
    const calls = vi.mocked(get).mock.calls;
    const lastArgs = calls[calls.length - 1]?.[1] as Record<string, unknown> | undefined;
    expect(lastArgs).toBeDefined();
    expect(lastArgs).not.toHaveProperty("sortField");
    expect(lastArgs).not.toHaveProperty("sortOrder");
  });
  it("关键字搜索提交后带 keyword 重查", async () => {
    vi.mocked(get).mockResolvedValue(summaryData);
    setup(<GovernancePage />);
    await screen.findByText("150.00");
    vi.mocked(get).mockClear();
    await userEvent.type(screen.getByPlaceholderText(zh["gov.filterKeyword"] ?? ""), "A{Enter}");
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ keyword: "A" }),
      ),
    );
  });
  it("点击行显示 detail-anchor", async () => {
    vi.mocked(get).mockResolvedValue(summaryData);
    setup(<GovernancePage />);
    await screen.findByText("150.00");
    expect(screen.queryByTestId("detail-anchor")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("项目A"));
    const anchor = await screen.findByTestId("detail-anchor");
    expect(anchor).toHaveTextContent("项目A");
  });
});
