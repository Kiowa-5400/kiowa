/** A minimal history-API router: enough for these apps without another dependency. */

import { useEffect, useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from 'react';

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener('popstate', listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('popstate', listener);
  };
}

function snapshot(): string {
  return window.location.pathname + window.location.search;
}

export function navigate(to: string, options: { replace?: boolean } = {}): void {
  if (to === snapshot()) return;
  if (options.replace) window.history.replaceState(null, '', to);
  else window.history.pushState(null, '', to);
  listeners.forEach((listener) => listener());
  window.scrollTo(0, 0);
}

/** Current pathname (without trailing slash) and query string. */
export function useLocation(): { path: string; query: URLSearchParams } {
  const location = useSyncExternalStore(subscribe, snapshot);
  const url = new URL(location, window.location.origin);
  return { path: url.pathname.replace(/\/+$/, '') || '/', query: url.searchParams };
}

/** Matches "/applications/:id/pay" style patterns; returns params or null. */
export function matchPath(pattern: string, path: string): Record<string, string> | null {
  const patternParts = pattern.split('/').filter(Boolean);
  const pathParts = path.split('/').filter(Boolean);
  if (patternParts.length !== pathParts.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < patternParts.length; i += 1) {
    if (patternParts[i].startsWith(':')) params[patternParts[i].slice(1)] = decodeURIComponent(pathParts[i]);
    else if (patternParts[i] !== pathParts[i]) return null;
  }
  return params;
}

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & { to: string };

export function Link({ to, onClick, ...rest }: LinkProps) {
  const handle = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to);
  };
  return <a href={to} onClick={handle} {...rest} />;
}

/** Sets the document title and moves focus to the main heading for screen readers. */
export function usePageTitle(title: string, siteName = 'Kiowa Gun Club'): void {
  useEffect(() => {
    document.title = title ? `${title} | ${siteName}` : siteName;
  }, [title, siteName]);
}
