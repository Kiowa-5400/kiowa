import { useState } from 'react';
import { api } from '@shared/api';
import { formatClock, formatDate } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Empty, ErrorState, Loading, Modal, useAsync } from '@shared/ui';
import { CustomSections, PageIntro, SectionCard } from '../components/Sections';
import { section, usePage, useSite } from '../site';

type Photo = { id: number; url: string; caption: string | null };
type Match = { id: number; discipline: string; event_date: string; start_time: string | null; notes: string | null; results_url: string | null; photos: Photo[] };
type MatchesResponse = { disciplines: { discipline: string; matches: Match[] }[]; years: number[] };

export function MatchesPage() {
  usePageTitle('Matches');
  const { site } = useSite();
  const page = usePage('matches');
  const [year, setYear] = useState<number | null>(null);
  const matches = useAsync((signal) => api<MatchesResponse>('/api/public/matches', { signal, query: { year: year ?? undefined } }), [year]);
  const [gallery, setGallery] = useState<Match | null>(null);
  const flyer = site.images.matches_flyer;

  return (
    <>
      <PageIntro section={section(page.data, 'intro')} kicker="Competition" />

      <div className="row-between" style={{ marginBottom: '1rem' }}>
        <SectionCard section={section(page.data, 'participation')} kicker="Everyone welcome" className="card participation" />
        {flyer && <a href={flyer} className="flyer"><img src={flyer} alt={site.image_alt.matches_flyer ?? 'Match flyer'} /></a>}
      </div>

      {matches.data && matches.data.years.length > 1 && (
        <div className="field" style={{ maxWidth: 220, marginBottom: '1rem' }}>
          <label htmlFor="match-year">Season</label>
          <select id="match-year" value={year ?? ''} onChange={(e) => setYear(e.target.value ? Number(e.target.value) : null)}>
            <option value="">All seasons</option>
            {matches.data.years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      )}

      {matches.loading && <Loading label="Loading matches…" />}
      {matches.error && <ErrorState message="The match schedule couldn't be loaded right now." onRetry={matches.reload} />}
      {matches.data && matches.data.disciplines.length === 0 && <Empty>No matches are scheduled yet. Check back soon.</Empty>}

      <div className="stack">
        {matches.data?.disciplines.map(({ discipline, matches: rows }, index) => (
          <section key={discipline} className="card" aria-labelledby={`discipline-${index}`}>
            <h2 id={`discipline-${index}`}>{discipline}</h2>
            <div className="table-wrap">
              <table className="table-stack">
                <thead><tr><th scope="col">Date</th><th scope="col">Start</th><th scope="col">Notes</th><th scope="col">Photos</th></tr></thead>
                <tbody>
                  {rows.map((match) => (
                    <tr key={match.id}>
                      <td data-label="Date">
                        <strong>{formatDate(match.event_date, 'medium')}</strong>
                        <br />
                        {match.results_url
                          ? <a href={match.results_url} rel="noopener noreferrer" aria-label={`View results for ${formatDate(match.event_date, 'medium')} on PractiScore`}>View results</a>
                          : <span className="small muted">(results not yet posted)</span>}
                      </td>
                      <td data-label="Start">{formatClock(match.start_time) || '—'}</td>
                      <td data-label="Notes">{match.notes ?? ''}</td>
                      <td data-label="Photos">
                        {match.photos.length > 0
                          ? <button type="button" className="btn btn-sm" onClick={() => setGallery(match)}>View {match.photos.length} photo{match.photos.length === 1 ? '' : 's'}</button>
                          : <span className="muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>

      <Modal open={gallery !== null} title={gallery ? `${gallery.discipline} — ${formatDate(gallery.event_date, 'medium')}` : ''} onClose={() => setGallery(null)}>
        <div className="gallery">
          {gallery?.photos.map((photo) => (
            <figure key={photo.id}>
              <img src={photo.url} alt={photo.caption ?? `Match photo from ${gallery.event_date}`} loading="lazy" />
              {photo.caption && <figcaption className="small muted">{photo.caption}</figcaption>}
            </figure>
          ))}
        </div>
      </Modal>
      <CustomSections sections={page.data} />
    </>
  );
}
