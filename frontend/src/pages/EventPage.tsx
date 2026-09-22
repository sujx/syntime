import { App, Button, Skeleton, Table } from "antd";
import type { TableProps } from "antd";
import { useState } from "react";
import { ROLE_ADMIN, ROLE_OPS } from "@/auth/roles";
import { useAuth } from "@/hooks/useAuth";
import { useEventList, useEventStatus, useEventTabCounts } from "@/features/events/hooks";
import type { EventLevel, EventRow, EventStatus } from "@/api/types";
import { zh } from "@/i18n/zh";
import styles from "./event/event.module.css";

type TabKey = "all" | EventStatus;

const TABS: { key: TabKey; label: string }[] = [
  { key: "all", label: zh["evt.tabAll"] ?? "" },
  { key: "unread", label: zh["evt.tabUnread"] ?? "" },
  { key: "read", label: zh["evt.tabRead"] ?? "" },
  { key: "handled", label: zh["evt.tabHandled"] ?? "" },
  { key: "ignored", label: zh["evt.tabIgnored"] ?? "" },
];

const LEVEL_META: Record<EventLevel, { cls: string; text: string }> = {
  critical: { cls: styles.lvlCritical ?? "", text: zh["evt.levelCritical"] ?? "" },
  warning: { cls: styles.lvlWarning ?? "", text: zh["evt.levelWarning"] ?? "" },
  info: { cls: styles.lvlInfo ?? "", text: zh["evt.levelInfo"] ?? "" },
};

const STATUS_META: Record<EventStatus, { cls: string; text: string }> = {
  unread: { cls: styles.pillDanger ?? "", text: zh["evt.statusUnread"] ?? "" },
  read: { cls: styles.pillInfo ?? "", text: zh["evt.statusRead"] ?? "" },
  handled: { cls: styles.pillSuccess ?? "", text: zh["evt.statusHandled"] ?? "" },
  ignored: { cls: styles.pillGray ?? "", text: zh["evt.statusIgnored"] ?? "" },
};

function fmtTime(iso: string | null): string {
  return iso ? iso.replace("T", " ").slice(0, 16) : "--";
}

export default function EventPage() {
  const { role } = useAuth();
  const { message } = App.useApp();
  const [tab, setTab] = useState<TabKey>("all");
  const [page, setPage] = useState(1);
  const canOperate = role === ROLE_ADMIN || role === ROLE_OPS;
  const { data: counts } = useEventTabCounts();
  const { data, isPending, isError, refetch, isFetching } = useEventList({
    status: tab === "all" ? undefined : tab,
    page,
    pageSize: 20,
  });
  const statusMutation = useEventStatus();

  const act = (row: EventRow, action: "read" | "ignore") => {
    statusMutation.mutate(
      { eventIds: [row.id], action },
      {
        onSuccess: () => void message.success(zh["evt.done"]),
        onError: () => void message.error(zh["evt.fail"]),
      },
    );
  };

  const countOf = (key: TabKey): number | undefined => (counts ? counts[key] : undefined);

  const columns: TableProps<EventRow>["columns"] = [
    {
      title: zh["evt.colTitle"],
      dataIndex: "title",
      render: (_: string, row) => {
        const lvl = LEVEL_META[row.eventLevel] ?? LEVEL_META.info;
        return (
          <span className={styles.titleCell}>
            <span className={`${styles.levelIcon} ${lvl.cls}`}>{lvl.text}</span>
            {row.title}
          </span>
        );
      },
    },
    {
      title: zh["evt.colResource"],
      key: "resource",
      render: (_: unknown, row) =>
        [row.instanceName, row.resourceId].filter(Boolean).join(" · ") || "--",
    },
    {
      title: zh["evt.colSource"],
      dataIndex: "source",
      render: (v: string) => (
        <span
          className={`${styles.sourceTag} ${v === "vendor" ? styles.srcVendor : styles.srcSelf}`}
        >
          {v === "vendor"
            ? zh["evt.sourceVendor"]
            : v === "manual"
              ? zh["evt.sourceManual"]
              : zh["evt.sourceRule"]}
        </span>
      ),
    },
    {
      title: zh["evt.colTime"],
      dataIndex: "occurredAt",
      render: (_: string | null, row) => fmtTime(row.occurredAt ?? row.receivedAt),
    },
    {
      title: zh["evt.colStatus"],
      dataIndex: "status",
      render: (v: EventStatus) => {
        const st = STATUS_META[v] ?? STATUS_META.unread;
        return <span className={`${styles.pill} ${st.cls}`}>{st.text}</span>;
      },
    },
    ...(canOperate
      ? [
          {
            title: zh["evt.colAction"],
            key: "action",
            render: (_: unknown, row: EventRow) => (
              <>
                {row.status === "unread" ? (
                  <Button
                    type="link"
                    size="small"
                    className={styles.link}
                    onClick={() => act(row, "read")}
                  >
                    {zh["evt.markRead"]}
                  </Button>
                ) : null}
                {row.status === "unread" || row.status === "read" ? (
                  <Button
                    type="link"
                    size="small"
                    autoInsertSpace={false}
                    className={styles.link}
                    onClick={() => act(row, "ignore")}
                  >
                    {zh["evt.ignore"]}
                  </Button>
                ) : null}
              </>
            ),
          },
        ]
      : []),
  ];

  return (
    <div data-testid="page-event">
      <h1 className="page-title" style={{ marginBottom: "var(--space-5)" }}>
        {zh["nav.event"]}
      </h1>
      <div className={styles.tabs}>
        {TABS.map((t) => {
          const c = countOf(t.key);
          return (
            <button
              key={t.key}
              type="button"
              className={`${styles.tab} ${tab === t.key ? styles.tabActive : ""}`}
              onClick={() => {
                setTab(t.key);
                setPage(1);
              }}
            >
              {t.label}
              {c != null ? (
                <span className={`${styles.count} ${t.key === "unread" ? styles.countUnread : ""}`}>
                  {c}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      {isPending ? <Skeleton active paragraph={{ rows: 6 }} /> : null}
      {isError ? (
        <div style={{ padding: "var(--space-5)", textAlign: "center" }}>
          {zh["common.loadFail"]}{" "}
          <Button type="link" autoInsertSpace={false} onClick={() => void refetch()}>
            {zh["common.retry"]}
          </Button>
        </div>
      ) : null}
      {!isPending && !isError ? (
        <Table<EventRow>
          rowKey="id"
          size="small"
          loading={isFetching}
          columns={columns}
          dataSource={data?.list ?? []}
          rowClassName={(r) => (r.status === "unread" ? (styles.unreadRow ?? "") : "")}
          locale={{ emptyText: zh["evt.empty"] }}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            showTotal: (total, r) =>
              (zh["gov.paginationInfo"] ?? "")
                .replace("{from}", String(r[0]))
                .replace("{to}", String(r[1]))
                .replace("{total}", String(total)),
            onChange: setPage,
          }}
        />
      ) : null}
    </div>
  );
}
