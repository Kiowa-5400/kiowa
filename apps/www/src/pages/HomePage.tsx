import { Link, usePageTitle } from '@shared/router';
import { ErrorState, Html, Loading } from '@shared/ui';
import { CustomSections, SectionCard } from '../components/Sections';
import { section, siteImage, usePage, useSite } from '../site';

export function HomePage() {
  usePageTitle('');
  const { site } = useSite();
  const page = usePage('home');
  const hero = section(page.data, 'hero');
  const heroImage = siteImage(site, 'hero');

  return (
    <>
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="kicker">Local. Safe. Welcoming.</p>
          <h1 id="hero-title">{hero?.heading ?? site.site_title}</h1>
          {hero && <Html html={hero.body_html} className="prose hero-lead" />}
          <div className="row" style={{ marginTop: '1.25rem' }}>
            <a className="btn btn-primary" href={`${site.apply_url}/apply`}>Renew or apply</a>
            <Link className="btn" to="/calendar">View the calendar</Link>
          </div>
        </div>
        <div className="hero-side">
          {heroImage && (
            <img className="hero-image" src={heroImage} alt={site.image_alt.hero ?? 'The Kiowa Gun Club range'} />
          )}
          <dl className="hero-panel">
            <div><dt>Range access</dt><dd>Member-first</dd></div>
            <div><dt>Club life</dt><dd>Friendly &amp; familiar</dd></div>
            <div><dt>Safety</dt><dd>Always the priority</dd></div>
          </dl>
        </div>
      </section>

      {page.loading && <Loading />}
      {page.error && <ErrorState message="We couldn't load the latest club news. Please try again shortly." onRetry={page.reload} />}

      {page.data && (
        <>
          <div className="grid-2" style={{ marginTop: '1.5rem' }}>
            <SectionCard section={section(page.data, 'welcome')} kicker="Welcome" />
            <SectionCard section={section(page.data, 'notice')} kicker="Membership" className="card card-accent" />
          </div>
          <div className="grid-2" style={{ marginTop: '1rem' }}>
            <article className="card">
              <SectionCard section={section(page.data, 'matches_teaser')} kicker="Matches" className="" />
              <p><Link to="/matches">View the full match schedule →</Link></p>
            </article>
            <article className="card">
              <SectionCard section={section(page.data, 'safety')} kicker="Safety" className="" />
              <p><Link to="/rules">Read the full range rules →</Link></p>
            </article>
          </div>
          <CustomSections sections={page.data} />
        </>
      )}
    </>
  );
}
