import MockAdapter from "axios-mock-adapter";
import { App as AntdApp, ConfigProvider } from "antd";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { AuthProvider } from "@/auth/AuthContext";
import { readSession } from "@/auth/tokenStore";
import { ROLE_ADMIN } from "@/auth/roles";
import { zh } from "@/i18n/zh";
import LoginPage from "../LoginPage";

const navigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const mod = await importOriginal<typeof import("react-router-dom")>();
  return { ...mod, useNavigate: () => navigate };
});

// 仅用于注入非 BizError 的 login 拒绝（client 层网络错误也会归一为 BizError，
// 适配器无法直达 LoginPage 的兜底分支），默认透传真实 useAuth
const loginOverride = vi.hoisted(() => ({
  current: null as null | ((name: string, password: string) => Promise<void>),
}));
vi.mock("@/hooks/useAuth", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAuth")>();
  return {
    ...mod,
    useAuth: () => {
      const value = mod.useAuth();
      return loginOverride.current ? { ...value, login: loginOverride.current } : value;
    },
  };
});

function renderLogin(
  initialEntries: Parameters<typeof MemoryRouter>[0]["initialEntries"] = ["/login"],
) {
  return render(
    <ConfigProvider>
      <AntdApp>
        <AuthProvider>
          <MemoryRouter initialEntries={initialEntries}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/dashboard" element={<div>仪表盘</div>} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </AntdApp>
    </ConfigProvider>,
  );
}

let mock: MockAdapter;
beforeEach(() => {
  mock = new MockAdapter(api);
  navigate.mockClear();
  loginOverride.current = null;
  localStorage.clear();
});
afterEach(() => {
  mock.restore();
  loginOverride.current = null;
});

it("登录成功后跳转 DEFAULT_PATH 并写会话", async () => {
  mock.onPost("/token/").reply(200, {
    code: 0,
    message: "ok",
    data: { access: "A", refresh: "R", role: ROLE_ADMIN, username: "admin" },
  });
  renderLogin();
  await userEvent.type(screen.getByLabelText("用户名"), "admin");
  await userEvent.type(screen.getByLabelText("密码"), "pwd12345");
  await userEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/dashboard", { replace: true }));
  expect(readSession()).toEqual({ username: "admin", role: ROLE_ADMIN });
});

it("40001 停留登录页并显示后端文案", async () => {
  mock.onPost("/token/").reply(400, { code: 40001, message: "用户名或密码错误", data: null });
  renderLogin();
  await userEvent.type(screen.getByLabelText("用户名"), "admin");
  await userEvent.type(screen.getByLabelText("密码"), "bad");
  await userEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await waitFor(() => expect(screen.getByText("用户名或密码错误")).toBeInTheDocument());
  expect(navigate).not.toHaveBeenCalled();
});

it("40100 停留登录页并提示账号或密码错误", async () => {
  // 真实后端对错误凭据返回 HTTP 401 + code 40100；40100 不在全局 TOAST_CODES，
  // 必须由登录页自行提示（原缺陷：AuthContext banner 被 fixed 全屏登录屏遮住）
  mock
    .onPost("/token/")
    .reply(401, { code: 40100, message: "找不到指定凭据对应的有效用户", data: null });
  renderLogin();
  await userEvent.type(screen.getByLabelText("用户名"), "demo");
  await userEvent.type(screen.getByLabelText("密码"), "wrong-pass");
  await userEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await waitFor(() =>
    expect(screen.getByText(zh["login.badCredentials"] ?? "")).toBeInTheDocument(),
  );
  expect(navigate).not.toHaveBeenCalled();
});

it("空字段不发请求", async () => {
  const spy = vi.fn();
  mock.onPost("/token/").reply(spy);
  renderLogin();
  await userEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  // userEvent 已包 act；再冲刷一次微任务队列即可确定性断言"未发起请求"，无需定时 sleep
  await act(async () => {
    await Promise.resolve();
  });
  expect(spy).not.toHaveBeenCalled();
});

it("短信页签只提示不发请求", async () => {
  const spy = vi.fn();
  mock.onPost("/token/").reply(spy);
  renderLogin();
  await userEvent.click(screen.getByRole("button", { name: "手机验证码" }));
  await waitFor(() => expect(screen.getByText(/尚未开放/)).toBeInTheDocument());
  expect(spy).not.toHaveBeenCalled();
});

it("state.from 命中已知路径时登录后跳转该路径", async () => {
  mock.onPost("/token/").reply(200, {
    code: 0,
    message: "ok",
    data: { access: "A", refresh: "R", role: ROLE_ADMIN, username: "admin" },
  });
  renderLogin([{ pathname: "/login", state: { from: "/event" } }]);
  await userEvent.type(screen.getByLabelText("用户名"), "admin");
  await userEvent.type(screen.getByLabelText("密码"), "pwd12345");
  await userEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/event", { replace: true }));
});

it("state.from 为未知路径时回落 DEFAULT_PATH", async () => {
  mock.onPost("/token/").reply(200, {
    code: 0,
    message: "ok",
    data: { access: "A", refresh: "R", role: ROLE_ADMIN, username: "admin" },
  });
  renderLogin([{ pathname: "/login", state: { from: "/nope" } }]);
  await userEvent.type(screen.getByLabelText("用户名"), "admin");
  await userEvent.type(screen.getByLabelText("密码"), "pwd12345");
  await userEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/dashboard", { replace: true }));
});

it("login 抛出非 BizError 时兜底提示登录失败文案", async () => {
  // client 拦截器把所有网络/HTTP 错误归一为 BizError，适配器无法构造非 BizError；
  // 故经 importOriginal 透传的 useAuth mock 注入一个普通 Error 拒绝
  loginOverride.current = () => Promise.reject(new Error("unexpected boom"));
  renderLogin();
  await userEvent.type(screen.getByLabelText("用户名"), "admin");
  await userEvent.type(screen.getByLabelText("密码"), "pwd12345");
  await userEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  // noUncheckedIndexedAccess：字典取值收窄为 string
  const failText = zh["login.fail"] ?? "";
  await waitFor(() => expect(screen.getByText(failText)).toBeInTheDocument());
  expect(navigate).not.toHaveBeenCalled();
});
