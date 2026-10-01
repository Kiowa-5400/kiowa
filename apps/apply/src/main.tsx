import React, { ChangeEvent, FormEvent, useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import './styles.css';

type ApplicationType = 'renew_membership' | 'waiting_list';

type DocumentRequirement = {
  label: string;
  required: boolean;
  description: string;
};

type FormDefinition = {
  application_types: { value: ApplicationType; label: string }[];
  document_requirements: Record<ApplicationType, DocumentRequirement[]>;
  rules_text: string;
};

type FormState = {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  application_type: ApplicationType;
  payment_method: 'card' | 'check' | 'cash';
  membership_notes: string;
  signature: string;
  accept_rules: boolean;
  documents: Record<string, string>;
};

const defaultFormDefinition: FormDefinition = {
  application_types: [
    { value: 'renew_membership', label: 'Renew My Membership' },
    { value: 'waiting_list', label: 'Apply for the Waiting List' },
  ],
  document_requirements: {
    renew_membership: [
      {
        label: 'NRA Membership Proof',
        required: true,
        description: 'Upload an image of your NRA membership card or mailing label.',
      },
      {
        label: 'Range Cleanup Discount Card',
        required: false,
        description: 'Optional: upload the cleanup card if you are claiming the discount.',
      },
    ],
    waiting_list: [
      {
        label: 'Background Check Cover Page',
        required: true,
        description: 'Upload the cover page from the criminalwatchdog.com background check report.',
      },
      {
        label: 'Concealed Carry License',
        required: false,
        description: 'Optional alternative: upload a concealed carry license from any state.',
      },
    ],
  },
  rules_text:
    'Range flag at gate must be raised anytime you are on the property. Range flag at firing line must be raised when shooting on the line or downrange.\n\nAll shooting on rifle ranges MUST be done from the permanent firing line.\n\nI will not shoot when work crews are on the range.\n\nI will follow all of the safety rules and guidelines I have been taught about safe gunhandling. I am responsible for my guest\'s actions while on property.',
};

const initialFormState: FormState = {
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  address: '',
  city: '',
  state: '',
  zip: '',
  application_type: 'renew_membership',
  payment_method: 'card',
  membership_notes: '',
  signature: '',
  accept_rules: false,
  documents: {},
};

function App() {
  const [formDefinition, setFormDefinition] = useState<FormDefinition>(defaultFormDefinition);
  const [formState, setFormState] = useState<FormState>(initialFormState);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const loadFormDefinition = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/application/form');
        if (!response.ok) {
          return;
        }
        const result = (await response.json()) as FormDefinition & {
          application_types?: { value: ApplicationType; label: string }[];
        };
        if (result.application_types?.length) {
          setFormDefinition({
            application_types: result.application_types,
            document_requirements: result.document_requirements ?? defaultFormDefinition.document_requirements,
            rules_text: result.rules_text ?? defaultFormDefinition.rules_text,
          });
        }
      } catch {
        // Fall back to the local default form when the backend is unavailable.
      }
    };

    void loadFormDefinition();
  }, []);

  const documentRequirements = formDefinition.document_requirements[formState.application_type];

  const updateField = <K extends keyof FormState>(field: K, value: FormState[K]) => {
    setFormState((current) => ({ ...current, [field]: value }));
  };

  const handleDocumentUpload = (event: ChangeEvent<HTMLInputElement>, label: string) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    updateField('documents', {
      ...formState.documents,
      [label]: file.name,
    });
  };

  const validateForm = () => {
    const requiredFields = [
      formState.first_name,
      formState.last_name,
      formState.email,
      formState.phone,
      formState.address,
      formState.city,
      formState.state,
      formState.zip,
      formState.signature,
    ];

    if (requiredFields.some((value) => !value.trim())) {
      return 'Please complete all required personal information fields before submitting.';
    }

    if (!formState.accept_rules) {
      return 'Please acknowledge the range safety rules before submitting your application.';
    }

    const requiredDocuments = documentRequirements.filter((doc) => doc.required);
    for (const requirement of requiredDocuments) {
      if (!formState.documents[requirement.label]) {
        return `Please upload ${requirement.label} before continuing.`;
      }
    }

    return '';
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage('');
    setSubmitMessage('');

    const validationMessage = validateForm();
    if (validationMessage) {
      setErrorMessage(validationMessage);
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await fetch('http://localhost:8000/api/application/submit', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...formState,
          documents: Object.keys(formState.documents),
        }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.detail || 'Submit failed.');
      }

      setSubmitMessage(payload?.message || 'Application submitted successfully.');
      setErrorMessage('');
      setFormState((current) => ({ ...current, signature: '', accept_rules: false }));
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Something went wrong.';
      setErrorMessage(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="page-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Member Services</p>
          <h1>Kiowa Gun Club Membership Application</h1>
        </div>
      </header>

      <form className="application-form" onSubmit={handleSubmit}>
        <section className="card">
          <h2>Application type</h2>
          <div className="stacked-grid two-up">
            {formDefinition.application_types.map((option) => (
              <label key={option.value} className={`option-card ${formState.application_type === option.value ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="application_type"
                  value={option.value}
                  checked={formState.application_type === option.value}
                  onChange={() => updateField('application_type', option.value)}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="card">
          <h2>Applicant information</h2>
          <div className="stacked-grid two-up">
            <label>
              First name
              <input value={formState.first_name} onChange={(event) => updateField('first_name', event.target.value)} />
            </label>
            <label>
              Last name
              <input value={formState.last_name} onChange={(event) => updateField('last_name', event.target.value)} />
            </label>
            <label>
              Email address
              <input type="email" value={formState.email} onChange={(event) => updateField('email', event.target.value)} />
            </label>
            <label>
              Phone number
              <input value={formState.phone} onChange={(event) => updateField('phone', event.target.value)} />
            </label>
            <label className="full-span">
              Street address
              <input value={formState.address} onChange={(event) => updateField('address', event.target.value)} />
            </label>
            <label>
              City
              <input value={formState.city} onChange={(event) => updateField('city', event.target.value)} />
            </label>
            <label>
              State
              <input value={formState.state} onChange={(event) => updateField('state', event.target.value)} />
            </label>
            <label>
              ZIP code
              <input value={formState.zip} onChange={(event) => updateField('zip', event.target.value)} />
            </label>
          </div>
        </section>

        <section className="card">
          <h2>Membership and payment details</h2>
          <div className="stacked-grid three-up">
            <label>
              Payment method
              <select value={formState.payment_method} onChange={(event) => updateField('payment_method', event.target.value as FormState['payment_method'])}>
                <option value="card">Credit card</option>
                <option value="check">Check</option>
                <option value="cash">Cash</option>
              </select>
            </label>
            <label>
              Expected amount
              <input value={formState.application_type === 'renew_membership' ? '$150' : '$0'} readOnly />
            </label>
            <label>
              Membership notes
              <input value={formState.membership_notes} onChange={(event) => updateField('membership_notes', event.target.value)} />
            </label>
          </div>
        </section>

        <section className="card">
          <h2>Required documentation</h2>
          <div className="documents-list">
            {documentRequirements.map((requirement) => (
              <div key={requirement.label} className="doc-item">
                <div>
                  <label className="doc-label">{requirement.label}</label>
                  <small>{requirement.description}</small>
                </div>
                <label className="file-picker">
                  {formState.documents[requirement.label] ? formState.documents[requirement.label] : 'Upload file'}
                  <input type="file" onChange={(event) => handleDocumentUpload(event, requirement.label)} />
                </label>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <h2>Range safety rules acknowledgement</h2>
          <div className="rules-box">
            <p>{formDefinition.rules_text}</p>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={formState.accept_rules}
              onChange={(event) => updateField('accept_rules', event.target.checked)}
            />
            I acknowledge and agree to the range safety rules above.
          </label>
        </section>

        <section className="card">
          <h2>Digital signature</h2>
          <label>
            Full legal name
            <input value={formState.signature} onChange={(event) => updateField('signature', event.target.value)} />
          </label>
        </section>

        {errorMessage && <p className="alert error">{errorMessage}</p>}
        {submitMessage && <p className="alert success">{submitMessage}</p>}

        <div className="actions">
          <button type="submit" className="primary-button" disabled={isSubmitting}>
            {isSubmitting ? 'Submitting...' : 'Submit Application'}
          </button>
        </div>
      </form>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
