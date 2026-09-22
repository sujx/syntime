import MockAdapter from "axios-mock-adapter";
import { App as AntdApp, ConfigProvider } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { api } from "@/api/client";
import { AuthProvider, useAuth } from "../AuthContext";
import { clear, getRefresh, readSession, setRefresh, writeSession } from "../tokenStore";
import { ROLE_ADMIN } from "../roles";

function Probe({ onLogout }: { onLogout?: () => void }) {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="role">{auth.role ?? "-"}</span>
      {/* login 会向调用方重抛 BizError（登录页需捕获），Probe 作为调用方就地吞掉，防未处理拒绝 */}
      <button onClick={() => void auth.login("admin", "pwd").catch(() => undefined)}>login</button>
      <button onClick={() => void auth.logout()}>logout</button>
      {onLogout && <button onClick={onLogout}>spy</button>}
    </div>
  );
}

const renderAuth = () =>
  render(
    <ConfigProvider>
      <AntdApp>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </AntdApp>
    </ConfigProvider>,
  );

let mock: MockAdapter;
beforeEach(() => {
  mock = new MockAdapter(api);
  localStorage.clear();
  clear();
});
afterEach(() => {
  mock.restore();
  clear();
});

const ENVELOPED = (data: unknown): [number, { code: number; message: string; data: unknown }] => [
  200,
  { code: 0, message: "ok", data },
];

describe("AuthContext", () => {
  it("挂载时用 localStorage 会话恢复为已登录（access 为空待刷新，不发任何请求）", () => {
    writeSession({ username: "ann", role: ROLE_ADMIN });
    setRefresh("R-1");
    renderAuth();
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("role")).toHaveTextContent(ROLE_ADMIN);
    // 恢复只读本地存储，绝不触发网络请求
    expect(mock.history.get.length).toBe(0);
    expect(mock.history.post.length).toBe(0);
  });

  it("login 成功：写 access/refresh/session 并置 authenticated", async () => {
    mock
      .onPost("/token/")
      .reply(() =>
        ENVELOPED({ access: "A-1", refresh: "R-1", role: ROLE_ADMIN, username: "admin" }),
      );
    renderAuth();
    await userEvent.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(readSession()).toEqual({ username: "admin", role: ROLE_ADMIN });
    expect(getRefresh()).toBe("R-1");
  });

  it("login 失败 40001：保持 anonymous 并显示后端 message", async () => {
    mock.onPost("/token/").reply(400, { code: 40001, message: "用户名或密码错误", data: null });
    renderAuth();
    await userEvent.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByText("用户名或密码错误")).toBeInTheDocument());
    expect(screen.getByTestId("status")).toHaveTextContent("anonymous");
  });

  it("logout：后端 500 也本地清空", async () => {
    writeSession({ username: "ann", role: ROLE_ADMIN });
    setRefresh("R-1");
    mock.onPost("/auth/logout/").reply(500, { code: 50000, message: "boom", data: null });
    renderAuth();
    await userEvent.click(screen.getByText("logout"));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    expect(readSession()).toBeNull();
    expect(getRefresh()).toBeNull();
  });

  it("logout 请求体带 refresh token", async () => {
    let body: unknown;
    setRefresh("R-9");
    writeSession({ username: "ann", role: ROLE_ADMIN });
    mock.onPost("/auth/logout/").reply((cfg) => {
      body = JSON.parse(cfg.data as string);
      return ENVELOPED(null);
    });
    renderAuth();
    await userEvent.click(screen.getByText("logout"));
    await waitFor(() => expect(body).toEqual({ refresh: "R-9" }));
  });
});
