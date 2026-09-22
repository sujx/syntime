import { Empty } from "antd";
import { zh } from "@/i18n/zh";

export default function ProjectSettlementPage() {
  return (
    <div data-testid="page-project-settlement">
      <h1 className="page-title" style={{ marginBottom: "var(--space-5)" }}>
        {zh["nav.projectSettlement"]}
      </h1>
      <Empty description={zh["placeholder.dataWiring"]} />
    </div>
  );
}
