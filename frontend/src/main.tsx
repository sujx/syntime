import { createRoot } from "react-dom/client";
import { App as AntdApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import "./styles/tokens.css";
import { antdTheme } from "./theme/antdTheme";

createRoot(document.getElementById("root")!).render(
  <ConfigProvider locale={zhCN} theme={antdTheme}>
    <AntdApp>
      <div style={{ padding: "var(--space-6)" }}>SynTime</div>
    </AntdApp>
  </ConfigProvider>,
);
