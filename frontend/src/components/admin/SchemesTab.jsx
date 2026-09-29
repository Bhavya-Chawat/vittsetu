import { useState } from 'react';
import { api } from '../../api/client';
import Modal from './Modal';

const NUMBER_FIELDS = [
  ['income_limit_annual', 'Income ceiling (₹/year)'],
  ['min_project_cost', 'Min project cost (₹)'],
  ['max_project_cost', 'Max project cost (₹)'],
  ['max_financing_pct', 'Max financing (%)'],
  ['max_loan_amount', 'Max loan (₹)'],
  ['interest_rate_to_beneficiary_pct', 'Beneficiary rate (% p.a.)'],
  ['moratorium_min_months', 'Moratorium min (months)'],
  ['moratorium_max_months', 'Moratorium max (months)'],
  ['repayment_tenure_max_months', 'Max tenure (months)'],
];

const fmt = (v) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));

function SchemeForm({ auth, scheme, onClose, onSaved }) {
  const [values, setValues] = useState(() => Object.fromEntries(
    NUMBER_FIELDS.map(([f]) => [f, scheme[f] == null ? '' : String(scheme[f])]),
  ));
  const [rates, setRates] = useState(() => ({ ...(scheme.rates_by_partner_type ?? {}) }));
  const [sourceUrl, setSourceUrl] = useState('');
  const [diff, setDiff] = useState(null); // changes awaiting confirmation
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function payload() {
    const body = { source_url: sourceUrl.trim() };
    for (const [f] of NUMBER_FIELDS) {
      const original = scheme[f] == null ? '' : String(scheme[f]);
      if (values[f] !== original) body[f] = values[f] === '' ? null : Number(values[f]);
    }
    if (scheme.rates_by_partner_type &&
        JSON.stringify(rates) !== JSON.stringify(scheme.rates_by_partner_type)) {
      body.rates_by_partner_type = Object.fromEntries(Object.entries(rates).map(([k, v]) => [k, Number(v)]));
    }
    return body;
  }

  async function preview(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.adminUpdateScheme(auth, scheme.code, payload(), { dryRun: true });
      if (res.changes.length === 0) setError('Nothing has changed.');
      else setDiff(res.changes);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.adminUpdateScheme(auth, scheme.code, payload());
      onSaved(res.scheme);
    } catch (err) {
      setError(err.message);
      setDiff(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={diff ? `Confirm changes to ${scheme.name}` : `Edit ${scheme.name}`} onClose={onClose} wide>
      {diff ? (
        <div>
          <p className="field-hint">These changes will apply immediately to eligibility, matching and the calculator:</p>
          <table className="admin-table diff-table">
            <thead><tr><th>Field</th><th>Current</th><th>New</th></tr></thead>
            <tbody>
              {diff.map((c) => (
                <tr key={c.field}>
                  <td>{c.field}</td>
                  <td className="diff-before">{fmt(c.before)}</td>
                  <td className="diff-after">{fmt(c.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {error && <div className="error-box">{error}</div>}
          <div className="btn-row">
            <button type="button" className="btn btn-secondary" onClick={() => setDiff(null)}>Back to edit</button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={confirm}>
              {busy ? 'Saving…' : `Confirm ${diff.length} change${diff.length === 1 ? '' : 's'}`}
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={preview} className="admin-form">
          <div className="form-grid">
            {NUMBER_FIELDS.map(([f, label]) => (
              <div className="field" key={f}>
                <label htmlFor={`sf-${f}`}>{label}</label>
                <input id={`sf-${f}`} type="number" step="any" min="0" value={values[f]}
                  onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))} />
              </div>
            ))}
            {scheme.rates_by_partner_type && Object.keys(rates).map((pt) => (
              <div className="field" key={pt}>
                <label htmlFor={`sf-rate-${pt}`}>Rate via {pt} (%)</label>
                <input id={`sf-rate-${pt}`} type="number" step="any" min="0" max="100" value={rates[pt]}
                  onChange={(e) => setRates((r) => ({ ...r, [pt]: e.target.value }))} />
              </div>
            ))}
            <div className="field span-2">
              <label htmlFor="sf-source">Source URL for this change *</label>
              <input id="sf-source" type="url" required placeholder="https://nsfdc.nic.in/…" value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)} />
              <div className="field-hint">
                Required: the official notice or page these figures come from. Current source: {scheme.source_url}
              </div>
            </div>
          </div>
          <p className="field-hint">
            Moratorium and tenure rules (e.g. 12 months for plantation) are defined in scripts/seed_schemes.py; the
            month fields here are fallbacks used only when a scheme has no rules.
          </p>
          {error && <div className="error-box">{error}</div>}
          <div className="btn-row">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Checking…' : 'Review changes'}</button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export default function SchemesTab({ auth, schemes, onSchemeSaved }) {
  const [editing, setEditing] = useState(null);

  return (
    <>
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr><th>Code</th><th>Name</th><th>Max loan</th><th>Interest</th><th>Last verified</th><th /></tr>
          </thead>
          <tbody>
            {schemes.map((s) => (
              <tr key={s.code}>
                <td>{s.code}</td>
                <td>{s.name}</td>
                <td>₹{s.max_loan_amount.toLocaleString('en-IN')}</td>
                <td>
                  {s.interest_rate_to_beneficiary_pct}%
                  {s.rates_by_partner_type && (
                    <div className="muted">
                      {Object.entries(s.rates_by_partner_type).map(([pt, r]) => `${pt} ${r}%`).join(' · ')}
                    </div>
                  )}
                </td>
                <td>{s.last_verified_date}<div className="muted"><a href={s.source_url} target="_blank" rel="noreferrer">source</a></div></td>
                <td><button type="button" className="btn btn-secondary btn-small" onClick={() => setEditing(s)}>Edit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <SchemeForm auth={auth} scheme={editing} onClose={() => setEditing(null)}
          onSaved={(saved) => { setEditing(null); onSchemeSaved(saved); }} />
      )}
    </>
  );
}
