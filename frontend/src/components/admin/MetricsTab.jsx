import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { PartnerMetrics, RoutingBadge } from '../PartnerHealth';
import Modal from './Modal';

const FIGURES = [
  ['npa_pct', 'NPA %', { min: 0, max: 100 }],
  ['overdue_pct', 'Overdue %', { min: 0, max: 100 }],
  ['fund_utilization_pct', 'Fund utilisation %', { min: 0, max: 100 }],
  ['allocated_funds_inr', 'Allocated funds (₹)', { min: 0 }],
  ['disbursed_funds_inr', 'Disbursed funds (₹)', { min: 0 }],
];

function MetricsImport({ auth, onImported }) {
  const fileRef = useRef(null);
  const [result, setResult] = useState(null);
  const [errors, setErrors] = useState(null);
  const [busy, setBusy] = useState(false);

  async function downloadTemplate() {
    try {
      const blob = await api.adminDownloadMetricsTemplate(auth);
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
      const res = await api.adminImportMetrics(auth, file, { dryRun, updatedBy: auth.user || 'admin' });
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
        <strong>Bulk import (CSV)</strong>
        <div className="field-hint">
          NSFDC doesn't publish these per partner — enter real figures only. Download the template, fill in
          figures with their "as of" date (an empty cell means "no data"), validate, then import. All-or-nothing.
        </div>
      </div>
      <div className="admin-toolbar-actions">
        <button type="button" className="btn btn-secondary btn-small" onClick={downloadTemplate}>Download CSV template</button>
        <input ref={fileRef} type="file" accept=".csv,text/csv" aria-label="Metrics CSV file" />
        <button type="button" className="btn btn-secondary btn-small" disabled={busy} onClick={() => runImport(true)}>Validate</button>
        <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => runImport(false)}>Import</button>
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

function MetricsForm({ auth, partner, onClose, onSaved }) {
  const real = !partner.metrics_is_demo;
  const [values, setValues] = useState(() => Object.fromEntries(
    FIGURES.map(([f]) => [f, real && partner[f] != null ? String(partner[f]) : '']),
  ));
  const [asOf, setAsOf] = useState(real && partner.metrics_as_of_date ? partner.metrics_as_of_date : new Date().toISOString().slice(0, 10));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = { metrics_as_of_date: asOf, updated_by: auth.user || 'admin' };
      for (const [f] of FIGURES) payload[f] = values[f] === '' ? null : Number(values[f]);
      onSaved(await api.adminUpdateMetrics(auth, partner.id, payload));
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Portfolio figures — ${partner.name}`} onClose={onClose}>
      <form onSubmit={save} className="admin-form">
        {partner.metrics_is_demo && (
          <div className="demo-banner">This partner currently shows DEMO DATA. Saving real figures replaces all of it.</div>
        )}
        <div className="form-grid">
          {FIGURES.map(([f, label, bounds]) => (
            <div className="field" key={f}>
              <label htmlFor={`mf-${f}`}>{label}</label>
              <input id={`mf-${f}`} type="number" step="any" {...bounds} value={values[f]} placeholder="no data"
                onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))} />
            </div>
          ))}
          <div className="field">
            <label htmlFor="mf-asof">Figures as of *</label>
            <input id="mf-asof" type="date" required max={new Date().toISOString().slice(0, 10)} value={asOf}
              onChange={(e) => setAsOf(e.target.value)} />
          </div>
        </div>
        <p className="field-hint">Leave a figure blank for "no data" — never estimate.</p>
        {error && <div className="error-box">{error}</div>}
        <div className="btn-row">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save figures'}</button>
        </div>
      </form>
    </Modal>
  );
}

export default function MetricsTab({ auth, onError }) {
  const [search, setSearch] = useState('');
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async (q = '') => {
    try {
      setData(await api.adminListPartners(auth, { q, page_size: 15 }));
    } catch (err) {
      onError(err.message);
    }
  }, [auth, onError]);

  useEffect(() => {
    const timer = setTimeout(() => load(search), 300);
    return () => clearTimeout(timer);
  }, [search, load]);

  return (
    <>
      <MetricsImport auth={auth} onImported={() => load(search)} />
      <div className="admin-toolbar">
        <strong>Edit one partner's figures</strong>
        <input type="search" className="filter-search" placeholder="Find a partner…" aria-label="Find a partner"
          value={search} onChange={(e) => setSearch(e.target.value)} style={{ marginTop: 8 }} />
        <div className="table-scroll">
          <table className="admin-table">
            <tbody>
              {data?.items.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}<div className="muted">{p.partner_type} · #{p.id}</div></td>
                  <td><RoutingBadge status={p.routing_status} reason={p.routing_reason} /></td>
                  <td><PartnerMetrics partner={p} /></td>
                  <td><button type="button" className="btn btn-secondary btn-small" onClick={() => setEditing(p)}>Edit figures</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && data.total > data.items.length && (
          <p className="field-hint">Showing {data.items.length} of {data.total} — refine the search.</p>
        )}
      </div>
      {editing && (
        <MetricsForm auth={auth} partner={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(search); }} />
      )}
    </>
  );
}
