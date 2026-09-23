import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntdApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authState = vi.hoisted(() => ({ role: "成本管理员" }));

vi.mock("@/api/client", () => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    username: "alice",
    role: authState.role,
    status: "authenticated",
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

import { get, post } from "@/api/client";
import EventPage from "@/pages/EventPage";
import { zh } from "@/i18n/zh";
import styles from "@/pages/event/event.module.css";
import { localText } from "@/test/localTime";

const row = {
  id: 11,
  eventNo: "EV-001",
  eventType: "arrears",
  eventTypeName: "欠费",
  eventLevel: "critical",
  source: "vendor",
  provider: "aliyun",
  vendorEventName: null,
  title: "账号欠费告警",
  content: null,
  resourceType: null,
  resourceId: null,
  instanceName: null,
  projectTag: null,
  cloudAccountName: "prod-main",
  occurredAt: "2026-09-20T02:00:00Z",
  receivedAt: "2026-09-20T02:01:00Z",
  status: "unread",
  handledBy: null,
  handledAt: null,
};
// 第二行：已读态，用于断言未读行高亮只落在 unread 行上
const readRow = {
  ...row,
  id: 12,
  eventNo: "EV-002",
  title: "域名到期提醒",
  eventLevel: "info",
  source: "manual",
  status: "read",
};
const pageData = { total: 2, page: 1, pageSize: 20, list: [row, readRow], unreadCount: 1 };

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AntdApp>
        <EventPage />
      </AntdApp>
    </QueryClientProvider>,
  );
}

describe("EventPage", () => {
  // 角色内联改写后必须复位，防止泄漏到后续用例
  beforeEach(() => {
    authState.role = "成本管理员";
  });
  afterEach(() => {
    authState.role = "成本管理员";
  });
  it("渲染列表、Tab 计数与未读行", async () => {
    vi.mocked(get).mockResolvedValue(pageData);
    setup();
    expect(await screen.findByText("账号欠费告警")).toBeInTheDocument();
    // Tab「未读」与状态 pill「未读」同文案（zh 字典既定），用 role 查询唯一锚定 Tab；
    // 计数徽标是 Tab 内 span，accessible name 拼接为「未读1」，正则同时钉住文案与数字
    const unreadTab = screen.getByRole("button", {
      name: new RegExp(`${zh["evt.tabUnread"] ?? ""}\\s*1`),
    });
    expect(within(unreadTab).getByText("1")).toBeInTheDocument();
    expect(screen.getByText(zh["evt.markRead"] ?? "")).toBeInTheDocument();
    expect(screen.getByText(zh["evt.sourceVendor"] ?? "")).toBeInTheDocument();
    expect(screen.getByText("急")).toBeInTheDocument(); // critical 级别图标
    // 未读行高亮：CSS Modules 在 vitest 下返回 scoped 类名（如 _unreadRow_xxxxx），
    // 从同一 styles 对象取值断言，落在未读行 <tr>、不落在已读行 <tr>
    const unreadRowClass = styles.unreadRow ?? "";
    expect(unreadRowClass).not.toBe("");
    expect(screen.getByText("账号欠费告警").closest("tr")).toHaveClass(unreadRowClass);
    expect(screen.getByText("域名到期提醒").closest("tr")).not.toHaveClass(unreadRowClass);
    // 发生时间按本地时区渲染；后端序列化的是 UTC，不可直接切片
    const unreadTr = screen.getByText("账号欠费告警").closest("tr");
    expect(
      within(unreadTr as HTMLElement).getByText(localText(row.occurredAt)),
    ).toBeInTheDocument();
  });
  it("标记已读走接口13并提示成功", async () => {
    vi.mocked(get).mockResolvedValue(pageData);
    vi.mocked(post).mockResolvedValue(null);
    setup();
    await screen.findByText("账号欠费告警");
    await userEvent.click(screen.getByText(zh["evt.markRead"] ?? ""));
    await waitFor(() =>
      expect(vi.mocked(post)).toHaveBeenCalledWith("/events/status/", {
        eventIds: [11],
        action: "read",
      }),
    );
    expect(await screen.findByText(zh["evt.done"] ?? "")).toBeInTheDocument();
  });
  it("切换 Tab 重查带 status 参数", async () => {
    vi.mocked(get).mockResolvedValue(pageData);
    setup();
    await screen.findByText("账号欠费告警");
    vi.mocked(get).mockClear();
    await userEvent.click(screen.getByText(zh["evt.tabHandled"] ?? ""));
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/events/",
        expect.objectContaining({ status: "handled" }),
      ),
    );
  });
  it("财务角色不渲染操作按钮", async () => {
    authState.role = "财务人员";
    vi.mocked(get).mockResolvedValue(pageData);
    setup();
    await screen.findByText("账号欠费告警");
    expect(screen.queryByText(zh["evt.markRead"] ?? "")).not.toBeInTheDocument();
  });
});
