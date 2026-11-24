import { useApp } from '../AppContext';
import { ProgressBar } from '../ui/primitives';

export default function IndexingProgress() {
  const { isIndexing, indexingStatus } = useApp();

  if (!isIndexing) return null;

  return (
    <div id="indexing-progress-container" className="indexing-progress-container">
      <ProgressBar label={indexingStatus || 'Indexing knowledge base…'} />
    </div>
  );
}
