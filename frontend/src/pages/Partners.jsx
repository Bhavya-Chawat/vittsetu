import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import L from 'leaflet';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import '../components/LeafletIconFix';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import { api } from '../api/client';
import StepProgress from '../components/StepProgress';
import { PartnerMetrics, RoutingBadge, RoutingLegend } from '../components/PartnerHealth';

const CAPACITY_LABEL_KEY = {
  available: 'capacity_available',
  limited: 'capacity_limited',
  not_accepting: 'capacity_not_accepting',
};

// One cached divIcon per (routing status, selected) — colours come from the
// .route-pin-* classes in index.css.
const iconCache = {};
function routingIcon(status, selected) {
  const key = `${status}-${selected}`;
  if (!iconCache[key]) {
    const size = selected ? 26 : 18;
    iconCache[key] = L.divIcon({
      className: 'route-pin-wrap',
      html: `<span class="route-pin route-pin-${status}${selected ? ' selected' : ''}"></span>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
      popupAnchor: [0, -size / 2],
    });
  }
  return iconCache[key];
}

function PartnerLine({ p, t }) {
  return (
    <div className="partner-meta">
      {p.partner_type}
      {[p.district, p.state].filter(Boolean).length > 0 && ` · ${[p.district, p.state].filter(Boolean).join(', ')}`}
      {p.distance_km != null && ` · ${p.distance_km} km ${t('distance_away')}`}
    </div>
  );
}

export default function Partners() {
  const { t } = useLanguage();
  const { state: appState, update } = useAppState();
  const navigate = useNavigate();

  const [partners, setPartners] = useState([]);
  const [excluded, setExcluded] = useState([]);
  const [note, setNote] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [locating, setLocating] = useState(false);
  const [showExcluded, setShowExcluded] = useState(false);

  const selectedId = appState.selectedPartner?.id ?? null;

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
      setPartners(res.partners);
      setExcluded(res.excluded);
      setNote(res.note);
      // Keep the current choice only if it's still routable for this search.
      const current = res.partners.find((p) => p.id === appState.selectedPartner?.id);
      update({ selectedPartner: current ?? null });
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

  function choose(partner) {
    // A different partner means any application routed earlier was for someone else.
    update({ selectedPartner: partner, routedApplication: null });
  }

  const steps = [t('step_eligibility'), t('step_requirement'), t('step_results'), t('step_calculator'), t('step_partners'), t('step_checklist')];
  const firstWithCoords = partners.find((p) => p.lat != null);
  const mapCenter = appState.location
    ? [appState.location.lat, appState.location.lon]
    : firstWithCoords
      ? [firstWithCoords.lat, firstWithCoords.lon]
      : [22.9734, 78.6569]; // India centroid fallback

  const mapped = [
    ...partners.map((p) => ({ p, routable: true })),
    ...excluded.map((p) => ({ p, routable: false })),
  ].filter(({ p }) => p.lat != null && p.lon != null);

  return (
    <div>
      <StepProgress steps={steps} current={4} />
      <div className="card">
        <h2>{t('partners_title')}</h2>
        <button className="btn btn-secondary" onClick={useMyLocation} disabled={locating} style={{ marginBottom: 16 }}>
          {locating ? '…' : t('use_my_location')}
        </button>

        {error && <div className="error-box">{error}</div>}
        {note && <div className="info-box">{note}</div>}
        {loading && <p>…</p>}

        <div className="map-wrap">
          <MapContainer center={mapCenter} zoom={appState.location ? 11 : 5} style={{ height: '100%', width: '100%' }}>
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {appState.location && (
              <Marker position={[appState.location.lat, appState.location.lon]}>
                <Popup>{t('you_are_here')}</Popup>
              </Marker>
            )}
            {mapped.map(({ p, routable }) => (
              <Marker
                key={p.id}
                position={[p.lat, p.lon]}
                icon={routingIcon(p.routing_status, p.id === selectedId)}
                zIndexOffset={p.id === selectedId ? 1000 : 0}
              >
                <Popup>
                  <div className="map-popup">
                    <strong>{p.name}</strong>
                    <div>{p.partner_type}</div>
                    {p.address && <div className="muted">{p.address}</div>}
                    <div style={{ margin: '6px 0' }}>
                      <RoutingBadge status={p.routing_status} reason={p.routing_reason} />
                    </div>
                    <div className="muted">{p.routing_reason}</div>
                    {routable && (
                      p.id === selectedId ? (
                        <div className="popup-selected">✓ {t('selected_partner')}</div>
                      ) : (
                        <button className="btn btn-primary btn-small" onClick={() => choose(p)}>
                          {t('select_partner')}
                        </button>
                      )
                    )}
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>
        <RoutingLegend />

        {partners.length === 0 && !loading && (
          <div className="info-box">
            No compatible Channel Partners found in our directory for this location/scheme yet —
            partner data is being progressively populated from NSFDC's official published lists.
          </div>
        )}

        <div role="radiogroup" aria-label={t('partners_title')}>
          {partners.map((p) => {
            const selected = p.id === selectedId;
            return (
              <div
                key={p.id}
                role="radio"
                aria-checked={selected}
                tabIndex={0}
                className={`partner-option${selected ? ' selected' : ''}`}
                onClick={() => choose(p)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    choose(p);
                  }
                }}
              >
                <span className="partner-radio" aria-hidden="true" />
                <div className="partner-option-body">
                  <div className="partner-option-head">
                    <span className="partner-name">{p.name}</span>
                    <span className="partner-badges">
                      <RoutingBadge status={p.routing_status} reason={p.routing_reason} />
                      <span className={`capacity-badge capacity-${p.capacity_status}`}>
                        {t(CAPACITY_LABEL_KEY[p.capacity_status])}
                      </span>
                    </span>
                  </div>
                  <PartnerLine p={p} t={t} />
                  <PartnerMetrics partner={p} />
                  <div className="routing-reason">{p.routing_reason}</div>
                </div>
              </div>
            );
          })}
        </div>

        {excluded.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <button className="btn btn-secondary" onClick={() => setShowExcluded((s) => !s)}>
              {t('excluded_title')} ({excluded.length})
            </button>
            {showExcluded && (
              <div className="excluded-list">
                <p className="field-hint">{t('excluded_hint')}</p>
                {excluded.map((p) => (
                  <div className="partner-option excluded" key={p.id}>
                    <div className="partner-option-body">
                      <div className="partner-option-head">
                        <span className="partner-name">{p.name}</span>
                        <RoutingBadge status={p.routing_status} reason={p.routing_reason} />
                      </div>
                      <PartnerLine p={p} t={t} />
                      <PartnerMetrics partner={p} />
                      <div className="routing-reason">{p.routing_reason}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {partners.length > 0 && !selectedId && <p className="field-hint">{t('choose_partner_hint')}</p>}

        <div className="btn-row">
          <button className="btn btn-secondary" onClick={() => navigate('/calculator')}>{t('back')}</button>
          <button className="btn btn-primary" disabled={!selectedId} onClick={() => navigate('/checklist')}>
            {t('view_checklist')}
          </button>
        </div>
      </div>
    </div>
  );
}
