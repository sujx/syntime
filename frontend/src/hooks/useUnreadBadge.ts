import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import { API } from "@/api/endpoints";
import type { PageResult } from "@/api/types";

interface EventPage extends PageResult<unknown> {
  unreadCount: number;
}

export function useUnreadBadge(enabled: boolean): number {
  const { data } = useQuery({
    queryKey: ["events", "unread-badge"],
    queryFn: () => get<EventPage>(API.events, { page: 1, pageSize: 1 }),
    enabled,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 0,
  });
  return data?.unreadCount ?? 0;
}
