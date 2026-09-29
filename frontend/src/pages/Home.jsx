import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { api } from '../api/client';

function CoverageStrip({ t }) {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.getStats().then(setStats).catch(() => setStats(null)); // decorative — hide on failure
  }, []);

  if (!stats) return null;
  const items = [
    [stats.schemes, t('stat_schemes')],
    [stats.partners, t('stat_partners')],
    [stats.states_covered, t('stat_states')],
    [stats.partners_mapped, t('stat_mapped')],
  ];
  return (
    <section className="coverage-strip" aria-label={t('stat_title')}>
      {items.map(([value, label]) => (
        <div key={label} className="coverage-item">
          <div className="coverage-value">{value.toLocaleString('en-IN')}</div>
          <div className="coverage-label">{label}</div>
        </div>
      ))}
      <p className="coverage-note">
        {t('stat_per_scheme')}{' '}
        {stats.per_scheme.map((s, i) => (
          <span key={s.code}>
            {i > 0 && ' · '}
            <strong>{s.code.replace('_', ' ')}</strong> {s.routable_partners}
          </span>
        ))}
      </p>
    </section>
  );
}

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

      <CoverageStrip t={t} />

      <div className="card" style={{ textAlign: 'left', marginTop: 32 }}>
        <h2>{t('home_how_title')}</h2>
        <p style={{ color: 'var(--color-text-muted)', lineHeight: 1.6 }}>{t('home_how_body')}</p>
      </div>
    </div>
  );
}
