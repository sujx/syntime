import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntdApp } from "antd";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/components/chart/ChartCard", () => ({
  ChartCard: ({ title, extra }: { title: string; extra?: string }) => (
    <div data-testid={`chart:${title}`}>{extra ? <span>{extra}</span> : null}</div>
  ),
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    username: "a",
    role: "成本管理员",
    status: "authenticated",
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

import { get } from "@/api/client";
import GovernancePage from "@/pages/GovernancePage";
import { zh } from "@/i18n/zh";

const trend = {
  current: [
    {
      date: "2026-09-01",
      items: [{ projectTag: "A", tagStatus: "normal", amount: "1.00" }],
    },
  ],
  compare: [],
  statRange: { start: "2026-09-01", end: "2026-09-02" },
  compareRange: { start: "2026-08-01", end: "2026-08-02" },
  billMonthIncomplete: true,
};
const summary = {
  total: 1,
  page: 1,
  pageSize: 20,
  resourceTypes: [],
  summary: { amountByResourceType: {}, totalAmount: "150.00" },
  list: [
    {
      projectTag: "A",
      tagStatus: "normal",
      amountByResourceType: {},
      totalAmount: "150.00",
      lastPeriodAmount: "100.00",
      lastPeriodRange: { start: "2026-08-01", end: "2026-08-31" },
      rate: "50.00",
      budgetAmount: "--",
      budgetRate: "--",
      overBudget: false,
      budgetIncomplete: false,
      statRange: { start: "2026-09-01", end: "2026-09-02" },
    },
  ],
};
const details = {
  total: 1,
  page: 1,
  pageSize: 20,
  list: [
    {
      instanceId: "i-abc",
      resourceType: "ecs",
      cloudAccountName: "prod",
      region: "cn-shanghai",
      amount: "150.00",
      chargeType: "postpaid",
      tagStatus: "normal",
    },
  ],
};

async function openDrawer() {
  vi.mocked(get).mockImplementation((url: string) =>
    url === "/cost/trend/"
      ? Promise.resolve(trend)
      : url === "/cost/summary/"
        ? Promise.resolve(summary)
        : url === "/cost/details/"
          ? Promise.resolve(details)
          : Promise.resolve({}),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AntdApp>
        <GovernancePage />
      </AntdApp>
    </QueryClientProvider>,
  );
  // 本夹具中合计与行金额同为 150.00（两个文本节点），改断唯一的项目标签行等待首查完成
  await screen.findByText("A");
}

describe("趋势卡 + 明细抽屉", () => {
  it("趋势卡随查询联动、对比开关默认开", async () => {
    await openDrawer();
    expect(await screen.findByTestId(`chart:${zh["gov.trendTitle"] ?? ""}`)).toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeChecked();
    // extra 串为「start ~ end · 预估注记」，用部分匹配断注记出现
    expect(screen.getByText(new RegExp(zh["gov.estNote"] ?? ""))).toBeInTheDocument();
    const calls = vi.mocked(get).mock.calls.filter((c) => c[0] === "/cost/trend/");
    expect(calls.length).toBeGreaterThan(0);
    // 默认区间为「本月」的计算值，只断言键存在且为字符串，避免日期漂移
    expect(calls[0]?.[1]).toEqual(
      expect.objectContaining({ startDate: expect.any(String), endDate: expect.any(String) }),
    );
  });
  it("点击行打开明细抽屉并请求接口 2", async () => {
    await openDrawer();
    // 抽屉未打开时不发明细请求（projectTag ?? "" 空串短路）
    expect(vi.mocked(get).mock.calls.some((c) => c[0] === "/cost/details/")).toBe(false);
    await userEvent.click(await screen.findByText("A"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(new RegExp(zh["gov.detailTitle"] ?? ""))).toBeInTheDocument();
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/details/",
        expect.objectContaining({
          projectTag: "A",
          tagStatus: "normal",
          startDate: "2026-09-01",
          endDate: "2026-09-02",
        }),
      ),
    );
    expect(await within(dialog).findByText("i-abc")).toBeInTheDocument();
  });
  it("instanceId null 渲染 --（财务屏蔽口径）", async () => {
    await openDrawer();
    vi.mocked(get).mockImplementation((url: string) =>
      url === "/cost/details/"
        ? Promise.resolve({ ...details, list: [{ ...details.list[0], instanceId: null }] })
        : Promise.resolve(url === "/cost/summary/" ? summary : url === "/cost/trend/" ? trend : {}),
    );
    await userEvent.click(await screen.findByText("A"));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("--")).toBeInTheDocument();
  });
});
