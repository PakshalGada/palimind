import { useEffect, useMemo, useState } from 'react';

const GRID = 12;

function hashSeed(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(a: number) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export default function AgentAvatar({
  seed,
  thinking = false,
  size = 16,
}: {
  seed: string;
  thinking?: boolean;
  size?: number;
}) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!thinking) return;
    const id = setInterval(() => setTick(t => t + 1), 400);
    return () => clearInterval(id);
  }, [thinking]);

  const colors = useMemo(() => {
    const base = hashSeed(seed) % 360;
    const rand = mulberry32(base + tick * 7919);
    return Array.from({ length: GRID * GRID }, () => {
      const h = (base + rand() * 44 - 22 + 360) % 360;
      const s = 48 + rand() * 30;
      const l = 34 + rand() * 34;
      return `hsl(${h.toFixed(0)}, ${s.toFixed(0)}%, ${l.toFixed(0)}%)`;
    });
  }, [seed, tick]);

  return (
    <span className="agent-avatar" style={{ width: size, height: size }} aria-hidden>
      <span className="agent-avatar-grid">
        {colors.map((c, i) => (
          <span key={`${i}-${c}`} className="agent-avatar-cell" style={{ background: c }} />
        ))}
      </span>
    </span>
  );
}
