import { api } from '@shared/api';
import { usePageTitle } from '@shared/router';
import { ErrorState, Loading, useAsync } from '@shared/ui';
import { CustomSections, PageIntro, SectionCard } from '../components/Sections';
import { section, siteImage, usePage, useSite } from '../site';

type Rules = { version: string; rules: string[]; agreement_clause: string; reporting_clause: string };

export function RulesPage() {
  usePageTitle('Range Rules');
  const { site } = useSite();
  const page = usePage('rules');
  const rules = useAsync((signal) => api<Rules>('/api/public/rules', { signal }), []);
  const photo = site.images.rules ? siteImage(site, 'rules') : null;

  if (page.loading || rules.loading) return <Loading />;
  if (page.error || rules.error) return <ErrorState message={page.error ?? rules.error ?? ''} onRetry={() => { page.reload(); rules.reload(); }} />;

  return (
    <>
      <PageIntro section={section(page.data, 'intro')} kicker="Safety first" />
      <div className="rules-layout">
        <article className="card">
          <ol className="rules-list">
            {rules.data?.rules.map((rule) => <li key={rule}>{rule}</li>)}
          </ol>
          {rules.data?.reporting_clause && <p className="muted">{rules.data.reporting_clause}</p>}
          <p className="small muted">Rules version {rules.data?.version}</p>
        </article>
        {photo && <img className="page-photo" src={photo} alt={site.image_alt.rules ?? 'Range rules sign'} />}
      </div>
      <div style={{ marginTop: '1rem' }}>
        <SectionCard section={section(page.data, 'dues_policy')} kicker="Membership" />
      </div>
      <CustomSections sections={page.data} />
    </>
  );
}
