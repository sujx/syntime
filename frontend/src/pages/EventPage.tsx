import { Empty } from "antd";
import { zh } from "@/i18n/zh";

export default function EventPage() {
  return (
    <div data-testid="page-event">
      <h1 className="page-title" style={{ marginBottom: "var(--space-5)" }}>
        {zh["nav.event"]}
      </h1>
      <Empty description={zh["placeholder.dataWiring"]} />
    </div>
  );
}
