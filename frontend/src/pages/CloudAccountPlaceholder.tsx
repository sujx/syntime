import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { zh } from "@/i18n/zh";
import { PlaceholderPage, Phase2Note, ImportDropzone } from "@/components/layout/PlaceholderPage";

interface Row {
  key: string;
  name: string;
  provider: string;
  lastSync: string;
  action: string;
}

const columns: ColumnsType<Row> = [
  { title: "账号名称", dataIndex: "name", key: "name" },
  { title: "云厂商", dataIndex: "provider", key: "provider" },
  { title: "上次同步", dataIndex: "lastSync", key: "lastSync" },
  {
    title: "操作",
    dataIndex: "action",
    key: "action",
    render: () => <span className="mono">{zh["placeholder.phase2Note"]}</span>,
  },
];

export default function CloudAccountPlaceholder() {
  return (
    <PlaceholderPage titleKey="nav.cloudAccount">
      <ImportDropzone />
      <Phase2Note />
      <Table<Row> columns={columns} dataSource={[]} pagination={false} />
    </PlaceholderPage>
  );
}
