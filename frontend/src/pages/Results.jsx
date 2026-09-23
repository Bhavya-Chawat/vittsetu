import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import StepProgress from '../components/StepProgress';

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
    update({ selectedScheme: scheme });
    navigate('/calculator');
  }

  return (
    <div>
      <StepProgress steps={steps} current={2} />

      <h2>{t('matched_title')}</h2>
      {result.matched.length === 0 && (
        <div className="info-box">No schemes matched your requirement exactly — see other schemes considered below.</div>
      )}
      {result.matched.map((m) => (
        <div className="scheme-card matched" key={m.scheme.code}>
          <h3>{m.scheme.name}</h3>
          <div className="scheme-meta">
            <span className="badge badge-rate">{m.scheme.interest_rate_to_beneficiary_pct}% p.a.</span>
            {' '}Up to ₹{m.scheme.max_loan_amount.toLocaleString('en-IN')} · {m.scheme.max_financing_pct}% financing
          </div>
          <strong style={{ fontSize: '0.85rem' }}>{t('why_matched')}:</strong>
          <ul className="reason-list">
            {m.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
          <button className="btn btn-primary" style={{ marginTop: 10 }} onClick={() => selectScheme(m.scheme)}>
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
