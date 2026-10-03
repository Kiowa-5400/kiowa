/**
 * Where each of the club's sites lives. A VITE_* variable overrides the
 * address; otherwise production builds use the real subdomains and the dev
 * server uses the local ports from the root package.json.
 */

const trim = (url: string) => url.replace(/\/+$/, '');
const PROD = import.meta.env.PROD;

export const WWW_URL: string = trim(import.meta.env.VITE_WWW_URL || (PROD ? 'https://kiowagunclub.org' : 'http://localhost:4173'));
export const PORTAL_URL: string = trim(import.meta.env.VITE_PORTAL_APP_URL || (PROD ? 'https://portal.kiowagunclub.org' : 'http://localhost:5174'));
export const APPLY_URL: string = trim(import.meta.env.VITE_APPLY_APP_URL || (PROD ? 'https://apply.kiowagunclub.org' : 'http://localhost:5173'));
export const BOARD_URL: string = trim(import.meta.env.VITE_BOARD_APP_URL || (PROD ? 'https://board.kiowagunclub.org' : 'http://localhost:4174'));

/** Application form link, e.g. applyUrl({ type: 'renewal' }). */
export function applyUrl(params: Record<string, string | number> = {}): string {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
  return `${APPLY_URL}/${query ? `?${query}` : ''}`;
}
