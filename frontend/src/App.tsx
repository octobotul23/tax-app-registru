import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "./lib/auth";
import Balance from "./pages/Balance";
import Dashboard from "./pages/Dashboard";
import DocumentDetail from "./pages/DocumentDetail";
import Documents from "./pages/Documents";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import Upload from "./pages/Upload";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/upload", label: "Upload" },
  { to: "/documents", label: "Documents" },
  { to: "/balance", label: "Who paid" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  const { user, checking, signOut } = useAuth();

  if (checking) {
    return (
      <div className="auth">
        <div className="row">
          <span className="spinner" aria-hidden="true" />
          <span className="muted">Loading…</span>
        </div>
      </div>
    );
  }

  if (!user) return <Login />;

  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <div className="sidebar__brand">
          <span className="sidebar__mark" aria-hidden="true">R</span>
          <span>Registru</span>
        </div>

        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className="navlink">
            {item.label}
          </NavLink>
        ))}

        <div className="sidebar__footer">
          <div className="row">
            <span className="avatar" aria-hidden="true">
              {user.display_name.slice(0, 2).toUpperCase()}
            </span>
            <div className="grow truncate">
              <div className="small truncate">{user.display_name}</div>
              <div className="xs subtle truncate">{user.email}</div>
            </div>
          </div>
          <button
            className="btn btn--ghost btn--sm btn--block"
            type="button"
            onClick={() => void signOut()}
            style={{ marginTop: "var(--space-3)" }}
          >
            Sign out
          </button>
        </div>
      </nav>

      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:id" element={<DocumentDetail />} />
          <Route path="/balance" element={<Balance />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
