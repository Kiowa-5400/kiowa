/** Small accessible UI building blocks shared by the three apps. */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';
import { errorMessage } from './api';

// ---------------------------------------------------------------- data ----

export type AsyncState<T> = { data: T | undefined; error: string | null; loading: boolean; reload: () => void };

/** Loads data on mount (and when deps change), exposing loading/error state. */
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    load(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((err) => {
        if (!controller.signal.aborted && !(err instanceof DOMException && err.name === 'AbortError')) setError(errorMessage(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** Wraps an async action with busy/error/success state for forms and buttons. */
export function useAction<A extends unknown[], R>(action: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const run = useCallback(
    async (...args: A): Promise<R | undefined> => {
      setBusy(true);
      setError(null);
      setFieldErrors({});
      try {
        return await action(...args);
      } catch (err) {
        setError(errorMessage(err));
        if (err && typeof err === 'object' && 'errors' in err) setFieldErrors((err as { errors: Record<string, string> }).errors);
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [action],
  );
  return { run, busy, error, fieldErrors, setError };
}

// -------------------------------------------------------------- states ----

export function Alert({ kind = 'info', children, title }: { kind?: 'info' | 'error' | 'success' | 'warning'; children: ReactNode; title?: string }) {
  return (
    <div className={`alert alert-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      {title && <strong>{title} </strong>}
      {children}
    </div>
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state">
      <Alert kind="error">{message}</Alert>
      {onRetry && (
        <p style={{ marginTop: '1rem' }}>
          <button type="button" className="btn" onClick={onRetry}>Try again</button>
        </p>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state">{children}</div>;
}

/** Renders HTML that the API has already sanitized server-side. */
export function Html({ html, className = 'prose' }: { html: string | null | undefined; className?: string }) {
  if (!html) return null;
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}

// --------------------------------------------------------------- forms ----

type FieldBase = { label: string; error?: string; hint?: ReactNode; required?: boolean };

export function TextField({ label, error, hint, required, id, ...input }: FieldBase & InputHTMLAttributes<HTMLInputElement>) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const describedBy = [hint ? `${fieldId}-hint` : '', error ? `${fieldId}-error` : ''].filter(Boolean).join(' ') || undefined;
  return (
    <div className="field">
      <label htmlFor={fieldId} className={required ? 'required' : undefined}>{label}</label>
      {hint && <span id={`${fieldId}-hint`} className="hint">{hint}</span>}
      {input.type === 'password'
        ? <PasswordInput id={fieldId} required={required} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...input} />
        : <input id={fieldId} required={required} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...input} />}
      {error && <span id={`${fieldId}-error`} className="error">{error}</span>}
    </div>
  );
}

/** A password input with an eye button so people can check what they typed. */
function PasswordInput(input: InputHTMLAttributes<HTMLInputElement>) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="password-input">
      <input {...input} type={visible ? 'text' : 'password'} autoCapitalize="none" autoCorrect="off" spellCheck={false} />
      <button type="button" className="password-toggle" aria-controls={input.id} aria-pressed={visible}
        aria-label={visible ? 'Hide password' : 'Show password'} title={visible ? 'Hide password' : 'Show password'}
        onClick={() => setVisible((v) => !v)}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
          {visible && <path d="M3 3l18 18" />}
        </svg>
      </button>
    </div>
  );
}

export function TextArea({ label, error, hint, required, id, ...input }: FieldBase & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <div className="field">
      <label htmlFor={fieldId} className={required ? 'required' : undefined}>{label}</label>
      {hint && <span id={`${fieldId}-hint`} className="hint">{hint}</span>}
      <textarea id={fieldId} required={required} aria-invalid={error ? true : undefined}
        aria-describedby={[hint ? `${fieldId}-hint` : '', error ? `${fieldId}-error` : ''].filter(Boolean).join(' ') || undefined} {...input} />
      {error && <span id={`${fieldId}-error`} className="error">{error}</span>}
    </div>
  );
}

export function SelectField({ label, error, hint, required, id, children, ...input }: FieldBase & SelectHTMLAttributes<HTMLSelectElement>) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <div className="field">
      <label htmlFor={fieldId} className={required ? 'required' : undefined}>{label}</label>
      {hint && <span id={`${fieldId}-hint`} className="hint">{hint}</span>}
      <select id={fieldId} required={required} aria-invalid={error ? true : undefined}
        aria-describedby={[hint ? `${fieldId}-hint` : '', error ? `${fieldId}-error` : ''].filter(Boolean).join(' ') || undefined} {...input}>
        {children}
      </select>
      {error && <span id={`${fieldId}-error`} className="error">{error}</span>}
    </div>
  );
}

export function Checkbox({ label, hint, ...input }: { label: ReactNode; hint?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="check">
      <input type="checkbox" {...input} />
      <span>
        {label}
        {hint && <span className="hint" style={{ display: 'block' }}>{hint}</span>}
      </span>
    </label>
  );
}

/** Lists field errors returned by the API at the top of a form. */
export function FormErrors({ error, fieldErrors }: { error: string | null; fieldErrors?: Record<string, string> }) {
  if (!error) return null;
  const extra = Object.values(fieldErrors ?? {}).filter((message) => message !== error);
  return (
    <Alert kind="error">
      {error}
      {extra.length > 0 && <ul>{extra.map((message) => <li key={message}>{message}</li>)}</ul>}
    </Alert>
  );
}

// -------------------------------------------------------------- dialog ----

/** Accessible modal built on <dialog>: focus trap, Escape to close, focus restore. */
export function Modal({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      const previous = document.activeElement as HTMLElement | null;
      dialog.showModal();
      return () => previous?.focus?.();
    }
    if (!open && dialog.open) dialog.close();
    return undefined;
  }, [open]);
  return (
    <dialog ref={ref} className="modal" aria-labelledby={headingId} onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      {open && (
        <>
          <div className="modal-header">
            <h2 id={headingId}>{title}</h2>
            <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close dialog">✕</button>
          </div>
          <div className="modal-body">{children}</div>
        </>
      )}
    </dialog>
  );
}

