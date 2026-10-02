import { usePageTitle } from '@shared/router';
import { ErrorState, Loading } from '@shared/ui';
import { CustomSections, PageIntro, SectionCard } from '../components/Sections';
import { section, siteImage, usePage, useSite } from '../site';

export function AboutPage() {
  usePageTitle('About');
  const { site } = useSite();
  const page = usePage('about');
  const photo = siteImage(site, 'about');

  if (page.loading) return <Loading />;
  if (page.error) return <ErrorState message={page.error} onRetry={page.reload} />;

  return (
    <>
      <PageIntro section={section(page.data, 'intro')} kicker="Club information" />
      <div className="grid-2">
        <SectionCard section={section(page.data, 'club')} kicker="The club" />
        <SectionCard section={section(page.data, 'activities')} kicker="Range activities" />
      </div>
      <div className="grid-2" style={{ marginTop: '1rem' }}>
        <SectionCard section={section(page.data, 'officers')} kicker="Leadership" />
        <article className="card">
          <p className="kicker">Location</p>
          <h2>Find the range</h2>
          {site.physical_address && <p style={{ whiteSpace: 'pre-line' }}>{site.physical_address}</p>}
          {site.map_url && <a className="btn" href={site.map_url} rel="noopener noreferrer">Get directions</a>}
        </article>
      </div>
      {photo && site.images.about && (
        <img className="page-photo" src={photo} alt={site.image_alt.about ?? 'Kiowa Gun Club'} />
      )}
      <CustomSections sections={page.data} />
    </>
  );
}
