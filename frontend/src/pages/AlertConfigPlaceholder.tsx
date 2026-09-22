import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { zh } from "@/i18n/zh";
import { PlaceholderPage, Phase2Note } from "@/components/layout/PlaceholderPage";

interface Row {
  key: string;
  name: string;
  threshold: string;
  channel: string;
  action: string;
}

const columns: ColumnsType<Row> = [
  { title: "规则名称", dataIndex: "name", key: "name" },
  { title: "阈值", dataIndex: "threshold", key: "threshold" },
  { title: "通知渠道", dataIndex: "channel", key: "channel" },
  {
    title: "操作",
    dataIndex: "action",
    key: "action",
    render: () => <span className="mono">{zh["placeholder.phase2Note"]}</span>,
  },
];

export default function AlertConfigPlaceholder() {
  return (
    <PlaceholderPage titleKey="nav.alertConfig">
      <Phase2Note />
      <Table<Row> columns={columns} dataSource={[]} pagination={false} />
    </PlaceholderPage>
  );
}
