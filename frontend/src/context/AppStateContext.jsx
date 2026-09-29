import { createContext, useContext, useEffect, useState } from 'react';

const AppStateContext = createContext(null);

// Wizard progress survives a page refresh within the tab (sessionStorage), and
// is gone when the tab closes — applicant details aren't kept on shared devices.
const STORAGE_KEY = 'vittsetu_wizard_v1';

const initialState = {
  profile: null, // { annual_family_income, is_sc_category, state, district, purpose }
  business: null, // { project_type, estimated_cost, activity_category }
  education: null, // { course_name, course_fee, repayment_started, course_duration_months }
  recommendResult: null, // RecommendResponse
  selectedScheme: null, // SchemeOut
  calculation: null, // CalculateResponse
  location: null, // { lat, lon }
  selectedPartner: null, // PartnerOut
  routedApplication: null, // ApplicationPublic, once routed to selectedPartner
};

function loadState() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
    return saved && typeof saved === 'object' ? { ...initialState, ...saved } : initialState;
  } catch {
    return initialState; // storage blocked or corrupt — start fresh
  }
}

function saveState(state) {
  try {
    if (state === initialState) sessionStorage.removeItem(STORAGE_KEY);
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // storage unavailable (private mode, quota) — the wizard still works in memory
  }
}

export function AppStateProvider({ children }) {
  const [state, setState] = useState(loadState);

  useEffect(() => saveState(state), [state]);

  const update = (patch) => setState((prev) => ({ ...prev, ...patch }));
  const reset = () => setState(initialState);
  const hasProgress = state.profile !== null;

  return (
    <AppStateContext.Provider value={{ state, update, reset, hasProgress }}>
      {children}
    </AppStateContext.Provider>
  );
}

export function useAppState() {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider');
  return ctx;
}
