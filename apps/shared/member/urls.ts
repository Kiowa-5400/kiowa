/**
 * Links between the member portal (sign-in, account, application status,
 * payment) and the application form, which are separate apps on separate
 * subdomains. The addresses themselves live in apps/shared/urls.ts.
 */

import { APPLY_URL, PORTAL_URL } from '../urls';

export { APPLY_URL, PORTAL_URL, WWW_URL, applyUrl } from '../urls';

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
