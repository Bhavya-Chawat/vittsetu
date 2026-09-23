import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';

export default function Admin() {
  const [token, setToken] = useState(localStorage.getItem('vittsetu_admin_token') || '');
  const [authed, setAuthed] = useState(false);
  const [partners, setPartners] = useState([]);
  const [schemes, setSchemes] = useState([]);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('partners');

  const load = useCallback(async (tok) => {
    setError(null);
    try {
      const [p, s] = await Promise.all([api.adminListPartners(tok), api.adminListSchemes(tok)]);
      setPartners(p);
      setSchemes(s);
      setAuthed(true);
      localStorage.setItem('vittsetu_admin_token', tok);
    } catch (err) {
      setAuthed(false);
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    if (token) load(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCapacityChange(partnerId, capacity_status) {
    try {
      await api.adminUpdateCapacity(token, partnerId, { capacity_status, updated_by: 'admin' });
      setPartners((prev) => prev.map((p) => (p.id === partnerId ? { ...p, capacity_status } : p)));
    } catch (err) {
      setError(err.message);
    }
  }

  if (!authed) {
    return (
      <div className="card">
        <h2>Admin Console</h2>
        <p className="subtitle">Enter the admin token (set via ADMIN_TOKEN in .env) to manage Channel Partner capacity and scheme data.</p>
        <div className="field">
          <label>Admin token</label>
          <input type="text" value={token} onChange={(e) => setToken(e.target.value)} />
        </div>
        {error && <div className="error-box">{error}</div>}
        <button className="btn btn-primary" onClick={() => load(token)}>Sign in</button>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Admin Console</h2>
      <div className="purpose-toggle" style={{ maxWidth: 400 }}>
        <button className={tab === 'partners' ? 'active' : ''} onClick={() => setTab('partners')}>Partners ({partners.length})</button>
        <button className={tab === 'schemes' ? 'active' : ''} onClick={() => setTab('schemes')}>Schemes ({schemes.length})</button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {tab === 'partners' && (
        <table className="admin-table">
          <thead>
            <tr><th>Name</th><th>Type</th><th>Location</th><th>Capacity</th></tr>
          </thead>
          <tbody>
            {partners.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{p.partner_type}</td>
                <td>{[p.district, p.state].filter(Boolean).join(', ')}</td>
                <td>
                  <select
                    className="capacity-select"
                    value={p.capacity_status}
                    onChange={(e) => handleCapacityChange(p.id, e.target.value)}
                  >
                    <option value="available">Available</option>
                    <option value="limited">Limited</option>
                    <option value="not_accepting">Not accepting</option>
                  </select>
                </td>
              </tr>
            ))}
            {partners.length === 0 && (
              <tr><td colSpan={4}>No partners yet — run scripts/ingest_partners.py to load NSFDC's official Channel Partner directories.</td></tr>
            )}
          </tbody>
        </table>
      )}

      {tab === 'schemes' && (
        <table className="admin-table">
          <thead>
            <tr><th>Code</th><th>Name</th><th>Max Loan</th><th>Interest</th><th>Last verified</th></tr>
          </thead>
          <tbody>
            {schemes.map((s) => (
              <tr key={s.code}>
                <td>{s.code}</td>
                <td>{s.name}</td>
                <td>₹{s.max_loan_amount.toLocaleString('en-IN')}</td>
                <td>{s.interest_rate_to_beneficiary_pct}%</td>
                <td>{s.last_verified_date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
