/**
 * Collapsible "Thinking" block shown above the streamed answer. Reuses the
 * long-standing .thinking-block styles from Messages.css so live and history
 * surfaces share one look.
 */
export default function ThinkingBlock({ text }: { text: string }) {
  if (!text) return null;
  return (
    <details className="thinking-block">
      <summary className="thinking-toggle">Thinking</summary>
      <div className="thinking-body">{text}</div>
    </details>
  );
}
