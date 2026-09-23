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
import Admin from './pages/Admin';

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
              <Route path="/admin" element={<Admin />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </AppStateProvider>
    </LanguageProvider>
  );
}
