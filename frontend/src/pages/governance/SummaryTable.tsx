import { Table } from "antd";
import type { TableProps } from "antd";
import type { SorterResult } from "antd/es/table/interface";
import { useEffect } from "react";
import type { ResourceTypeInfo, SummaryRow } from "@/api/types";
import { toMoneyNumber } from "@/features/charts/palette";
import { useSummary, type GovernanceFilters } from "@/features/governance/hooks";
import { zh } from "@/i18n/zh";
import styles from "./governance.module.css";

type SortOrder = "ascend" | "descend" | null;

function toSortOrder(filters: GovernanceFilters, col: string): SortOrder | undefined {
  if (filters.sortField !== col) return undefined;
  if (filters.sortOrder === "asc") return "ascend";
  if (filters.sortOrder === "desc") return "descend";
  return null;
}

function applySort(
  filters: GovernanceFilters,
  sorter: SorterResult<SummaryRow> | SorterResult<SummaryRow>[],
): GovernanceFilters {
  const s = Array.isArray(sorter) ? sorter[0] : sorter;
  const next: GovernanceFilters = { ...filters, page: undefined };
  const order = s?.order;
  if (!order) {
    delete next.sortField;
    delete next.sortOrder;
    return next;
  }
  const key = s?.columnKey ?? (s?.column as { key?: string } | undefined)?.key;
  if (key != null) {
    next.sortField = String(key);
    next.sortOrder = order === "ascend" ? "asc" : "desc";
  }
  return next;
}

export function SummaryTable({
  filters,
  onFiltersChange,
  onRowOpen,
  onTypes,
}: {
  filters: GovernanceFilters;
  onFiltersChange: (next: GovernanceFilters) => void;
  onRowOpen: (row: SummaryRow) => void;
  onTypes?: (types: ResourceTypeInfo[]) => void;
}) {
  const { data, isFetching } = useSummary(filters);
  const types = data?.resourceTypes ?? [];
  useEffect(() => {
    if (data?.resourceTypes) onTypes?.(data.resourceTypes);
  }, [data?.resourceTypes, onTypes]);

  const columns: TableProps<SummaryRow>["columns"] = [
    {
      title: zh["gov.colTag"],
      dataIndex: "projectTag",
      key: "projectTag",
      fixed: "left",
      sorter: true,
      sortOrder: toSortOrder(filters, "projectTag"),
    },
    ...types.map((t) => ({
      title: `${t.displayName}${zh["gov.feeSuffix"]}`,
      key: t.code,
      render: (_: unknown, row: SummaryRow) => <MoneyCell v={row.amountByResourceType[t.code]} />,
    })),
    {
      title: zh["gov.colTotal"],
      dataIndex: "totalAmount",
      key: "totalAmount",
      sorter: true,
      sortOrder: toSortOrder(filters, "totalAmount"),
      render: (v: string) => <span className={styles.bold}>{v}</span>,
    },
    {
      title: zh["gov.colLast"],
      key: "last",
      render: (_: unknown, row: SummaryRow) => (
        <div>
          <div>{row.lastPeriodAmount}</div>
          <RateCell v={row.rate} />
        </div>
      ),
    },
    {
      title: zh["gov.colBudgetAmount"],
      dataIndex: "budgetAmount",
      key: "budgetAmount",
      sorter: true,
      sortOrder: toSortOrder(filters, "budgetAmount"),
      render: (v: string) => <MoneyCell v={v} />,
    },
    {
      title: zh["gov.colBudgetRate"],
      key: "budgetRate",
      sorter: true,
      sortOrder: toSortOrder(filters, "budgetRate"),
      render: (_: unknown, row: SummaryRow) => <BudgetCell row={row} />,
    },
  ];

  const head = data?.summary;
  const first = data?.list[0];
  const range = first?.statRange;
  const compare = first?.lastPeriodRange;

  return (
    <section className={styles.card}>
      <div className={styles.head}>
        <span className={styles.headTitle}>{zh["gov.tableTitle"]}</span>
        <span className={styles.headMeta}>
          {range ? (
            <span>
              {zh["gov.statRange"]} {range.start} ~ {range.end}
            </span>
          ) : null}
          {compare ? (
            <span>
              {zh["gov.compareRange"]} {compare.start} ~ {compare.end}
            </span>
          ) : null}
          {head ? (
            <span className={styles.total}>
              {zh["gov.totalPrefix"]} <strong>{head.totalAmount}</strong>
            </span>
          ) : null}
        </span>
      </div>
      <Table<SummaryRow>
        rowKey="projectTag"
        size="small"
        loading={isFetching}
        columns={columns}
        dataSource={data?.list ?? []}
        scroll={{ x: "max-content" }}
        locale={{ emptyText: zh["gov.empty"] }}
        pagination={{
          current: filters.page ?? 1,
          pageSize: 20,
          total: data?.total ?? 0,
          showTotal: (total, r) =>
            (zh["gov.paginationInfo"] ?? "")
              .replace("{from}", String(r[0]))
              .replace("{to}", String(r[1]))
              .replace("{total}", String(total)),
        }}
        onChange={(pag, _f, sorter, extra) => {
          if (extra.action === "sort") onFiltersChange(applySort(filters, sorter));
          else if (extra.action === "paginate") onFiltersChange({ ...filters, page: pag.current });
        }}
        onRow={(row) => ({ onClick: () => onRowOpen(row) })}
        rowClassName={(row) => `${styles.rowClickable} ${row.overBudget ? styles.overRow : ""}`}
      />
    </section>
  );
}

function MoneyCell({ v }: { v: string | undefined }) {
  return <span>{v ?? "--"}</span>;
}

function RateCell({ v }: { v: string }) {
  const n = toMoneyNumber(v);
  return (
    <span className={n == null ? styles.muted : n >= 0 ? styles.rateUp : styles.rateDown}>
      {v === "--" ? "--" : `${(n ?? 0) >= 0 ? "↑" : "↓"} ${Math.abs(n ?? 0)}`}
    </span>
  );
}

function BudgetCell({ row }: { row: SummaryRow }) {
  const n = toMoneyNumber(row.budgetRate);
  const pct = n == null ? 0 : Math.min(Math.max(n, 0), 100);
  return (
    <div style={{ minWidth: 110 }}>
      <span>
        {row.budgetRate === "--" ? "--" : `${row.budgetRate}%`}
        {row.budgetIncomplete ? (
          <span className={styles.muted}> {zh["gov.budgetIncomplete"]}</span>
        ) : null}
      </span>
      <div className={styles.budgetBar}>
        <div
          className={
            n != null && row.overBudget
              ? `${styles.budgetFill} ${styles.budgetFillOver}`
              : styles.budgetFill
          }
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
