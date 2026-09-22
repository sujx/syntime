import { App as AntdApp, ConfigProvider } from "antd";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AuthProvider } from "../AuthContext";
import { RequireAuth } from "../RequireAuth";
import { clear, setRefresh, writeSession } from "../tokenStore";
import { ROLE_ADMIN } from "../roles";

const tree = (to: string) => (
  <ConfigProvider>
    <AntdApp>
      <AuthProvider>
        <MemoryRouter initialEntries={[to]}>
          <Routes>
            <Route path="/login" element={<div>登录页</div>} />
            <Route
              path="/dashboard"
              element={
                <RequireAuth>
                  <div>仪表盘</div>
                </RequireAuth>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </AntdApp>
  </ConfigProvider>
);

beforeEach(() => {
  localStorage.clear();
  clear();
});
afterEach(() => {
  clear();
});

describe("RequireAuth", () => {
  it("未登录重定向到 /login", () => {
    render(tree("/dashboard"));
    expect(screen.getByText("登录页")).toBeInTheDocument();
  });
  it("已恢复会话则放行", () => {
    writeSession({ username: "ann", role: ROLE_ADMIN });
    setRefresh("R-1");
    render(tree("/dashboard"));
    expect(screen.getByText("仪表盘")).toBeInTheDocument();
  });
});
