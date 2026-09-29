import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import StepProgress from '../components/StepProgress';

const inr = (n) => `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

const AVAILABILITY_CLASS = {
  local: 'avail-local',
  unspecified: 'avail-local',
  elsewhere: 'avail-elsewhere',
  none: 'avail-none',
};

function ComparisonTable({ rows, t }) {
  return (
    <div className="table-scroll">
      <table className="compare-table">
        <thead>
          <tr>
            <th>{t('compare_scheme')}</th>
            <th>{t('compare_rate')}</th>
            <th>{t('compare_loan')}</th>
            <th>{t('compare_moratorium')}</th>
            <th>{t('compare_tenure')}</th>
            <th>{t('compare_instalment')}</th>
            <th>{t('compare_partners')}</th>
            <th>{t('compare_availability')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.code} className={r.is_best_fit ? 'best-row' : ''}>
              <th scope="row">
                {r.name}
                {r.is_best_fit && <div><span className="best-fit-badge">{t('best_fit_badge')}</span></div>}
              </th>
              <td>
                <strong>{r.effective_rate_pct}%</strong>
                {r.rate_display !== `${r.effective_rate_pct}%` && <div className="muted">({r.rate_display})</div>}
              </td>
              <td>{inr(r.loan_for_this_cost)}</td>
              <td title={r.moratorium_basis}>
                {r.moratorium_months != null ? `${r.moratorium_months} ${t('months_short')}` : t('depends_on_course')}
              </td>
              <td title={r.tenure_basis}>{r.tenure_max_months} {t('months_short')}</td>
              <td>{r.quarterly_instalment != null ? inr(r.quarterly_instalment) : '—'}</td>
              <td>{r.partner_types.join(', ')}</td>
              <td>
                <span className={`avail-dot ${AVAILABILITY_CLASS[r.availability.level]}`} aria-hidden="true" />
                {r.availability.summary}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="field-hint">{t('compare_footnote')}</p>
    </div>
  );
}

export default function Results() {
  const { t } = useLanguage();
  const { state: appState, update } = useAppState();
  const navigate = useNavigate();
  const [showRejected, setShowRejected] = useState(false);

  useEffect(() => {
    if (!appState.recommendResult) navigate('/eligibility');
  }, [appState.recommendResult, navigate]);

  const result = appState.recommendResult;
  const steps = [t('step_eligibility'), t('step_requirement'), t('step_results'), t('step_calculator'), t('step_partners'), t('step_checklist')];

  if (!result) return null;

  function selectScheme(scheme) {
    update({ selectedScheme: scheme, routedApplication: null, calculation: null });
    navigate('/calculator');
  }

  const best = result.best_fit;
  const bestMatch = best && result.matched.find((m) => m.scheme.code === best.scheme_code);
  const others = result.matched.filter((m) => m.scheme.code !== best?.scheme_code);
  const activity = result.activity;

  return (
    <div>
      <StepProgress steps={steps} current={2} />

      {activity?.category && (
        <p className="field-hint">
          {t('activity_label')}: <strong>{activity.label}</strong>{' '}
          ({activity.source === 'user_confirmed' ? t('activity_confirmed') : t('activity_auto')})
        </p>
      )}

      {result.matched.length === 0 && (
        <div className="info-box">No schemes matched your requirement exactly — see other schemes considered below.</div>
      )}

      {bestMatch && (
        <div className="best-fit-card">
          <div className="best-fit-head">
            <span className="best-fit-badge">{t('best_fit_badge')}</span>
            <h2>{t('best_fit_title')}: {best.scheme_name}</h2>
          </div>
          <div className="best-fit-rate">
            {best.effective_rate_pct}% p.a.
            {best.effective_rate_partner_type && <span className="muted"> via {best.effective_rate_partner_type}</span>}
          </div>
          <ul className="reason-list">
            {best.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
          {bestMatch.matched_course && (
            <p className="field-hint">{t('matched_course')}: <strong>{bestMatch.matched_course}</strong></p>
          )}
          <details className="best-fit-details">
            <summary>{t('why_matched')}</summary>
            <ul className="reason-list">
              {bestMatch.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </details>
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => selectScheme(bestMatch.scheme)}>
            {t('select_scheme')}
          </button>
        </div>
      )}

      {result.comparison.length > 1 && (
        <div className="card">
          <h2>{t('compare_title')}</h2>
          <ComparisonTable rows={result.comparison} t={t} />
        </div>
      )}

      {others.length > 0 && <h2>{t('other_matches')}</h2>}
      {others.map((m) => (
        <div className="scheme-card matched" key={m.scheme.code}>
          <h3>{m.scheme.name}</h3>
          {best?.alternatives[m.scheme.code] && (
            <>
              <strong style={{ fontSize: '0.85rem' }}>{t('trade_offs')}:</strong>
              <ul className="reason-list">
                {best.alternatives[m.scheme.code].map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </>
          )}
          <details style={{ marginTop: 8 }}>
            <summary className="field-hint">{t('why_matched')}</summary>
            <ul className="reason-list">
              {m.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </details>
          <button className="btn btn-secondary" style={{ marginTop: 10 }} onClick={() => selectScheme(m.scheme)}>
            {t('select_scheme')}
          </button>
        </div>
      ))}

      {result.rejected.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <button className="btn btn-secondary" onClick={() => setShowRejected((s) => !s)}>
            {t('rejected_title')} ({result.rejected.length})
          </button>
          {showRejected && result.rejected.map((m) => (
            <div className="scheme-card rejected" key={m.scheme.code} style={{ marginTop: 10 }}>
              <h3>{m.scheme.name}</h3>
              <strong style={{ fontSize: '0.85rem' }}>{t('why_not')}:</strong>
              <ul className="reason-list">
                {m.reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
