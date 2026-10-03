import { useId, useRef, useState } from 'react';
import { api, errorMessage } from '@shared/api';
import { formatBytes } from '@shared/format';
import type { DocumentRequirement, UploadedDocument } from './types';

const REVIEW_BADGE: Record<string, string> = { pending: 'badge-warning', approved: 'badge-success', rejected: 'badge-danger' };

/**
 * One document requirement: shows what's already uploaded and lets the member
 * add a file from their computer, or take a photo with their phone.
 */
export function DocumentUpload({ applicationId, requirement, documents, editable, maxMb, onChange, error }: {
  applicationId: number;
  requirement: DocumentRequirement;
  documents: UploadedDocument[];
  editable: boolean;
  maxMb: number;
  onChange: () => void;
  error?: string;
}) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const mine = documents.filter((d) => d.document_type === requirement.document_type);

  async function upload(file: File) {
    setProblem(null);
    if (file.size > maxMb * 1024 * 1024) {
      setProblem(`That file is ${formatBytes(file.size)}. The limit is ${maxMb} MB — try a smaller photo or scan.`);
      return;
    }
    const body = new FormData();
    body.append('document_type', requirement.document_type);
    body.append('file', file);
    setBusy(true);
    try {
      await api(`/api/applications/${applicationId}/documents`, { body });
      onChange();
    } catch (err) {
      setProblem(errorMessage(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  }

  async function remove(id: number) {
    setProblem(null);
    try {
      await api(`/api/documents/${id}`, { method: 'DELETE' });
      onChange();
    } catch (err) {
      setProblem(errorMessage(err));
    }
  }

  const message = problem ?? error;
  return (
    <div className={`upload card card-muted ${message ? 'has-error' : ''}`}>
      <div className="row-between">
        <div>
          <label htmlFor={inputId} className={`field-label ${requirement.required ? 'required' : ''}`}>{requirement.label}</label>
          <p className="small muted" style={{ margin: 0 }}>{requirement.description}</p>
        </div>
        {mine.length > 0 && <span className="badge badge-success">Uploaded</span>}
      </div>

      {mine.length > 0 && (
        <ul className="upload-list">
          {mine.map((doc) => (
            <li key={doc.id}>
              <span>{doc.original_filename} <span className="small muted">({formatBytes(doc.size_bytes)})</span></span>
              <span className={`badge ${REVIEW_BADGE[doc.review_status]}`}>{doc.review_status === 'pending' ? 'Waiting for review' : doc.review_status}</span>
              {doc.review_notes && <span className="small muted">Board note: {doc.review_notes}</span>}
              {editable && doc.review_status === 'pending' && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => void remove(doc.id)} aria-label={`Remove ${doc.original_filename}`}>Remove</button>
              )}
            </li>
          ))}
        </ul>
      )}

      {editable && (
        <div className="field" style={{ marginTop: '0.75rem' }}>
          <input
            ref={input}
            id={inputId}
            type="file"
            accept="image/*,application/pdf,.pdf,.heic"
            disabled={busy}
            aria-describedby={message ? `${inputId}-error` : undefined}
            onChange={(e) => { const file = e.target.files?.[0]; if (file) void upload(file); }}
          />
          <span className="hint">Take a photo with your phone or choose a PDF, JPG or PNG (up to {maxMb} MB).</span>
          {busy && <span role="status"><span className="spinner" aria-hidden="true" /> Uploading…</span>}
          {message && <span id={`${inputId}-error`} className="error" role="alert">{message}</span>}
        </div>
      )}
    </div>
  );
}
