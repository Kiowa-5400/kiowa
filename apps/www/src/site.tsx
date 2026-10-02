import { createContext, useContext, type ReactNode } from 'react';
import { api } from '@shared/api';
import { useAsync, type AsyncState } from '@shared/ui';
import defaultLogo from '../assets/kiowa-gun.avif';
import defaultHero from '../assets/kiowa-hero.avif';

export type Site = {
  site_title: string;
  site_subtitle: string;
  contact_email: string | null;
  contact_phone: string | null;
  mailing_address: string | null;
  physical_address: string | null;
  map_url: string | null;
  social: Record<'facebook' | 'instagram' | 'youtube', string | null>;
  footer_links: { label: string; url: string }[];
  dues_amount: string;
  accepting_waiting_list: boolean;
  background_check_url: string | null;
  images: Record<string, string | null>;
  image_alt: Record<string, string | null>;
  apply_url: string;
  rules_version: string;
};

export type Section = {
  id: number;
  section_key: string;
  label: string | null;
  heading: string | null;
  body_html: string;
  is_custom: boolean;
};

const FALLBACK: Site = {
  site_title: 'Kiowa Gun Club',
  site_subtitle: 'Great Bend, Kansas',
  contact_email: null,
  contact_phone: null,
  mailing_address: null,
  physical_address: null,
  map_url: null,
  social: { facebook: null, instagram: null, youtube: null },
  footer_links: [],
  dues_amount: '150.00',
  accepting_waiting_list: true,
  background_check_url: null,
  images: {},
  image_alt: {},
  apply_url: import.meta.env.VITE_APPLY_APP_URL || 'http://localhost:5173',
  rules_version: '',
};

const DEFAULT_IMAGES: Record<string, string> = { logo: defaultLogo, hero: defaultHero };

const SiteContext = createContext<{ site: Site; state: AsyncState<Site> } | null>(null);

export function SiteProvider({ children }: { children: ReactNode }) {
  const state = useAsync((signal) => api<Site>('/api/public/site', { signal }), []);
  // If the API is unreachable the layout still renders with safe defaults.
  return <SiteContext.Provider value={{ site: state.data ?? FALLBACK, state }}>{children}</SiteContext.Provider>;
}

export function useSite() {
  const value = useContext(SiteContext);
  if (!value) throw new Error('useSite must be used inside SiteProvider');
  return value;
}

/** Board-uploaded image for a slot, falling back to the bundled original. */
export function siteImage(site: Site, key: string): string | null {
  return site.images[key] ?? DEFAULT_IMAGES[key] ?? null;
}

export function usePage(slug: string): AsyncState<Section[]> {
  return useAsync((signal) => api<Section[]>(`/api/public/pages/${slug}`, { signal }), [slug]);
}

export function section(sections: Section[] | undefined, key: string): Section | undefined {
  return sections?.find((s) => s.section_key === key);
}

export const BOARD_APP_URL: string = import.meta.env.VITE_BOARD_APP_URL || 'http://localhost:4174';
