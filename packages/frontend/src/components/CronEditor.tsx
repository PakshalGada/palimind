import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';

type Mode = 'easy' | 'advanced';
type ScheduleType = 'interval' | 'daily' | 'weekly' | 'monthly';
type IntervalUnit = 'minutes' | 'hours';

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

interface EasyState {
  type: ScheduleType;
  every: number;
  everyUnit: IntervalUnit;
  minute: number;
  hour: number;
  days: number[];
  dom: number;
}

const DEFAULT_STATE: EasyState = {
  type: 'interval',
  every: 15,
  everyUnit: 'minutes',
  minute: 0,
  hour: 9,
  days: [1, 2, 3, 4, 5],
  dom: 1,
};

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** Build a 5-field cron string from the easy-mode state. */
function stateToCron(s: EasyState): string {
  switch (s.type) {
    case 'interval':
      if (s.everyUnit === 'minutes') return `*/${Math.max(1, s.every)} * * * *`;
      return `${s.minute} */${Math.max(1, s.every)} * * *`;
    case 'daily':
      return `${s.minute} ${s.hour} * * *`;
    case 'weekly': {
      const days = s.days.length ? s.days.slice().sort((a, b) => a - b) : [1];
      return `${s.minute} ${s.hour} * * ${days.join(',')}`;
    }
    case 'monthly':
      return `${s.minute} ${s.hour} ${s.dom} * *`;
  }
}

/** Best-effort parse of a simple cron back into easy-mode state. Returns null if not parseable. */
function cronToState(expr: string): EasyState | null {
  const f = (expr || '').trim().split(/\s+/);
  if (f.length !== 5) return null;
  const [min, hour, dom, month, dow] = f;
  const m = (v: string) => parseInt(v, 10);

  const isStar = (v: string) => v === '*';
  const parseTime = (): { minute: number; hour: number } | null => {
    if (isStar(min) || isStar(hour)) return null;
    return { minute: m(min), hour: m(hour) };
  };

  // Every N minutes: */N * * * *
  if (min.startsWith('*/') && isStar(hour) && isStar(dom) && isStar(month) && isStar(dow)) {
    return { ...DEFAULT_STATE, type: 'interval', everyUnit: 'minutes', every: parseInt(min.slice(2), 10) || 1 };
  }
  // Every N hours: M */N * * *
  if (hour.startsWith('*/') && isStar(dom) && isStar(month) && isStar(dow) && !isStar(min) && !isStar(hour)) {
    return { ...DEFAULT_STATE, type: 'interval', everyUnit: 'hours', every: parseInt(hour.slice(2), 10) || 1, minute: m(min) };
  }
  // Daily: M H * * *
  if (!isStar(min) && !isStar(hour) && isStar(dom) && isStar(month) && isStar(dow)) {
    const t = parseTime();
    if (!t) return null;
    return { ...DEFAULT_STATE, type: 'daily', ...t };
  }
  // Weekly: M H * * dow list
  if (!isStar(min) && !isStar(hour) && isStar(dom) && isStar(month) && !isStar(dow)) {
    const days = dow.split(',').map(m).filter(n => !isNaN(n) && n >= 0 && n <= 6);
    if (!days.length) return null;
    const t = parseTime();
    if (!t) return null;
    return { ...DEFAULT_STATE, type: 'weekly', ...t, days };
  }
  // Monthly: M H dom * *
  if (!isStar(min) && !isStar(hour) && !isStar(dom) && isStar(month) && isStar(dow)) {
    const t = parseTime();
    if (!t) return null;
    return { ...DEFAULT_STATE, type: 'monthly', ...t, dom: Math.min(31, Math.max(1, m(dom))) };
  }
  return null;
}

const PRESETS: { label: string; cron: string }[] = [
  { label: 'Every minute', cron: '* * * * *' },
  { label: 'Every 5 min', cron: '*/5 * * * *' },
  { label: 'Every 15 min', cron: '*/15 * * * *' },
  { label: 'Every hour', cron: '0 * * * *' },
  { label: 'Daily 9am', cron: '0 9 * * *' },
  { label: 'Weekdays 9am', cron: '0 9 * * 1-5' },
];

/** Human-readable description of a simple 5-field cron. */
export function describeCron(expr: string): string {
  const f = (expr || '').trim().split(/\s+/);
  if (f.length !== 5) return 'Invalid cron';
  const [min, hour, dom, month, dow] = f;
  const isStar = (v: string) => v === '*';
  const time = !isStar(min) && !isStar(hour)
    ? `${pad(parseInt(hour, 10))}:${pad(parseInt(min, 10))}`
    : null;

  if (min.startsWith('*/') && isStar(hour) && isStar(dom) && isStar(month) && isStar(dow))
    return `Every ${parseInt(min.slice(2), 10)} minutes`;
  if (isStar(min) && isStar(hour) && isStar(dom) && isStar(month) && isStar(dow)) return 'Every minute';
  if (hour.startsWith('*/') && isStar(dom) && isStar(month) && isStar(dow))
    return `Every ${parseInt(hour.slice(2), 10)} hours${min !== '0' && !isStar(min) ? ` at minute ${parseInt(min, 10)}` : ''}`;
  if (isStar(dom) && isStar(month) && isStar(dow) && time)
    return `Daily at ${time}`;
  if (isStar(dom) && isStar(month) && !isStar(dow) && time) {
    const names = dow.split(',').map(d => {
      const n = parseInt(d, 10) % 7;
      return DAY_NAMES[n];
    });
    return `Weekly on ${names.join(', ')} at ${time}`;
  }
  if (!isStar(dom) && isStar(month) && isStar(dow) && time)
    return `Monthly on day ${parseInt(dom, 10)} at ${time}`;
  return expr.trim();
}

export default function CronEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (cron: string) => void;
}) {
  const [mode, setMode] = useState<Mode>(() => (cronToState(value) ? 'easy' : 'advanced'));
  const [state, setState] = useState<EasyState>(() => cronToState(value) || DEFAULT_STATE);
  const [raw, setRaw] = useState(value);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<{ ok: boolean; error?: string } | null>(null);
  const lastExpr = useRef(value);

  // When the caller's cron changes externally, resync easy/raw state.
  useEffect(() => {
    if (value === lastExpr.current) return;
    lastExpr.current = value;
    setRaw(value);
    const parsed = cronToState(value);
    if (parsed) setState(parsed);
    if (mode === 'advanced') {
      setValidation(null);
      void runValidation(value);
    }
  }, [value]);

  const push = (cron: string) => {
    lastExpr.current = cron;
    onChange(cron);
  };

  const runValidation = async (expr: string) => {
    setValidating(true);
    try {
      const res = await api.agents.validateCron(expr);
      setValidation(res.valid ? { ok: true } : { ok: false, error: res.error || 'Invalid cron' });
    } catch {
      setValidation({ ok: false, error: 'Could not reach the validation service.' });
    }
    setValidating(false);
  };

  const syncFromEasy = (s: EasyState) => {
    setState(s);
    const cron = stateToCron(s);
    setRaw(cron);
    push(cron);
  };

  const patchState = (p: Partial<EasyState>) => {
    const next = { ...state, ...p };
    if (p.type === 'interval') next.dom = DEFAULT_STATE.dom;
    syncFromEasy(next);
  };

  const switchMode = (m: Mode) => {
    setMode(m);
    if (m === 'easy') {
      const parsed = cronToState(raw) || DEFAULT_STATE;
      setState(parsed);
      const cron = stateToCron(parsed);
      if (cron !== raw) push(cron);
    } else {
      setRaw(lastExpr.current);
      setValidation(null);
      void runValidation(lastExpr.current);
    }
  };

  const time = (m: number, h: number) => `${pad(h)}:${pad(m)}`;

  const description = useMemo(() => describeCron(lastExpr.current), [lastExpr.current]);

  return (
    <div className="cron-editor">
      <div className="cron-editor-tabs" role="tablist" aria-label="Cron editor mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'easy'}
          className={`cron-tab${mode === 'easy' ? ' active' : ''}`}
          onClick={() => switchMode('easy')}
        >
          Easy
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'advanced'}
          className={`cron-tab${mode === 'advanced' ? ' active' : ''}`}
          onClick={() => switchMode('advanced')}
        >
          Advanced
        </button>
      </div>

      {mode === 'easy' ? (
        <div className="cron-easy">
          <div className="cron-presets">
            {PRESETS.map(p => {
              const active = lastExpr.current.trim() === p.cron;
              return (
                <button
                  type="button"
                  key={p.cron}
                  className={`cron-preset${active ? ' active' : ''}`}
                  onClick={() => {
                    const parsed = cronToState(p.cron);
                    if (parsed) setState(parsed);
                    setRaw(p.cron);
                    push(p.cron);
                  }}
                >
                  {p.label}
                </button>
              );
            })}
          </div>

          <div className="cron-type-row">
            <span className="cron-field-label">Runs</span>
            <div className="cron-segmented">
              {([
                ['interval', 'Interval'],
                ['daily', 'Daily'],
                ['weekly', 'Weekly'],
                ['monthly', 'Monthly'],
              ] as [ScheduleType, string][]).map(([t, label]) => (
                <button
                  type="button"
                  key={t}
                  className={`cron-segment${state.type === t ? ' active' : ''}`}
                  onClick={() => patchState({ type: t })}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {state.type === 'interval' && (
            <div className="cron-inline-row">
              <span className="cron-field-label">Every</span>
              <input
                type="number"
                className="cron-num-input"
                min={1}
                max={59}
                value={state.every}
                onChange={e => patchState({ every: Math.max(1, parseInt(e.target.value, 10) || 1) })}
              />
              <select
                className="cron-select"
                value={state.everyUnit}
                onChange={e => patchState({ everyUnit: e.target.value as IntervalUnit })}
              >
                <option value="minutes">minutes</option>
                <option value="hours">hours</option>
              </select>
              {state.everyUnit === 'hours' && (
                <>
                  <span className="cron-field-label">at minute</span>
                  <input
                    type="number"
                    className="cron-num-input"
                    min={0}
                    max={59}
                    value={state.minute}
                    onChange={e => patchState({ minute: Math.min(59, Math.max(0, parseInt(e.target.value, 10) || 0)) })}
                  />
                </>
              )}
            </div>
          )}

          {(state.type === 'daily' || state.type === 'weekly' || state.type === 'monthly') && (
            <div className="cron-inline-row">
              <span className="cron-field-label">at</span>
              <input
                type="time"
                className="cron-time-input"
                value={time(state.minute, state.hour)}
                onChange={e => {
                  const [h, m] = e.target.value.split(':').map(v => parseInt(v, 10));
                  patchState({ hour: isNaN(h) ? state.hour : h, minute: isNaN(m) ? state.minute : m });
                }}
              />
            </div>
          )}

          {state.type === 'weekly' && (
            <div className="cron-weekdays">
              {DAY_NAMES.map((name, idx) => {
                const on = state.days.includes(idx);
                return (
                  <button
                    type="button"
                    key={name}
                    className={`cron-day${on ? ' active' : ''}`}
                    onClick={() => {
                      const days = on ? state.days.filter(d => d !== idx) : [...state.days, idx];
                      patchState({ days: days.length ? days : state.days });
                    }}
                  >
                    {name}
                  </button>
                );
              })}
            </div>
          )}

          {state.type === 'monthly' && (
            <div className="cron-inline-row">
              <span className="cron-field-label">on day</span>
              <input
                type="number"
                className="cron-num-input"
                min={1}
                max={31}
                value={state.dom}
                onChange={e => patchState({ dom: Math.min(31, Math.max(1, parseInt(e.target.value, 10) || 1)) })}
              />
            </div>
          )}
        </div>
      ) : (
        <div className="cron-advanced">
          <div className="cron-raw-row">
            <input
              className={`cron-raw-input${validation && !validation.ok ? ' invalid' : ''}${validation?.ok ? ' valid' : ''}`}
              value={raw}
              placeholder="*/15 * * * *"
              onChange={e => {
                const v = e.target.value;
                setRaw(v);
                push(v);
                if (v.trim()) {
                  setValidating(true);
                  void api.agents.validateCron(v)
                    .then(res => setValidation(res.valid ? { ok: true } : { ok: false, error: res.error || 'Invalid cron' }))
                    .catch(() => setValidation({ ok: false, error: 'Validation unavailable.' }))
                    .finally(() => setValidating(false));
                } else {
                  setValidation(null);
                }
              }}
            />
            {validating && <span className="cron-validating">checking…</span>}
          </div>
          <div className="cron-raw-hint">
            Standard 5-field cron: <code>minute hour day-of-month month day-of-week</code>
          </div>
        </div>
      )}

      <div className="cron-summary">
        <span className="cron-summary-label">Schedule</span>
        <code className="cron-summary-expr">{lastExpr.current || '—'}</code>
        <span className="cron-summary-desc">{description}</span>
        {mode === 'advanced' && validation && !validation.ok && (
          <span className="cron-validation-error">{validation.error}</span>
        )}
      </div>
    </div>
  );
}
