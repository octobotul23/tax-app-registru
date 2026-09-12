import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { Field } from "../components/ui";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <form className="auth__card" onSubmit={submit}>
        <div className="stack stack--tight">
          <div className="row">
            <span className="sidebar__mark" aria-hidden="true">R</span>
            <h1>Registru</h1>
          </div>
          <p className="muted small">
            Shared ledger for receipts and business spending.
          </p>
        </div>

        {error ? (
          <div className="notice notice--bad" role="alert">
            {error}
          </div>
        ) : null}

        <Field label="Email">
          <input
            className="input"
            type="email"
            name="email"
            autoComplete="username"
            required
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>

        <Field label="Password">
          <input
            className="input"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>

        <button className="btn btn--primary btn--lg btn--block" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="xs subtle center">
          Accounts are created by an administrator. There is no public sign-up.
        </p>
      </form>
    </div>
  );
}
