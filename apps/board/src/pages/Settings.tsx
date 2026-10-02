import { useState } from 'react';
import { api } from '@shared/api';
import { formatMoney } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Alert, Checkbox, ErrorState, FormErrors, Loading, TextArea, TextField, useAction, useAsync } from '@shared/ui';
import { useAuth } from '../auth';
import { PageHeader } from '../components/common';

type Settings = {
  site_title: string; site_subtitle: string; contact_email: string | null; contact_phone: string | null; mailing_address: string | null;
  physical_address: string | null; map_url: string | null; social_facebook: string | null; social_instagram: string | null; social_youtube: string | null;
  footer_links: { label: string; url: string }[]; background_check_url: string | null; dues_amount: string; cleanup_discount_amount: string;
  renewal_cutoff_month: number; renewal_cutoff_day: number; accepting_waiting_list: boolean; rules_version: string; range_rules: string[];
  agreement_clause: string; reporting_clause: string;
};

export function SettingsPage() {
  usePageTitle('Settings');
  const { can } = useAuth();
  const settings = useAsync((signal) => api<Settings>('/api/board/settings', { signal }), []);
  if (settings.loading) return <Loading />;
  if (settings.error || !settings.data) return <ErrorState message={settings.error ?? ''} onRetry={settings.reload} />;
  return (
    <div className="stack">
      <PageHeader title="Settings" description="Club details shown across the website, membership dues, and the Range Rules." />
      <SiteForm initial={settings.data} />
      {can('settings.manage') ? (
        <>
          <MembershipForm initial={settings.data} />
          <RulesForm initial={settings.data} />
        </>
      ) : <Alert kind="info">Dues and the Range Rules can be changed by the treasurer, vice president or president.</Alert>}
    </div>
  );
}

function SiteForm({ initial }: { initial: Settings }) {
  const [form, setForm] = useState({
    site_title: initial.site_title, site_subtitle: initial.site_subtitle, contact_email: initial.contact_email ?? '', contact_phone: initial.contact_phone ?? '',
    mailing_address: initial.mailing_address ?? '', physical_address: initial.physical_address ?? '', map_url: initial.map_url ?? '',
    social_facebook: initial.social_facebook ?? '', social_instagram: initial.social_instagram ?? '', social_youtube: initial.social_youtube ?? '',
    background_check_url: initial.background_check_url ?? '',
  });
  const [links, setLinks] = useState(initial.footer_links);
  const [saved, setSaved] = useState(false);
  const save = useAction(async () => {
    await api('/api/board/settings/site', { method: 'PUT', body: { ...form, footer_links: links.filter((l) => l.label && l.url) } });
    setSaved(true);
  });
  const text = (k: keyof typeof form) => ({ value: form[k], onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { setForm({ ...form, [k]: e.target.value }); setSaved(false); } });
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <h2>Club details</h2>
      <FormErrors error={save.error} fieldErrors={save.fieldErrors} />
      {saved && <Alert kind="success">Saved. The website shows the new details now.</Alert>}
      <div className="grid-2">
        <TextField label="Club name (website title)" required {...text('site_title')} />
        <TextField label="Subtitle" {...text('site_subtitle')} />
        <TextField label="Contact email" type="email" {...text('contact_email')} />
        <TextField label="Contact phone" type="tel" {...text('contact_phone')} />
      </div>
      <div className="grid-2">
        <TextArea label="Mailing address" rows={3} {...text('mailing_address')} />
        <TextArea label="Range location" rows={3} {...text('physical_address')} />
      </div>
      <TextField label="Map link" type="url" {...text('map_url')} />
      <TextField label="Background check website (shown to waiting-list applicants)" type="url" {...text('background_check_url')} />
      <div className="grid-3">
        <TextField label="Facebook page" type="url" placeholder="https://" {...text('social_facebook')} />
        <TextField label="Instagram" type="url" placeholder="https://" {...text('social_instagram')} />
        <TextField label="YouTube" type="url" placeholder="https://" {...text('social_youtube')} />
      </div>
      <fieldset className="stack-sm">
        <legend>Extra links in the website footer</legend>
        {links.map((link, i) => (
          <div key={i} className="row">
            <TextField label="Text" value={link.label} onChange={(e) => setLinks(links.map((l, j) => (j === i ? { ...l, label: e.target.value } : l)))} />
            <TextField label="Link" type="url" value={link.url} onChange={(e) => setLinks(links.map((l, j) => (j === i ? { ...l, url: e.target.value } : l)))} />
            <button type="button" className="btn btn-sm btn-danger" onClick={() => setLinks(links.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <div><button type="button" className="btn btn-sm" onClick={() => setLinks([...links, { label: '', url: 'https://' }])}>+ Add a link</button></div>
      </fieldset>
      <div><button className="btn btn-primary" type="submit" disabled={save.busy}>Save club details</button></div>
    </form>
  );
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function MembershipForm({ initial }: { initial: Settings }) {
  const [form, setForm] = useState({
    dues_amount: initial.dues_amount, cleanup_discount_amount: initial.cleanup_discount_amount,
    renewal_cutoff_month: initial.renewal_cutoff_month, renewal_cutoff_day: initial.renewal_cutoff_day, accepting_waiting_list: initial.accepting_waiting_list,
  });
  const [saved, setSaved] = useState(false);
  const save = useAction(async () => {
    if (!window.confirm(`Set annual dues to ${formatMoney(form.dues_amount)}? This applies to everyone who pays from now on.`)) return;
    await api('/api/board/settings/membership', { method: 'PUT', body: form });
    setSaved(true);
  });
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <h2>Dues and renewal</h2>
      <FormErrors error={save.error} fieldErrors={save.fieldErrors} />
      {saved && <Alert kind="success">Saved.</Alert>}
      <div className="grid-2">
        <TextField label="Annual dues ($)" inputMode="decimal" required value={form.dues_amount} onChange={(e) => setForm({ ...form, dues_amount: e.target.value })} />
        <TextField label="Range cleanup-day discount ($)" inputMode="decimal" value={form.cleanup_discount_amount}
          hint="Taken off when the board approves a member's discount card. Use 0 for no discount."
          onChange={(e) => setForm({ ...form, cleanup_discount_amount: e.target.value })} />
      </div>
      <fieldset>
        <legend>Last day to pay dues each year</legend>
        <div className="row">
          <select aria-label="Month" value={form.renewal_cutoff_month} onChange={(e) => setForm({ ...form, renewal_cutoff_month: Number(e.target.value) })}>
            {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>
          <input aria-label="Day" type="number" min={1} max={31} value={form.renewal_cutoff_day} style={{ width: '6rem' }}
            onChange={(e) => setForm({ ...form, renewal_cutoff_day: Number(e.target.value) })} />
        </div>
        <p className="small muted">Reminders go out 45 and 15 days before this date. Members who haven't paid by then are moved to Terminated the next day.</p>
      </fieldset>
      <Checkbox label="Accept new waiting-list applications" checked={form.accepting_waiting_list} onChange={(e) => setForm({ ...form, accepting_waiting_list: e.target.checked })} />
      <div><button className="btn btn-primary" type="submit" disabled={save.busy}>Save dues settings</button></div>
    </form>
  );
}

function RulesForm({ initial }: { initial: Settings }) {
  const [rules, setRules] = useState(initial.range_rules.join('\n'));
  const [agreement, setAgreement] = useState(initial.agreement_clause);
  const [reporting, setReporting] = useState(initial.reporting_clause);
  const [version, setVersion] = useState(initial.rules_version);
  const save = useAction(async () => {
    if (!window.confirm('Publish these rules? Everyone who applies from now on will agree to this new version.')) return;
    const result = await api<Settings>('/api/board/settings/rules', { method: 'PUT', body: { range_rules: rules.split('\n').map((r) => r.trim()).filter(Boolean), agreement_clause: agreement, reporting_clause: reporting } });
    setVersion(result.rules_version);
  });
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <h2>Range Rules</h2>
      <p className="muted">Current version: <strong>{version}</strong>. These appear on the Rules page and in every application. Each application records the version the member agreed to.</p>
      <FormErrors error={save.error} />
      <TextArea label="Rules (one rule per line)" rows={14} value={rules} onChange={(e) => setRules(e.target.value)} />
      <TextArea label="If you see a rule broken… (shown under the rules)" rows={4} value={reporting} onChange={(e) => setReporting(e.target.value)} />
      <TextArea label="Agreement members sign" rows={4} value={agreement} onChange={(e) => setAgreement(e.target.value)} />
      <div><button className="btn btn-primary" type="submit" disabled={save.busy}>Publish new version</button></div>
    </form>
  );
}
