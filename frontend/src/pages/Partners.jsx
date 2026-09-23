import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import '../components/LeafletIconFix';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import { api } from '../api/client';
import StepProgress from '../components/StepProgress';

const CAPACITY_LABEL_KEY = {
  available: 'capacity_available',
  limited: 'capacity_limited',
  not_accepting: 'capacity_not_accepting',
};

export default function Partners() {
  const { t } = useLanguage();
  const { state: appState, update } = useAppState();
  const navigate = useNavigate();

  const [partners, setPartners] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [locating, setLocating] = useState(false);

  useEffect(() => {
    if (!appState.selectedScheme) navigate('/eligibility');
  }, [appState.selectedScheme, navigate]);

  async function fetchPartners(loc) {
    setLoading(true);
    setError(null);
    try {
      const res = await api.partnersNearby({
        lat: loc?.lat ?? null,
        lon: loc?.lon ?? null,
        state: appState.profile?.state ?? null,
        district: appState.profile?.district ?? null,
        scheme_code: appState.selectedScheme?.code,
        limit: 10,
      });
      setPartners(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchPartners(appState.location);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function useMyLocation() {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const loc = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        update({ location: loc });
        fetchPartners(loc);
        setLocating(false);
      },
      () => setLocating(false),
      { timeout: 8000 }
    );
  }

  const steps = [t('step_eligibility'), t('step_requirement'), t('step_results'), t('step_calculator'), t('step_partners'), t('step_checklist')];
  const mapCenter = appState.location
    ? [appState.location.lat, appState.location.lon]
    : partners.find((p) => p.lat)
      ? [partners.find((p) => p.lat).lat, partners.find((p) => p.lat).lon]
      : [22.9734, 78.6569]; // India centroid fallback

  return (
    <div>
      <StepProgress steps={steps} current={4} />
      <div className="card">
        <h2>{t('partners_title')}</h2>
        <button className="btn btn-secondary" onClick={useMyLocation} disabled={locating} style={{ marginBottom: 16 }}>
          {locating ? '…' : t('use_my_location')}
        </button>

        {error && <div className="error-box">{error}</div>}
        {loading && <p>…</p>}

        <div className="map-wrap">
          <MapContainer center={mapCenter} zoom={appState.location ? 11 : 5} style={{ height: '100%', width: '100%' }}>
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {appState.location && (
              <Marker position={[appState.location.lat, appState.location.lon]}>
                <Popup>You are here</Popup>
              </Marker>
            )}
            {partners.filter((p) => p.lat && p.lon).map((p) => (
              <Marker key={p.id} position={[p.lat, p.lon]}>
                <Popup>
                  <strong>{p.name}</strong><br />
                  {p.partner_type}<br />
                  {p.address}
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>

        {partners.length === 0 && !loading && (
          <div className="info-box">
            No compatible Channel Partners found in our directory for this location/scheme yet —
            partner data is being progressively populated from NSFDC's official published lists.
          </div>
        )}

        {partners.map((p) => (
          <div className="partner-list-item" key={p.id}>
            <div>
              <div className="partner-name">{p.name}</div>
              <div className="partner-meta">
                {p.partner_type} · {[p.district, p.state].filter(Boolean).join(', ')}
                {p.distance_km != null && ` · ${p.distance_km} km ${t('distance_away')}`}
              </div>
            </div>
            <span className={`capacity-badge capacity-${p.capacity_status}`}>
              {t(CAPACITY_LABEL_KEY[p.capacity_status])}
            </span>
          </div>
        ))}

        <div className="btn-row">
          <button className="btn btn-secondary" onClick={() => navigate('/calculator')}>{t('back')}</button>
          <button
            className="btn btn-primary"
            onClick={() => { update({ selectedPartner: partners[0] ?? null }); navigate('/checklist'); }}
          >
            {t('view_checklist')}
          </button>
        </div>
      </div>
    </div>
  );
}
