import { Link, useLocation } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';

export default function Layout({ children }) {
  const { lang, setLang, t } = useLanguage();
  const location = useLocation();

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
          <Link className={location.pathname === '/admin' ? 'active' : ''} to="/admin">
            {t('nav_admin')}
          </Link>
        </nav>
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
