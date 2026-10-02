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
  documentation_method: 'background_check' | 'concealed_carry';
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
        description: 'Upload an image of your NRA membership card or magazine mailing label.',
      },
      {
        label: 'Range Cleanup Discount Card',
        required: false,
        description: 'Optional: upload the cleanup card if you are claiming the discount.',
      },
    ],
    waiting_list: [
      {
        label: 'Background Check OR Concealed Carry License',
        required: true,
        description: 'Choose either a background-check report cover page or a concealed-carry license image.',
      },
    ],
  },
  rules_text:
    'Kiowa Gun Club Range Rules\n\n1. Range flag at gate must be raised anytime you are on the property. Range flag at firing line must be raised when shooting on the line or downrange.\n2. All shooting on rifle ranges MUST be done from the permanent firing line.\n3. I will not shoot when work crews are on the range.\n4. I will follow all of the safety rules and guidelines I have been taught about safe gunhandling. I am responsible for my guest\'s actions while on property.\n5. I will NOT shoot center fire rifles, including .223 pistols, toward or in pistol ranges #1 and #2.\n6. I will follow the club calendar, as scheduled events will take precedence.\n7. I will not shoot with artificial lighting.\n8. I will take all my targets and trash I brought to the range home, or deposit in trash cans provided. I WILL NOT LEAVE MY TARGETS ON THE BACKER BOARDS.\n9. I will only shoot at targets that are safe, NOT trash cans, rocks, or other items that may cause ricochets.\n10. During scheduled shoots, modified rules may apply.\n11. No hunting of any kind is allowed on club property.\n12. Shotgun shooting is NOT ALLOWED on club property. This includes handguns while shooting shotshells.\n13. A member must accompany guests at all times.\n14. Vehicles are allowed to be driven to the backstops to set up or check targets, provided they stay on the rock. No vehicles are allowed behind the backstops.\n15. No alcoholic beverages are allowed on club property at any time.\n16. Eye and ear protection is required at all matches. We recommend using them whenever you are shooting.\n17. Do not leave live rounds lying on the range. Dispose of them in the misfire container located at the end of the backstop between ranges #1 and #2.\n18. The use of binary explosives is prohibited. (Tannerite, Shockwave, etc.)\n19. The gun club requires proof of background check or concealed carry license.\n\nI have read, understand, and agree to follow the Kiowa Gun Club Range Rules.',
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
  documentation_method: 'background_check',
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
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

  useEffect(() => {
    const loadFormDefinition = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/application/form-definition`);
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

  const triggerDocumentLabel = formState.application_type === 'waiting_list'
    ? 'Background Check OR Concealed Carry License'
    : 'NRA Membership Proof';

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
      const documents = { ...formState.documents };
      if (formState.application_type === 'waiting_list') {
        const documentKey = 'Background Check OR Concealed Carry License';
        documents[documentKey] = documents[documentKey] || 'document-uploaded';
      }

      const response = await fetch(`${apiBaseUrl}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...formState,
          application_type: formState.application_type,
          documents,
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
          {formState.application_type === 'waiting_list' && (
            <div className="stacked-grid two-up" style={{ marginBottom: '1rem' }}>
              <label className={`option-card ${formState.documentation_method === 'background_check' ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="documentation_method"
                  checked={formState.documentation_method === 'background_check'}
                  onChange={() => updateField('documentation_method', 'background_check')}
                />
                <span>Background Check</span>
              </label>
              <label className={`option-card ${formState.documentation_method === 'concealed_carry' ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="documentation_method"
                  checked={formState.documentation_method === 'concealed_carry'}
                  onChange={() => updateField('documentation_method', 'concealed_carry')}
                />
                <span>Concealed Carry License</span>
              </label>
            </div>
          )}
          <div className="documents-list">
            {documentRequirements.map((requirement) => (
              <div key={requirement.label} className="doc-item">
                <div>
                  <label className="doc-label">{requirement.label}</label>
                  <small>{requirement.description}</small>
                </div>
                <label className="file-picker">
                  {formState.documents[requirement.label] ? formState.documents[requirement.label] : 'Upload file'}
                  <input type="file" accept="image/*,.pdf" capture="environment" onChange={(event) => handleDocumentUpload(event, requirement.label)} />
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
            I have read, understand, and agree to follow the Kiowa Gun Club Range Rules.
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
