import { Fragment, useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { formatDateTime } from '../../utils/dates';

const PAGE_SIZE = 25;
const fmt = (v) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));

export default function AuditTab({ auth, onError }) {
  const [entityType, setEntityType] = useState('');
  const [entityId, setEntityId] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await api.adminAudit(auth, { entity_type: entityType, entity_id: entityId.trim(), page, page_size: PAGE_SIZE }));
    } catch (err) {
      onError(err.message);
    }
  }, [auth, entityType, entityId, page, onError]);

  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <div className="admin-toolbar filters">
        <select aria-label="Entity type" value={entityType} onChange={(e) => { setEntityType(e.target.value); setPage(1); }}>
          <option value="">All changes</option>
          <option value="partner">Partners</option>
          <option value="scheme">Schemes</option>
          <option value="application">Applications</option>
        </select>
        <input type="search" className="filter-search" aria-label="Entity id"
          placeholder="Partner id, scheme code or reference" value={entityId}
          onChange={(e) => { setEntityId(e.target.value); setPage(1); }} />
      </div>

      <div className="table-scroll">
        <table className="admin-table">
          <thead><tr><th>When</th><th>Who</th><th>What</th><th>Changed</th><th /></tr></thead>
          <tbody>
            {data?.items.map((e) => (
              <Fragment key={e.id}>
                <tr>
                  <td>{formatDateTime(e.created_at)}</td>
                  <td>{e.actor}</td>
                  <td>{e.entity_type} <strong>{e.entity_id}</strong> — {e.action.replace('_', ' ')}</td>
                  <td>{e.before === null ? <span className="muted">new record</span> : e.changed_fields.join(', ')}</td>
                  <td>
                    <button type="button" className="btn btn-secondary btn-small" aria-expanded={open === e.id}
                      onClick={() => setOpen(open === e.id ? null : e.id)}>
                      {open === e.id ? 'Hide' : 'Details'}
                    </button>
                  </td>
                </tr>
                {open === e.id && (
                  <tr className="audit-detail">
                    <td colSpan={5}>
                      <table className="admin-table diff-table">
                        <thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>
                        <tbody>
                          {e.changed_fields.map((f) => (
                            <tr key={f}>
                              <td>{f}</td>
                              <td className="diff-before">{fmt(e.before?.[f])}</td>
                              <td className="diff-after">{fmt(e.after?.[f])}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {data && data.items.length === 0 && <tr><td colSpan={5}>No changes recorded yet.</td></tr>}
          </tbody>
        </table>
      </div>

      {data && data.total > PAGE_SIZE && (
        <nav className="pager" aria-label="Audit pages">
          <button type="button" className="btn btn-secondary btn-small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Newer</button>
          <span>Page {page} of {totalPages} · {data.total} changes</span>
          <button type="button" className="btn btn-secondary btn-small" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Older →</button>
        </nav>
      )}
    </>
  );
}
