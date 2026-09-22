import type { Role } from "./roles";
import { isRole } from "./roles";

const REFRESH_KEY = "syntime.refresh";
const SESSION_KEY = "syntime.session";

export interface SessionInfo {
  username: string;
  role: Role;
}

// access 仅存内存，不落任何 Storage
let access: string | null = null;

export function setAccess(token: string | null): void {
  access = token;
}
export function getAccess(): string | null {
  return access;
}

export function setRefresh(token: string): void {
  localStorage.setItem(REFRESH_KEY, token);
}
export function getRefresh(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function readSession(): SessionInfo | null {
  const raw = localStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) {
      const { username, role } = parsed as { username?: unknown; role?: unknown };
      if (typeof username === "string" && isRole(role)) {
        return { username, role };
      }
    }
  } catch {
    /* 损坏的会话按未登录处理 */
  }
  return null;
}

export function writeSession(session: SessionInfo): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clear(): void {
  access = null;
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(SESSION_KEY);
}
