/**
 * Fetch wrapper.
 *
 * Every request sends the session cookie (`credentials: "include"`) and every
 * failure arrives as an ApiError carrying the backend's own message - those
 * messages are written to be shown to a person, so the UI displays them
 * verbatim rather than replacing them with "Something went wrong".
 */

import type {
  BalanceReport,
  CategoryTotal,
  DashboardSummary,
  DocumentDetail,
  DocumentPage,
  DocumentUpdate,
  ExchangeRate,
  Settlement,
  SystemStatus,
  UUID,
  UploadResult,
  User,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(status: number, message: string, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  /** 409 from a money endpoint means an exchange rate is missing. */
  get isMissingRate(): boolean {
    return this.status === 409 && typeof this.payload === "object"
      && this.payload !== null && "missing_rate_for" in this.payload;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init.headers,
    },
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload: unknown = text ? safeParse(text) : null;

  if (!response.ok) {
    throw new ApiError(response.status, extractMessage(payload, response), payload);
  }
  return payload as T;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function extractMessage(payload: unknown, response: Response): string {
  if (typeof payload === "string" && payload) return payload;
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors arrive as a list of field problems.
    if (Array.isArray(detail)) {
      const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
      if (first?.msg) {
        const field = Array.isArray(first.loc) ? first.loc.at(-1) : undefined;
        return field ? `${String(field)}: ${first.msg}` : first.msg;
      }
    }
  }
  return `Request failed (${response.status})`;
}

export const api = {
  // --- auth ---------------------------------------------------------------
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  me: () => request<User>("/api/auth/me"),

  changePassword: (current_password: string, new_password: string) =>
    request<void>("/api/auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  // --- users --------------------------------------------------------------
  users: () => request<User[]>("/api/users"),

  createUser: (body: {
    email: string;
    password: string;
    display_name: string;
    is_admin?: boolean;
    equity_share?: string;
  }) => request<User>("/api/users", { method: "POST", body: JSON.stringify(body) }),

  updateUser: (id: UUID, body: Partial<Pick<User, "display_name" | "is_active" | "is_admin">> & { equity_share?: string }) =>
    request<User>(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),

  // --- documents ----------------------------------------------------------
  documents: (query?: Query) =>
    request<DocumentPage>(buildUrl("/api/documents", query)),

  document: (id: UUID) => request<DocumentDetail>(`/api/documents/${id}`),

  upload: (form: FormData) =>
    request<UploadResult>("/api/documents", { method: "POST", body: form }),

  updateDocument: (id: UUID, body: DocumentUpdate) =>
    request<DocumentDetail>(`/api/documents/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  rescan: (id: UUID) =>
    request<DocumentDetail>(`/api/documents/${id}/rescan`, { method: "POST" }),

  deleteDocument: (id: UUID) =>
    request<void>(`/api/documents/${id}`, { method: "DELETE" }),

  imageUrl: (id: UUID) => `/api/documents/${id}/image`,
  thumbUrl: (id: UUID) => `/api/documents/${id}/thumbnail`,

  // --- reports ------------------------------------------------------------
  balance: (query?: Query) =>
    request<BalanceReport>(buildUrl("/api/reports/balance", query)),

  dashboard: () => request<DashboardSummary>("/api/reports/dashboard"),

  categories: (query?: Query) =>
    request<CategoryTotal[]>(buildUrl("/api/reports/categories", query)),

  // --- settlements --------------------------------------------------------
  settlements: () => request<Settlement[]>("/api/settlements"),

  createSettlement: (body: {
    from_user_id: UUID;
    to_user_id: UUID;
    amount_base: string;
    settled_on: string;
    note?: string;
  }) => request<Settlement>("/api/settlements", { method: "POST", body: JSON.stringify(body) }),

  deleteSettlement: (id: UUID) =>
    request<void>(`/api/settlements/${id}`, { method: "DELETE" }),

  // --- rates --------------------------------------------------------------
  rates: () => request<ExchangeRate[]>("/api/rates"),

  currentRates: () => request<Record<string, string | null>>("/api/rates/current"),

  currencies: () => request<string[]>("/api/rates/currencies"),

  saveRate: (body: {
    currency: string;
    rate_to_base: string;
    effective_from: string;
    note?: string;
  }) => request<ExchangeRate>("/api/rates", { method: "POST", body: JSON.stringify(body) }),

  deleteRate: (id: UUID) => request<void>(`/api/rates/${id}`, { method: "DELETE" }),

  revalue: () =>
    request<{ examined: number; revalued: number }>("/api/rates/revalue", {
      method: "POST",
    }),

  // --- system -------------------------------------------------------------
  systemStatus: () => request<SystemStatus>("/api/system/status"),
};
