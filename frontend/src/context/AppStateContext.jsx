import { createContext, useContext, useState } from 'react';

const AppStateContext = createContext(null);

const initialState = {
  profile: null, // { annual_family_income, is_sc_category, state, district, purpose }
  business: null, // { project_type, estimated_cost }
  education: null, // { course_name, course_fee, repayment_started }
  recommendResult: null, // RecommendResponse
  selectedScheme: null, // SchemeOut
  calculation: null, // CalculateResponse
  location: null, // { lat, lon }
  selectedPartner: null, // PartnerOut
};

export function AppStateProvider({ children }) {
  const [state, setState] = useState(initialState);

  const update = (patch) => setState((prev) => ({ ...prev, ...patch }));
  const reset = () => setState(initialState);

  return (
    <AppStateContext.Provider value={{ state, update, reset }}>
      {children}
    </AppStateContext.Provider>
  );
}

export function useAppState() {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider');
  return ctx;
}
