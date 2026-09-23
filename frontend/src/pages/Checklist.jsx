import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import StepProgress from '../components/StepProgress';

export default function Checklist() {
  const { t } = useLanguage();
  const { state: appState } = useAppState();
  const navigate = useNavigate();

  useEffect(() => {
    if (!appState.selectedScheme) navigate('/eligibility');
  }, [appState.selectedScheme, navigate]);

  const scheme = appState.selectedScheme;
  const partner = appState.selectedPartner;
  const steps = [t('step_eligibility'), t('step_requirement'), t('step_results'), t('step_calculator'), t('step_partners'), t('step_checklist')];

  if (!scheme) return null;

  return (
    <div>
      <StepProgress steps={steps} current={5} />
      <div className="card">
        <h2>{t('checklist_title')}</h2>
        <p className="subtitle"><strong>{scheme.name}</strong></p>

        <h3>{t('checklist_docs')}</h3>
        <ul className="reason-list">
          {scheme.required_documents.map((d, i) => <li key={i}>{d}</li>)}
        </ul>

        {partner ? (
          <>
            <h3>{t('checklist_partner')}</h3>
            <div className="scheme-card matched">
              <div className="partner-name">{partner.name}</div>
              <div className="partner-meta">
                {partner.partner_type} · {[partner.district, partner.state].filter(Boolean).join(', ')}
              </div>
              {partner.phone && <div className="partner-meta">☎ {partner.phone}</div>}
              {partner.address && <div className="partner-meta">{partner.address}</div>}
            </div>
          </>
        ) : (
          <div className="info-box">No partner selected yet — go back to find one near you.</div>
        )}

        <div className="info-box" style={{ marginTop: 16 }}>{t('pmsuraj_note')}</div>

        <div className="btn-row">
          <button className="btn btn-secondary" onClick={() => navigate('/partners')}>{t('back')}</button>
          <a className="btn btn-primary" href="https://pmsuraj.dosje.gov.in/" target="_blank" rel="noreferrer">
            {t('continue_pmsuraj')}
          </a>
        </div>
      </div>
    </div>
  );
}
