import { useState } from 'react';
import { api } from '../../api/client';
import { INDIAN_STATES } from '../../data/indianStates';
import Modal from './Modal';
import { PARTNER_TYPES } from './constants';

const TEXT_FIELDS = ['name', 'state', 'district', 'address', 'phone', 'email', 'source_url'];

function toForm(partner) {
  const form = { partner_type: partner?.partner_type ?? 'SCA', eligible_scheme_codes: partner?.eligible_scheme_codes ?? [] };
  for (const f of TEXT_FIELDS) form[f] = partner?.[f] ?? '';
  form.lat = partner?.lat ?? '';
  form.lon = partner?.lon ?? '';
  return form;
}

function toPayload(form) {
  const payload = { partner_type: form.partner_type, eligible_scheme_codes: form.eligible_scheme_codes };
  for (const f of TEXT_FIELDS) payload[f] = form[f].trim() === '' ? null : form[f].trim();
  payload.lat = form.lat === '' ? null : Number(form.lat);
  payload.lon = form.lon === '' ? null : Number(form.lon);
  return payload;
}

/** Add (partner = null) or edit a Channel Partner. On edit, only changed fields are sent. */
export default function PartnerForm({ auth, partner, schemes, onClose, onSaved }) {
  const [form, setForm] = useState(() => toForm(partner));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [geo, setGeo] = useState(null); // { busy, message }

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  function toggleScheme(code) {
    setForm((f) => ({
      ...f,
      eligible_scheme_codes: f.eligible_scheme_codes.includes(code)
        ? f.eligible_scheme_codes.filter((c) => c !== code)
        : [...f.eligible_scheme_codes, code],
    }));
  }

  async function geocode() {
    if (!form.address.trim()) {
      setGeo({ message: 'Enter an address first.' });
      return;
    }
    setGeo({ busy: true, message: 'Looking up…' });
    try {
      const res = await api.adminGeocode(auth, { address: form.address, state: form.state || null });
      setForm((f) => ({ ...f, lat: res.lat.toFixed(6), lon: res.lon.toFixed(6) }));
      setGeo({ message: `Found: ${res.display_name}. Check it's the right place before saving.` });
    } catch (err) {
      setGeo({ message: err.message });
    }
  }

  async function save(e) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(form);
      let saved;
      if (partner) {
        const original = toPayload(toForm(partner));
        const changed = Object.fromEntries(
          Object.entries(payload).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(original[k])),
        );
        saved = Object.keys(changed).length ? await api.adminUpdatePartner(auth, partner.id, changed) : partner;
      } else {
        saved = await api.adminCreatePartner(auth, payload);
      }
      onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={partner ? `Edit partner #${partner.id}` : 'Add Channel Partner'} onClose={onClose} wide>
      <form onSubmit={save} className="admin-form">
        <div className="form-grid">
          <div className="field span-2">
            <label htmlFor="pf-name">Name *</label>
            <input id="pf-name" type="text" required maxLength={300} value={form.name} onChange={set('name')} />
          </div>
          <div className="field">
            <label htmlFor="pf-type">Partner type *</label>
            <select id="pf-type" value={form.partner_type} onChange={set('partner_type')}>
              {PARTNER_TYPES.map((pt) => <option key={pt} value={pt}>{pt}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="pf-state">State / UT</label>
            <select id="pf-state" value={form.state} onChange={set('state')}>
              <option value="">—</option>
              {INDIAN_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="pf-district">District</label>
            <input id="pf-district" type="text" maxLength={100} value={form.district} onChange={set('district')} />
          </div>
          <div className="field span-2">
            <label htmlFor="pf-address">Address</label>
            <textarea id="pf-address" maxLength={1000} value={form.address} onChange={set('address')} />
          </div>
          <div className="field">
            <label htmlFor="pf-lat">Latitude</label>
            <input id="pf-lat" type="number" step="any" min="6" max="37.6" value={form.lat} onChange={set('lat')} />
          </div>
          <div className="field">
            <label htmlFor="pf-lon">Longitude</label>
            <input id="pf-lon" type="number" step="any" min="68" max="97.5" value={form.lon} onChange={set('lon')} />
          </div>
          <div className="field span-2 geocode-row">
            <button type="button" className="btn btn-secondary btn-small" onClick={geocode} disabled={geo?.busy}>
              📍 Geocode address
            </button>
            <span className="field-hint">
              {geo?.message ?? 'Looks up coordinates on OpenStreetMap (max 1 request/second).'}
            </span>
          </div>
          <div className="field">
            <label htmlFor="pf-phone">Phone</label>
            <input id="pf-phone" type="text" maxLength={100} value={form.phone} onChange={set('phone')} />
          </div>
          <div className="field">
            <label htmlFor="pf-email">Email</label>
            <input id="pf-email" type="text" maxLength={200} value={form.email} onChange={set('email')} />
          </div>
          <fieldset className="field span-2 scheme-checks">
            <legend>Schemes channelled</legend>
            {schemes.map((s) => (
              <label key={s.code} className="check-pill">
                <input type="checkbox" checked={form.eligible_scheme_codes.includes(s.code)} onChange={() => toggleScheme(s.code)} />
                {s.code}
              </label>
            ))}
          </fieldset>
          <div className="field span-2">
            <label htmlFor="pf-source">Source URL</label>
            <input id="pf-source" type="text" placeholder="http://nsfdc.nic.in/our-channel-partners" value={form.source_url} onChange={set('source_url')} />
          </div>
        </div>
        {error && <div className="error-box">{error}</div>}
        <div className="btn-row">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save partner'}</button>
        </div>
      </form>
    </Modal>
  );
}
