import type { ThemeConfig } from "antd";

export const CHART_COLORS = [
  "#4C7DF0",
  "#1FB56B",
  "#F5A623",
  "#E85A5A",
  "#EC4899",
  "#58B99E",
  "#D4A24C",
  "#8B5CF6",
] as const;

export const UNASSIGNED_COLOR = "#9AA6BC";

export const SIDEBAR_BG_GRADIENT =
  "linear-gradient(168deg, #2A2166 0%, #23337A 30%, #1E4E7E 55%, #17646B 80%, #4A3D20 100%)";

export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: "#4C7DF0",
    colorText: "#2A3450",
    colorTextSecondary: "#56627A",
    colorTextTertiary: "#9AA6BC",
    colorBorder: "#E3E8F0",
    colorBorderSecondary: "#EEF0F4",
    colorError: "#E85A5A",
    colorSuccess: "#1FB56B",
    colorWarning: "#F5A623",
    borderRadius: 8,
    controlHeight: 36,
    fontFamily: "'Inter', -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif",
  },
  components: {
    Table: { headerBg: "#F4F6FA", headerColor: "#3E4A63", rowHoverBg: "#F4F6FA" },
    Layout: { siderBg: "#23337A" },
    Button: { primaryShadow: "0 1px 2px rgba(59, 99, 216, 0.2)" },
  },
};
