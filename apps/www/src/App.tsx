import { useEffect, useState, type ComponentType } from 'react';
import { Link, useLocation } from '@shared/router';
import { APPLY_URL, BOARD_URL, PORTAL_URL } from '@shared/urls';
import { siteImage, useSite } from './site';
import { AboutPage } from './pages/AboutPage';
import { CalendarPage } from './pages/CalendarPage';
import { ContactPage } from './pages/ContactPage';
import { HomePage } from './pages/HomePage';
import { MatchesPage } from './pages/MatchesPage';
import { MembershipPage } from './pages/MembershipPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RulesPage } from './pages/RulesPage';

const NAV = [
  { to: '/', label: 'Home' },
  { to: '/matches', label: 'Matches' },
  { to: '/calendar', label: 'Calendar' },
  { to: '/about', label: 'About' },
  { to: '/rules', label: 'Rules' },
  { to: '/membership', label: 'Membership' },
  { to: '/contact', label: 'Contact' },
];

const PAGES: Record<string, ComponentType> = {
  '/': HomePage,
  '/matches': MatchesPage,
  '/calendar': CalendarPage,
  '/about': AboutPage,
  '/rules': RulesPage,
  '/membership': MembershipPage,
  '/contact': ContactPage,
};

export function App() {
  const { path } = useLocation();
  const { site } = useSite();
  const [menuOpen, setMenuOpen] = useState(false);
  const Page = PAGES[path] ?? NotFoundPage;
  const logo = siteImage(site, 'logo');

  useEffect(() => setMenuOpen(false), [path]);

  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="site-header">
        <div className="container topbar">
          <Link to="/" className="brand" aria-label={`${site.site_title} home`}>
            {logo && <img className="brand-mark" src={logo} alt="" height={56} />}
            <span>
              <span className="brand-title">{site.site_title}</span>
              <span className="brand-subtitle">{site.site_subtitle}</span>
            </span>
          </Link>
          <button type="button" className="btn btn-sm nav-toggle" aria-expanded={menuOpen} aria-controls="main-nav"
            onClick={() => setMenuOpen((open) => !open)}>
            {menuOpen ? 'Close menu' : 'Menu'}
          </button>
          <nav id="main-nav" className={`nav ${menuOpen ? 'open' : ''}`} aria-label="Main navigation">
            {NAV.map((item) => (
              <Link key={item.to} to={item.to} aria-current={path === item.to ? 'page' : undefined}>{item.label}</Link>
            ))}
            <a href={PORTAL_URL}>Member login</a>
            <a className="btn btn-primary btn-sm nav-cta" href={APPLY_URL}>Renew or apply</a>
          </nav>
        </div>
      </header>

      <main id="main" className="container site-main" tabIndex={-1}>
        <Page />
      </main>

      <Footer />
    </>
  );
}

function Footer() {
  const { site } = useSite();
  const social = Object.entries(site.social).filter(([, url]) => url) as [string, string][];
  return (
    <footer className="site-footer">
      <div className="container footer-grid">
        <div>
          <p className="footer-title">{site.site_title}</p>
          {site.mailing_address && <p className="muted" style={{ whiteSpace: 'pre-line' }}>{site.mailing_address}</p>}
        </div>
        <div>
          {site.contact_email && <p><a href={`mailto:${site.contact_email}`}>{site.contact_email}</a></p>}
          {site.contact_phone && <p><a href={`tel:${site.contact_phone.replace(/[^\d+]/g, '')}`}>{site.contact_phone}</a></p>}
          {social.length > 0 && (
            <p className="row">
              {social.map(([name, url]) => <a key={name} href={url} rel="noopener noreferrer">{name[0].toUpperCase() + name.slice(1)}</a>)}
            </p>
          )}
        </div>
        <nav aria-label="Footer">
          <ul className="footer-links">
            {site.footer_links.map((link) => <li key={link.url}><a href={link.url}>{link.label}</a></li>)}
            <li><a href={PORTAL_URL}>Member portal</a></li>
            <li><a href={BOARD_URL}>Board login</a></li>
          </ul>
        </nav>
      </div>
      <p className="container small muted">© {new Date().getFullYear()} {site.site_title}. Members and guests only.</p>
    </footer>
  );
}
