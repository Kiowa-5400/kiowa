export type Profile = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  membership_status: 'member' | 'waiting_list' | 'non_member' | 'expired' | 'terminated';
  member_since: string | null;
  nra_number: string | null;
  nra_expiration_date: string | null;
  nra_active: boolean;
  background_check_cleared: boolean;
  sms_opt_in: boolean;
  sms_opt_in_at: string | null;
  email_opt_out: boolean;
  email_verified: boolean;
  is_board: boolean;
  renewal: { paid_through: string | null; next_cutoff: string; is_current: boolean; days_until_cutoff: number };
};

export type DocumentRequirement = { document_type: DocumentType; label: string; required: boolean; description: string };
export type DocumentType = 'nra_proof' | 'background_check' | 'concealed_carry' | 'cleanup_discount' | 'other';

export type UploadedDocument = {
  id: number;
  document_type: DocumentType;
  label: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string;
  review_status: 'pending' | 'approved' | 'rejected';
  review_notes: string | null;
  application_id: number | null;
  purged: boolean;
};

export type PaymentSummary = {
  id: number;
  amount: string;
  status: string;
  method: string;
  paid_at: string | null;
  created_at: string;
  refunded_amount: string;
  covers_through: string | null;
};

export type Application = {
  id: number;
  application_type: 'renewal' | 'waiting_list';
  status: 'draft' | 'submitted' | 'needs_info' | 'approved' | 'declined' | 'completed' | 'withdrawn';
  status_label: string;
  documentation_method: 'background_check' | 'concealed_carry' | null;
  claims_cleanup_discount: boolean;
  applicant_notes: string | null;
  rules_version: string | null;
  printed_name: string | null;
  signature_name: string | null;
  signed_at: string | null;
  submitted_at: string | null;
  info_request_message: string | null;
  decision_reason: string | null;
  payment_status: string;
  payment_requested_at: string | null;
  created_at: string;
  document_requirements: DocumentRequirement[];
  documents: UploadedDocument[];
  eligibility: { eligible: boolean; reasons: string[]; amount: string };
  payments: PaymentSummary[];
};

export type FormDefinition = {
  application_types: { value: 'renewal' | 'waiting_list'; label: string }[];
  rules: { version: string; rules: string[]; agreement_clause: string; reporting_clause: string };
  dues_amount: string;
  cleanup_discount_amount: string;
  accepting_waiting_list: boolean;
  background_check_url: string | null;
  max_upload_mb: number;
  accepted_file_types: string[];
};
