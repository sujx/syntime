import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/api/client";
import { API } from "@/api/endpoints";
import type { EventPageData, EventStatus } from "@/api/types";

export interface EventListParams {
  status?: EventStatus;
  eventLevel?: string;
  keyword?: string;
  startDate?: string;
  endDate?: string;
  page?: number;
  pageSize?: number;
  sortField?: string;
  sortOrder?: "asc" | "desc";
}

export function useEventList(params: EventListParams) {
  return useQuery({
    queryKey: ["events", "list", params],
    queryFn: () => get<EventPageData>(API.events, { ...params }),
    placeholderData: keepPreviousData,
  });
}

const TAB_STATUSES: EventStatus[] = ["unread", "read", "handled", "ignored"];

/** Tab 计数：pageSize=1 各取 total（R4）；全部 Tab 用当前列表 total 之外再补一发 */
export function useEventTabCounts() {
  return useQuery({
    queryKey: ["events", "tab-counts"],
    queryFn: async () => {
      const all = await get<EventPageData>(API.events, { page: 1, pageSize: 1 });
      const byStatus = await Promise.all(
        TAB_STATUSES.map((s) =>
          get<EventPageData>(API.events, { page: 1, pageSize: 1, status: s }),
        ),
      );
      return {
        all: all.total,
        unread: all.unreadCount,
        read: byStatus[1]?.total ?? 0,
        handled: byStatus[2]?.total ?? 0,
        ignored: byStatus[3]?.total ?? 0,
      };
    },
    placeholderData: keepPreviousData,
  });
}

export type EventAction = "read" | "handle" | "ignore";

export function useEventStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { eventIds: number[]; action: EventAction }) =>
      post<null>(API.eventStatus, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["events"] }); // 含 list / tab-counts / unread-badge
    },
  });
}
