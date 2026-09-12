import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type {
  DocumentUpdate,
  FundingSource,
  LineItem,
  UUID,
} from "../api/types";
import {
  Field,
  Notice,
  ScopeChip,
  ScopePicker,
  StatusChip,
} from "../components/ui";
import {
  STATUS_EXPLANATION,
  confidenceLabel,
  formatDateTime,
  formatMoney,
  toDateInput,
  toNumber,
} from "../lib/format";
import { useAsync, usePolling } from "../lib/hooks";

type Draft = {
  funding_source: FundingSource;
  payer_id: UUID;
  title: string;
  merchant_name: string;
  merchant_tax_id: string;
  document_date: string;
  currency: string;
  subtotal: string;
  tax_total: string;
  total: string;
  category: string;
  notes: string;
  line_items: LineItem[];
};

export default function DocumentDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();

  const document_ = useAsync(() => api.document(id), [id]);
  const users = useAsync(() => api.users(), []);
  const currencies = useAsync(() => api.currencies(), []);

  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const doc = document_.data;
  const scanning = doc?.status === "PENDING" || doc?.status === "PROCESSING";

  usePolling(() => document_.reload(), 4000, Boolean(scanning));

  // Rebuild the form whenever a fresh version arrives - which includes the
  // moment the scan finishes and fills the fields in underneath the user.
  useEffect(() => {
    if (!doc) return;
    setDraft({
      funding_source: doc.funding_source,
      payer_id: doc.payer_id,
      title: doc.title ?? "",
      merchant_name: doc.merchant_name ?? "",
      merchant_tax_id: doc.merchant_tax_id ?? "",
      document_date: toDateInput(doc.document_date),
      currency: doc.currency ?? "RON",
      subtotal: doc.subtotal ?? "",
      tax_total: doc.tax_total ?? "",
      total: doc.total ?? "",
      category: doc.category ?? "",
      notes: doc.notes ?? "",
      line_items: doc.line_items.map((item) => ({ ...item })),
    });
  }, [doc]);

  function edit<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
    setSaved(false);
  }

  function editLine(index: number, changes: Partial<LineItem>) {
    setDraft((current) => {
      if (!current) return current;
      const next = [...current.line_items];
      const existing = next[index];
      if (!existing) return current;
      next[index] = { ...existing, ...changes };
      return { ...current, line_items: next };
    });
    setSaved(false);
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const payload: DocumentUpdate = {
        funding_source: draft.funding_source,
        payer_id: draft.payer_id,
        title: draft.title || null,
        merchant_name: draft.merchant_name || null,
        merchant_tax_id: draft.merchant_tax_id || null,
        document_date: draft.document_date || null,
        currency: draft.currency,
        subtotal: draft.subtotal || null,
        tax_total: draft.tax_total || null,
        total: draft.total || null,
        category: draft.category || null,
        notes: draft.notes || null,
        line_items: draft.line_items.map((item) => ({
          description: item.description,
          quantity: item.quantity || null,
          unit_price: item.unit_price || null,
          line_total: item.line_total || null,
          vat_rate: item.vat_rate || null,
          category: item.category || null,
        })),
      };
      const updated = await api.updateDocument(id, payload);
      document_.setData(updated);
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm("Remove this document from the ledger? The photo is kept.")) return;
    try {
      await api.deleteDocument(id);
      navigate("/documents");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not delete");
    }
  }

  if (document_.error) {
    return (
      <div className="page page--narrow">
        <Notice tone="bad">{document_.error}</Notice>
        <Link className="btn btn--outline" to="/documents">
          Back to documents
        </Link>
      </div>
    );
  }

  if (!doc || !draft) {
    return (
      <div className="page page--narrow">
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  // Independent arithmetic, recomputed live as the user types. This is the
  // same check the backend scores with - surfacing it here is what turns
  // reviewing from "read every digit" into "confirm the sum agrees".
  const lineSum = draft.line_items.reduce(
    (running, item) => running + toNumber(item.line_total),
    0,
  );
  const statedTotal = toNumber(draft.total);
  const pricedLines = draft.line_items.filter((item) => item.line_total).length;
  const sumMismatch =
    pricedLines >= 2 && statedTotal > 0 && Math.abs(lineSum - statedTotal) > 0.05;

  return (
    <div className="page">
      <header className="page__head">
        <div className="page__title">
          <div className="row row--wrap">
            <ScopeChip scope={doc.funding_source} />
            <StatusChip status={doc.status} />
            {doc.ai_confidence !== null ? (
              <span className="xs subtle">{confidenceLabel(doc.ai_confidence)}</span>
            ) : null}
          </div>
          <h1>{doc.merchant_name ?? doc.title ?? "Untitled document"}</h1>
          <p className="muted small">{STATUS_EXPLANATION[doc.status]}</p>
        </div>
        <div className="row">
          <Link className="btn btn--ghost" to="/documents">
            Back
          </Link>
          <button className="btn btn--danger" type="button" onClick={() => void remove()}>
            Remove
          </button>
        </div>
      </header>

      {error ? <Notice tone="bad">{error}</Notice> : null}
      {saved ? <Notice tone="good">Saved and marked as verified by you.</Notice> : null}

      {doc.ai_error ? (
        <Notice tone="warn">
          <strong>Scanner note:</strong> {doc.ai_error}
        </Notice>
      ) : null}

      {scanning ? (
        <Notice tone="info">
          <span className="row">
            <span className="spinner" aria-hidden="true" />
            Reading this document now. The fields will fill in on their own.
          </span>
        </Notice>
      ) : null}

      {sumMismatch ? (
        <Notice tone="warn">
          The listed items add up to{" "}
          <strong>{formatMoney(String(lineSum), draft.currency)}</strong> but the total
          says <strong>{formatMoney(draft.total, draft.currency)}</strong>. One of them
          was misread — check the photo before saving.
        </Notice>
      ) : null}

      <div className="review">
        <div className="review__photo">
          <a href={api.imageUrl(doc.id)} target="_blank" rel="noreferrer">
            <img src={api.imageUrl(doc.id)} alt="The uploaded document" />
          </a>
        </div>

        <div className="stack stack--loose">
          <section className="card stack">
            <h3>Whose money</h3>
            <ScopePicker
              value={draft.funding_source}
              onChange={(next) => edit("funding_source", next)}
            />

            <Field label="Paid by">
              <select
                className="select"
                value={draft.payer_id}
                onChange={(event) => edit("payer_id", event.target.value)}
              >
                {users.data?.map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.display_name}
                  </option>
                ))}
              </select>
            </Field>
          </section>

          <section className="card stack">
            <h3>The numbers</h3>

            <div className="field-grid">
              <Field label="Merchant">
                <input
                  className="input"
                  value={draft.merchant_name}
                  onChange={(event) => edit("merchant_name", event.target.value)}
                />
              </Field>

              <Field label="Fiscal code" hint="CUI / CIF">
                <input
                  className="input"
                  value={draft.merchant_tax_id}
                  onChange={(event) => edit("merchant_tax_id", event.target.value)}
                />
              </Field>

              <Field label="Date">
                <input
                  className="input"
                  type="date"
                  value={draft.document_date}
                  onChange={(event) => edit("document_date", event.target.value)}
                />
              </Field>

              <Field label="Currency">
                <select
                  className="select"
                  value={draft.currency}
                  onChange={(event) => edit("currency", event.target.value)}
                >
                  {(currencies.data ?? ["RON", "EUR", "USD"]).map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Net (before tax)">
                <input
                  className="input"
                  inputMode="decimal"
                  value={draft.subtotal}
                  onChange={(event) => edit("subtotal", event.target.value)}
                />
              </Field>

              <Field label="Tax (TVA)">
                <input
                  className="input"
                  inputMode="decimal"
                  value={draft.tax_total}
                  onChange={(event) => edit("tax_total", event.target.value)}
                />
              </Field>

              <Field label="Total" hint="The number that goes into the books">
                <input
                  className={`input${sumMismatch ? " input--error" : ""}`}
                  inputMode="decimal"
                  value={draft.total}
                  onChange={(event) => edit("total", event.target.value)}
                />
              </Field>

              <Field label="Category" hint="Free text, e.g. Materials, Fuel, Tools">
                <input
                  className="input"
                  value={draft.category}
                  onChange={(event) => edit("category", event.target.value)}
                />
              </Field>
            </div>

            {draft.currency !== "RON" && doc.total_base ? (
              <p className="hint">
                Valued at {formatMoney(doc.total_base, "RON")} using a rate of{" "}
                {doc.fx_rate ?? "—"}. Adjust the rate in Settings if your bank charged
                a different one.
              </p>
            ) : null}

            <Field label="Note">
              <textarea
                className="textarea"
                value={draft.notes}
                onChange={(event) => edit("notes", event.target.value)}
              />
            </Field>
          </section>

          <section className="card card--flush">
            <div className="card__head" style={{ padding: "var(--space-5)", marginBottom: 0 }}>
              <h3>Items</h3>
              <button
                className="btn btn--ghost btn--sm"
                type="button"
                onClick={() =>
                  edit("line_items", [
                    ...draft.line_items,
                    {
                      description: "",
                      quantity: null,
                      unit_price: null,
                      line_total: null,
                      vat_rate: null,
                      category: null,
                    },
                  ])
                }
              >
                Add row
              </button>
            </div>

            {draft.line_items.length === 0 ? (
              <p className="muted small" style={{ padding: "0 var(--space-5) var(--space-5)" }}>
                Nothing itemised. That is fine — only the total affects the balance.
              </p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Description</th>
                      <th className="num">Qty</th>
                      <th className="num">Unit</th>
                      <th className="num">Line total</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {draft.line_items.map((item, index) => (
                      <tr key={index}>
                        <td>
                          <input
                            className="input"
                            value={item.description}
                            onChange={(event) =>
                              editLine(index, { description: event.target.value })
                            }
                          />
                        </td>
                        <td className="num">
                          <input
                            className="input num"
                            inputMode="decimal"
                            style={{ width: 70 }}
                            value={item.quantity ?? ""}
                            onChange={(event) =>
                              editLine(index, { quantity: event.target.value || null })
                            }
                          />
                        </td>
                        <td className="num">
                          <input
                            className="input num"
                            inputMode="decimal"
                            style={{ width: 90 }}
                            value={item.unit_price ?? ""}
                            onChange={(event) =>
                              editLine(index, { unit_price: event.target.value || null })
                            }
                          />
                        </td>
                        <td className="num">
                          <input
                            className="input num"
                            inputMode="decimal"
                            style={{ width: 100 }}
                            value={item.line_total ?? ""}
                            onChange={(event) =>
                              editLine(index, { line_total: event.target.value || null })
                            }
                          />
                        </td>
                        <td>
                          <button
                            className="btn btn--ghost btn--sm"
                            type="button"
                            aria-label={`Remove row ${index + 1}`}
                            onClick={() =>
                              edit(
                                "line_items",
                                draft.line_items.filter((_, i) => i !== index),
                              )
                            }
                          >
                            ×
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={3} className="right muted small">
                        Items add up to
                      </td>
                      <td className="num money">
                        {formatMoney(String(lineSum), draft.currency)}
                      </td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </section>

          <div className="row row--between">
            <div className="xs subtle">
              {doc.ai_model ? (
                <>
                  Read by {doc.ai_model}
                  {doc.scanned_at ? ` on ${formatDateTime(doc.scanned_at)}` : ""}.{" "}
                </>
              ) : null}
              {doc.confirmed_at ? `Verified ${formatDateTime(doc.confirmed_at)}.` : null}
            </div>
            <div className="row">
              <button
                className="btn btn--outline"
                type="button"
                disabled={scanning}
                onClick={() => void api.rescan(id).then(() => document_.reload())}
              >
                Scan again
              </button>
              <button
                className="btn btn--primary"
                type="button"
                disabled={saving}
                onClick={() => void save()}
              >
                {saving ? "Saving…" : "Save and verify"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
