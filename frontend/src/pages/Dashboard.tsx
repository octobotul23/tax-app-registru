import { Link } from "react-router-dom";

import { api } from "../api/client";
import { Empty, Notice, PageHead, ScopeChip, SkeletonRows } from "../components/ui";
import { formatMoney, formatMoneyCompact } from "../lib/format";
import { useAsync, usePolling } from "../lib/hooks";

export default function Dashboard() {
  const summary = useAsync(() => api.dashboard(), []);
  const recent = useAsync(() => api.documents({ limit: 6 }), []);

  const scansInFlight = (summary.data?.pending_scans ?? 0) > 0;

  // While something is being read, refresh so the user watches it land rather
  // than wondering whether to reload.
  usePolling(
    () => {
      summary.reload();
      recent.reload();
    },
    5000,
    scansInFlight,
  );

  const currency = summary.data?.base_currency ?? "RON";

  return (
    <div className="page">
      <PageHead
        title="Overview"
        subtitle="What has been spent, and what still needs a look."
        actions={
          <Link className="btn btn--primary" to="/upload">
            Add receipt
          </Link>
        }
      />

      {summary.error ? <Notice tone="bad">{summary.error}</Notice> : null}

      {summary.data?.needs_review ? (
        <Notice tone="warn">
          <strong>{summary.data.needs_review}</strong>{" "}
          {summary.data.needs_review === 1 ? "document needs" : "documents need"} checking
          before {summary.data.needs_review === 1 ? "its total counts" : "their totals count"}{" "}
          as verified.{" "}
          <Link to="/documents?status=NEEDS_REVIEW">Review them</Link>
        </Notice>
      ) : null}

      {summary.data?.failed_scans ? (
        <Notice tone="bad">
          <strong>{summary.data.failed_scans}</strong> could not be read at all. Open each
          one and type the total in by hand.{" "}
          <Link to="/documents?status=FAILED">Show them</Link>
        </Notice>
      ) : null}

      <section className="grid">
        <div className="card">
          <div className="stat">
            <span className="stat__label">Spent this month</span>
            <span className="stat__value">
              {summary.loading ? "—" : formatMoneyCompact(summary.data?.spend_this_month, currency)}
            </span>
            <span className="stat__hint">
              {summary.data?.receipts_this_month ?? 0} receipts
            </span>
          </div>
        </div>

        <div className="card">
          <div className="stat">
            <span className="stat__label">Being read</span>
            <span className="stat__value">{summary.data?.pending_scans ?? 0}</span>
            <span className="stat__hint">
              {scansInFlight ? "The model is working through the queue" : "Nothing queued"}
            </span>
          </div>
        </div>

        <div className="card">
          <div className="stat">
            <span className="stat__label">Needs checking</span>
            <span className="stat__value">{summary.data?.needs_review ?? 0}</span>
            <span className="stat__hint">Uncertain readings</span>
          </div>
        </div>

        <div className="card">
          <div className="stat">
            <span className="stat__label">Failed</span>
            <span className="stat__value">{summary.data?.failed_scans ?? 0}</span>
            <span className="stat__hint">Enter these by hand</span>
          </div>
        </div>
      </section>

      <section className="grid grid--2">
        <div className="card">
          <div className="card__head">
            <h3>Where the money went</h3>
            <span className="xs subtle">Last 12 months</span>
          </div>

          {summary.loading ? (
            <SkeletonRows count={3} />
          ) : summary.data?.top_categories.length ? (
            <div className="stack stack--tight">
              {summary.data.top_categories.map((row, index) => (
                <div
                  key={`${row.category ?? "none"}-${row.funding_source}-${index}`}
                  className="ledger-line"
                >
                  <span className="row">
                    <ScopeChip scope={row.funding_source} />
                    <span>{row.category ?? "Uncategorised"}</span>
                  </span>
                  <span className="money">{formatMoney(row.total_base, currency)}</span>
                </div>
              ))}
            </div>
          ) : (
            <Empty title="Nothing categorised yet">
              Categories appear once you tag a few receipts while reviewing them.
            </Empty>
          )}
        </div>

        <div className="card card--flush">
          <div className="card__head" style={{ padding: "var(--space-5)", marginBottom: 0 }}>
            <h3>Latest uploads</h3>
            <Link className="small" to="/documents">
              See all
            </Link>
          </div>

          {recent.loading ? (
            <div style={{ padding: "0 var(--space-5) var(--space-5)" }}>
              <SkeletonRows count={4} />
            </div>
          ) : recent.data?.items.length ? (
            <div>
              {recent.data.items.map((document) => (
                <Link
                  key={document.id}
                  className="doc-row"
                  to={`/documents/${document.id}`}
                >
                  <img
                    className="doc-row__thumb"
                    src={api.thumbUrl(document.id)}
                    alt=""
                    loading="lazy"
                  />
                  <div className="doc-row__main">
                    <span className="doc-row__title truncate">
                      {document.merchant_name ?? document.title ?? "Untitled"}
                    </span>
                    <span className="doc-row__meta">
                      <ScopeChip scope={document.funding_source} />
                    </span>
                  </div>
                  <div className="doc-row__amount">
                    <span className="money">
                      {document.total
                        ? formatMoney(document.total, document.currency ?? currency)
                        : "—"}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <Empty icon="📄" title="No documents yet">
              Photograph a receipt to get started.
            </Empty>
          )}
        </div>
      </section>
    </div>
  );
}
