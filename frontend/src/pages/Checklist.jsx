import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import { api } from '../api/client';
import StepProgress from '../components/StepProgress';
import { RoutingBadge } from '../components/PartnerHealth';

function RouteApplication({ scheme, partner }) {
  const { t } = useLanguage();
  const { state: appState, update } = useAppState();
  const [name, setName] = useState('');
  const [contact, setContact] = useState('');
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const routed = appState.routedApplication;

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const application = await api.createApplication({
        scheme_code: scheme.code,
        partner_id: partner.id,
        consent,
        applicant_name: name || null,
        applicant_contact: contact || null,
        state: appState.profile?.state ?? null,
        district: appState.profile?.district ?? null,
        project_cost: appState.business?.estimated_cost ?? appState.education?.course_fee ?? null,
        // The (possibly reduced) loan amount chosen in the calculator, if it was for this scheme.
        loan_amount: appState.calculation?.scheme_code === scheme.code ? appState.calculation.loan_amount : null,
      });
      update({ routedApplication: application });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (routed) {
    return (
      <div className="route-done">
        <h3>✓ {t('route_done_title')}</h3>
        <div className="field-hint">{t('route_reference')}</div>
        <div className="reference-number">{routed.reference}</div>
        <p className="field-hint">{t('route_save_hint')}</p>
        <Link className="btn btn-secondary" to={`/track?ref=${encodeURIComponent(routed.reference)}`}>
          {t('route_track_link')}
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      <p className="subtitle">{t('route_intro')}</p>
      <div className="field">
        <label htmlFor="route-name">{t('route_name_label')}</label>
        <input id="route-name" type="text" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="route-contact">{t('route_contact_label')}</label>
        <input id="route-contact" type="text" maxLength={100} value={contact} onChange={(e) => setContact(e.target.value)} />
        <div className="field-hint">{t('route_contact_hint')}</div>
      </div>
      <div className="field checkbox-field">
        <input id="route-consent" type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <label htmlFor="route-consent" style={{ marginBottom: 0, fontWeight: 400 }}>{t('route_consent')}</label>
      </div>
      {error && <div className="error-box">{error}</div>}
      <button type="submit" className="btn btn-primary" disabled={!consent || submitting}>
        {submitting ? '…' : t('route_submit')}
      </button>
    </form>
  );
}

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
              <div className="partner-option-head">
                <span className="partner-name">{partner.name}</span>
                <RoutingBadge status={partner.routing_status} reason={partner.routing_reason} />
              </div>
              <div className="partner-meta">
                {partner.partner_type} · {[partner.district, partner.state].filter(Boolean).join(', ')}
              </div>
              {partner.phone && <div className="partner-meta">☎ {partner.phone}</div>}
              {partner.address && <div className="partner-meta">{partner.address}</div>}
            </div>
          </>
        ) : (
          <div className="info-box">{t('no_partner_selected')}</div>
        )}
      </div>

      {partner && (
        <div className="card">
          <h2>{t('route_title')}</h2>
          <RouteApplication scheme={scheme} partner={partner} />
        </div>
      )}

      <div className="card">
        <div className="info-box">{appState.routedApplication ? t('route_next_pmsuraj') : t('pmsuraj_note')}</div>
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
