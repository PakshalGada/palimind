/**
 * "Thought for Xs" badge shown once the answer starts streaming. The same
 * markup used to be assembled twice (token + agent:token paths).
 */
export default function ThoughtDurationBadge({ duration }: { duration: string }) {
  return (
    <div className="thought-duration-badge">
      <svg
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
      Thought for {duration}
    </div>
  );
}
