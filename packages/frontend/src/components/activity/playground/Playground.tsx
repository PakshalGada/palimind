import { useEffect, useMemo, useState } from 'react';
import { useTheme } from '../../../design/ThemeProvider';
import { useActivityState } from '../hooks';
import { Icon } from '../icons';
import { ActivityStore } from '../store';
import { RunSurface } from '../shell/RunSurface';
import { SCENARIOS } from './scripts';

export default function ActivityPlayground() {
  const { theme, toggleTheme } = useTheme();
  const [scenarioId, setScenarioId] = useState(SCENARIOS[3].id);
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [runToken, setRunToken] = useState(0);
  const [store, setStore] = useState(() => new ActivityStore());
  const scenario = useMemo(
    () => SCENARIOS.find((item) => item.id === scenarioId) ?? SCENARIOS[0],
    [scenarioId],
  );
  const state = useActivityState(store);

  useEffect(() => {
    setPlaying(true);
    setRunToken((value) => value + 1);
  }, [scenarioId]);

  useEffect(() => {
    if (!playing) return undefined;
    const next = new ActivityStore();
    setStore(next);
    const timers: number[] = [];
    let cancelled = false;
    for (const step of scenario.steps) {
      timers.push(
        window.setTimeout(() => {
          if (cancelled) return;
          if (step.event) {
            const event = step.event;
            const now = Date.now();
            if (event.type === 'run.start') {
              next.dispatch({ ...event, startedAt: now });
            } else if (event.type === 'tool.start') {
              next.dispatch({ ...event, startedAt: event.startedAt ?? now });
            } else if (event.type === 'tool.end') {
              next.dispatch({ ...event, at: event.at ?? now });
            } else if (event.type === 'run.end') {
              next.dispatch({ ...event, at: event.at ?? now });
            } else if (event.type === 'reasoning.delta') {
              next.dispatch({ ...event, at: event.at ?? now });
            } else if (event.type === 'reasoning.end') {
              next.dispatch({ ...event, at: event.at ?? now });
            } else if (event.type === 'tool.approval') {
              next.dispatch({ ...event, at: event.at ?? now });
            } else {
              next.dispatch(event);
            }
          }
          if (step.buffer) next.buffers.get(step.buffer.key).append(step.buffer.text);
        }, step.at / speed),
      );
    }
    const last = scenario.steps[scenario.steps.length - 1]?.at ?? 0;
    timers.push(
      window.setTimeout(() => {
        if (!cancelled) setPlaying(false);
      }, last / speed + 120),
    );
    return () => {
      cancelled = true;
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [playing, runToken, speed, scenario]);

  const showAnswer = Boolean(state?.answerStarted);

  return (
    <div
      className={`act ${reduced ? 'act-reduce' : ''}`}
      style={{ minHeight: '100vh', background: 'var(--color-bg)', color: 'var(--color-text-primary)', padding: 24 }}
    >
      <div style={{ maxWidth: 760, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <header style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 15 }}>Activity playground</strong>
          <span className="act-muted" style={{ fontSize: 12 }}>
            Dev only
          </span>
          <span style={{ marginInlineStart: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
            <button type="button" className="act-btn" onClick={toggleTheme}>
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={13} />
              {theme === 'dark' ? 'Light' : 'Dark'}
            </button>
            <button
              type="button"
              className={`act-btn ${reduced ? 'act-btn--primary' : ''}`}
              onClick={() => setReduced((value) => !value)}
            >
              Reduced motion
            </button>
          </span>
        </header>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <select
            className="act-select"
            value={scenarioId}
            aria-label="Scenario"
            onChange={(event) => setScenarioId(event.target.value)}
            style={{ border: '1px solid var(--act-hairline)', borderRadius: 6, padding: '4px 8px' }}
          >
            {SCENARIOS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            Speed
            <input
              type="range"
              min={0.5}
              max={4}
              step={0.5}
              value={speed}
              onChange={(event) => setSpeed(Number(event.target.value))}
            />
            <span className="act-tabular">{speed}x</span>
          </label>
          <button
            type="button"
            className="act-btn act-btn--primary"
            onClick={() => {
              setPlaying(true);
              setRunToken((value) => value + 1);
            }}
          >
            <Icon name="play" size={13} />
            Replay
          </button>
          <button type="button" className="act-btn" onClick={() => setPlaying(false)}>
            Stop
          </button>
        </div>

        <div style={{ borderTop: '1px solid var(--act-hairline)', paddingTop: 16, minHeight: 220 }}>
          <RunSurface store={store}>
            {showAnswer && (
              <div style={{ maxWidth: 720, marginTop: 12, fontSize: 14, lineHeight: 1.6 }}>
                {scenario.answer}
              </div>
            )}
          </RunSurface>
        </div>
      </div>
    </div>
  );
}
