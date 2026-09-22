import { render, screen } from "@testing-library/react";
import { App as AntdApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { describe, expect, it } from "vitest";
import { antdTheme, CHART_COLORS, SIDEBAR_BG_GRADIENT, UNASSIGNED_COLOR } from "../theme/antdTheme";
import { Seal, Wordmark } from "../brand/brand";
import { zh } from "../i18n/zh";

describe("task2 runtime smoke (dev-server substitute)", () => {
  it("renders ConfigProvider+AntdApp with theme and brand marks without errors", () => {
    const errors: unknown[] = [];
    const origError = console.error;
    console.error = (...args: unknown[]) => errors.push(args);
    render(
      <ConfigProvider locale={zhCN} theme={antdTheme}>
        <AntdApp>
          <Seal size={36} />
          <Wordmark onDark size={18} />
          <div style={{ padding: "var(--space-6)" }}>{zh["brand.name"]}</div>
        </AntdApp>
      </ConfigProvider>,
    );
    console.error = origError;
    expect(errors).toEqual([]);
    expect(screen.getByRole("img", { name: "SynTime" }).tagName).toBe("svg");
    expect(screen.getByText("Syn")).toBeInTheDocument();
    expect(screen.getByText("Time")).toBeInTheDocument();
    expect(screen.getByText("SynTime · 与时偕行")).toBeInTheDocument();
  });

  it("exports stable theme constants", () => {
    expect(CHART_COLORS).toHaveLength(8);
    expect(UNASSIGNED_COLOR).toBe("#9AA6BC");
    expect(SIDEBAR_BG_GRADIENT).toContain("linear-gradient(168deg");
    expect(antdTheme.token?.colorPrimary).toBe("#4C7DF0");
  });
});
