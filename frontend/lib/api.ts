// Thin fetch wrapper for the FastAPI backend, reached through the /api rewrite in next.config.ts.

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown,
  ) {
    super(`API error ${status}`);
  }

  /** Stable machine code from `{"detail": {"code": ...}}` error bodies, if any. */
  get code(): string | undefined {
    const detail = (this.detail as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      return String((detail as { code: unknown }).code);
    }
    return undefined;
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.detail as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
    if (Array.isArray(detail) && detail.length > 0) {
      // FastAPI validation errors: [{loc, msg}, ...]
      return detail
        .map((d: { loc?: unknown[]; msg?: string }) =>
          [d.loc?.slice(1).join("."), d.msg].filter(Boolean).join(": "),
        )
        .join("; ");
    }
    if (typeof detail === "string") return detail;
    return `Request failed (${error.status}).`;
  }
  return "Something went wrong. Is the backend running?";
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const isForm = init.body instanceof FormData;
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    headers: isForm
      ? init.headers
      : { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type User = {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  timezone: string;
};

export type Session = { token: string; user: User };
