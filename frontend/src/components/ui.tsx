/** Shared presentational pieces. No data fetching lives here. */

import type { ReactNode } from "react";

import type { DocumentStatus, FundingSource } from "../api/types";
import {
  SCOPE_SHORT,
  STATUS_EXPLANATION,
  STATUS_LABEL,
  initials,
} from "../lib/format";

export function ScopeChip({ scope }: { scope: FundingSource }) {
  return (
    <span className="chip chip--scope" data-scope={scope}>
      {SCOPE_SHORT[scope]}
    </span>
  );
}

export function StatusChip({ status }: { status: DocumentStatus }) {
  return (
    <span
      className="chip chip--status"
      data-status={status}
      title={STATUS_EXPLANATION[status]}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

export function Avatar({ name }: { name: string }) {
  return (
    <span className="avatar" aria-hidden="true">
      {initials(name)}
    </span>
  );
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn" | "good" | "bad";
  children: ReactNode;
}) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "bad" ? "alert" : undefined}>
      <div className="grow">{children}</div>
    </div>
  );
}

export function Empty({
  icon = "◇",
  title,
  children,
}: {
  icon?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty__icon" aria-hidden="true">{icon}</div>
      <h3>{title}</h3>
      {children ? <p className="small">{children}</p> : null}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row" role="status">
      <span className="spinner" aria-hidden="true" />
      {label ? <span className="small muted">{label}</span> : null}
      <span className="visually-hidden">Loading</span>
    </span>
  );
}

export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className="stack" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="skeleton" style={{ height: 56 }} />
      ))}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="label">{label}</span>
      {children}
      {hint ? <span className="hint">{hint}</span> : null}
    </label>
  );
}

/**
 * The business-versus-personal choice.
 *
 * Given its own oversized control rather than a dropdown because it is the one
 * decision that changes what the ledger does with the money - everything else
 * on the upload screen is just description.
 */
export function ScopePicker({
  value,
  onChange,
  name = "funding_source",
}: {
  value: FundingSource;
  onChange: (next: FundingSource) => void;
  name?: string;
}) {
  const options: Array<{ scope: FundingSource; title: string; desc: string }> = [
    {
      scope: "BUSINESS",
      title: "Business money",
      desc: "Paid from the company account. Nobody is owed anything.",
    },
    {
      scope: "PERSONAL",
      title: "My own money",
      desc: "Paid out of pocket for the business. The business owes it back.",
    },
  ];

  return (
    <div className="choice" role="radiogroup" aria-label="Whose money paid for this">
      {options.map((option) => (
        <label
          key={option.scope}
          className="choice__option"
          data-scope={option.scope}
          data-selected={value === option.scope}
        >
          <input
            type="radio"
            name={name}
            value={option.scope}
            checked={value === option.scope}
            onChange={() => onChange(option.scope)}
          />
          <span className="choice__title">{option.title}</span>
          <span className="choice__desc">{option.desc}</span>
        </label>
      ))}
    </div>
  );
}

export function PageHead({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page__head">
      <div className="page__title">
        <h1>{title}</h1>
        {subtitle ? <p className="muted small">{subtitle}</p> : null}
      </div>
      {actions ? <div className="row">{actions}</div> : null}
    </header>
  );
}
