import { useApp } from '../AppContext';
import { ProgressBar } from '../ui/primitives';
import Thinking from './Thinking';

export default function IndexingProgress() {
  const { isIndexing, indexingStatus } = useApp();

  if (!isIndexing) return null;

  return (
    <div id="indexing-progress-container" className="indexing-progress-container">
      <ProgressBar
        label={
          <>
            <Thinking variant="beacon" size={12} />
            {indexingStatus || 'Indexing Knowledge Base...'}
          </>
        }
      />
    </div>
  );
}
