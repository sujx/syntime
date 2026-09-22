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
    expect(await screen.findByText("云服务器 ECS费用")).toBeInTheDocument();
    expect(screen.getByText(zh["gov.totalPrefix"] ?? "")).toBeInTheDocument();
    expect(await screen.findByText(/1000\.00/)).toBeInTheDocument();
    expect(screen.getByText("150.00")).toBeInTheDocument();
    // 未分配行金额为空字典 → 动态列显示 --
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
  });
  it("排序走服务端参数", async () => {
    vi.mocked(get).mockResolvedValue(summaryData);
    setup(<GovernancePage />);
    await screen.findByText("150.00");
    vi.mocked(get).mockClear();
    await userEvent.click(screen.getByRole("columnheader", { name: /项目总支出/ }));
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ sortField: "totalAmount", sortOrder: "asc" }),
      ),
    );
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
});
