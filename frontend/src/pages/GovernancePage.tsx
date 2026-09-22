import { Empty } from "antd";
import { zh } from "@/i18n/zh";

export default function GovernancePage() {
  return (
    <div data-testid="page-governance">
      <h1 className="page-title" style={{ marginBottom: "var(--space-5)" }}>
        {zh["nav.governance"]}
      </h1>
      <Empty description={zh["placeholder.dataWiring"]} />
    </div>
  );
}
