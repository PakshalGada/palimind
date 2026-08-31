import { useApp } from '../AppContext';

export default function IndexingProgress() {
  const { isIndexing, indexingStatus } = useApp();

  if (!isIndexing) return null;

  return (
    <div id="indexing-progress-container" className="indexing-progress-container">
      <div className="progress-bar-label" id="progress-bar-label">
        <span className="pulse-dot" />
        {indexingStatus || 'Indexing Knowledge Base...'}
      </div>
      <div className="progress-bar-track">
        <div className="progress-bar-fill" />
      </div>
    </div>
  );
}
