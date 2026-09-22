import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { zh } from "@/i18n/zh";
import { PlaceholderPage, Phase2Note } from "@/components/layout/PlaceholderPage";

interface Row {
  key: string;
  name: string;
  owner: string;
  action: string;
}

const columns: ColumnsType<Row> = [
  { title: "预算名称", dataIndex: "name", key: "name" },
  { title: "负责人", dataIndex: "owner", key: "owner" },
  {
    title: "操作",
    dataIndex: "action",
    key: "action",
    render: () => <span className="mono">{zh["placeholder.phase2Note"]}…</span>,
  },
];

export default function BudgetPlaceholder() {
  return (
    <PlaceholderPage titleKey="nav.budget">
      <Phase2Note />
      <Table<Row> columns={columns} dataSource={[]} pagination={false} />
    </PlaceholderPage>
  );
}
