const BASE = '';

async function errorFrom(res) {
  let detail = res.statusText;
  let body = null;
  try {
    body = await res.json();
    detail = typeof body.detail === 'string' ? body.detail : body.detail?.message || JSON.stringify(body);
  } catch {
    // ignore
  }
  const err = new Error(detail);
  err.status = res.status;
  err.body = body;
  return err;
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  if (!res.ok) throw await errorFrom(res);
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
  listActivities: () => request('/api/activities'),
  classifyActivity: (text) =>
    request('/api/activities/classify', { method: 'POST', body: JSON.stringify({ text }) }),
  interpret: (payload) =>
    request('/api/interpret', { method: 'POST', body: JSON.stringify(payload) }),
  ask: (payload) => request('/ask', { method: 'POST', body: JSON.stringify(payload) }),
  createApplication: (payload) =>
    request('/api/applications', { method: 'POST', body: JSON.stringify(payload) }),
  getApplication: (reference) => request(`/api/applications/${encodeURIComponent(reference.trim())}`),

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
  adminUpdateMetrics: (token, partnerId, payload) =>
    request(`/api/admin/partners/${partnerId}/metrics`, {
      method: 'PATCH',
      headers: { 'X-Admin-Token': token },
      body: JSON.stringify(payload),
    }),
  adminDownloadMetricsTemplate: async (token) => {
    const res = await fetch('/api/admin/partners/metrics/template.csv', { headers: { 'X-Admin-Token': token } });
    if (!res.ok) throw await errorFrom(res);
    return res.blob();
  },
  adminImportMetrics: async (token, file, { dryRun = false, updatedBy = 'admin' } = {}) => {
    const form = new FormData();
    form.append('file', file);
    const params = new URLSearchParams({ dry_run: String(dryRun), updated_by: updatedBy });
    const res = await fetch(`/api/admin/partners/metrics/import?${params}`, {
      method: 'POST',
      headers: { 'X-Admin-Token': token }, // no Content-Type: the browser sets the multipart boundary
      body: form,
    });
    if (!res.ok) throw await errorFrom(res);
    return res.json();
  },
  adminListApplications: (token) => request('/api/admin/applications', { headers: { 'X-Admin-Token': token } }),
  adminUpdateApplicationStatus: (token, reference, payload) =>
    request(`/api/admin/applications/${encodeURIComponent(reference)}/status`, {
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
