/**
 * Where each member-facing site lives. The member portal (sign-in, account,
 * application status, payment) and the application form are separate apps
 * on separate subdomains, so links between them are full URLs.
 */

const trim = (url: string) => url.replace(/\/+$/, '');

export const WWW_URL: string = trim(import.meta.env.VITE_WWW_URL || 'http://localhost:4173');
export const PORTAL_URL: string = trim(import.meta.env.VITE_PORTAL_APP_URL || 'http://localhost:5174');
export const APPLY_URL: string = trim(import.meta.env.VITE_APPLY_APP_URL || 'http://localhost:5173');

/** Application form link, e.g. applyUrl({ type: 'renewal' }). */
export function applyUrl(params: Record<string, string | number> = {}): string {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
  return `${APPLY_URL}/${query ? `?${query}` : ''}`;
}

/** Portal sign-in page that returns to `next` (a full URL on one of the member apps) afterwards. */
export function portalLoginUrl(next?: string): string {
  return `${PORTAL_URL}/login${next ? `?next=${encodeURIComponent(next)}` : ''}`;
}

/**
 * Turns a `next` value from the sign-in page into somewhere safe to go:
 * a same-app path, or a full URL on the portal or application site. Anything
 * else (another host, protocol-relative "//evil", javascript:) is dropped.
 */
export function safeNext(next: string | null | undefined): { path: string } | { href: string } | null {
  if (!next) return null;
  if (next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\')) return { path: next };
  try {
    const url = new URL(next);
    if ([new URL(PORTAL_URL).origin, new URL(APPLY_URL).origin].includes(url.origin)) return { href: url.href };
  } catch {
    // Not a URL.
  }
  return null;
}
