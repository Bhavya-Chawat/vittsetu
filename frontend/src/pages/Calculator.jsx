import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import { api } from '../api/client';
import StepProgress from '../components/StepProgress';

function formatINR(n) {
  return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

export default function Calculator() {
  const { t } = useLanguage();
  const { state: appState } = useAppState();
  const navigate = useNavigate();

  const scheme = appState.selectedScheme;
  const cost = appState.business?.estimated_cost ?? appState.education?.course_fee;

  const [tenure, setTenure] = useState(scheme?.repayment_tenure_max_months ?? 12);
  const [calc, setCalc] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!scheme || !cost) navigate('/eligibility');
  }, [scheme, cost, navigate]);

  const runCalc = useCallback(async (tenureMonths) => {
    if (!scheme || !cost) return;
    try {
      const res = await api.calculate({ scheme_code: scheme.code, project_cost: cost, tenure_months: tenureMonths });
      setCalc(res);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [scheme, cost]);

  useEffect(() => { runCalc(tenure); }, [tenure, runCalc]);

  const steps = [t('step_eligibility'), t('step_requirement'), t('step_results'), t('step_calculator'), t('step_partners'), t('step_checklist')];

  if (!scheme) return null;

  return (
    <div>
      <StepProgress steps={steps} current={3} />
      <div className="card">
        <h2>{scheme.name} — {t('step_calculator')}</h2>

        <div className="field">
          <label>{t('calc_tenure')}: {tenure} months</label>
          <input
            type="range"
            min="6"
            max={scheme.repayment_tenure_max_months}
            step="6"
            value={tenure}
            onChange={(e) => setTenure(Number(e.target.value))}
          />
        </div>

        {error && <div className="error-box">{error}</div>}

        {calc && (
          <>
            <div className="calc-grid">
              <div className="calc-stat">
                <div className="label">{t('calc_loan_amount')}</div>
                <div className="value">{formatINR(calc.loan_amount)}</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_contribution')}</div>
                <div className="value">{formatINR(calc.applicant_contribution)}</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_interest')}</div>
                <div className="value">{calc.interest_rate_pct}% p.a.</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_emi')}</div>
                <div className="value">{formatINR(calc.monthly_emi)}</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_moratorium')}</div>
                <div className="value">{calc.moratorium_months} mo</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_total_interest')}</div>
                <div className="value">{formatINR(calc.total_interest)}</div>
              </div>
            </div>
            <ul className="notes-list">
              {calc.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </>
        )}

        <div className="btn-row">
          <button className="btn btn-secondary" onClick={() => navigate('/results')}>{t('back')}</button>
          <button className="btn btn-primary" onClick={() => navigate('/partners')}>{t('find_partners')}</button>
        </div>
      </div>
    </div>
  );
}
