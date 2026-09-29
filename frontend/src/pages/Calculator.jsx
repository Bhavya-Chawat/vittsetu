import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import { api } from '../api/client';
import StepProgress from '../components/StepProgress';

const FREQUENCIES = ['monthly', 'quarterly', 'half_yearly'];

function formatINR(n) {
  return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

function compactINR(n) {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(n >= 1e8 ? 0 : 1)}Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(n >= 1e6 ? 0 : 1)}L`;
  if (n >= 1e3) return `₹${(n / 1e3).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

/** Stacked bars: principal (bottom) and interest (top) of each instalment. Plain SVG, no chart library. */
function RepaymentChart({ schedule, t }) {
  const W = 640;
  const H = 220;
  const m = { top: 10, right: 8, bottom: 26, left: 52 };
  const plotW = W - m.left - m.right;
  const plotH = H - m.top - m.bottom;
  const maxY = Math.max(...schedule.map((r) => r.instalment)) || 1;
  const slot = plotW / schedule.length;
  const barW = Math.max(1, slot * 0.72);
  const y = (v) => m.top + plotH - (v / maxY) * plotH;
  const ticks = [0, maxY / 2, maxY];
  const labelEvery = Math.ceil(schedule.length / 8);

  const totalPrincipal = schedule.reduce((s, r) => s + r.principal, 0);
  const totalInterest = schedule.reduce((s, r) => s + r.interest, 0);

  return (
    <figure className="chart">
      <figcaption>
        <strong>{t('chart_title')}</strong>
        <span className="chart-legend">
          <span><i className="swatch swatch-principal" /> {t('chart_principal')} {formatINR(totalPrincipal)}</span>
          <span><i className="swatch swatch-interest" /> {t('chart_interest')} {formatINR(totalInterest)}</span>
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`${t('chart_title')}: ${schedule.length} instalments, principal ${formatINR(totalPrincipal)}, interest ${formatINR(totalInterest)}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={m.left} x2={W - m.right} y1={y(v)} y2={y(v)} className="chart-grid" />
            <text x={m.left - 6} y={y(v)} className="chart-axis" textAnchor="end" dominantBaseline="middle">{compactINR(v)}</text>
          </g>
        ))}
        {schedule.map((r, i) => {
          const x = m.left + i * slot + (slot - barW) / 2;
          return (
            <g key={r.period}>
              <title>{`#${r.period} (month ${r.due_month}): ${t('chart_principal')} ${formatINR(r.principal)}, ${t('chart_interest')} ${formatINR(r.interest)}`}</title>
              <rect x={x} y={y(r.principal)} width={barW} height={plotH + m.top - y(r.principal)} className="bar-principal" />
              <rect x={x} y={y(r.principal + r.interest)} width={barW} height={y(r.principal) - y(r.principal + r.interest)} className="bar-interest" />
              {(i % labelEvery === 0 || i === schedule.length - 1) && (
                <text x={x + barW / 2} y={H - 8} className="chart-axis" textAnchor="middle">{r.period}</text>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

function ScheduleTable({ schedule, t }) {
  return (
    <details className="schedule">
      <summary>{t('schedule_title')} ({schedule.length})</summary>
      <div className="table-scroll schedule-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>{t('schedule_period')}</th><th>{t('schedule_due')}</th><th>{t('schedule_opening')}</th>
              <th>{t('schedule_instalment')}</th><th>{t('schedule_interest')}</th><th>{t('schedule_principal')}</th>
              <th>{t('schedule_closing')}</th>
            </tr>
          </thead>
          <tbody>
            {schedule.map((r) => (
              <tr key={r.period}>
                <td>{r.period}</td><td>{r.due_month}</td><td>{formatINR(r.opening_balance)}</td>
                <td>{formatINR(r.instalment)}</td><td>{formatINR(r.interest)}</td><td>{formatINR(r.principal)}</td>
                <td>{formatINR(r.closing_balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export default function Calculator() {
  const { t } = useLanguage();
  const { state: appState, update } = useAppState();
  const navigate = useNavigate();

  const scheme = appState.selectedScheme;
  const cost = appState.business?.estimated_cost ?? appState.education?.course_fee;
  const isEducation = scheme?.scheme_type === 'education_loan';

  // A selected partner fixes the rate; otherwise default to the partner type the recommender expects.
  const partner = appState.selectedPartner?.eligible_scheme_codes?.includes(scheme?.code) ? appState.selectedPartner : null;
  const expectedType = appState.recommendResult?.comparison?.find((r) => r.code === scheme?.code)?.effective_rate_partner_type ?? '';

  const [frequency, setFrequency] = useState('quarterly');
  const [tenure, setTenure] = useState(null); // null = maximum
  const [loanInput, setLoanInput] = useState(''); // '' = maximum
  const [partnerType, setPartnerType] = useState(expectedType);
  const [treatment, setTreatment] = useState('capitalized');
  const [courseDuration, setCourseDuration] = useState(appState.education?.course_duration_months ?? '');
  const [repaymentStarted, setRepaymentStarted] = useState(appState.education?.repayment_started ?? false);
  const [calc, setCalc] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!scheme || !cost) navigate('/eligibility');
  }, [scheme, cost, navigate]);

  useEffect(() => {
    if (!scheme || !cost) return undefined;
    const timer = setTimeout(async () => {
      try {
        const res = await api.calculate({
          scheme_code: scheme.code,
          project_cost: cost,
          loan_amount: loanInput === '' ? null : Number(loanInput),
          tenure_months: tenure,
          repayment_frequency: frequency,
          partner_id: partner?.id ?? null,
          partner_type: partner ? null : partnerType || null,
          activity_category: appState.business?.activity_category ?? null,
          repayment_started: repaymentStarted,
          course_duration_months: courseDuration === '' ? null : Number(courseDuration),
          moratorium_interest: treatment,
        });
        setCalc(res);
        setError(null);
        update({ calculation: res });
      } catch (err) {
        setError(err.message);
      }
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheme, cost, loanInput, tenure, frequency, partner?.id, partnerType, repaymentStarted, courseDuration, treatment]);

  const steps = [t('step_eligibility'), t('step_requirement'), t('step_results'), t('step_calculator'), t('step_partners'), t('step_checklist')];

  if (!scheme) return null;

  const rateOptions = calc?.rate_options ?? {};
  const ratesVary = new Set(Object.values(rateOptions)).size > 1;
  const freqLabel = (f) => t(`freq_${f}`);

  return (
    <div>
      <StepProgress steps={steps} current={3} />
      <div className="card">
        <h2>{scheme.name} — {t('step_calculator')}</h2>

        <div className="calc-controls">
          <div className="field">
            <label id="freq-label">{t('calc_frequency')}</label>
            <div className="segmented" role="radiogroup" aria-labelledby="freq-label">
              {FREQUENCIES.map((f) => (
                <button key={f} type="button" role="radio" aria-checked={frequency === f}
                  className={frequency === f ? 'active' : ''} onClick={() => setFrequency(f)}>
                  {freqLabel(f)}
                </button>
              ))}
            </div>
            <div className="field-hint">{t('freq_hint')}</div>
          </div>

          {ratesVary && (
            <div className="field">
              {partner ? (
                <>
                  <label>{t('calc_rate_from_partner')}</label>
                  <div>{partner.name} ({partner.partner_type}) — <strong>{calc?.interest_rate_pct}% p.a.</strong></div>
                </>
              ) : (
                <>
                  <label htmlFor="partner-type">{t('calc_partner_type')}</label>
                  <select id="partner-type" value={partnerType} onChange={(e) => setPartnerType(e.target.value)}>
                    <option value="">{t('calc_partner_type_any')}</option>
                    {Object.entries(rateOptions).map(([pt, r]) => (
                      <option key={pt} value={pt}>{pt} — {r}%</option>
                    ))}
                  </select>
                </>
              )}
            </div>
          )}

          {isEducation && (
            <>
              <div className="field checkbox-field">
                <input id="calc-repayment-started" type="checkbox" checked={repaymentStarted}
                  onChange={(e) => setRepaymentStarted(e.target.checked)} />
                <label htmlFor="calc-repayment-started" style={{ marginBottom: 0 }}>{t('calc_repayment_started')}</label>
              </div>
              {!repaymentStarted && (
                <div className="field">
                  <label htmlFor="calc-course-duration">{t('course_duration_label')}</label>
                  <input id="calc-course-duration" type="number" min="1" max="120" value={courseDuration}
                    onChange={(e) => setCourseDuration(e.target.value)} />
                </div>
              )}
            </>
          )}

          {calc && (
            <>
              <div className="field">
                <label htmlFor="loan-amount">{t('calc_loan_input')}: {formatINR(calc.loan_amount)}</label>
                <input id="loan-amount-range" type="range" aria-label={t('calc_loan_input')}
                  min={Math.min(1000, calc.max_loan_amount)} max={calc.max_loan_amount} step="1000"
                  value={calc.loan_amount} onChange={(e) => setLoanInput(e.target.value)} />
                <div className="inline-inputs">
                  <input id="loan-amount" type="number" min="1" max={calc.max_loan_amount} step="1"
                    value={loanInput === '' ? calc.loan_amount : loanInput}
                    onChange={(e) => setLoanInput(e.target.value)} />
                  <button type="button" className="btn btn-secondary btn-small" onClick={() => setLoanInput('')}>
                    {t('calc_loan_max')}: {formatINR(calc.max_loan_amount)}
                  </button>
                </div>
              </div>

              <div className="field">
                <label htmlFor="tenure">
                  {t('calc_tenure')}: {calc.tenure_months} {t('months_short')}
                  <span className="muted">
                    {' '}({t('tenure_breakdown').replace('{m}', calc.moratorium_months).replace('{r}', calc.repayment_months)})
                  </span>
                </label>
                <input id="tenure" type="range" min={calc.min_tenure_months} max={calc.max_tenure_months}
                  step={calc.period_months} value={calc.tenure_months}
                  onChange={(e) => setTenure(Number(e.target.value))} />
                <div className="range-ends muted">
                  <span>{calc.min_tenure_months}</span><span>{calc.max_tenure_months}</span>
                </div>
              </div>

              <div className="field">
                <label id="treatment-label">{t('calc_moratorium_interest')}: {formatINR(calc.moratorium_interest)}</label>
                <div className="segmented" role="radiogroup" aria-labelledby="treatment-label">
                  {['capitalized', 'serviced'].map((v) => (
                    <button key={v} type="button" role="radio" aria-checked={treatment === v}
                      className={treatment === v ? 'active' : ''} onClick={() => setTreatment(v)}>
                      {t(`calc_${v}`)}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        {error && <div className="error-box">{error}</div>}

        {calc && (
          <>
            <div className="calc-grid">
              <div className="calc-stat">
                <div className="label">{t('calc_loan_amount')}</div>
                <div className="value">{formatINR(calc.loan_amount)}</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_contribution')}</div>
                <div className="value">{formatINR(calc.applicant_contribution)}</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_interest')}</div>
                <div className="value">{calc.interest_rate_pct}% p.a.</div>
                {calc.rate_partner_type && <div className="muted">via {calc.rate_partner_type}</div>}
              </div>
              <div className="calc-stat highlight">
                <div className="label">{t('calc_instalment')} ({freqLabel(calc.repayment_frequency).toLowerCase()}) × {calc.number_of_instalments}</div>
                <div className="value">{formatINR(calc.instalment_amount)}</div>
                <div className="muted">{t('calc_monthly_equiv').replace('{amount}', formatINR(calc.monthly_equivalent))}</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_moratorium')}</div>
                <div className="value">{calc.moratorium_months} mo</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_total_interest')}</div>
                <div className="value">{formatINR(calc.total_interest)}</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_total_payment')}</div>
                <div className="value">{formatINR(calc.total_payment)}</div>
              </div>
              <div className="calc-stat">
                <div className="label">{t('calc_total_cost')}</div>
                <div className="value">{formatINR(calc.total_cost)}</div>
              </div>
            </div>

            <RepaymentChart schedule={calc.schedule} t={t} />
            <ScheduleTable schedule={calc.schedule} t={t} />

            <ul className="notes-list">
              {calc.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </>
        )}

        <div className="btn-row">
          <button className="btn btn-secondary" onClick={() => navigate('/results')}>{t('back')}</button>
          <button className="btn btn-primary" onClick={() => navigate('/partners')}>{t('find_partners')}</button>
        </div>
      </div>
    </div>
  );
}
