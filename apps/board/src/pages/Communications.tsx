import { useState } from 'react';
import { api } from '@shared/api';
import { formatBytes, formatDateTime } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Alert, Checkbox, Empty, ErrorState, FormErrors, Loading, Modal, TextArea, TextField, useAction, useAsync } from '@shared/ui';
import { GroupPicker, PageHeader, PersonSearch, RichTextEditor, StatusBadge, type GroupCount } from '../components/common';

type Picked = { id: number; name: string };

function useAudience() {
  const groups = useAsync((signal) => api<GroupCount[]>('/api/board/people/groups', { signal }), []);
  const [selectedGroups, setSelectedGroups] = useState<string[]>(['active_members']);
  const [people, setPeople] = useState<Picked[]>([]);
  return { groups, selectedGroups, setSelectedGroups, people, setPeople, body: { groups: selectedGroups, person_ids: people.map((p) => p.id) } };
}

// ---------------------------------------------------------------- email ----

type EmailCampaign = {
  id: number; subject: string; recipient_summary: string; created_at: string; created_by: string; sent: number; failed: number;
  delivered: number; opened: number; clicked: number; bounced: number; complained: number; attachments: string[]; kind: string;
};

export function EmailPage() {
  usePageTitle('Email');
  const audience = useAudience();
  const history = useAsync((signal) => api<EmailCampaign[]>('/api/board/email/campaigns', { signal }), []);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [attachments, setAttachments] = useState<{ id: number; filename: string; size_bytes: number }[]>([]);
  const [preview, setPreview] = useState<{ html: string; count: number; excluded: number } | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [detail, setDetail] = useState<number | null>(null);

  const attach = useAction(async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const uploaded = await api<{ id: number; filename: string; size_bytes: number }>('/api/board/email/attachments', { body: form });
    setAttachments([...attachments, uploaded]);
  });
  const showPreview = useAction(async () => {
    if (!subject.trim() || !body.trim()) throw new Error('Add a subject and a message first.');
    const [rendered, count] = await Promise.all([
      api<{ html: string }>('/api/board/email/preview', { body: { subject, body_html: body } }),
      api<{ count: number; excluded_unsubscribed: number }>('/api/board/email/audience', { body: audience.body }),
    ]);
    setPreview({ html: rendered.html, count: count.count, excluded: count.excluded_unsubscribed });
  });
  const send = useAction(async () => {
    const r = await api<{ sent: number; failed: number }>('/api/board/email/send', { body: { subject, body_html: body, ...audience.body, attachment_ids: attachments.map((a) => a.id) } });
    setPreview(null);
    setResult(`Sent to ${r.sent} ${r.sent === 1 ? 'person' : 'people'}.${r.failed ? ` ${r.failed} could not be sent; see the history below.` : ''}`);
    setSubject(''); setBody(''); setAttachments([]);
    history.reload();
  });

  return (
    <div className="stack">
      <PageHeader title="Email" description="Write an email to members or other groups. People who unsubscribed are skipped automatically." />
      {result && <Alert kind="success">{result}</Alert>}
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); void showPreview.run(); }}>
        <FormErrors error={showPreview.error} />
        {audience.groups.data && <GroupPicker groups={audience.groups.data} selected={audience.selectedGroups} onChange={audience.setSelectedGroups} />}
        <PersonSearch selected={audience.people} onChange={audience.setPeople} />
        <TextField label="Subject" required value={subject} onChange={(e) => setSubject(e.target.value)} />
        <RichTextEditor id="email-body" label="Message" value={body} onChange={setBody} />
        <div className="field">
          <label htmlFor="attach">Attach a file (PDF or picture, up to 5 files)</label>
          <input id="attach" type="file" accept="application/pdf,image/*" disabled={attach.busy || attachments.length >= 5}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void attach.run(f); e.target.value = ''; }} />
          {attach.error && <span className="error">{attach.error}</span>}
          {attachments.length > 0 && (
            <p className="row">{attachments.map((a) => (
              <span key={a.id} className="badge">📎 {a.filename} ({formatBytes(a.size_bytes)})
                <button type="button" className="chip-remove" aria-label={`Remove ${a.filename}`} onClick={() => setAttachments(attachments.filter((x) => x.id !== a.id))}>✕</button></span>
            ))}</p>
          )}
        </div>
        <div><button className="btn btn-primary" type="submit" disabled={showPreview.busy}>Preview before sending</button></div>
      </form>

      <Modal open={preview !== null} title="Preview" onClose={() => setPreview(null)}>
        {preview && (
          <div className="stack">
            <p>This will go to <strong>{preview.count}</strong> {preview.count === 1 ? 'person' : 'people'}{preview.excluded > 0 && ` (${preview.excluded} unsubscribed and will be skipped)`}.</p>
            <p><strong>Subject:</strong> {subject}</p>
            <iframe title="Email preview" className="email-preview" sandbox="" srcDoc={preview.html} />
            <FormErrors error={send.error} />
            <div className="row">
              <button type="button" className="btn btn-primary" disabled={send.busy || preview.count === 0} onClick={() => void send.run()}>{send.busy ? 'Sending…' : `Send to ${preview.count}`}</button>
              <button type="button" className="btn" onClick={() => setPreview(null)}>Keep editing</button>
            </div>
          </div>
        )}
      </Modal>

      <section className="stack" aria-labelledby="email-history">
        <h2 id="email-history">Sent emails</h2>
        <p className="small muted">Delivered, opened and clicked counts come from the email service and update over the next few hours. Some email apps block open tracking, so “opened” is a minimum.</p>
        {history.loading && <Loading />}
        {history.error && <ErrorState message={history.error} onRetry={history.reload} />}
        {history.data && history.data.length === 0 && <Empty>No emails sent yet.</Empty>}
        {history.data && history.data.length > 0 && (
          <div className="table-wrap">
            <table className="table-stack">
              <thead><tr><th>Subject</th><th>To</th><th>Sent</th><th>Delivered</th><th>Opened</th><th>Clicked</th><th>Problems</th><th></th></tr></thead>
              <tbody>
                {history.data.map((c) => (
                  <tr key={c.id}>
                    <td data-label="Subject">{c.subject}<div className="small muted">{formatDateTime(c.created_at)} by {c.created_by}</div></td>
                    <td data-label="To">{c.recipient_summary}</td>
                    <td data-label="Sent">{c.sent}</td>
                    <td data-label="Delivered">{c.delivered}</td>
                    <td data-label="Opened">{c.opened}</td>
                    <td data-label="Clicked">{c.clicked}</td>
                    <td data-label="Problems">{c.failed + c.bounced + c.complained > 0 ? <span className="badge badge-danger">{c.failed} failed · {c.bounced} bounced · {c.complained} spam</span> : 'None'}</td>
                    <td data-label=""><button type="button" className="btn btn-sm" onClick={() => setDetail(c.id)}>Details</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Modal open={detail !== null} title="Email details" onClose={() => setDetail(null)}>
        {detail !== null && <EmailDetail id={detail} />}
      </Modal>
    </div>
  );
}

type EmailRecipient = { email: string; status: string; error: string | null; delivered_at: string | null; opened_at: string | null; clicked_at: string | null; bounce_type: string | null };

function EmailDetail({ id }: { id: number }) {
  const detail = useAsync((signal) => api<{ subject: string; recipients: EmailRecipient[] }>(`/api/board/email/campaigns/${id}`, { signal }), [id]);
  if (detail.loading) return <Loading />;
  if (detail.error || !detail.data) return <ErrorState message={detail.error ?? ''} />;
  return (
    <div className="table-wrap">
      <table className="table-stack">
        <thead><tr><th>Email</th><th>Status</th><th>Opened</th><th>Clicked</th></tr></thead>
        <tbody>
          {detail.data.recipients.map((r) => (
            <tr key={r.email}>
              <td data-label="Email">{r.email}{r.error && <div className="small error">{r.error}</div>}{r.bounce_type && <div className="small muted">{r.bounce_type}</div>}</td>
              <td data-label="Status"><StatusBadge status={r.status} /></td>
              <td data-label="Opened">{r.opened_at ? formatDateTime(r.opened_at) : '—'}</td>
              <td data-label="Clicked">{r.clicked_at ? formatDateTime(r.clicked_at) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ SMS ----

type SmsCampaign = {
  id: number; kind: string; body: string; recipient_summary: string; created_at: string; created_by: string; sent: number; failed: number;
  skipped_no_consent: number; delivered: number; undelivered: number; in_flight: number; has_media: boolean;
};

export function SmsPage() {
  usePageTitle('Text messages');
  const audience = useAudience();
  const history = useAsync((signal) => api<SmsCampaign[]>('/api/board/sms/campaigns', { signal }), []);
  const [text, setText] = useState('');
  const [picture, setPicture] = useState<{ id: number; url: string } | null>(null);
  const [review, setReview] = useState<{ count: number; no_consent: number; no_valid_phone: number; risky_words: string[]; safe_body: string; segments: number } | null>(null);
  const [useSafe, setUseSafe] = useState(true);
  const [result, setResult] = useState<string | null>(null);

  const upload = useAction(async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    setPicture(await api<{ id: number; url: string }>('/api/board/media', { body: form }));
  });
  const check = useAction(async () => {
    if (!text.trim()) throw new Error('Write a message first.');
    const [count, words] = await Promise.all([
      api<{ count: number; no_consent: number; no_valid_phone: number }>('/api/board/sms/audience', { body: audience.body }),
      api<{ risky_words: string[]; safe_body: string; segments: number }>('/api/board/sms/check', { body: { body: text } }),
    ]);
    setReview({ ...count, ...words });
    setUseSafe(words.risky_words.length > 0);
  });
  const send = useAction(async () => {
    const r = await api<{ sent: number; failed: number; skipped_no_consent: number }>('/api/board/sms/send', {
      body: { body: text, ...audience.body, use_safe_version: useSafe, media_asset_id: picture?.id ?? null },
    });
    setReview(null);
    setResult(`Text sent to ${r.sent}. ${r.failed ? `${r.failed} failed. ` : ''}${r.skipped_no_consent ? `${r.skipped_no_consent} skipped because they haven't agreed to texts.` : ''}`);
    setText(''); setPicture(null);
    history.reload();
  });

  return (
    <div className="stack">
      <PageHeader title="Text messages" description="Texts only go to people who have agreed to receive them. Everyone else in the group is skipped." />
      {result && <Alert kind="success">{result}</Alert>}
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); void check.run(); }}>
        <FormErrors error={check.error} />
        {audience.groups.data && <GroupPicker groups={audience.groups.data} selected={audience.selectedGroups} onChange={audience.setSelectedGroups} />}
        <PersonSearch selected={audience.people} onChange={audience.setPeople} />
        <TextArea label="Message" required maxLength={1600} value={text} onChange={(e) => setText(e.target.value)} hint={`${text.length} characters. Texts over 160 characters are split into parts.`} />
        <div className="field">
          <label htmlFor="sms-pic">Picture (optional)</label>
          <input id="sms-pic" type="file" accept="image/jpeg,image/png,image/gif" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload.run(f); }} />
          {picture && <img src={picture.url} alt="" className="thumb" />}
          {upload.error && <span className="error">{upload.error}</span>}
        </div>
        <div><button className="btn btn-primary" type="submit" disabled={check.busy}>Review before sending</button></div>
      </form>

      <Modal open={review !== null} title="Review text message" onClose={() => setReview(null)}>
        {review && (
          <div className="stack">
            <p>This will go to <strong>{review.count}</strong> {review.count === 1 ? 'person' : 'people'} who agreed to texts.
              {review.no_consent > 0 && ` ${review.no_consent} in these groups haven't agreed and will be skipped.`}
              {review.no_valid_phone > 0 && ` ${review.no_valid_phone} have no valid mobile number.`}</p>
            {review.risky_words.length > 0 && (
              <Alert kind="warning" title="Phone carriers may block this text.">
                Words like {review.risky_words.map((w) => `“${w}”`).join(', ')} often get filtered. We suggest sending this version instead:
                <blockquote>{review.safe_body}</blockquote>
                <Checkbox label="Send the suggested version" checked={useSafe} onChange={(e) => setUseSafe(e.target.checked)} />
              </Alert>
            )}
            <p className="sms-bubble">{review.risky_words.length && useSafe ? review.safe_body : text}</p>
            <FormErrors error={send.error} />
            <div className="row">
              <button type="button" className="btn btn-primary" disabled={send.busy || review.count === 0} onClick={() => void send.run()}>{send.busy ? 'Sending…' : `Send to ${review.count}`}</button>
              <button type="button" className="btn" onClick={() => setReview(null)}>Keep editing</button>
            </div>
          </div>
        )}
      </Modal>

      <section className="stack" aria-labelledby="sms-history">
        <h2 id="sms-history">Sent texts</h2>
        <p className="small muted">Delivery results come from the phone carriers and can take a few minutes. Automatic dues reminders are listed here too.</p>
        {history.loading && <Loading />}
        {history.data && history.data.length === 0 && <Empty>No texts sent yet.</Empty>}
        {history.data && history.data.length > 0 && (
          <div className="table-wrap">
            <table className="table-stack">
              <thead><tr><th>Message</th><th>To</th><th>Sent</th><th>Delivered</th><th>Not delivered</th><th>Waiting</th><th>Skipped (no consent)</th></tr></thead>
              <tbody>
                {history.data.map((c) => (
                  <tr key={c.id}>
                    <td data-label="Message">{c.body}{c.has_media && ' 🖼'}<div className="small muted">{formatDateTime(c.created_at)} by {c.created_by}</div></td>
                    <td data-label="To">{c.recipient_summary}</td>
                    <td data-label="Sent">{c.sent}</td>
                    <td data-label="Delivered">{c.delivered}</td>
                    <td data-label="Not delivered">{c.failed + c.undelivered}</td>
                    <td data-label="Waiting">{c.in_flight}</td>
                    <td data-label="Skipped (no consent)">{c.skipped_no_consent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
