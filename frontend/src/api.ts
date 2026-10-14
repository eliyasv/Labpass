import type { components } from "./generated/api";

type Schemas = components["schemas"];
export type Auth = Schemas["AuthView"];
export type Workshop = Schemas["WorkshopView"];
export type Booking = Schemas["BookingView"];
export type Credentials = Schemas["Login"];

const messages: Record<string, string> = {
  invalid_credentials: "That email and password do not match.",
  registration_conflict: "This email already has an account. Try signing in.",
  authentication_required: "Please sign in to continue.",
  session_expired: "Your session has expired. Please sign in again.",
  csrf_invalid: "Your session changed. Refresh the page and sign in again.",
  origin_not_allowed:
    "This address is not allowed to make changes. Use the configured LabPass address.",
  already_booked: "You already have a seat in this workshop.",
  workshop_full:
    "The last seat was just taken. Refresh to see current availability.",
  capacity_below_reservations:
    "Capacity cannot be lower than the number of reserved seats.",
  admin_required: "An administrator account is required.",
  booking_not_found: "This booking could not be found for your account.",
  workshop_not_found: "This workshop could not be found.",
  database_unavailable_retry_same_key:
    "The service is temporarily unavailable. Please try again.",
  authentication_busy: "Sign-in is busy. Please try again shortly.",
  network_error:
    "We could not confirm the response. Check your connection and try again.",
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public requestId: string | null = null,
  ) {
    super(
      messages[code] ||
        (status === 422
          ? "Check your details and try again."
          : "The request could not be completed. Please try again."),
    );
  }
  get uncertain() {
    return this.status === 0 || this.status >= 500;
  }
}

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
  auth?: Auth,
  key?: string,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && method !== "GET") headers["X-CSRF-Token"] = auth.csrf_token;
  if (key) headers["Idempotency-Key"] = key;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(15000)])
        : AbortSignal.timeout(15000),
    });
  } catch {
    throw new ApiError(0, "network_error");
  }
  const requestId = response.headers.get("X-Request-ID");
  if (response.status === 204) return undefined as T;
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      response.ok ? 0 : response.status,
      "invalid_response",
      requestId,
    );
  }
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(
      response.status,
      typeof detail === "string" ? detail : "validation_error",
      requestId,
    );
  }
  return data as T;
}

export const api = {
  me: (signal?: AbortSignal) =>
    request<Auth>("/auth/me", "GET", undefined, undefined, undefined, signal),
  register: (body: Credentials) =>
    request<Schemas["UserView"]>("/auth/register", "POST", body),
  login: (body: Credentials) => request<Auth>("/auth/login", "POST", body),
  logout: (auth: Auth) =>
    request<void>("/auth/logout", "POST", undefined, auth),
  workshops: (offset = 0, signal?: AbortSignal) =>
    request<Workshop[]>(
      `/workshops?limit=50&offset=${offset}`,
      "GET",
      undefined,
      undefined,
      undefined,
      signal,
    ),
  workshop: (id: string) => request<Workshop>(`/workshops/${id}`),
  bookings: (offset = 0, signal?: AbortSignal) =>
    request<Booking[]>(
      `/bookings?limit=50&offset=${offset}`,
      "GET",
      undefined,
      undefined,
      undefined,
      signal,
    ),
  book: (auth: Auth, workshopId: string, key: string) =>
    request<Booking>(
      "/bookings",
      "POST",
      { workshop_id: workshopId } satisfies Schemas["BookingCreate"],
      auth,
      key,
    ),
  cancel: (auth: Auth, id: string) =>
    request<Booking>(`/bookings/${id}/cancel`, "POST", undefined, auth),
  createWorkshop: (auth: Auth, title: string, capacity: number) =>
    request<Workshop>(
      "/admin/workshops",
      "POST",
      { title, capacity } satisfies Schemas["WorkshopCreate"],
      auth,
    ),
  capacity: (auth: Auth, id: string, capacity: number) =>
    request<Workshop>(
      `/admin/workshops/${id}/capacity`,
      "PATCH",
      { capacity } satisfies Schemas["CapacityUpdate"],
      auth,
    ),
};
