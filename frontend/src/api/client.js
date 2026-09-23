const BASE = '';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  listSchemes: () => request('/api/schemes'),
  getScheme: (code) => request(`/api/schemes/${code}`),
  checkEligibility: (profile) =>
    request('/api/eligibility', { method: 'POST', body: JSON.stringify({ profile }) }),
  recommend: (payload) =>
    request('/api/recommend', { method: 'POST', body: JSON.stringify(payload) }),
  calculate: (payload) =>
    request('/api/calculate', { method: 'POST', body: JSON.stringify(payload) }),
  partnersNearby: (payload) =>
    request('/api/partners/nearby', { method: 'POST', body: JSON.stringify(payload) }),
  interpret: (payload) =>
    request('/api/interpret', { method: 'POST', body: JSON.stringify(payload) }),
  ask: (payload) => request('/ask', { method: 'POST', body: JSON.stringify(payload) }),

  // Admin
  adminListPartners: (token) => request('/api/admin/partners', { headers: { 'X-Admin-Token': token } }),
  adminCreatePartner: (token, payload) =>
    request('/api/admin/partners', {
      method: 'POST',
      headers: { 'X-Admin-Token': token },
      body: JSON.stringify(payload),
    }),
  adminUpdateCapacity: (token, partnerId, payload) =>
    request(`/api/admin/partners/${partnerId}/capacity`, {
      method: 'PATCH',
      headers: { 'X-Admin-Token': token },
      body: JSON.stringify(payload),
    }),
  adminListSchemes: (token) => request('/api/admin/schemes', { headers: { 'X-Admin-Token': token } }),
  adminUpdateScheme: (token, code, payload) =>
    request(`/api/admin/schemes/${code}`, {
      method: 'PUT',
      headers: { 'X-Admin-Token': token },
      body: JSON.stringify(payload),
    }),
};
