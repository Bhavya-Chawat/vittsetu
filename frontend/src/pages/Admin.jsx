import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import OverviewTab from '../components/admin/OverviewTab';
import PartnersTab from '../components/admin/PartnersTab';
import MetricsTab from '../components/admin/MetricsTab';
import ApplicationsTab from '../components/admin/ApplicationsTab';
import SchemesTab from '../components/admin/SchemesTab';
import AuditTab from '../components/admin/AuditTab';

// The token lives in sessionStorage: it's gone when the tab closes, unlike localStorage.
const SESSION_KEY = 'vittsetu_admin_session';
const LEGACY_KEY = 'vittsetu_admin_token'; // older builds kept the token in localStorage

function loadSession() {
  try {
    localStorage.removeItem(LEGACY_KEY);
    return JSON.parse(sessionStorage.getItem(SESSION_KEY)) ?? { token: '', user: '' };
  } catch {
    return { token: '', user: '' };
  }
}

function saveSession(session) {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // storage unavailable — you'll just need to sign in again after a reload
  }
}

const TABS = [
  ['overview', 'Overview'],
  ['partners', 'Partners'],
  ['metrics', 'Portfolio metrics'],
  ['applications', 'Applications'],
  ['schemes', 'Schemes'],
  ['audit', 'Audit log'],
];

export default function Admin() {
  const [session] = useState(loadSession);
  const [token, setToken] = useState(session.token);
  const [user, setUser] = useState(session.user);
  const [authed, setAuthed] = useState(false);
  const [schemes, setSchemes] = useState([]);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('overview');

  // Stable identity so tabs don't refetch on every render.
  const auth = useMemo(() => ({ token, user: user.trim() }), [token, user]);

  const signIn = useCallback(async (credentials) => {
    setError(null);
    try {
      setSchemes(await api.adminListSchemes(credentials));
      setAuthed(true);
      saveSession(credentials);
    } catch (err) {
      setAuthed(false);
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    if (session.token) signIn({ token: session.token, user: session.user });
  }, [session, signIn]);

  function signOut() {
    saveSession(null);
    setToken('');
    setAuthed(false);
  }

  if (!authed) {
    return (
      <div className="card">
        <h2>Admin Console</h2>
        <p className="subtitle">Enter the admin token (ADMIN_TOKEN in .env) to manage Channel Partners, portfolio figures, schemes and applications.</p>
        <form onSubmit={(e) => { e.preventDefault(); signIn(auth); }}>
          <div className="field">
            <label htmlFor="admin-token">Admin token</label>
            <input id="admin-token" type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="admin-user">Your name</label>
            <input id="admin-user" type="text" maxLength={100} value={user} onChange={(e) => setUser(e.target.value)} />
            <div className="field-hint">Recorded in the audit log against every change you make.</div>
          </div>
          {error && <div className="error-box">{error}</div>}
          <button type="submit" className="btn btn-primary" disabled={!token}>Sign in</button>
        </form>
      </div>
    );
  }

  return (
    <div className="card admin-card">
      <div className="admin-head">
        <h2>Admin Console</h2>
        <span className="muted">Signed in{auth.user && ` as ${auth.user}`}</span>
        <button type="button" className="btn btn-secondary btn-small" onClick={signOut}>Sign out</button>
      </div>
      <div className="tab-bar" role="tablist" aria-label="Admin sections">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id}
            className={tab === id ? 'active' : ''} onClick={() => { setTab(id); setError(null); }}>
            {label}
          </button>
        ))}
      </div>

      {error && <div className="error-box">{error}</div>}

      <div role="tabpanel">
        {tab === 'overview' && <OverviewTab auth={auth} onError={setError} />}
        {tab === 'partners' && <PartnersTab auth={auth} schemes={schemes} onError={setError} />}
        {tab === 'metrics' && <MetricsTab auth={auth} onError={setError} />}
        {tab === 'applications' && <ApplicationsTab auth={auth} onError={setError} />}
        {tab === 'schemes' && (
          <SchemesTab auth={auth} schemes={schemes}
            onSchemeSaved={(saved) => setSchemes((prev) => prev.map((s) => (s.code === saved.code ? saved : s)))} />
        )}
        {tab === 'audit' && <AuditTab auth={auth} onError={setError} />}
      </div>
    </div>
  );
}
