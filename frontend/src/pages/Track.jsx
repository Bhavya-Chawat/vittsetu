import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { api } from '../api/client';
import { formatDateTime } from '../utils/dates';

const LIFECYCLE = ['routed', 'acknowledged_by_partner', 'handed_off_to_pmsuraj', 'sanctioned', 'disbursed'];

function StatusSteps({ status }) {
  const { t } = useLanguage();
  const rejected = status === 'rejected';
  const current = LIFECYCLE.indexOf(status);
  return (
    <div className="status-steps">
      {LIFECYCLE.map((s, i) => {
        const done = !rejected && i < current;
        const active = !rejected && i === current;
        return (
          <div key={s} className={`status-step${done ? ' done' : ''}${active ? ' active' : ''}`}>
            <span className="step-dot">{done ? '✓' : i + 1}</span>
            <span>{t(`status_${s}`)}</span>
          </div>
        );
      })}
      {rejected && (
        <div className="status-step rejected">
          <span className="step-dot">✕</span>
          <span>{t('status_rejected')}</span>
        </div>
      )}
    </div>
  );
}

export default function Track() {
  const { t } = useLanguage();
  const [params, setParams] = useSearchParams();
  const [reference, setReference] = useState(params.get('ref') ?? '');
  const [application, setApplication] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const lookup = useCallback(async (ref) => {
    if (!ref.trim()) return;
    setLoading(true);
    setError(null);
    setApplication(null);
    try {
      setApplication(await api.getApplication(ref));
    } catch (err) {
      setError(err.status === 404 ? t('track_not_found') : err.message);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    const ref = params.get('ref');
    if (ref) lookup(ref);
    // Only on first load — later lookups come from the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSubmit(e) {
    e.preventDefault();
    setParams({ ref: reference.trim() });
    lookup(reference);
  }

  return (
    <div>
      <div className="card">
        <h2>{t('track_title')}</h2>
        <form onSubmit={handleSubmit} className="track-form">
          <div className="field" style={{ flex: 1, marginBottom: 0 }}>
            <label htmlFor="track-ref">{t('track_ref_label')}</label>
            <input
              id="track-ref"
              type="text"
              placeholder="VS-2026-000123"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              autoComplete="off"
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={loading || !reference.trim()}>
            {loading ? '…' : t('track_button')}
          </button>
        </form>
        {error && <div className="error-box" style={{ marginTop: 16 }}>{error}</div>}
      </div>

      {application && (
        <div className="card">
          <div className="reference-number">{application.reference}</div>
          <p className="subtitle">
            <strong>{application.scheme_name}</strong>
            {application.requested_loan_amount != null &&
              ` · ₹${application.requested_loan_amount.toLocaleString('en-IN')}`}
          </p>

          <StatusSteps status={application.status} />

          <h3>{t('checklist_partner')}</h3>
          <div className="scheme-card">
            <div className="partner-name">{application.partner_name}</div>
            <div className="partner-meta">{application.partner_type}</div>
            {application.partner_phone && <div className="partner-meta">☎ {application.partner_phone}</div>}
            {application.partner_address && <div className="partner-meta">{application.partner_address}</div>}
          </div>

          <h3>{t('track_timeline')}</h3>
          <ul className="timeline">
            {application.timeline.map((e, i) => (
              <li key={i}>
                <span className="muted">{formatDateTime(e.created_at)}</span> — {t(`status_${e.to_status}`)}
              </li>
            ))}
          </ul>

          {application.status !== 'rejected' && application.status !== 'disbursed' && (
            <div className="info-box">{t('route_next_pmsuraj')}</div>
          )}
        </div>
      )}
    </div>
  );
}
