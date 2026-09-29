import { createContext, useContext, useEffect, useState } from 'react';
import { translate } from '../i18n/strings';

const LanguageContext = createContext(null);
const STORAGE_KEY = 'vittsetu_lang';

function initialLang() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === 'hi' || saved === 'en' ? saved : 'en';
  } catch {
    return 'en';
  }
}

export function LanguageProvider({ children }) {
  const [lang, setLang] = useState(initialLang);
  const t = (key) => translate(lang, key);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, lang); // a per-device preference
    } catch {
      // storage unavailable — the choice just won't persist
    }
    document.documentElement.lang = lang;
  }, [lang]);

  return (
    <LanguageContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useLanguage must be used within LanguageProvider');
  return ctx;
}
