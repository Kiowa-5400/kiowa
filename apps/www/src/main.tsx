import React from 'react';
import ReactDOM from 'react-dom/client';
import clubLogo from '../assets/kiowa-gun.avif';
import clubHeroImage from '../assets/kiowa-hero.avif';
import './styles.css';
import { AboutPage } from './pages/AboutPage';
import { CalendarPage } from './pages/CalendarPage';
import { ContactPage } from './pages/ContactPage';
import { MatchesPage } from './pages/MatchesPage';

function App() {
  const heroBackground = `linear-gradient(180deg, rgba(19, 29, 24, 0.18), rgba(19, 29, 24, 0.46)), url(${clubHeroImage})`;

  return (
    <main className="page-shell">
      <header className="topbar">
        <div className="brand-block">
          <img className="brand-mark" src={clubLogo} alt="Kiowa Gun Club logo" />
          <p className="eyebrow">Great Bend, Kansas</p>
          <h1>Kiowa Gun Club</h1>
        </div>
        <nav className="nav" aria-label="Main navigation">
          <a href="https://apply.kiowagunclub.org">Apply</a>
          <a href="https://board.kiowagunclub.org">Board</a>
          <a href="https://www.kiowagunclub.org/rules">Rules</a>
        </nav>
      </header>

      {page ? <section className="content-page">{page}</section> : <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow light">Local. Safe. Welcoming.</p>
          <h2>Built for neighbors, families, and responsible shooters.</h2>
          <p>
            A community range rooted in the heart of Kansas—where safety, tradition, and good company still matter.
          </p>
        </div>

        <div className="hero-side" aria-label="Club highlights and imagery">
          <div
            className="hero-image hero-image-main"
            role="img"
            aria-label="Kiowa Gun Club range and local community"
            style={{ backgroundImage: heroBackground }}
          >
            <span className="image-label">Member-owned range</span>
          </div>

          <div className="hero-panel">
            <div>
              <span>Range Access</span>
              <strong>Member-first</strong>
            </div>
            <div>
              <span>Club Life</span>
              <strong>Friendly & familiar</strong>
            </div>
            <div>
              <span>Safety</span>
              <strong>Always priority</strong>
            </div>
          </div>
        </div>
      </section>

      {!page && <div className="info-strip" aria-label="Club quick facts">
        <span>Membership renewals</span>
        <span>Range events</span>
        <span>Responsible shooting</span>
        <span>Community standards</span>
      </div>

      <section className="cards">
        <article className="card">
          <h3>Membership</h3>
          <p>Renew your membership online and keep your personal details current for the next season.</p>
        </article>
        <article className="card">
          <h3>Range Events</h3>
          <p>Join the regular pistol shoots and informal club gatherings that keep the community connected.</p>
        </article>
        <article className="card">
          <h3>Club Standards</h3>
          <p>Everyone is welcome to a safe, respectful range experience with clear expectations and support.</p>
        </article>
      </section>

      <div className="cta-group">
        <a className="primary-button" href="https://apply.kiowagunclub.org">Renew or apply</a>
        <a className="secondary-button" href="https://board.kiowagunclub.org">Board login</a>
      </div>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
