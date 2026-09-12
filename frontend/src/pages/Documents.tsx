import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { DocumentStatus, FundingSource } from "../api/types";
import {
  Empty,
  Notice,
  PageHead,
  ScopeChip,
  SkeletonRows,
  StatusChip,
} from "../components/ui";
import { formatDate, formatMoney } from "../lib/format";
import { useAsync, usePolling } from "../lib/hooks";

const PAGE_SIZE = 50;

export default function Documents() {
  // Filters live in the URL so a filtered view is linkable and survives a
  // reload - the dashboard links straight to "everything needing review".
  const [params, setParams] = useSearchParams();

  const filters = {
    kind: params.get("kind") ?? "",
    status: params.get("status") ?? "",
    funding_source: params.get("funding_source") ?? "",
    payer_id: params.get("payer_id") ?? "",
    search: params.get("search") ?? "",
    date_from: params.get("date_from") ?? "",
    date_to: params.get("date_to") ?? "",
  };
  const offset = Number(params.get("offset") ?? 0);

  // Debounce handle for the search box, cleared on unmount so a pending
  // keystroke cannot call setParams after the page has gone.
  const searchTimer = useRef<number | undefined>(undefined);
  useEffect(
    () => () => {
      if (searchTimer.current) window.clearTimeout(searchTimer.current);
    },
    [],
  );

  const users = useAsync(() => api.users(), []);
  const page = useAsync(
    () => api.documents({ ...filters, limit: PAGE_SIZE, offset }),
    [params.toString()],
  );

  const stillScanning = Boolean(
    page.data?.items.some(
      (item) => item.status === "PENDING" || item.status === "PROCESSING",
    ),
  );
  usePolling(() => page.reload(), 5000, stillScanning);

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset"); // a new filter always starts at the first page
    setParams(next, { replace: true });
  }

  function goToOffset(next: number) {
    const params2 = new URLSearchParams(params);
    if (next > 0) params2.set("offset", String(next));
    else params2.delete("offset");
    setParams(params2);
    window.scrollTo({ top: 0 });
  }

  const total = page.data?.total ?? 0;
  const showing = page.data?.items.length ?? 0;
  const hasFilters = Object.values(filters).some(Boolean);

  return (
    <div className="page">
      <PageHead
        title="Documents"
        subtitle={
          page.loading
            ? "Loading…"
            : `${total} document${total === 1 ? "" : "s"}${hasFilters ? " matching your filters" : ""}`
        }
        actions={
          <Link className="btn btn--primary" to="/upload">
            Add receipt
          </Link>
        }
      />

      <section className="card">
        <div className="field-grid">
          <label className="field">
            <span className="label">Search</span>
            <input
              className="input"
              type="search"
              placeholder="Merchant, note or item"
              defaultValue={filters.search}
              onChange={(event) => {
                // Debounced so typing does not fire a request per keystroke.
                const value = event.target.value;
                if (searchTimer.current) window.clearTimeout(searchTimer.current);
                searchTimer.current = window.setTimeout(
                  () => setFilter("search", value),
                  350,
                );
              }}
            />
          </label>

          <label className="field">
            <span className="label">Money</span>
            <select
              className="select"
              value={filters.funding_source}
              onChange={(event) => setFilter("funding_source", event.target.value)}
            >
              <option value="">Both</option>
              <option value="BUSINESS">Business money</option>
              <option value="PERSONAL">Own money</option>
            </select>
          </label>

          <label className="field">
            <span className="label">Status</span>
            <select
              className="select"
              value={filters.status}
              onChange={(event) => setFilter("status", event.target.value)}
            >
              <option value="">Any</option>
              <option value="NEEDS_REVIEW">Needs checking</option>
              <option value="CONFIRMED">Verified</option>
              <option value="PARSED">Read, unchecked</option>
              <option value="PENDING">Queued</option>
              <option value="FAILED">Failed</option>
            </select>
          </label>

          <label className="field">
            <span className="label">Paid by</span>
            <select
              className="select"
              value={filters.payer_id}
              onChange={(event) => setFilter("payer_id", event.target.value)}
            >
              <option value="">Anyone</option>
              {users.data?.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.display_name}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="label">Kind</span>
            <select
              className="select"
              value={filters.kind}
              onChange={(event) => setFilter("kind", event.target.value)}
            >
              <option value="">All</option>
              <option value="RECEIPT">Receipts</option>
              <option value="OBJECT_LIST">Object lists</option>
            </select>
          </label>

          <label className="field">
            <span className="label">From</span>
            <input
              className="input"
              type="date"
              value={filters.date_from}
              onChange={(event) => setFilter("date_from", event.target.value)}
            />
          </label>

          <label className="field">
            <span className="label">To</span>
            <input
              className="input"
              type="date"
              value={filters.date_to}
              onChange={(event) => setFilter("date_to", event.target.value)}
            />
          </label>
        </div>

        {hasFilters ? (
          <button
            className="btn btn--ghost btn--sm"
            type="button"
            style={{ marginTop: "var(--space-4)" }}
            onClick={() => setParams(new URLSearchParams(), { replace: true })}
          >
            Clear filters
          </button>
        ) : null}
      </section>

      {page.error ? <Notice tone="bad">{page.error}</Notice> : null}

      <section className="card card--flush">
        {page.loading && !page.data ? (
          <div style={{ padding: "var(--space-5)" }}>
            <SkeletonRows count={6} />
          </div>
        ) : showing === 0 ? (
          <Empty
            icon="🔍"
            title={hasFilters ? "Nothing matches those filters" : "No documents yet"}
          >
            {hasFilters
              ? "Try widening the date range or clearing a filter."
              : "Photograph a receipt and it will appear here."}
          </Empty>
        ) : (
          page.data?.items.map((document) => {
            const payer = users.data?.find((u) => u.id === document.payer_id);
            return (
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
                    {document.merchant_name ??
                      document.title ??
                      (document.kind === "OBJECT_LIST" ? "Object list" : "Unread receipt")}
                  </span>
                  <span className="doc-row__meta">
                    <ScopeChip scope={document.funding_source as FundingSource} />
                    <StatusChip status={document.status as DocumentStatus} />
                    <span>{formatDate(document.document_date ?? document.created_at)}</span>
                    {payer ? <span>· {payer.display_name}</span> : null}
                  </span>
                </div>
                <div className="doc-row__amount">
                  <span className="money">
                    {document.total
                      ? formatMoney(document.total, document.currency ?? "RON")
                      : "—"}
                  </span>
                  {document.currency && document.currency !== "RON" && document.total_base ? (
                    <span className="xs subtle money">
                      {formatMoney(document.total_base, "RON")}
                    </span>
                  ) : null}
                </div>
              </Link>
            );
          })
        )}
      </section>

      {total > PAGE_SIZE ? (
        <div className="row row--between">
          <button
            className="btn btn--outline"
            type="button"
            disabled={offset === 0}
            onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <span className="small muted">
            {offset + 1}–{offset + showing} of {total}
          </span>
          <button
            className="btn btn--outline"
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => goToOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}
