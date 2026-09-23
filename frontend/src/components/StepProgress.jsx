export default function StepProgress({ steps, current }) {
  return (
    <div className="step-progress">
      {steps.map((step, i) => (
        <div key={step} className={`step ${i === current ? 'active' : ''} ${i < current ? 'done' : ''}`}>
          <span className="step-dot">{i < current ? '✓' : i + 1}</span>
          <span className="step-label">{step}</span>
        </div>
      ))}
    </div>
  );
}
