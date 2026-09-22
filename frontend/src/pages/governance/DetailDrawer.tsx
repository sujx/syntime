import { Drawer, Table } from "antd";
import type { TableProps } from "antd";
import { useState } from "react";
import type { DetailRow, SummaryRow } from "@/api/types";
import { useDetails } from "@/features/governance/hooks";
import { zh } from "@/i18n/zh";
import styles from "./governance.module.css";

export function DetailDrawer({ row, onClose }: { row: SummaryRow | null; onClose: () => void }) {
  const [page, setPage] = useState(1);
  const range = row
    ? { startDate: row.statRange.start, endDate: row.statRange.end }
    : { startDate: "", endDate: "" };
  const { data, isFetching } = useDetails(
    row?.projectTag ?? "",
    row?.tagStatus ?? null,
    range,
    page,
  );
  const columns: TableProps<DetailRow>["columns"] = [
    {
      title: zh["gov.colInstance"] ?? "",
      dataIndex: "instanceId",
      render: (v: string | null) => <span className={styles.mono}>{v ?? "--"}</span>,
    },
    { title: zh["gov.resourceType"] ?? "", dataIndex: "resourceType" },
    { title: zh["gov.colAccount"] ?? "", dataIndex: "cloudAccountName" },
    {
      title: zh["gov.colRegion"] ?? "",
      dataIndex: "region",
      render: (v: string | null) => v ?? "--",
    },
    { title: zh["gov.colAmount"] ?? "", dataIndex: "amount" },
    { title: zh["gov.colCharge"] ?? "", dataIndex: "chargeType" },
    { title: zh["gov.colTagStatus"] ?? "", dataIndex: "tagStatus" },
  ];
  return (
    <Drawer
      open={row !== null}
      onClose={() => {
        setPage(1);
        onClose();
      }}
      destroyOnHidden
      width={560}
      title={`${zh["gov.detailTitle"] ?? ""} · ${row?.projectTag ?? ""}`}
    >
      <Table<DetailRow>
        rowKey={(r) => `${r.instanceId ?? "-"}|${r.resourceType}`}
        size="small"
        loading={isFetching}
        columns={columns}
        dataSource={data?.list ?? []}
        pagination={{ pageSize: 20, total: data?.total ?? 0, current: page, onChange: setPage }}
        locale={{ emptyText: zh["common.empty"] }}
      />
    </Drawer>
  );
}
