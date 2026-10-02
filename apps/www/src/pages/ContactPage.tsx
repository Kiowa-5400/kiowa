import { usePageTitle } from '@shared/router';
import { ErrorState, Loading } from '@shared/ui';
import { CustomSections, PageIntro, SectionCard } from '../components/Sections';
import { section, usePage, useSite } from '../site';

export function ContactPage() {
  usePageTitle('Contact');
  const { site } = useSite();
  const page = usePage('contact');

  if (page.loading) return <Loading />;
  if (page.error) return <ErrorState message={page.error} onRetry={page.reload} />;

  return (
    <>
      <PageIntro section={section(page.data, 'intro')} kicker="Get in touch" />
      <div className="grid-3">
        {site.mailing_address && (
          <article className="card">
            <p className="kicker">Mailing address</p>
            <h2>{site.site_title}</h2>
            <p style={{ whiteSpace: 'pre-line' }}>{site.mailing_address}</p>
          </article>
        )}
        {site.physical_address && (
          <article className="card">
            <p className="kicker">Range location</p>
            <h2>Visit the club</h2>
            <p style={{ whiteSpace: 'pre-line' }}>{site.physical_address}</p>
            {site.map_url && <a className="btn" href={site.map_url} rel="noopener noreferrer">Open map</a>}
          </article>
        )}
        <article className="card">
          <p className="kicker">Email &amp; phone</p>
          <h2>Club contact</h2>
          {site.contact_email && <p><a href={`mailto:${site.contact_email}`}>{site.contact_email}</a></p>}
          {site.contact_phone && <p><a href={`tel:${site.contact_phone.replace(/[^\d+]/g, '')}`}>{site.contact_phone}</a></p>}
          <p className="muted">For match-day questions, membership questions, and general club information.</p>
        </article>
      </div>
      <div style={{ marginTop: '1rem' }}>
        <SectionCard section={section(page.data, 'membership_contacts')} kicker="Membership" />
      </div>
      <CustomSections sections={page.data} />
    </>
  );
}
