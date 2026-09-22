import axios, { AxiosError, type AxiosRequestConfig } from "axios";
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

let toastHandler: ToastHandler | null = null;
let tokenProvider: TokenProvider | null = null;

export function setToastHandler(handler: ToastHandler | null): void {
  toastHandler = handler;
}
export function setTokenProvider(provider: TokenProvider | null): void {
  tokenProvider = provider;
}
export function resetClientState(): void {
  toastHandler = null;
  tokenProvider = null;
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

api.interceptors.request.use((config) => {
  // 显式序列化 params 进 URL：保证任何观察者（devtools/proxy/mock）都能看到完整查询串
  if (config.params && typeof config.params === "object") {
    const query = toQuery(config.params as Record<string, unknown>);
    config.url = `${config.url ?? ""}${query ? `?${query}` : ""}`;
    delete config.params;
  }
  const token = tokenProvider?.();
  if (token) {
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

api.interceptors.response.use(
  (response) => {
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
  },
  (error: unknown) => {
    if (error instanceof BizError) return Promise.reject(error);
    return Promise.reject(toBizError(error as AxiosError<Envelope<unknown>>));
  },
);

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
