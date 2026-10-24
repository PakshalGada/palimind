import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { formatTimestamp } from './format';
import type { VideoTarget } from './types';

/**
 * Full-screen media viewer used by media-transcript citations. Rendered once
 * by the stream provider so it survives the live turn being replaced by
 * history after the response completes.
 */
export default function VideoOverlay({
  target,
  onClose,
}: {
  target: VideoTarget | null;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!target) return;
    const video = videoRef.current;
    if (!video) return;
    const seek = () => {
      video.currentTime = target.start;
      void video.play().catch(() => {});
    };
    video.addEventListener('loadedmetadata', seek);
    return () => video.removeEventListener('loadedmetadata', seek);
  }, [target]);

  useEffect(() => {
    if (!target) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [target, onClose]);

  if (!target) return null;

  return createPortal(
    <div
      className="video-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Media citation player"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="video-panel">
        <div className="video-label">
          <span>
            {target.file} @ {formatTimestamp(target.start)}
            {target.end ? `–${formatTimestamp(target.end)}` : ''}
          </span>
          <button type="button" className="video-close" onClick={onClose}>
            Close
          </button>
        </div>
        <video
          key={`${target.file}:${target.start}`}
          ref={videoRef}
          className="video-player"
          controls
          src={`/api/media/stream?path=${encodeURIComponent(target.file)}`}
        />
      </div>
    </div>,
    document.body,
  );
}
