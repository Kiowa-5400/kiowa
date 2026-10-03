/**
 * Fetch wrapper shared by the three apps.
 *
 * Sessions are HttpOnly cookies set by the API, so every request is sent with
 * credentials. State-changing requests carry the CSRF token the API returned
 * with the session; it is kept in memory only.
 */

export const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? 'https://app.kiowagunclub.org' : 'http://localhost:8000')
).replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  errors: Record<string, string>;
  code?: string;

  constructor(status: number, message: string, errors: Record<string, string> = {}, code?: string) {
    super(message);
    this.status = status;
    this.errors = errors;
    this.code = code;
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

type Listener = (error: ApiError) => void;
const unauthorizedListeners = new Set<Listener>();

/** Called when the API answers 401, so the app can return to its sign-in screen. */
export function onUnauthorized(listener: Listener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null | string[]>;
  signal?: AbortSignal;
  /** Don't notify unauthorized listeners (used by session probes and login forms). */
  quiet401?: boolean;
};

export function apiUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(path.startsWith('http') ? path : `${API_BASE_URL}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v));
    else url.searchParams.set(key, String(value));
  }
  return url.toString();
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? (options.body !== undefined ? 'POST' : 'GET');
  const headers = new Headers();
  let body: BodyInit | undefined;
  if (options.body instanceof FormData) {
    body = options.body;
  } else if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(options.body);
  }
  if (method !== 'GET' && csrfToken) headers.set('X-CSRF-Token', csrfToken);

  let response: Response;
  try {
    response = await fetch(apiUrl(path, options.query), { method, headers, body, credentials: 'include', signal: options.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, "We couldn't reach the club's server. Check your connection and try again.");
  }

  const isJson = response.headers.get('content-type')?.includes('application/json');
  const payload = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const message = (payload && typeof payload.detail === 'string' && payload.detail) || `Request failed (${response.status}).`;
    const error = new ApiError(response.status, message, payload?.errors ?? {}, payload?.code);
    if (response.status === 401 && !options.quiet401) unauthorizedListeners.forEach((listener) => listener(error));
    throw error;
  }
  if (payload && typeof payload === 'object' && 'csrf_token' in payload && typeof payload.csrf_token === 'string') {
    setCsrfToken(payload.csrf_token);
  }
  return (payload ?? undefined) as T;
}

/** Downloads a file from an authenticated endpoint (cookies included). */
export async function downloadFile(path: string, query?: RequestOptions['query']): Promise<void> {
  const response = await fetch(apiUrl(path, query), { credentials: 'include' });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(response.status, payload?.detail || 'Download failed.');
  }
  const disposition = response.headers.get('content-disposition') ?? '';
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? 'download';
  const url = URL.createObjectURL(await response.blob());
  const link = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return 'Something went wrong.';
}

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

