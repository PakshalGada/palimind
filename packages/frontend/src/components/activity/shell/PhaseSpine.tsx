import type { RunPhase } from '../model';

type Section = 'gather' | 'analyze' | 'write';

const SECTION_OF: Record<RunPhase, Section> = {
  routing: 'gather',
  searching: 'gather',
  reading: 'gather',
  analyzing: 'analyze',
  synthesizing: 'analyze',
  writing: 'write',
};

const SECTIONS: readonly { id: Section; label: string }[] = [
  { id: 'gather', label: 'Gather' },
  { id: 'analyze', label: 'Analyze' },
  { id: 'write', label: 'Write' },
];

/** Index of the furthest section any phase event has reached. */
function furthestIndex(phase?: RunPhase): number {
  if (!phase) return -1;
  return SECTIONS.findIndex((section) => section.id === SECTION_OF[phase]);
}

/**
 * A 2px segment bar: three equal-weight sections that fill by real phase
 * events, never by percentages. The active section pulses at full opacity.
 * Hidden entirely under reduced motion (CSS).
 */
export function PhaseSpine({ phase }: { phase?: RunPhase }) {
  const active = furthestIndex(phase);
  return (
    <div className="act-spine" role="presentation" aria-hidden="true">
      {SECTIONS.map((section, index) => {
        const state = index < active ? 'done' : index === active ? 'active' : 'todo';
        return (
          <span
            key={section.id}
            className={`act-spine__seg act-spine__seg--${state}`}
            data-phase={section.label}
          />
        );
      })}
    </div>
  );
}
