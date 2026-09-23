export interface Envelope<T> {
  code: number;
  message: string;
  data: T;
}

export interface PageResult<T> {
  total: number;
  page: number;
  pageSize: number;
  list: T[];
}

export type MoneyString = string;

export interface StatRange {
  start: string;
  end: string;
}

export interface ResourceTypeInfo {
  code: string;
  displayName: string;
}

export interface SummaryRow {
  projectTag: string;
  tagStatus: string | null;
  amountByResourceType: Record<string, string>;
  totalAmount: string;
  lastPeriodAmount: string;
  lastPeriodRange: StatRange;
  rate: string;
  budgetAmount: string;
  budgetRate: string;
  overBudget: boolean;
  budgetIncomplete: boolean;
  statRange: StatRange;
}

export interface SummaryData extends PageResult<SummaryRow> {
  resourceTypes: ResourceTypeInfo[];
  summary: { amountByResourceType: Record<string, string>; totalAmount: string };
}

export interface TrendItem {
  projectTag: string;
  tagStatus: string | null;
  amount: string;
}

export interface TrendPoint {
  date: string;
  items: TrendItem[];
}

export interface TrendData {
  current: TrendPoint[];
  compare: TrendPoint[];
  statRange: StatRange;
  compareRange: StatRange;
  billMonthIncomplete: boolean;
}

export interface DetailRow {
  instanceId: string | null;
  resourceType: string;
  cloudAccountName: string;
  region: string | null;
  amount: string;
  chargeType: string;
  tagStatus: string;
}

export type DetailData = PageResult<DetailRow>;

export interface DashboardCards {
  cloudAccountTotal: number;
  enabled: number;
  disabled: number;
  assetTotal: number;
  running: number;
  stopped: number;
  monthAmount: string;
  monthRate: string;
  isEstimate: boolean;
  unallocatedAmount: string;
  unallocatedRatio: string;
  eventPending: number;
  eventHigh: number;
  eventWarning: number;
}

export interface SyncAccount {
  accountName: string;
  vendor: string;
  lastSyncTime: string | null;
  /** success / running / failed；为 null 表示该账号尚无同步日志（「无记录」态，见 ui-spec 5.16） */
  status: string | null;
}

export interface SyncStatusData {
  accounts: SyncAccount[];
  lastAggregateTime: string | null;
}

export interface DashboardData {
  cards: DashboardCards;
  trend: TrendData;
  syncStatus: SyncStatusData;
}

export type EventLevel = "info" | "warning" | "critical";
export type EventStatus = "unread" | "read" | "handled" | "ignored";

export interface EventRow {
  id: number;
  eventNo: string | null;
  eventType: string;
  eventTypeName: string;
  eventLevel: EventLevel;
  source: string;
  provider: string | null;
  vendorEventName: string | null;
  title: string;
  content: string | null;
  resourceType: string | null;
  resourceId: string | null;
  instanceName: string | null;
  projectTag: string | null;
  cloudAccountName: string | null;
  occurredAt: string | null;
  receivedAt: string | null;
  status: EventStatus;
  handledBy: string | null;
  handledAt: string | null;
}

export interface EventPageData extends PageResult<EventRow> {
  unreadCount: number;
}
