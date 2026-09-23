import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';

export default function Home() {
  const { t } = useLanguage();
  const navigate = useNavigate();

  return (
    <div className="hero">
      <h1>{t('home_title')}</h1>
      <p className="subtitle">{t('home_sub')}</p>
      <button className="btn btn-primary" onClick={() => navigate('/eligibility')}>
        {t('home_cta')}
      </button>

      <div className="card" style={{ textAlign: 'left', marginTop: 32 }}>
        <h2>How the Channel Finance System works</h2>
        <p style={{ color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
          NSFDC does not lend to you directly. It provides concessional funds to over 100
          Channel Partners — State Channelizing Agencies (SCAs), Public Sector Banks, Regional
          Rural Banks, NBFC-MFIs, Cooperative Banks/Societies, and Small Finance Banks — who then
          disburse loans to eligible Scheduled Caste beneficiaries at reduced interest rates.
          VittSetu helps you find the right scheme and the right partner for your specific need,
          then hands you off to the official PM-SURAJ portal to actually apply.
        </p>
      </div>
    </div>
  );
}
