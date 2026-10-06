import { useEffect, useState } from 'react';
import { Hash, MessageCircle, Search, TrendingUp } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { Modal, EmptyState } from '../ui/primitives';
import type { SocialSignal } from '../types';
import './SocialSignals.css';

function sentimentClass(label: string): string {
  if (label === 'positive') return 'is-positive';
  if (label === 'negative') return 'is-negative';
  return 'is-neutral';
}

export default function SocialSignals() {
  const { addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [signal, setSignal] = useState<SocialSignal | null>(null);

  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener('palimind:open-social', handler);
    return () => window.removeEventListener('palimind:open-social', handler);
  }, []);

  const run = async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setSignal(null);
    try {
      const data = await api.research.social(query.trim());
      if (data.error) {
        addToast(data.error);
      } else {
        setSignal(data);
      }
    } catch {
      addToast('Social search failed.');
    } finally {
      setLoading(false);
    }
  };

  const sentiment = signal?.sentiment;

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      title="X / Twitter Signals"
      subtitle="Real-time social sentiment, trends and posts (via web index)."
      width={760}
    >
      <div className="social-search">
        <Search size={15} className="social-search-icon" />
        <input
          value={query}
          placeholder="Topic, ticker or hashtag…"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void run();
          }}
        />
        <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={run} disabled={loading}>
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>

      {!signal && !loading && (
        <EmptyState
          icon={<MessageCircle size={26} />}
          title="Analyse social sentiment"
          description="Enter a topic to gauge X/Twitter sentiment, spot trends and read cited posts."
        />
      )}

      {signal && (
        <div className="social-results">
          <div className="social-summary">
            <div className={`social-sentiment ${sentimentClass(sentiment?.label ?? 'neutral')}`}>
              <span className="social-sentiment-label">{sentiment?.label}</span>
              <span className="social-sentiment-score">{sentiment?.score?.toFixed(2)}</span>
            </div>
            <div className="social-summary-meta">
              <span>{signal.count} posts analysed</span>
              <span>
                {sentiment?.positive ?? 0} positive · {sentiment?.negative ?? 0} negative
              </span>
            </div>
          </div>

          {(signal.trends.hashtags.length > 0 ||
            signal.trends.cashtags.length > 0 ||
            signal.trends.keywords.length > 0) && (
            <div className="social-trends">
              <div className="social-trends-title">
                <TrendingUp size={13} /> Trends
              </div>
              <div className="social-trend-chips">
                {signal.trends.hashtags.map(([tag, count]) => (
                  <span key={`h-${tag}`} className="social-chip">
                    <Hash size={11} />
                    {tag} <em>{count}</em>
                  </span>
                ))}
                {signal.trends.cashtags.map(([tag, count]) => (
                  <span key={`c-${tag}`} className="social-chip is-cashtag">
                    ${tag} <em>{count}</em>
                  </span>
                ))}
                {signal.trends.keywords.slice(0, 8).map((kw) => (
                  <span key={`k-${kw}`} className="social-chip is-keyword">
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="social-posts">
            {signal.posts.length === 0 && <div className="social-empty">No posts found.</div>}
            {signal.posts.map((post, i) => (
              <a
                key={i}
                className="social-post"
                href={post.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <span className={`social-post-badge ${sentimentClass(post.sentiment?.label ?? 'neutral')}`}>
                  {post.sentiment?.label ?? 'neutral'}
                </span>
                <span className="social-post-body">
                  <span className="social-post-author">@{post.author || 'unknown'}</span>
                  <span className="social-post-text">{post.text}</span>
                </span>
              </a>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
