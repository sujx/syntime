export const ROLE_ADMIN = "成本管理员";
export const ROLE_OPS = "云运维";
export const ROLE_FINANCE = "财务人员";

export type Role = typeof ROLE_ADMIN | typeof ROLE_OPS | typeof ROLE_FINANCE;

export const ALL_ROLES: readonly Role[] = [ROLE_ADMIN, ROLE_OPS, ROLE_FINANCE];

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ALL_ROLES as readonly string[]).includes(value);
}
