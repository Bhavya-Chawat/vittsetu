import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api/client';
import { useLanguage } from '../context/LanguageContext';
import { PartnerMetrics, RoutingBadge, RoutingLegend } from '../components/PartnerHealth';
import { formatDateTime } from '../utils/dates';

// Mirrors NEXT_STATUS in routers/applications.py; "rejected" is allowed from any open status.
const NEXT_STATUS = {
  routed: 'acknowledged_by_partner',
  acknowledged_by_partner: 'handed_off_to_pmsuraj',
  handed_off_to_pmsuraj: 'sanctioned',
  sanctioned: 'disbursed',
};

function MetricsImport({ token, onImported }) {
  const fileRef = useRef(null);
  const [result, setResult] = useState(null);
  const [errors, setErrors] = useState(null);
  const [busy, setBusy] = useState(false);

  async function downloadTemplate() {
    try {
      const blob = await api.adminDownloadMetricsTemplate(token);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'partner_metrics_template.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setErrors([{ line: '-', error: err.message }]);
    }
  }

  async function runImport(dryRun) {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setResult(null);
    setErrors(null);
    try {
      const res = await api.adminImportMetrics(token, file, { dryRun });
      setResult(res);
      if (!dryRun) onImported();
    } catch (err) {
      setErrors(err.body?.detail?.errors ?? [{ line: '-', error: err.message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-toolbar">
      <div>
        <strong>Portfolio metrics (NPA / overdue / fund utilisation)</strong>
        <div className="field-hint">
          NSFDC doesn't publish these per partner — enter real figures only. Download the template, fill in
          figures with their "as of" date (an empty cell means "no data"), then import. Imports are all-or-nothing.
        </div>
      </div>
      <div className="admin-toolbar-actions">
        <button className="btn btn-secondary btn-small" onClick={downloadTemplate}>Download CSV template</button>
        <input ref={fileRef} type="file" accept=".csv,text/csv" />
        <button className="btn btn-secondary btn-small" disabled={busy} onClick={() => runImport(true)}>Validate</button>
        <button className="btn btn-primary btn-small" disabled={busy} onClick={() => runImport(false)}>Import</button>
      </div>
      {result && (
        <div className="info-box">
          {result.dry_run ? 'Validation passed — would update' : 'Updated'} {result.updated} partner(s);
          {' '}{result.unchanged} unchanged, {result.skipped_blank} blank row(s) skipped.
        </div>
      )}
      {errors && (
        <div className="error-box">
          No changes applied:
          <ul className="reason-list">
            {errors.map((e, i) => <li key={i}>Line {e.line}: {e.error}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function ApplicationsTable({ token, applications, onUpdated, onError }) {
  const { t } = useLanguage();

  async function advance(reference, status) {
    try {
      const updated = await api.adminUpdateApplicationStatus(token, reference, { status, updated_by: 'admin' });
      onUpdated(updated);
    } catch (err) {
      onError(err.message);
    }
  }

  if (applications.length === 0) return <p className="field-hint">No applications routed yet.</p>;

  return (
    <div className="table-scroll">
      <table className="admin-table">
        <thead>
          <tr><th>Reference</th><th>Created</th><th>Scheme</th><th>Partner</th><th>Applicant</th><th>Status</th><th>Next</th></tr>
        </thead>
        <tbody>
          {applications.map((a) => {
            const next = NEXT_STATUS[a.status];
            const open = a.status !== 'rejected' && a.status !== 'disbursed';
            return (
              <tr key={a.reference}>
                <td><strong>{a.reference}</strong></td>
                <td>{formatDateTime(a.created_at)}</td>
                <td>{a.scheme_code}</td>
                <td>{a.partner_name}</td>
                <td>
                  {a.applicant_name || <span className="muted">(no name)</span>}
                  {a.applicant_contact && <div className="muted">{a.applicant_contact}</div>}
                </td>
                <td>{t(`status_${a.status}`)}</td>
                <td className="admin-actions">
                  {next && (
                    <button className="btn btn-secondary btn-small" onClick={() => advance(a.reference, next)}>
                      → {t(`status_${next}`)}
                    </button>
                  )}
                  {open && (
                    <button className="btn btn-danger btn-small" onClick={() => advance(a.reference, 'rejected')}>
                      Reject
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Admin() {
  const [token, setToken] = useState(localStorage.getItem('vittsetu_admin_token') || '');
  const [authed, setAuthed] = useState(false);
  const [partners, setPartners] = useState([]);
  const [schemes, setSchemes] = useState([]);
  const [applications, setApplications] = useState([]);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('partners');

  const load = useCallback(async (tok) => {
    setError(null);
    try {
      const [p, s, a] = await Promise.all([
        api.adminListPartners(tok), api.adminListSchemes(tok), api.adminListApplications(tok),
      ]);
      setPartners(p);
      setSchemes(s);
      setApplications(a);
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
      const updated = await api.adminUpdateCapacity(token, partnerId, { capacity_status, updated_by: 'admin' });
      setPartners((prev) => prev.map((p) => (p.id === partnerId ? updated : p)));
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

  const demoCount = partners.filter((p) => p.metrics_is_demo).length;

  return (
    <div className="card admin-card">
      <h2>Admin Console</h2>
      <div className="purpose-toggle" style={{ maxWidth: 560 }}>
        <button className={tab === 'partners' ? 'active' : ''} onClick={() => setTab('partners')}>Partners ({partners.length})</button>
        <button className={tab === 'applications' ? 'active' : ''} onClick={() => setTab('applications')}>Applications ({applications.length})</button>
        <button className={tab === 'schemes' ? 'active' : ''} onClick={() => setTab('schemes')}>Schemes ({schemes.length})</button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {tab === 'partners' && (
        <>
          <MetricsImport token={token} onImported={() => load(token)} />
          {demoCount > 0 && (
            <div className="demo-banner">
              {demoCount} partner(s) show DEMO DATA — illustrative figures from scripts/seed_demo_metrics.py, not real
              NSFDC data. Importing real figures for a partner replaces its demo figures.
            </div>
          )}
          <RoutingLegend />
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr><th>Name</th><th>Type</th><th>Location</th><th>Routing</th><th>Portfolio figures</th><th>Capacity</th></tr>
              </thead>
              <tbody>
                {partners.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}<div className="muted">#{p.id}</div></td>
                    <td>{p.partner_type}</td>
                    <td>{[p.district, p.state].filter(Boolean).join(', ')}</td>
                    <td>
                      <RoutingBadge status={p.routing_status} reason={p.routing_reason} />
                      <div className="routing-reason">{p.routing_reason}</div>
                    </td>
                    <td><PartnerMetrics partner={p} /></td>
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
                  <tr><td colSpan={6}>No partners yet — run scripts/ingest_partners.py to load NSFDC's official Channel Partner directories.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === 'applications' && (
        <ApplicationsTable
          token={token}
          applications={applications}
          onUpdated={(updated) => setApplications((prev) => prev.map((a) => (a.reference === updated.reference ? updated : a)))}
          onError={setError}
        />
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
