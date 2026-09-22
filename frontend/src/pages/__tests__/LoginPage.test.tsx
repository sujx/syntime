import MockAdapter from "axios-mock-adapter";
import { App as AntdApp, ConfigProvider } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { AuthProvider } from "@/auth/AuthContext";
import { readSession } from "@/auth/tokenStore";
import { ROLE_ADMIN } from "@/auth/roles";
import LoginPage from "../LoginPage";

const navigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const mod = await importOriginal<typeof import("react-router-dom")>();
  return { ...mod, useNavigate: () => navigate };
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
  localStorage.clear();
});
afterEach(() => {
  mock.restore();
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

it("空字段不发请求", async () => {
  const spy = vi.fn();
  mock.onPost("/token/").reply(spy);
  renderLogin();
  await userEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await new Promise((r) => setTimeout(r, 50));
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
