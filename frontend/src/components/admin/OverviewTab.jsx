import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useLanguage } from '../../context/LanguageContext';
import { ROUTING_STATUSES } from './constants';

/** Horizontal bar list: label, bar proportional to the largest value, count. */
function BarList({ rows, colorFor }) {
  const max = Math.max(1, ...rows.map(([, v]) => v));
  return (
    <ul className="bar-list">
      {rows.map(([key, value, label]) => (
        <li key={key}>
          <span className="bar-label">{label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(value / max) * 100}%`, background: colorFor?.(key) }} />
          </span>
          <span className="bar-value">{value}</span>
        </li>
      ))}
    </ul>
  );
}

export default function OverviewTab({ auth, onError }) {
  const { t } = useLanguage();
  const [m, setM] = useState(null);

  useEffect(() => {
    api.adminMetrics(auth).then(setM).catch((err) => onError(err.message));
  }, [auth, onError]);

  if (!m) return <p className="field-hint">Loading…</p>;

  return (
    <div className="overview-grid">
      <section className="stat-card">
        <div className="stat-label">Applications routed</div>
        <div className="stat-value">{m.applications_total}</div>
      </section>
      <section className="stat-card">
        <div className="stat-label">Median days, routed → disbursed</div>
        <div className="stat-value">{m.median_days_routed_to_disbursed ?? '—'}</div>
        <div className="muted">{m.disbursed_count ? `across ${m.disbursed_count} disbursed` : 'nothing disbursed yet'}</div>
      </section>
      <section className="stat-card">
        <div className="stat-label">Partners</div>
        <div className="stat-value">{m.partners_total}</div>
        <div className="muted">{m.partners_with_real_metrics} with real figures · {m.partners_with_demo_metrics} demo</div>
      </section>
      <section className="stat-card">
        <div className="stat-label">Data gaps</div>
        <div className="muted">{m.partners_missing_coordinates} without coordinates</div>
        <div className="muted">{m.partners_missing_district} without district</div>
      </section>

      <section className="stat-card span-2">
        <h3>Applications by status</h3>
        <BarList rows={Object.entries(m.applications_by_status).map(([s, n]) => [s, n, t(`status_${s}`)])}
          colorFor={(s) => (s === 'rejected' ? 'var(--color-danger)' : s === 'disbursed' ? 'var(--color-accent)' : undefined)} />
      </section>
      <section className="stat-card span-2">
        <h3>Partners by routing status</h3>
        <BarList rows={ROUTING_STATUSES.map((s) => [s, m.partners_by_routing_status[s] ?? 0, t(`routing_${s}`)])}
          colorFor={(s) => `var(--routing-${s})`} />
        {m.partners_with_demo_metrics > 0 && (
          <p className="field-hint">Includes DEMO DATA figures for {m.partners_with_demo_metrics} partner(s).</p>
        )}
      </section>
    </div>
  );
}
