import { Checkbox, TextField } from '@shared/ui';

export type ProfileForm = {
  first_name: string;
  last_name: string;
  phone: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  zip_code: string;
  nra_number: string;
  nra_expiration_date: string;
  sms_opt_in: boolean;
};

export function profileForm(profile: Partial<Record<keyof ProfileForm, unknown>>): ProfileForm {
  const text = (value: unknown) => (typeof value === 'string' ? value : '');
  return {
    first_name: text(profile.first_name),
    last_name: text(profile.last_name),
    phone: text(profile.phone),
    address_line1: text(profile.address_line1),
    address_line2: text(profile.address_line2),
    city: text(profile.city),
    state: text(profile.state) || 'KS',
    zip_code: text(profile.zip_code),
    nra_number: text(profile.nra_number),
    nra_expiration_date: text(profile.nra_expiration_date),
    sms_opt_in: Boolean(profile.sms_opt_in),
  };
}

/** Converts blank strings to null so the API clears/omits them. */
export function profilePayload(form: ProfileForm): Record<string, string | boolean | null> {
  return Object.fromEntries(Object.entries(form).map(([k, v]) => [k, typeof v === 'string' && v.trim() === '' ? null : v]));
}

export function ProfileFields({ form, onChange, errors, nraRequired }: {
  form: ProfileForm;
  onChange: (form: ProfileForm) => void;
  errors: Record<string, string>;
  nraRequired?: boolean;
}) {
  const set = (key: keyof ProfileForm) => (e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...form, [key]: e.target.value });
  return (
    <div className="stack">
      <fieldset className="stack">
        <legend>Your name and contact information</legend>
        <div className="grid-2">
          <TextField label="First name" autoComplete="given-name" required value={form.first_name} onChange={set('first_name')} error={errors.first_name} />
          <TextField label="Last name" autoComplete="family-name" required value={form.last_name} onChange={set('last_name')} error={errors.last_name} />
        </div>
        <TextField label="Mobile phone" type="tel" inputMode="tel" autoComplete="tel" required value={form.phone} onChange={set('phone')} error={errors.phone} />
        <Checkbox
          checked={form.sms_opt_in}
          onChange={(e) => onChange({ ...form, sms_opt_in: e.target.checked })}
          label="Yes, text me about matches, events, and dues renewal reminders."
          hint="Optional — it won't affect your membership. Message and data rates may apply; frequency varies. Reply STOP to any text to opt out, or change this anytime here. We never sell or share your number."
        />
      </fieldset>
      <fieldset className="stack">
        <legend>Mailing address</legend>
        <TextField label="Street address" autoComplete="address-line1" required value={form.address_line1} onChange={set('address_line1')} error={errors.address_line1} />
        <TextField label="Apartment, suite, PO box (optional)" autoComplete="address-line2" value={form.address_line2} onChange={set('address_line2')} />
        <div className="grid-3">
          <TextField label="City" autoComplete="address-level2" required value={form.city} onChange={set('city')} error={errors.city} />
          <TextField label="State" autoComplete="address-level1" required maxLength={2} value={form.state} onChange={set('state')} error={errors.state} />
          <TextField label="ZIP code" autoComplete="postal-code" inputMode="numeric" required value={form.zip_code} onChange={set('zip_code')} error={errors.zip_code} />
        </div>
      </fieldset>
      <fieldset className="stack">
        <legend>NRA membership</legend>
        <p className="small muted">Current NRA membership is required for club membership.</p>
        <div className="grid-2">
          <TextField label={nraRequired ? 'NRA member number' : 'NRA member number (if you have it)'} inputMode="numeric" required={nraRequired}
            value={form.nra_number} onChange={(e) => onChange({ ...form, nra_number: e.target.value.replace(/\D/g, '') })}
            maxLength={12} error={errors.nra_number} hint="5 to 12 digits, from your card." />
          <TextField label="NRA membership expiration date" type="date" required value={form.nra_expiration_date}
            onChange={set('nra_expiration_date')} error={errors.nra_expiration_date} />
        </div>
      </fieldset>
    </div>
  );
}
