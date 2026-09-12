import { useState, type FormEvent } from "react";

import { ApiError, api } from "../api/client";
import { Avatar, Field, Notice, PageHead } from "../components/ui";
import { formatDate, today } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { useAuth } from "../lib/auth";

export default function Settings() {
  const { user, refresh } = useAuth();
  const users = useAsync(() => api.users(), []);
  const rates = useAsync(() => api.rates(), []);
  const currencies = useAsync(() => api.currencies(), []);
  const status = useAsync(() => api.systemStatus(), []);

  const [message, setMessage] = useState<{ tone: "good" | "bad"; text: string } | null>(
    null,
  );
  const [addingPartner, setAddingPartner] = useState(false);

  function report(tone: "good" | "bad", text: string) {
    setMessage({ tone, text });
    window.setTimeout(() => setMessage(null), 6000);
  }

  async function createPartner(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api.createUser({
        email: String(form.get("email")),
        password: String(form.get("password")),
        display_name: String(form.get("display_name")),
        equity_share: String(form.get("equity_share") || "0.5"),
      });
      setAddingPartner(false);
      users.reload();
      report("good", "Partner account created.");
    } catch (cause) {
      report("bad", cause instanceof ApiError ? cause.message : "Could not create it");
    }
  }

  async function saveRate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api.saveRate({
        currency: String(form.get("currency")),
        rate_to_base: String(form.get("rate_to_base")),
        effective_from: String(form.get("effective_from")),
        note: String(form.get("note") ?? "") || undefined,
      });
      rates.reload();
      report("good", "Rate saved.");
    } catch (cause) {
      report("bad", cause instanceof ApiError ? cause.message : "Could not save the rate");
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api.changePassword(
        String(form.get("current_password")),
        String(form.get("new_password")),
      );
      (event.target as HTMLFormElement).reset();
      report("good", "Password changed.");
    } catch (cause) {
      report("bad", cause instanceof ApiError ? cause.message : "Could not change it");
    }
  }

  async function revalue() {
    try {
      const result = await api.revalue();
      rates.reload();
      report(
        "good",
        `Checked ${result.examined} document(s); ${result.revalued} now have a value in lei.`,
      );
    } catch (cause) {
      report("bad", cause instanceof ApiError ? cause.message : "Could not revalue");
    }
  }

  const base = status.data?.base_currency ?? "RON";
  const foreign = (currencies.data ?? []).filter((code) => code !== base);

  return (
    <div className="page page--narrow">
      <PageHead title="Settings" />

      {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}

      {/* --- system health ------------------------------------------------ */}
      <section className="card stack">
        <div className="card__head">
          <h3>Receipt scanner</h3>
          <button className="btn btn--ghost btn--sm" type="button" onClick={status.reload}>
            Check again
          </button>
        </div>

        {status.loading ? (
          <div className="skeleton" style={{ height: 60 }} />
        ) : status.data?.ai.reachable && status.data.ai.model_installed ? (
          <Notice tone="good">
            Working. Receipts are read by <strong>{status.data.ai.model}</strong> on your
            own server — no image ever leaves the machine.
          </Notice>
        ) : status.data?.ai.reachable ? (
          <Notice tone="warn">
            The model server is up, but <strong>{status.data.ai.model}</strong> is not
            installed. Uploads will queue until it is.
            {status.data.ai.hint ? (
              <div className="mono xs" style={{ marginTop: "var(--space-2)" }}>
                {status.data.ai.hint}
              </div>
            ) : null}
          </Notice>
        ) : (
          <Notice tone="bad">
            Cannot reach the model server. Uploads still work and will be read once it
            comes back.
          </Notice>
        )}

        {status.data && !status.data.heic_support ? (
          <Notice tone="warn">
            HEIC support is missing, so photos straight from an iPhone will be
            rejected. Install <span className="mono">pillow-heif</span> on the server.
          </Notice>
        ) : null}
      </section>

      {/* --- partners ----------------------------------------------------- */}
      <section className="card stack">
        <div className="card__head">
          <h3>Partners</h3>
          {user?.is_admin && !addingPartner ? (
            <button
              className="btn btn--outline btn--sm"
              type="button"
              onClick={() => setAddingPartner(true)}
            >
              Add partner
            </button>
          ) : null}
        </div>

        <div className="stack stack--tight">
          {users.data?.map((partner) => (
            <div className="row" key={partner.id}>
              <Avatar name={partner.display_name} />
              <div className="grow truncate">
                <div>{partner.display_name}</div>
                <div className="xs subtle truncate">{partner.email}</div>
              </div>
              <span className="xs subtle nowrap">
                {(Number(partner.equity_share) * 100).toFixed(0)}% share
              </span>
              {!partner.is_active ? (
                <span className="chip chip--status" data-status="FAILED">
                  Inactive
                </span>
              ) : null}
            </div>
          ))}
        </div>

        <p className="hint">
          Shares decide each partner's fair portion of what has been funded
          personally. Two equal partners are 50% each.
        </p>

        {addingPartner ? (
          <form className="stack" onSubmit={createPartner}>
            <div className="field-grid">
              <Field label="Name">
                <input className="input" name="display_name" required />
              </Field>
              <Field label="Email">
                <input className="input" name="email" type="email" required />
              </Field>
              <Field label="Password" hint="At least 10 characters">
                <input
                  className="input"
                  name="password"
                  type="password"
                  minLength={10}
                  required
                />
              </Field>
              <Field label="Share" hint="0.5 for an equal partner">
                <input
                  className="input"
                  name="equity_share"
                  inputMode="decimal"
                  defaultValue="0.5"
                />
              </Field>
            </div>
            <div className="row row--end">
              <button
                className="btn btn--ghost"
                type="button"
                onClick={() => setAddingPartner(false)}
              >
                Cancel
              </button>
              <button className="btn btn--primary" type="submit">
                Create account
              </button>
            </div>
          </form>
        ) : null}
      </section>

      {/* --- exchange rates ----------------------------------------------- */}
      <section className="card stack">
        <div className="card__head">
          <h3>Exchange rates</h3>
          <button className="btn btn--ghost btn--sm" type="button" onClick={() => void revalue()}>
            Re-value stuck receipts
          </button>
        </div>

        <p className="hint">
          Everything is reported in {base}. Enter the rate your bank actually gave you —
          a rate applies from its date until you enter a newer one, so historical
          receipts keep the value they had at the time.
        </p>

        {rates.data?.some((rate) => rate.note?.startsWith("PLACEHOLDER")) ? (
          <Notice tone="warn">
            Some rates are still the placeholder values set at install. Replace them
            before relying on any figure in a foreign currency.
          </Notice>
        ) : null}

        {rates.data?.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Currency</th>
                  <th className="num">1 unit = {base}</th>
                  <th>From</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rates.data.map((rate) => (
                  <tr key={rate.id}>
                    <td>{rate.currency}</td>
                    <td className="num money">{rate.rate_to_base}</td>
                    <td className="nowrap">
                      {formatDate(rate.effective_from)}
                      {rate.note ? <div className="xs subtle">{rate.note}</div> : null}
                    </td>
                    <td>
                      <button
                        className="btn btn--ghost btn--sm"
                        type="button"
                        aria-label={`Delete the ${rate.currency} rate`}
                        onClick={() => {
                          if (!window.confirm("Delete this rate?")) return;
                          void api.deleteRate(rate.id).then(rates.reload);
                        }}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {foreign.length ? (
          <form className="stack" onSubmit={saveRate}>
            <div className="field-grid">
              <Field label="Currency">
                <select className="select" name="currency" defaultValue={foreign[0]}>
                  {foreign.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={`Rate into ${base}`} hint={`e.g. 4,97 if 1 EUR = 4,97 ${base}`}>
                <input className="input" name="rate_to_base" inputMode="decimal" required />
              </Field>
              <Field label="Effective from">
                <input
                  className="input"
                  name="effective_from"
                  type="date"
                  defaultValue={today()}
                  required
                />
              </Field>
              <Field label="Note">
                <input className="input" name="note" placeholder="Optional" />
              </Field>
            </div>
            <div className="row row--end">
              <button className="btn btn--primary" type="submit">
                Save rate
              </button>
            </div>
          </form>
        ) : null}
      </section>

      {/* --- password ------------------------------------------------------ */}
      <section className="card stack">
        <h3>Your password</h3>
        <form className="stack" onSubmit={changePassword}>
          <div className="field-grid">
            <Field label="Current password">
              <input
                className="input"
                name="current_password"
                type="password"
                autoComplete="current-password"
                required
              />
            </Field>
            <Field label="New password" hint="At least 10 characters">
              <input
                className="input"
                name="new_password"
                type="password"
                autoComplete="new-password"
                minLength={10}
                required
              />
            </Field>
          </div>
          <div className="row row--end">
            <button className="btn btn--outline" type="submit">
              Change password
            </button>
          </div>
        </form>
      </section>

      <button
        className="btn btn--ghost btn--sm"
        type="button"
        onClick={() => void refresh()}
        style={{ alignSelf: "flex-start" }}
      >
        Refresh account details
      </button>
    </div>
  );
}
