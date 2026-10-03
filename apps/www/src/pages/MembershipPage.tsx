import { api } from '@shared/api';
import { formatBytes, formatMoney } from '@shared/format';
import { Link, usePageTitle } from '@shared/router';
import { ErrorState, Loading, useAsync } from '@shared/ui';
import { CustomSections, SectionCard } from '../components/Sections';
import { section, usePage, useSite } from '../site';

type PublicDocument = { id: number; title: string; description: string | null; url: string; mime_type: string; size_bytes: number };

export function MembershipPage() {
  usePageTitle('Membership');
  const { site } = useSite();
  const page = usePage('membership');
  const documents = useAsync((signal) => api<PublicDocument[]>('/api/public/documents', { signal }), []);

  if (page.loading) return <Loading />;
  if (page.error) return <ErrorState message={page.error} onRetry={page.reload} />;

  return (
    <>
      <header className="page-hero">
        <p className="kicker">Join or renew</p>
        <h1>Membership</h1>
        <p className="lead">Annual dues are {formatMoney(site.dues_amount)}. Renew your membership or apply for the waiting list online — upload your documents from a phone or computer.</p>
        <div className="row">
          <a className="btn btn-primary" href={`${site.apply_url}/?type=renewal`}>Renew my membership</a>
          {site.accepting_waiting_list && <a className="btn" href={`${site.apply_url}/?type=waiting_list`}>Apply for the waiting list</a>}
          <a className="btn btn-ghost" href={`${site.portal_url}/login`}>Member login</a>
        </div>
      </header>

      <div className="grid-2">
        <SectionCard section={section(page.data, 'terms')} kicker="Dues & requirements" />
        <SectionCard section={section(page.data, 'background_check')} kicker="New members" />
      </div>

      <div className="grid-2" style={{ marginTop: '1rem' }}>
        <article className="card">
          <p className="kicker">Before you apply</p>
          <h2>What you'll need</h2>
          <ul>
            <li>A photo of your current National Rifle Association (NRA) membership card, or the mailing label from an NRA magazine.</li>
            <li>New members: your background check cover page, or a concealed carry license from any state.</li>
            <li>Renewing members claiming the discount: your range cleanup-day discount card.</li>
            <li>A few minutes to read and sign the <Link to="/rules">Range Rules</Link>.</li>
          </ul>
        </article>
        <article className="card">
          <p className="kicker">Forms</p>
          <h2>Downloads</h2>
          {documents.loading && <Loading />}
          {documents.error && <p className="muted">Downloads are unavailable right now.</p>}
          {documents.data && documents.data.length === 0 && <p className="muted">No forms are posted right now.</p>}
          <ul className="doc-list">
            {documents.data?.map((doc) => (
              <li key={doc.id}>
                <a href={doc.url} rel="noopener">{doc.title}</a>{' '}
                <span className="small muted">({doc.mime_type === 'application/pdf' ? 'PDF' : 'Image'}, {formatBytes(doc.size_bytes)})</span>
                {doc.description && <div className="small muted">{doc.description}</div>}
              </li>
            ))}
          </ul>
        </article>
      </div>
      <CustomSections sections={page.data} />
    </>
  );
}
