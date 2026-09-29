import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { INDIAN_STATES } from '../../data/indianStates';
import { PartnerMetrics, RoutingBadge, RoutingLegend } from '../PartnerHealth';
import PartnerForm from './PartnerForm';
import { PARTNER_TYPES, ROUTING_STATUSES } from './constants';

const PAGE_SIZE = 25;
const EMPTY_FILTERS = { q: '', partner_type: '', state: '', routing_status: '', missing: '' };

export default function PartnersTab({ auth, schemes, onError }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [search, setSearch] = useState(''); // debounced into filters.q
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(undefined); // undefined = closed, null = new, object = edit

  const load = useCallback(async () => {
    try {
      setData(await api.adminListPartners(auth, { ...filters, page, page_size: PAGE_SIZE }));
    } catch (err) {
      onError(err.message);
    }
  }, [auth, filters, page, onError]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setFilters((f) => (f.q === search ? f : { ...f, q: search }));
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const setFilter = (key) => (e) => {
    setFilters((f) => ({ ...f, [key]: e.target.value }));
    setPage(1);
  };

  function toggleMissing(value) {
    setFilters((f) => ({ ...f, missing: f.missing === value ? '' : value }));
    setPage(1);
  }

  async function changeCapacity(partnerId, capacity_status) {
    try {
      const updated = await api.adminUpdateCapacity(auth, partnerId, { capacity_status, updated_by: auth.user || 'admin' });
      setData((d) => ({ ...d, items: d.items.map((p) => (p.id === partnerId ? updated : p)) }));
    } catch (err) {
      onError(err.message);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <div className="admin-toolbar filters">
        <input
          type="search"
          className="filter-search"
          placeholder="Search name, address, state, district…"
          aria-label="Search partners"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select aria-label="Partner type" value={filters.partner_type} onChange={setFilter('partner_type')}>
          <option value="">All types</option>
          {PARTNER_TYPES.map((pt) => <option key={pt} value={pt}>{pt}</option>)}
        </select>
        <select aria-label="State" value={filters.state} onChange={setFilter('state')}>
          <option value="">All states</option>
          {INDIAN_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select aria-label="Routing status" value={filters.routing_status} onChange={setFilter('routing_status')}>
          <option value="">Any routing status</option>
          {ROUTING_STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
        </select>
        <button type="button" className={`chip${filters.missing === 'coordinates' ? ' active' : ''}`}
          aria-pressed={filters.missing === 'coordinates'} onClick={() => toggleMissing('coordinates')}>
          Missing coordinates {data && `(${data.missing_coordinates})`}
        </button>
        <button type="button" className={`chip${filters.missing === 'district' ? ' active' : ''}`}
          aria-pressed={filters.missing === 'district'} onClick={() => toggleMissing('district')}>
          Missing district {data && `(${data.missing_district})`}
        </button>
        {(search || Object.values(filters).some(Boolean)) && (
          <button type="button" className="btn btn-secondary btn-small"
            onClick={() => { setFilters(EMPTY_FILTERS); setSearch(''); setPage(1); }}>
            Clear filters
          </button>
        )}
        <button type="button" className="btn btn-primary btn-small push-right" onClick={() => setEditing(null)}>
          + Add partner
        </button>
      </div>

      <RoutingLegend />

      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr><th>Name</th><th>Type</th><th>Location</th><th>Routing</th><th>Portfolio figures</th><th>Capacity</th><th /></tr>
          </thead>
          <tbody>
            {data?.items.map((p) => (
              <tr key={p.id}>
                <td>{p.name}<div className="muted">#{p.id}</div></td>
                <td>{p.partner_type}</td>
                <td>
                  {[p.district, p.state].filter(Boolean).join(', ') || <span className="muted">—</span>}
                  {p.lat == null && <div className="warn-text">no coordinates</div>}
                </td>
                <td>
                  <RoutingBadge status={p.routing_status} reason={p.routing_reason} />
                  <div className="routing-reason">{p.routing_reason}</div>
                </td>
                <td><PartnerMetrics partner={p} /></td>
                <td>
                  <select className="capacity-select" aria-label={`Capacity for ${p.name}`} value={p.capacity_status}
                    onChange={(e) => changeCapacity(p.id, e.target.value)}>
                    <option value="available">Available</option>
                    <option value="limited">Limited</option>
                    <option value="not_accepting">Not accepting</option>
                  </select>
                </td>
                <td><button type="button" className="btn btn-secondary btn-small" onClick={() => setEditing(p)}>Edit</button></td>
              </tr>
            ))}
            {data && data.items.length === 0 && (
              <tr><td colSpan={7}>No partners match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {data && (
        <nav className="pager" aria-label="Partner pages">
          <button type="button" className="btn btn-secondary btn-small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Prev</button>
          <span>Page {page} of {totalPages} · {data.total} partner{data.total === 1 ? '' : 's'}</span>
          <button type="button" className="btn btn-secondary btn-small" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next →</button>
        </nav>
      )}

      {editing !== undefined && (
        <PartnerForm
          auth={auth}
          partner={editing}
          schemes={schemes}
          onClose={() => setEditing(undefined)}
          onSaved={() => { setEditing(undefined); load(); }}
        />
      )}
    </>
  );
}
