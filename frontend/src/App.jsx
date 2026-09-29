import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { LanguageProvider } from './context/LanguageContext';
import { AppStateProvider } from './context/AppStateContext';
import Layout from './components/Layout';
import Home from './pages/Home';
import Eligibility from './pages/Eligibility';
import Requirement from './pages/Requirement';
import Results from './pages/Results';
import Calculator from './pages/Calculator';
import Partners from './pages/Partners';
import Checklist from './pages/Checklist';
import AskVittSetu from './pages/AskVittSetu';
import Track from './pages/Track';

// Admin-only code isn't needed by applicants — load it on demand.
const Admin = lazy(() => import('./pages/Admin'));

export default function App() {
  return (
    <LanguageProvider>
      <AppStateProvider>
        <BrowserRouter>
          <Layout>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/eligibility" element={<Eligibility />} />
              <Route path="/requirement" element={<Requirement />} />
              <Route path="/results" element={<Results />} />
              <Route path="/calculator" element={<Calculator />} />
              <Route path="/partners" element={<Partners />} />
              <Route path="/checklist" element={<Checklist />} />
              <Route path="/ask" element={<AskVittSetu />} />
              <Route path="/track" element={<Track />} />
              <Route path="/admin" element={<Suspense fallback={<p>…</p>}><Admin /></Suspense>} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </AppStateProvider>
    </LanguageProvider>
  );
}
