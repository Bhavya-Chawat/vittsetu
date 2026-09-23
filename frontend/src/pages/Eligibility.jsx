import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import { api } from '../api/client';
import StepProgress from '../components/StepProgress';
import { INDIAN_STATES } from '../data/indianStates';

export default function Eligibility() {
  const { t } = useLanguage();
  const { state: appState, update } = useAppState();
  const navigate = useNavigate();

  const [income, setIncome] = useState(appState.profile?.annual_family_income ?? '');
  const [isSc, setIsSc] = useState(appState.profile?.is_sc_category ?? false);
  const [stateName, setStateName] = useState(appState.profile?.state ?? '');
  const [district, setDistrict] = useState(appState.profile?.district ?? '');
  const [purpose, setPurpose] = useState(appState.profile?.purpose ?? 'business');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const steps = [t('step_eligibility'), t('step_requirement'), t('step_results'), t('step_calculator'), t('step_partners'), t('step_checklist')];

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const profile = {
      annual_family_income: Number(income),
      is_sc_category: isSc,
      state: stateName || null,
      district: district || null,
      purpose,
    };
    try {
      const res = await api.checkEligibility(profile);
      setResult(res);
      update({ profile });
      if (res.eligible) {
        setTimeout(() => navigate('/requirement'), 600);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <StepProgress steps={steps} current={0} />
      <div className="card">
        <h2>{t('step_eligibility')}</h2>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label>{t('income_label')}</label>
            <input
              type="number"
              min="0"
              required
              value={income}
              onChange={(e) => setIncome(e.target.value)}
              placeholder="e.g. 320000"
            />
          </div>

          <div className="field checkbox-field">
            <input
              type="checkbox"
              id="sc-check"
              checked={isSc}
              onChange={(e) => setIsSc(e.target.checked)}
            />
            <label htmlFor="sc-check" style={{ marginBottom: 0 }}>
              {t('sc_label')}
              <div className="field-hint">{t('sc_note')}</div>
            </label>
          </div>

          <div className="field">
            <label>{t('state_label')}</label>
            <select value={stateName} onChange={(e) => setStateName(e.target.value)}>
              <option value="">—</option>
              {INDIAN_STATES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>{t('district_label')}</label>
            <input type="text" value={district} onChange={(e) => setDistrict(e.target.value)} />
          </div>

          <div className="field">
            <label>&nbsp;</label>
            <div className="purpose-toggle">
              <button type="button" className={purpose === 'business' ? 'active' : ''} onClick={() => setPurpose('business')}>
                {t('purpose_business')}
              </button>
              <button type="button" className={purpose === 'education' ? 'active' : ''} onClick={() => setPurpose('education')}>
                {t('purpose_education')}
              </button>
            </div>
          </div>

          {error && <div className="error-box">{error}</div>}

          {result && !result.eligible && (
            <div className="error-box">
              <strong>{t('not_eligible_title')}</strong>
              <ul className="reason-list">
                {result.reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}

          {result && result.eligible && (
            <div className="info-box">
              {result.reasons.map((r, i) => <div key={i}>{r}</div>)}
            </div>
          )}

          <div className="btn-row">
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? '…' : t('continue')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
