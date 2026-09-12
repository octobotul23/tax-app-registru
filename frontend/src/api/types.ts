/**
 * Mirrors of the backend schemas.
 *
 * Money is `string`, not `number`, throughout. Pydantic serialises `Decimal`
 * to a JSON string precisely so the value survives the trip intact - parsing it
 * into a JavaScript number would reintroduce the binary-float error the backend
 * went to some trouble to avoid. Format for display, never arithmetic.
 */

export type Money = string;
export type UUID = string;
/** ISO date, `YYYY-MM-DD`. */
export type IsoDate = string;

export type FundingSource = "BUSINESS" | "PERSONAL";
export type DocumentKind = "RECEIPT" | "OBJECT_LIST";
export type DocumentStatus =
  | "PENDING"
  | "PROCESSING"
  | "PARSED"
  | "NEEDS_REVIEW"
  | "CONFIRMED"
  | "FAILED";

export interface User {
  id: UUID;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
  equity_share: Money;
  created_at: string;
}

export interface LineItem {
  id?: UUID;
  line_no?: number;
  description: string;
  quantity: Money | null;
  unit_price: Money | null;
  line_total: Money | null;
  vat_rate: Money | null;
  category: string | null;
}

export interface DocumentSummary {
  id: UUID;
  kind: DocumentKind;
  status: DocumentStatus;
  funding_source: FundingSource;
  uploader_id: UUID;
  payer_id: UUID;
  title: string | null;
  merchant_name: string | null;
  document_date: IsoDate | null;
  currency: string | null;
  total: Money | null;
  total_base: Money | null;
  category: string | null;
  ai_confidence: number | null;
  image_bytes: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  original_filename: string | null;
  image_mime: string;
  merchant_tax_id: string | null;
  subtotal: Money | null;
  tax_total: Money | null;
  fx_rate: Money | null;
  notes: string | null;
  ai_model: string | null;
  ai_error: string | null;
  scan_attempts: number;
  scanned_at: string | null;
  confirmed_by_id: UUID | null;
  confirmed_at: string | null;
  line_items: LineItem[];
}

export interface DocumentPage {
  items: DocumentSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface UploadResult {
  document: DocumentDetail;
  /** Set when an identical photo is already on file. A warning, not an error. */
  duplicate_of: UUID | null;
}

export interface DocumentUpdate {
  funding_source?: FundingSource;
  payer_id?: UUID;
  title?: string | null;
  merchant_name?: string | null;
  merchant_tax_id?: string | null;
  document_date?: IsoDate | null;
  currency?: string;
  subtotal?: Money | null;
  tax_total?: Money | null;
  total?: Money | null;
  fx_rate?: Money | null;
  notes?: string | null;
  category?: string | null;
  line_items?: Omit<LineItem, "id" | "line_no">[];
}

export interface PartnerBalance {
  user_id: UUID;
  display_name: string;
  equity_share: Money;
  personal_outlay: Money;
  business_outlay: Money;
  unverified_outlay: Money;
  fair_share: Money;
  settlements_received: Money;
  settlements_paid: Money;
  /** Positive: the partnership owes them. Negative: they owe it. */
  net_position: Money;
  document_count: number;
}

export interface SettlementSuggestion {
  from_user_id: UUID;
  from_display_name: string;
  to_user_id: UUID;
  to_display_name: string;
  amount: Money;
}

export interface BalanceReport {
  base_currency: string;
  period_start: IsoDate | null;
  period_end: IsoDate | null;
  total_personal_outlay: Money;
  total_business_outlay: Money;
  total_unverified: Money;
  partners: PartnerBalance[];
  suggested_settlements: SettlementSuggestion[];
  excluded_document_count: number;
}

export interface CategoryTotal {
  category: string | null;
  funding_source: FundingSource;
  total_base: Money;
  document_count: number;
}

export interface DashboardSummary {
  base_currency: string;
  pending_scans: number;
  needs_review: number;
  failed_scans: number;
  receipts_this_month: number;
  spend_this_month: Money;
  top_categories: CategoryTotal[];
}

export interface Settlement {
  id: UUID;
  from_user_id: UUID;
  to_user_id: UUID;
  amount_base: Money;
  settled_on: IsoDate;
  note: string | null;
  created_by_id: UUID | null;
  created_at: string;
}

export interface ExchangeRate {
  id: UUID;
  currency: string;
  rate_to_base: Money;
  effective_from: IsoDate;
  note: string | null;
  created_at: string;
}

export interface SystemStatus {
  base_currency: string;
  currencies: string[];
  heic_support: boolean;
  ai: {
    reachable: boolean;
    model: string;
    model_installed: boolean;
    installed_models: string[];
    hint: string | null;
  };
}
