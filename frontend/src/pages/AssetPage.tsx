import { Empty } from "antd";
import { zh } from "@/i18n/zh";

export default function AssetPage() {
  return (
    <div data-testid="page-asset">
      <h1 className="page-title" style={{ marginBottom: "var(--space-5)" }}>
        {zh["nav.asset"]}
      </h1>
      <Empty description={zh["placeholder.dataWiring"]} />
    </div>
  );
}
