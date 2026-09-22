import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntdApp } from "antd";
import { describe, expect, it, vi } from "vitest";

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
  occurredAt: "2026-09-20T10:00:00+08:00",
  receivedAt: "2026-09-20T10:01:00+08:00",
  status: "unread",
  handledBy: null,
  handledAt: null,
};
const pageData = { total: 1, page: 1, pageSize: 20, list: [row], unreadCount: 1 };

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
  it("渲染列表、Tab 计数与未读行", async () => {
    vi.mocked(get).mockResolvedValue(pageData);
    setup();
    expect(await screen.findByText("账号欠费告警")).toBeInTheDocument();
    // Tab「未读」与状态 pill「未读」同文案（zh 字典既定），用 role 查询唯一锚定 Tab
    expect(
      screen.getByRole("button", { name: new RegExp(zh["evt.tabUnread"] ?? "") }),
    ).toBeInTheDocument();
    expect(screen.getByText(zh["evt.markRead"] ?? "")).toBeInTheDocument();
    expect(screen.getByText(zh["evt.sourceVendor"] ?? "")).toBeInTheDocument();
    expect(screen.getByText("急")).toBeInTheDocument(); // critical 级别图标
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
    authState.role = "成本管理员";
  });
});
