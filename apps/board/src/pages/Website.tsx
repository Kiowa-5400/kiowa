import { useState } from 'react';
import { api } from '@shared/api';
import { formatDateTime } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Alert, Checkbox, ErrorState, FormErrors, Loading, TextField, useAction, useAsync } from '@shared/ui';
import { PageHeader, RichTextEditor } from '../components/common';

type Section = { id: number; section_key: string; label: string | null; heading: string | null; body_html: string; is_custom: boolean; is_visible: boolean; updated_at: string };
type PageGroup = { slug: string; label: string; sections: Section[] };
type ImageSlot = { key: string; label: string; url: string | null; alt_text: string | null; original_filename: string | null };

const WWW_URL: string = import.meta.env.VITE_WWW_URL || 'http://localhost:4173';

export function WebsitePage() {
  usePageTitle('Website text & photos');
  const pages = useAsync((signal) => api<PageGroup[]>('/api/board/pages', { signal }), []);
  const [slug, setSlug] = useState('home');
  const [tab, setTab] = useState<'text' | 'photos'>('text');
  const current = pages.data?.find((p) => p.slug === slug);

  return (
    <div className="stack">
      <PageHeader title="Website text & photos" description="Change the words and pictures on the public website. Changes show up as soon as you save."
        actions={<a className="btn" href={`${WWW_URL}${slug === 'home' ? '/' : `/${slug}`}`} target="_blank" rel="noopener">View the website</a>} />
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'text'} className={`btn ${tab === 'text' ? 'btn-primary' : ''}`} onClick={() => setTab('text')}>Page text</button>
        <button type="button" role="tab" aria-selected={tab === 'photos'} className={`btn ${tab === 'photos' ? 'btn-primary' : ''}`} onClick={() => setTab('photos')}>Photos</button>
      </div>
      {tab === 'photos' ? <Photos /> : (
        <>
          {pages.loading && <Loading />}
          {pages.error && <ErrorState message={pages.error} onRetry={pages.reload} />}
          {pages.data && (
            <div className="field" style={{ maxWidth: 320 }}>
              <label htmlFor="page-pick">Which page?</label>
              <select id="page-pick" value={slug} onChange={(e) => setSlug(e.target.value)}>
                {pages.data.map((p) => <option key={p.slug} value={p.slug}>{p.label}</option>)}
              </select>
            </div>
          )}
          {current && (
            <div className="stack">
              {current.sections.map((s) => <SectionEditor key={s.id} section={s} onChange={pages.reload} />)}
              <AddSection slug={slug} onAdded={pages.reload} />
            </div>
          )}
          <p className="small muted">The Range Rules list, dues amount and contact details are edited under Settings, so they stay the same everywhere they appear.</p>
        </>
      )}
    </div>
  );
}

function SectionEditor({ section, onChange }: { section: Section; onChange: () => void }) {
  const [heading, setHeading] = useState(section.heading ?? '');
  const [body, setBody] = useState(section.body_html);
  const [visible, setVisible] = useState(section.is_visible);
  const [saved, setSaved] = useState(false);
  const save = useAction(async () => {
    const result = await api<Section>(`/api/board/sections/${section.id}`, { method: 'PUT', body: { heading, body_html: body, is_visible: visible } });
    setBody(result.body_html);
    setSaved(true);
    onChange();
  });
  const remove = useAction(async () => {
    if (!window.confirm('Delete this section?')) return;
    await api(`/api/board/sections/${section.id}`, { method: 'DELETE' });
    onChange();
  });
  const dirty = heading !== (section.heading ?? '') || body !== section.body_html || visible !== section.is_visible;
  return (
    <section className="card stack" aria-label={section.label ?? section.heading ?? 'Section'}>
      <div className="row-between">
        <p className="kicker">{section.label ?? 'Section'}</p>
        <span className="small muted">Last saved {formatDateTime(section.updated_at)}</span>
      </div>
      <FormErrors error={save.error ?? remove.error} />
      {saved && !dirty && <Alert kind="success">Saved.</Alert>}
      <TextField label="Heading" value={heading} onChange={(e) => { setHeading(e.target.value); setSaved(false); }} />
      <RichTextEditor id={`section-${section.id}`} label="Text" value={body} onChange={(html) => { setBody(html); setSaved(false); }} />
      <Checkbox label="Show this section on the website" checked={visible} onChange={(e) => { setVisible(e.target.checked); setSaved(false); }} />
      <div className="row-between">
        <button type="button" className="btn btn-primary" disabled={!dirty || save.busy} onClick={() => void save.run()}>{save.busy ? 'Saving…' : 'Save'}</button>
        {section.is_custom && <button type="button" className="btn btn-danger btn-sm" onClick={() => void remove.run()}>Delete section</button>}
      </div>
    </section>
  );
}

function AddSection({ slug, onAdded }: { slug: string; onAdded: () => void }) {
  const add = useAction(async () => {
    await api(`/api/board/pages/${slug}/sections`, { body: { heading: 'New section', body_html: '<p>Write something here.</p>' } });
    onAdded();
  });
  return (
    <div>
      <FormErrors error={add.error} />
      <button type="button" className="btn" disabled={add.busy} onClick={() => void add.run()}>+ Add a section to this page</button>
    </div>
  );
}

function Photos() {
  const slots = useAsync((signal) => api<ImageSlot[]>('/api/board/images', { signal }), []);
  if (slots.loading) return <Loading />;
  if (slots.error) return <ErrorState message={slots.error} onRetry={slots.reload} />;
  return (
    <div className="grid-2">
      {slots.data?.map((slot) => <PhotoSlot key={slot.key} slot={slot} onChange={slots.reload} />)}
    </div>
  );
}

function PhotoSlot({ slot, onChange }: { slot: ImageSlot; onChange: () => void }) {
  const [alt, setAlt] = useState(slot.alt_text ?? '');
  const replace = useAction(async (file: File) => {
    const body = new FormData();
    body.append('file', file);
    body.append('alt_text', alt);
    await api(`/api/board/images/${slot.key}`, { method: 'PUT', body });
    onChange();
  });
  const reset = useAction(async () => {
    if (!window.confirm('Go back to the original picture?')) return;
    await api(`/api/board/images/${slot.key}`, { method: 'DELETE' });
    onChange();
  });
  return (
    <section className="card stack-sm" aria-label={slot.label}>
      <h2>{slot.label}</h2>
      {slot.url ? <img src={slot.url} alt={slot.alt_text ?? ''} className="slot-preview" /> : <p className="muted">Using the original picture.</p>}
      <FormErrors error={replace.error ?? reset.error} />
      <TextField label="Describe the picture (for people using screen readers)" value={alt} onChange={(e) => setAlt(e.target.value)} />
      <div className="field">
        <label htmlFor={`slot-${slot.key}`}>Upload a new picture</label>
        <input id={`slot-${slot.key}`} type="file" accept="image/*" disabled={replace.busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) void replace.run(f); e.target.value = ''; }} />
      </div>
      {slot.url && <div><button type="button" className="btn btn-sm" onClick={() => void reset.run()}>Use the original picture</button></div>}
    </section>
  );
}
