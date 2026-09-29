import { useLanguage } from '../context/LanguageContext';

// Keep in sync with the .routing-* colours in index.css.
const ROUTING_COLORS = {
  eligible: '#1a8f5e',
  no_data: '#6b7c8f',
  deprioritized: '#c27a12',
  excluded: '#b02a2a',
};

const ROUTING_ORDER = ['eligible', 'no_data', 'deprioritized', 'excluded'];

export function RoutingBadge({ status, reason }) {
  const { t } = useLanguage();
  if (!status) return null;
  return (
    <span className={`routing-badge routing-${status}`} title={reason || undefined}>
      {t(`routing_${status}`)}
    </span>
  );
}

export function DemoTag() {
  const { t } = useLanguage();
  return (
    <span className="demo-tag" title={t('demo_data_note')}>
      {t('demo_data')}
    </span>
  );
}

function fmtPct(v) {
  return `${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 1 })}%`;
}

/** Admin-entered portfolio figures, with "no data" for anything absent — never a guess. */
export function PartnerMetrics({ partner }) {
  const { t } = useLanguage();
  const utilization =
    partner.fund_utilization_pct ??
    (partner.allocated_funds_inr && partner.disbursed_funds_inr != null
      ? (partner.disbursed_funds_inr / partner.allocated_funds_inr) * 100
      : null);
  const items = [
    [t('metric_npa'), partner.npa_pct],
    [t('metric_overdue'), partner.overdue_pct],
    [t('metric_utilization'), utilization],
  ];

  if (items.every(([, v]) => v == null)) {
    return <div className="partner-metrics muted">{t('metrics_no_data')}</div>;
  }
  return (
    <div className="partner-metrics">
      {partner.metrics_is_demo && <DemoTag />}
      {items.map(([label, v]) => (
        <span key={label}>
          {label}: <strong>{v == null ? t('metric_missing') : fmtPct(v)}</strong>
        </span>
      ))}
      {partner.metrics_as_of_date && (
        <span className="muted">
          {t('metric_as_of')} {partner.metrics_as_of_date}
        </span>
      )}
    </div>
  );
}

export function RoutingLegend() {
  const { t } = useLanguage();
  return (
    <div className="routing-legend" aria-label={t('routing_legend_title')}>
      <span className="legend-title">{t('routing_legend_title')}:</span>
      {ROUTING_ORDER.map((s) => (
        <span key={s} className="legend-item">
          <span className="legend-swatch" style={{ background: ROUTING_COLORS[s] }} />
          {t(`routing_${s}`)}
        </span>
      ))}
    </div>
  );
}
