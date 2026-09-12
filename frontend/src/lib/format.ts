/**
 * Display formatting.
 *
 * Numbers and dates render in the `ro-RO` locale - `1.234,56 RON`, `03.04.2025` -
 * because that is how the receipts themselves are printed, and a ledger that
 * formats differently from the paperwork it mirrors is needlessly hard to check.
 * Interface labels are in English; they all live here so translating the app is
 * one file.
 */

import type { DocumentStatus, FundingSource, Money } from "../api/types";

const LOCALE = "ro-RO";

/** Parse a backend money string for display or comparison only. */
export function toNumber(value: Money | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function formatMoney(
  value: Money | null | undefined,
  currency = "RON",
  options: { signed?: boolean; hideCurrency?: boolean } = {},
): string {
  const amount = toNumber(value);
  const formatter = new Intl.NumberFormat(LOCALE, {
    style: options.hideCurrency ? "decimal" : "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: options.signed ? "exceptZero" : "auto",
  });
  return formatter.format(amount);
}

/** Compact form for dashboard tiles: 12.400 rather than 12.400,00. */
export function formatMoneyCompact(value: Money | null | undefined, currency = "RON"): string {
  const amount = toNumber(value);
  if (Math.abs(amount) >= 100_000) {
    return new Intl.NumberFormat(LOCALE, {
      style: "currency",
      currency,
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(amount);
  }
  return formatMoney(value, currency);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** `YYYY-MM-DD` for a date input, from a Date or an ISO string. */
export function toDateInput(value: string | Date | null | undefined): string {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function today(): string {
  return toDateInput(new Date());
}

export function firstOfThisMonth(): string {
  const now = new Date();
  return toDateInput(new Date(now.getFullYear(), now.getMonth(), 1));
}

export function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

// --- labels ----------------------------------------------------------------

export const SCOPE_LABEL: Record<FundingSource, string> = {
  BUSINESS: "Business money",
  PERSONAL: "Own money",
};

export const SCOPE_SHORT: Record<FundingSource, string> = {
  BUSINESS: "Business",
  PERSONAL: "Personal",
};

export const SCOPE_DESCRIPTION: Record<FundingSource, string> = {
  BUSINESS: "Paid from the company account. Recorded, but nobody is owed anything.",
  PERSONAL: "Paid from your own pocket for the business. The business owes you this back.",
};

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  PENDING: "Queued",
  PROCESSING: "Reading",
  PARSED: "Read",
  NEEDS_REVIEW: "Check it",
  CONFIRMED: "Verified",
  FAILED: "Failed",
};

export const STATUS_EXPLANATION: Record<DocumentStatus, string> = {
  PENDING: "Waiting for the scanner to pick it up.",
  PROCESSING: "The model is reading this receipt now.",
  PARSED: "Read confidently, but nobody has checked the numbers yet.",
  NEEDS_REVIEW: "The reading is uncertain. Check the total against the photo.",
  CONFIRMED: "A person has verified these numbers against the photo.",
  FAILED: "Could not be read. Enter the numbers by hand.",
};

export function confidenceLabel(value: number | null): string {
  if (value === null) return "Not scanned";
  if (value >= 0.85) return "High confidence";
  if (value >= 0.6) return "Moderate confidence";
  return "Low confidence";
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
