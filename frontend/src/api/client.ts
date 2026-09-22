import axios, { AxiosError, AxiosHeaders, type AxiosResponse } from "axios";
import type { AxiosRequestConfig } from "axios";
import type { Envelope } from "./types";

export class BizError extends Error {
  readonly code: number;
  readonly httpStatus: number;
  constructor(message: string, code: number, httpStatus: number) {
    super(message);
    this.name = "BizError";
    this.code = code;
    this.httpStatus = httpStatus;
  }
}

export const UNAUTHORIZED = 40100;
const TOAST_CODES = new Set([40001, 40300, 40900, 42900, 50000]);

// 网络/超时归一码：同样需要 toast（中文提示已内置于 message）
const NETWORK_ERROR = -1;

function shouldToast(code: number): boolean {
  return code === NETWORK_ERROR || TOAST_CODES.has(code);
}

type ToastHandler = (message: string) => void;
type TokenProvider = () => string | null;

export interface TokenPair {
  access: string;
  refresh: string;
}

export interface RefreshConfig {
  tokenReader: () => TokenPair | null;
  onAccessRotated: (access: string) => void;
  onSessionLost: () => void;
}

// 免刷新 URL：登录取 token 与登出自身 401 时不得触发刷新
const AUTH_FREE_URLS = ["/token/", "/auth/logout/"];

let toastHandler: ToastHandler | null = null;
let tokenProvider: TokenProvider | null = null;
let refreshConfig: RefreshConfig | null = null;
let inflight: Promise<TokenPair | null> | null = null;

export function setToastHandler(handler: ToastHandler | null): void {
  toastHandler = handler;
}
export function setTokenProvider(provider: TokenProvider | null): void {
  tokenProvider = provider;
}
export function configureRefresh(config: RefreshConfig | null): void {
  refreshConfig = config;
  inflight = null;
}
export function resetClientState(): void {
  toastHandler = null;
  tokenProvider = null;
  refreshConfig = null;
  inflight = null;
}

function isEnvelope(body: unknown): body is Envelope<unknown> {
  return typeof body === "object" && body !== null && "code" in body && "message" in body;
}

export const api = axios.create({ baseURL: "/api", timeout: 30_000 });

function toQuery(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item));
    } else {
      search.append(key, String(value));
    }
  }
  return search.toString();
}

type RetriableRequestConfig = AxiosRequestConfig & { _retriedAfterRefresh?: boolean };

api.interceptors.request.use((config) => {
  // 显式序列化 params 进 URL：保证任何观察者（devtools/proxy/mock）都能看到完整查询串
  if (config.params && typeof config.params === "object") {
    const query = toQuery(config.params as Record<string, unknown>);
    const separator = (config.url ?? "").includes("?") ? "&" : "?";
    config.url = `${config.url ?? ""}${query ? `${separator}${query}` : ""}`;
    delete config.params;
  }
  const token = tokenProvider?.();
  // 刷新后的重放已手动覆盖 Authorization，请求拦截器不得用（可能滞后的）provider 再覆盖
  if (token && !(config as RetriableRequestConfig)._retriedAfterRefresh) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

function toBizError(err: AxiosError<Envelope<unknown>>): BizError {
  const body = err.response?.data;
  if (isEnvelope(body)) {
    return new BizError(body.message, body.code, err.response?.status ?? 0);
  }
  if (err.code === "ECONNABORTED") {
    return new BizError("请求超时，请稍后重试", NETWORK_ERROR, err.response?.status ?? 0);
  }
  if (!err.response) {
    // 网络异常/超时统一归一为 code=-1（mock 与真实环境对 request 字段的填充不一致，不依赖它）
    return new BizError("网络异常，请稍后重试", NETWORK_ERROR, 0);
  }
  return new BizError("系统内部错误", 50000, err.response?.status ?? 0);
}

function unwrapFulfilled(response: AxiosResponse): AxiosResponse {
  const body: unknown = response.data;
  if (isEnvelope(body)) {
    if (body.code === 0) {
      response.data = body.data;
      return response;
    }
    // 关键：40300/40900 等以 HTTP 200 到达，业务失败在此转 reject，按 code 分流
    throw new BizError(body.message, body.code, response.status);
  }
  return response;
}

function isAuthFree(url: string | undefined): boolean {
  return url !== undefined && AUTH_FREE_URLS.some((free) => url.includes(free));
}

// 单飞刷新：并发 401 共享同一个 inflight Promise；裸 axios.post 走完整路径，
// 不入 api 实例拦截器（防递归）、不带 Authorization（防旧 access 干扰）
function tryRefresh(): Promise<TokenPair | null> {
  if (!refreshConfig) return Promise.resolve(null);
  if (inflight) return inflight;
  const pair = refreshConfig.tokenReader();
  if (!pair) return Promise.resolve(null);
  inflight = axios
    .post<Envelope<TokenPair>>("/api/token/refresh/", { refresh: pair.refresh })
    .then((res) => (isEnvelope(res.data) && res.data.code === 0 ? res.data.data : null))
    .catch(() => null)
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

api.interceptors.response.use(unwrapFulfilled, async (error: unknown) => {
  const biz =
    error instanceof BizError ? error : toBizError(error as AxiosError<Envelope<unknown>>);
  const config = (error as AxiosError | undefined)?.config as
    (RetriableRequestConfig & { headers?: AxiosHeaders }) | undefined;
  const isUnauth = biz.httpStatus === 401 || biz.code === UNAUTHORIZED;
  if (isUnauth && config && !config._retriedAfterRefresh && !isAuthFree(config.url)) {
    const rotated = await tryRefresh();
    if (rotated) {
      refreshConfig?.onAccessRotated(rotated.access);
      config._retriedAfterRefresh = true;
      // 重放前手动覆盖 Authorization（请求拦截器对带标记的 config 不再注入）
      config.headers = AxiosHeaders.from(config.headers).set(
        "Authorization",
        `Bearer ${rotated.access}`,
      );
      return api.request(config);
    }
    refreshConfig?.onSessionLost();
  }
  return Promise.reject(biz);
});

export async function call<T>(config: AxiosRequestConfig): Promise<T> {
  try {
    const res = await api.request<T>(config);
    return res.data;
  } catch (err) {
    if (err instanceof BizError && shouldToast(err.code)) {
      toastHandler?.(err.message);
    }
    throw err;
  }
}

export function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return call<T>({ method: "get", url, params });
}
export function post<T>(url: string, data?: unknown): Promise<T> {
  return call<T>({ method: "post", url, data });
}
