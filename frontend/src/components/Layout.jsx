import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';

export default function Layout({ children }) {
  const { lang, setLang, t } = useLanguage();
  const { hasProgress, reset } = useAppState();
  const location = useLocation();
  const navigate = useNavigate();

  function startOver() {
    if (!window.confirm(t('start_over_confirm'))) return;
    reset();
    navigate('/');
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark">V</span>
          <span className="brand-name">{t('appName')}</span>
        </Link>
        <nav className="topnav">
          <Link className={location.pathname === '/' ? 'active' : ''} to="/">
            {t('nav_home')}
          </Link>
          <Link className={location.pathname === '/ask' ? 'active' : ''} to="/ask">
            {t('nav_ask')}
          </Link>
          <Link className={location.pathname === '/track' ? 'active' : ''} to="/track">
            {t('nav_track')}
          </Link>
          <Link className={location.pathname === '/admin' ? 'active' : ''} to="/admin">
            {t('nav_admin')}
          </Link>
        </nav>
        {hasProgress && (
          <button type="button" className="btn btn-secondary btn-small" onClick={startOver}>
            ↺ {t('start_over')}
          </button>
        )}
        <div className="lang-pill">
          <button className={lang === 'en' ? 'active' : ''} onClick={() => setLang('en')}>
            {t('lang_en')}
          </button>
          <button className={lang === 'hi' ? 'active' : ''} onClick={() => setLang('hi')}>
            {t('lang_hi')}
          </button>
        </div>
      </header>
      <main className="app-main">{children}</main>
      <footer className="app-footer">
        <p>{t('pmsuraj_note')}</p>
      </footer>
    </div>
  );
}
