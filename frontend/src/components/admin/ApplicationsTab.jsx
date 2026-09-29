import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useLanguage } from '../../context/LanguageContext';
import { formatDateTime } from '../../utils/dates';
import { APPLICATION_STATUSES, NEXT_STATUS } from './constants';

export default function ApplicationsTab({ auth, onError }) {
  const { t } = useLanguage();
  const [status, setStatus] = useState('');
  const [applications, setApplications] = useState(null);

  const load = useCallback(async () => {
    try {
      setApplications(await api.adminListApplications(auth, { status }));
    } catch (err) {
      onError(err.message);
    }
  }, [auth, status, onError]);

  useEffect(() => { load(); }, [load]);

  async function advance(reference, next) {
    try {
      const updated = await api.adminUpdateApplicationStatus(auth, reference, { status: next, updated_by: auth.user || 'admin' });
      setApplications((prev) => prev
        .map((a) => (a.reference === updated.reference ? updated : a))
        .filter((a) => !status || a.status === status));
    } catch (err) {
      onError(err.message);
    }
  }

  return (
    <>
      <div className="admin-toolbar filters">
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {APPLICATION_STATUSES.map((s) => <option key={s} value={s}>{t(`status_${s}`)}</option>)}
        </select>
      </div>
      {applications && applications.length === 0 && <p className="field-hint">No applications{status && ' with this status'}.</p>}
      {applications && applications.length > 0 && (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr><th>Reference</th><th>Created</th><th>Scheme</th><th>Partner</th><th>Applicant</th><th>Status</th><th>Next</th></tr>
            </thead>
            <tbody>
              {applications.map((a) => {
                const next = NEXT_STATUS[a.status];
                const open = a.status !== 'rejected' && a.status !== 'disbursed';
                return (
                  <tr key={a.reference}>
                    <td><strong>{a.reference}</strong></td>
                    <td>{formatDateTime(a.created_at)}</td>
                    <td>{a.scheme_code}</td>
                    <td>{a.partner_name}</td>
                    <td>
                      {a.applicant_name || <span className="muted">(no name)</span>}
                      {a.applicant_contact && <div className="muted">{a.applicant_contact}</div>}
                    </td>
                    <td>{t(`status_${a.status}`)}</td>
                    <td className="admin-actions">
                      {next && (
                        <button type="button" className="btn btn-secondary btn-small" onClick={() => advance(a.reference, next)}>
                          → {t(`status_${next}`)}
                        </button>
                      )}
                      {open && (
                        <button type="button" className="btn btn-danger btn-small" onClick={() => advance(a.reference, 'rejected')}>
                          Reject
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
