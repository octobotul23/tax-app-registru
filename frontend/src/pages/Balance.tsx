import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { SettlementSuggestion } from "../api/types";
import { Avatar, Empty, Field, Notice, PageHead } from "../components/ui";
import {
  firstOfThisMonth,
  formatDate,
  formatMoney,
  today,
  toNumber,
} from "../lib/format";
import { useAsync } from "../lib/hooks";

export default function Balance() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const report = useAsync(
    () => api.balance({ period_start: from || undefined, period_end: to || undefined }),
    [from, to],
  );
  const users = useAsync(() => api.users(), []);
  const settlements = useAsync(() => api.settlements(), []);

  const [recording, setRecording] = useState<SettlementSuggestion | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currency = report.data?.base_currency ?? "RON";

  async function recordSettlement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!recording) return;

    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      await api.createSettlement({
        from_user_id: recording.from_user_id,
        to_user_id: recording.to_user_id,
        amount_base: String(form.get("amount") ?? ""),
        settled_on: String(form.get("settled_on") ?? today()),
        note: String(form.get("note") ?? "") || undefined,
      });
      setRecording(null);
      report.reload();
      settlements.reload();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not record it");
    }
  }

  return (
    <div className="page">
      <PageHead
        title="Who paid how much"
        subtitle="Money each of you put in from your own pocket, and what that means you are owed."
      />

      <section className="card">
        <div className="row row--wrap">
          <Field label="From">
            <input
              className="input"
              type="date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
            />
          </Field>
          <Field label="To">
            <input
              className="input"
              type="date"
              value={to}
              onChange={(event) => setTo(event.target.value)}
            />
          </Field>
          <div className="row" style={{ alignSelf: "flex-end", paddingBottom: 2 }}>
            <button
              className="btn btn--outline btn--sm"
              type="button"
              onClick={() => {
                setFrom(firstOfThisMonth());
                setTo(today());
              }}
            >
              This month
            </button>
            <button
              className="btn btn--ghost btn--sm"
              type="button"
              onClick={() => {
                setFrom("");
                setTo("");
              }}
            >
              All time
            </button>
          </div>
        </div>
      </section>

      {report.error ? <Notice tone="bad">{report.error}</Notice> : null}
      {error ? <Notice tone="bad">{error}</Notice> : null}

      {report.data && toNumber(report.data.total_unverified) > 0 ? (
        <Notice tone="warn">
          <strong>{formatMoney(report.data.total_unverified, currency)}</strong> of
          this comes from readings nobody has checked yet. Those totals are the
          model's word, not a person's.{" "}
          <Link to="/documents?status=NEEDS_REVIEW">Check them</Link>
        </Notice>
      ) : null}

      {report.data && report.data.excluded_document_count > 0 ? (
        <Notice tone="info">
          {report.data.excluded_document_count} document
          {report.data.excluded_document_count === 1 ? " is" : "s are"} left out —
          still queued, or the total could not be read.{" "}
          <Link to="/documents?status=FAILED">See which</Link>
        </Notice>
      ) : null}

      {/* The headline answer. */}
      {report.data?.suggested_settlements.length ? (
        <section className="stack">
          {report.data.suggested_settlements.map((suggestion) => (
            <div
              className="settle-banner"
              key={`${suggestion.from_user_id}-${suggestion.to_user_id}`}
            >
              <div>
                <strong>{suggestion.from_display_name}</strong> owes{" "}
                <strong>{suggestion.to_display_name}</strong>{" "}
                <strong>{formatMoney(suggestion.amount, currency)}</strong>
                <div className="small" style={{ opacity: 0.85 }}>
                  To even out what each of you has funded personally.
                </div>
              </div>
              <button
                className="btn btn--primary"
                type="button"
                onClick={() => setRecording(suggestion)}
              >
                Mark as paid
              </button>
            </div>
          ))}
        </section>
      ) : report.data && !report.loading ? (
        <Notice tone="good">
          You are square. Neither of you owes the other anything for this period.
        </Notice>
      ) : null}

      {recording ? (
        <form className="card stack" onSubmit={recordSettlement}>
          <h3>
            Record: {recording.from_display_name} paid {recording.to_display_name}
          </h3>
          <div className="field-grid">
            <Field label={`Amount (${currency})`}>
              <input
                className="input"
                name="amount"
                inputMode="decimal"
                defaultValue={recording.amount}
                required
              />
            </Field>
            <Field label="Date">
              <input
                className="input"
                name="settled_on"
                type="date"
                defaultValue={today()}
                required
              />
            </Field>
            <Field label="Note" hint="Optional, e.g. bank transfer">
              <input className="input" name="note" />
            </Field>
          </div>
          <div className="row row--end">
            <button className="btn btn--ghost" type="button" onClick={() => setRecording(null)}>
              Cancel
            </button>
            <button className="btn btn--primary" type="submit">
              Record payment
            </button>
          </div>
        </form>
      ) : null}

      <section className="grid grid--2">
        {report.data?.partners.map((partner) => {
          const net = toNumber(partner.net_position);
          const tone = net > 0.01 ? "owed" : net < -0.01 ? "owing" : "zero";
          return (
            <article className="balance-card" key={partner.user_id}>
              <div className="balance-card__name">
                <Avatar name={partner.display_name} />
                <span className="grow">{partner.display_name}</span>
                <span className="xs subtle">
                  {(toNumber(partner.equity_share) * 100).toFixed(0)}% share
                </span>
              </div>

              <div>
                <div className="ledger-line">
                  <span>Paid from own pocket</span>
                  <span className="money">
                    {formatMoney(partner.personal_outlay, currency)}
                  </span>
                </div>
                <div className="ledger-line">
                  <span className="muted">Their fair share of that</span>
                  <span className="money muted">
                    −{formatMoney(partner.fair_share, currency)}
                  </span>
                </div>
                {toNumber(partner.settlements_received) > 0 ? (
                  <div className="ledger-line">
                    <span className="muted">Already paid back to them</span>
                    <span className="money muted">
                      −{formatMoney(partner.settlements_received, currency)}
                    </span>
                  </div>
                ) : null}
                {toNumber(partner.settlements_paid) > 0 ? (
                  <div className="ledger-line">
                    <span className="muted">They paid the other partner</span>
                    <span className="money muted">
                      +{formatMoney(partner.settlements_paid, currency)}
                    </span>
                  </div>
                ) : null}

                <div className="ledger-line ledger-line--total">
                  <span>
                    {tone === "owed"
                      ? "Owed to them"
                      : tone === "owing"
                        ? "They owe"
                        : "Square"}
                  </span>
                  <span className={`money money--${tone}`}>
                    {formatMoney(String(Math.abs(net)), currency)}
                  </span>
                </div>
              </div>

              <div className="xs subtle">
                {partner.document_count} receipt
                {partner.document_count === 1 ? "" : "s"} · spent{" "}
                {formatMoney(partner.business_outlay, currency)} of business money
                {toNumber(partner.unverified_outlay) > 0
                  ? ` · ${formatMoney(partner.unverified_outlay, currency)} unchecked`
                  : ""}
              </div>
            </article>
          );
        })}
      </section>

      <section className="grid grid--2">
        <div className="card">
          <div className="card__head">
            <h3>Totals</h3>
          </div>
          <div className="ledger-line">
            <span>Funded personally, both of you</span>
            <span className="money">
              {formatMoney(report.data?.total_personal_outlay, currency)}
            </span>
          </div>
          <div className="ledger-line">
            <span>Spent from business money</span>
            <span className="money">
              {formatMoney(report.data?.total_business_outlay, currency)}
            </span>
          </div>
          <p className="hint" style={{ marginTop: "var(--space-3)" }}>
            Business-money spending is tracked for the books but creates no debt
            between the two of you — the company already paid for it.
          </p>
        </div>

        <div className="card card--flush">
          <div className="card__head" style={{ padding: "var(--space-5)", marginBottom: 0 }}>
            <h3>Payments between you</h3>
          </div>
          {settlements.data?.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>From → To</th>
                    <th className="num">Amount</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {settlements.data.map((entry) => {
                    const payer = users.data?.find((u) => u.id === entry.from_user_id);
                    const payee = users.data?.find((u) => u.id === entry.to_user_id);
                    return (
                      <tr key={entry.id}>
                        <td className="nowrap">{formatDate(entry.settled_on)}</td>
                        <td className="truncate">
                          {payer?.display_name ?? "?"} → {payee?.display_name ?? "?"}
                          {entry.note ? (
                            <div className="xs subtle truncate">{entry.note}</div>
                          ) : null}
                        </td>
                        <td className="num money">
                          {formatMoney(entry.amount_base, currency)}
                        </td>
                        <td>
                          <button
                            className="btn btn--ghost btn--sm"
                            type="button"
                            aria-label="Remove this payment"
                            onClick={() => {
                              if (!window.confirm("Remove this recorded payment?")) return;
                              void api.deleteSettlement(entry.id).then(() => {
                                settlements.reload();
                                report.reload();
                              });
                            }}
                          >
                            ×
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty icon="↔" title="No payments recorded">
              When one of you pays the other back, record it here so the balance
              returns to zero.
            </Empty>
          )}
        </div>
      </section>
    </div>
  );
}
