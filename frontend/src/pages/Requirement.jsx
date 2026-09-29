import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import { useAppState } from '../context/AppStateContext';
import { api } from '../api/client';
import StepProgress from '../components/StepProgress';

export default function Requirement() {
  const { t, lang } = useLanguage();
  const { state: appState, update } = useAppState();
  const navigate = useNavigate();

  const purpose = appState.profile?.purpose ?? 'business';

  useEffect(() => {
    if (!appState.profile) navigate('/eligibility');
  }, [appState.profile, navigate]);

  const [freeText, setFreeText] = useState('');
  const [interpreting, setInterpreting] = useState(false);
  const [interpretNote, setInterpretNote] = useState(null);

  const [projectType, setProjectType] = useState(appState.business?.project_type ?? '');
  const [projectCost, setProjectCost] = useState(appState.business?.estimated_cost ?? '');
  const [courseName, setCourseName] = useState(appState.education?.course_name ?? '');
  const [courseFee, setCourseFee] = useState(appState.education?.course_fee ?? '');
  const [repaymentStarted, setRepaymentStarted] = useState(appState.education?.repayment_started ?? false);
  const [courseDuration, setCourseDuration] = useState(appState.education?.course_duration_months ?? '');

  // Activity: suggested deterministically from the description, confirmed by the user.
  const [categories, setCategories] = useState([]);
  const [activity, setActivity] = useState(appState.business?.activity_category ?? '');
  const [activityTouched, setActivityTouched] = useState(Boolean(appState.business?.activity_category));
  const [suggestion, setSuggestion] = useState(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (purpose !== 'business') return;
    api.listActivities().then(setCategories).catch(() => setCategories([]));
  }, [purpose]);

  useEffect(() => {
    if (purpose !== 'business' || !projectType.trim()) return undefined;
    const timer = setTimeout(async () => {
      try {
        const res = await api.classifyActivity(projectType);
        setSuggestion(res.category ? res : null);
        if (!activityTouched) setActivity(res.category ?? '');
      } catch {
        setSuggestion(null);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [projectType, purpose, activityTouched]);

  async function handleInterpret() {
    if (!freeText.trim()) return;
    setInterpreting(true);
    setInterpretNote(null);
    try {
      const res = await api.interpret({ text: freeText, language: lang });
      if (purpose === 'business') {
        if (res.project_type) setProjectType(res.project_type);
        if (res.estimated_cost) setProjectCost(res.estimated_cost);
        if (res.activity_category) {
          setActivity(res.activity_category);
          setActivityTouched(false); // still a suggestion until the user confirms
        }
      } else {
        if (res.course_name) setCourseName(res.course_name);
        if (res.course_fee) setCourseFee(res.course_fee);
      }
      setInterpretNote(res.confidence_note);
    } catch (err) {
      setInterpretNote(err.message);
    } finally {
      setInterpreting(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const payload = {
        profile: appState.profile,
        lat: appState.location?.lat ?? null,
        lon: appState.location?.lon ?? null,
      };
      if (purpose === 'business') {
        const business = {
          project_type: projectType,
          estimated_cost: Number(projectCost),
          activity_category: activity || null,
        };
        payload.business = business;
        update({ business });
      } else {
        const education = {
          course_name: courseName,
          course_fee: Number(courseFee),
          repayment_started: repaymentStarted,
          course_duration_months: courseDuration ? Number(courseDuration) : null,
        };
        payload.education = education;
        update({ education });
      }
      const result = await api.recommend(payload);
      update({ recommendResult: result, calculation: null });
      navigate('/results');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const steps = [t('step_eligibility'), t('step_requirement'), t('step_results'), t('step_calculator'), t('step_partners'), t('step_checklist')];
  const categoryLabel = (c) => (lang === 'hi' ? c.label_hi : c.label);
  const shownSuggestion = projectType.trim() ? suggestion : null;

  return (
    <div>
      <StepProgress steps={steps} current={1} />
      <div className="card">
        <h2>{t('step_requirement')}</h2>

        <div className="field">
          <label htmlFor="free-text">{t('or_describe')}</label>
          <textarea
            id="free-text"
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder={t('describe_placeholder')}
          />
          <button type="button" className="btn btn-secondary" style={{ marginTop: 8 }} onClick={handleInterpret} disabled={interpreting}>
            {interpreting ? '…' : t('interpret_button')}
          </button>
          {interpretNote && <div className="field-hint" style={{ marginTop: 6 }}>{interpretNote}</div>}
        </div>

        <form onSubmit={handleSubmit}>
          {purpose === 'business' ? (
            <>
              <div className="field">
                <label htmlFor="project-type">{t('project_type_label')}</label>
                <input id="project-type" type="text" required value={projectType} onChange={(e) => setProjectType(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="activity">{t('activity_label')}</label>
                <select
                  id="activity"
                  required
                  value={activity}
                  onChange={(e) => {
                    setActivity(e.target.value);
                    setActivityTouched(true);
                  }}
                >
                  <option value="">{t('activity_choose')}</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>{categoryLabel(c)}</option>
                  ))}
                </select>
                {shownSuggestion && (
                  <div className="field-hint">
                    {t('activity_suggested')}: <strong>{categoryLabel(categories.find((c) => c.id === shownSuggestion.category) ?? { label: shownSuggestion.label, label_hi: shownSuggestion.label })}</strong>
                    {' '}({t('activity_matched')}: {shownSuggestion.matched_keywords.join(', ')})
                  </div>
                )}
                <div className="field-hint">{t('activity_confirm_hint')}</div>
              </div>
              <div className="field">
                <label htmlFor="project-cost">{t('project_cost_label')}</label>
                <input id="project-cost" type="number" min="1" required value={projectCost} onChange={(e) => setProjectCost(e.target.value)} />
              </div>
            </>
          ) : (
            <>
              <div className="field">
                <label htmlFor="course-name">{t('course_name_label')}</label>
                <input id="course-name" type="text" required value={courseName} onChange={(e) => setCourseName(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="course-fee">{t('course_fee_label')}</label>
                <input id="course-fee" type="number" min="1" required value={courseFee} onChange={(e) => setCourseFee(e.target.value)} />
              </div>
              <div className="field checkbox-field">
                <input
                  type="checkbox"
                  id="repayment-started"
                  checked={repaymentStarted}
                  onChange={(e) => setRepaymentStarted(e.target.checked)}
                />
                <label htmlFor="repayment-started" style={{ marginBottom: 0 }}>{t('repayment_started_label')}</label>
              </div>
              <div className="field">
                <label htmlFor="course-duration">{t('course_duration_label')}</label>
                <input
                  id="course-duration"
                  type="number"
                  min="1"
                  max="120"
                  required={!repaymentStarted}
                  value={courseDuration}
                  onChange={(e) => setCourseDuration(e.target.value)}
                />
                <div className="field-hint">{t('course_duration_hint')}</div>
              </div>
            </>
          )}

          {error && <div className="error-box">{error}</div>}

          <div className="btn-row">
            <button type="button" className="btn btn-secondary" onClick={() => navigate('/eligibility')}>{t('back')}</button>
            <button type="submit" className="btn btn-primary" disabled={loading}>{loading ? '…' : t('continue')}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
