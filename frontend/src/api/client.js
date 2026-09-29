const BASE = '';

async function errorFrom(res) {
  let detail = res.statusText;
  let body = null;
  try {
    body = await res.json();
    if (typeof body.detail === 'string') detail = body.detail;
    else if (Array.isArray(body.detail)) {
      // FastAPI validation errors: [{loc: [...], msg}, ...]
      detail = body.detail.map((e) => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join('; ');
    } else detail = body.detail?.message || JSON.stringify(body);
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

const json = (method, body) => ({ method, body: JSON.stringify(body) });

function query(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  ).toString();
  return qs ? `?${qs}` : '';
}

/** auth = { token, user }. The user name is percent-encoded: header values must be ASCII. */
function adminHeaders({ token, user }) {
  return { 'X-Admin-Token': token, ...(user ? { 'X-Admin-User': encodeURIComponent(user) } : {}) };
}

function admin(auth, path, options = {}) {
  return request(path, { ...options, headers: { ...adminHeaders(auth), ...options.headers } });
}

export const api = {
  listSchemes: () => request('/api/schemes'),
  getScheme: (code) => request(`/api/schemes/${code}`),
  getStats: () => request('/api/stats'),
  checkEligibility: (profile) => request('/api/eligibility', json('POST', { profile })),
  recommend: (payload) => request('/api/recommend', json('POST', payload)),
  calculate: (payload) => request('/api/calculate', json('POST', payload)),
  partnersNearby: (payload) => request('/api/partners/nearby', json('POST', payload)),
  listActivities: () => request('/api/activities'),
  classifyActivity: (text) => request('/api/activities/classify', json('POST', { text })),
  interpret: (payload) => request('/api/interpret', json('POST', payload)),
  ask: (payload) => request('/ask', json('POST', payload)),
  createApplication: (payload) => request('/api/applications', json('POST', payload)),
  getApplication: (reference) => request(`/api/applications/${encodeURIComponent(reference.trim())}`),

  // Admin — every call takes auth = { token, user }
  adminListPartners: (auth, params) => admin(auth, `/api/admin/partners${query(params)}`),
  adminCreatePartner: (auth, payload) => admin(auth, '/api/admin/partners', json('POST', payload)),
  adminUpdatePartner: (auth, id, payload) => admin(auth, `/api/admin/partners/${id}`, json('PATCH', payload)),
  adminUpdateCapacity: (auth, id, payload) => admin(auth, `/api/admin/partners/${id}/capacity`, json('PATCH', payload)),
  adminUpdateMetrics: (auth, id, payload) => admin(auth, `/api/admin/partners/${id}/metrics`, json('PATCH', payload)),
  adminGeocode: (auth, payload) => admin(auth, '/api/admin/geocode', json('POST', payload)),
  adminDownloadMetricsTemplate: async (auth) => {
    const res = await fetch('/api/admin/partners/metrics/template.csv', { headers: adminHeaders(auth) });
    if (!res.ok) throw await errorFrom(res);
    return res.blob();
  },
  adminImportMetrics: async (auth, file, { dryRun = false, updatedBy = 'admin' } = {}) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`/api/admin/partners/metrics/import${query({ dry_run: dryRun, updated_by: updatedBy })}`, {
      method: 'POST',
      headers: adminHeaders(auth), // no Content-Type: the browser sets the multipart boundary
      body: form,
    });
    if (!res.ok) throw await errorFrom(res);
    return res.json();
  },
  adminListApplications: (auth, params) => admin(auth, `/api/admin/applications${query(params)}`),
  adminUpdateApplicationStatus: (auth, reference, payload) =>
    admin(auth, `/api/admin/applications/${encodeURIComponent(reference)}/status`, json('PATCH', payload)),
  adminListSchemes: (auth) => admin(auth, '/api/admin/schemes'),
  adminUpdateScheme: (auth, code, payload, { dryRun = false } = {}) =>
    admin(auth, `/api/admin/schemes/${code}${query({ dry_run: dryRun })}`, json('PUT', payload)),
  adminAudit: (auth, params) => admin(auth, `/api/admin/audit${query(params)}`),
  adminMetrics: (auth) => admin(auth, '/api/admin/metrics'),
};
