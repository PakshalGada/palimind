import { memo, useEffect, useMemo, useState, type ReactNode, type RefObject } from 'react';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { useThrottledValue } from '../../hooks/useThrottledValue';
import { formatMarkdown } from '../../utils/markdown';
import {
  ARTIFACT_TYPE_LABEL,
  parseArtifactFiles,
  type ArtifactFile,
} from '../../utils/artifacts';
import HighlightedCode from '../HighlightedCode';
import MermaidPreview from '../MermaidPreview';
import ArtifactFileTree from './ArtifactFileTree';
import { sourceLanguage } from './languages';
import type { ActiveArtifact, ViewMode } from './types';

function svgDocument(source: string): string {
  return `<!doctype html><html><body style="margin:0;padding:12px;display:flex;align-items:center;justify-content:center;min-height:100%">${source}</body></html>`;
}

function filePreview(file: ArtifactFile, title: string) {
  if (file.language === 'markdown') {
    return (
      <div
        className="artifact-markdown"
        dangerouslySetInnerHTML={{ __html: formatMarkdown(file.content) }}
      />
    );
  }
  if (file.language === 'html') {
    return (
      <iframe
        className="artifact-frame"
        title={file.path || title}
        sandbox="allow-scripts allow-forms allow-modals allow-popups"
        srcDoc={file.content}
      />
    );
  }
  if (file.path.toLowerCase().endsWith('.svg')) {
    return (
      <iframe
        className="artifact-frame"
        title={file.path || title}
        sandbox=""
        srcDoc={svgDocument(file.content)}
      />
    );
  }
  return <HighlightedCode code={file.content} language={file.language} />;
}

function PreviewSurface({
  artifact,
  scrollRef,
  className,
  children,
}: {
  artifact: ActiveArtifact;
  scrollRef?: RefObject<HTMLDivElement | null>;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      ref={scrollRef}
      className={`artifact-preview artifact-preview--${artifact.type}${
        artifact.streaming ? ' is-streaming' : ''
      }${className ? ` ${className}` : ''}`}
    >
      {children}
    </div>
  );
}

function ArtifactPreview({
  artifact,
  content,
  viewMode,
  scrollRef,
}: {
  artifact: ActiveArtifact;
  content: string;
  viewMode: ViewMode;
  scrollRef?: RefObject<HTMLDivElement | null>;
}) {
  // While editing we debounce (wait for quiet); while streaming we throttle
  // (keep up with the stream). Frames reload their whole document on every
  // srcDoc change, so they update much less often.
  const frameType = artifact.type === 'html' || artifact.type === 'svg';
  const throttled = useThrottledValue(
    content,
    artifact.streaming ? (frameType ? 700 : 400) : 0,
  );
  const debounced = useDebouncedValue(content, frameType ? 420 : 180);
  const previewContent = artifact.streaming ? throttled : debounced;
  const sourceLang = sourceLanguage(artifact.type, artifact.language);

  const files = useMemo(() => {
    if (artifact.type === 'multi-file' || artifact.type === 'code-file') {
      const parsed = parseArtifactFiles(previewContent);
      if (parsed.length) return parsed;
    }
    // Edited content must not fall back to the stale pre-edit file snapshot.
    return previewContent === artifact.content ? (artifact.files ?? []) : [];
  }, [artifact.content, artifact.type, artifact.files, previewContent]);

  const singleFile =
    artifact.filePaths?.length === 1 ? files[0]?.content : undefined;

  const [selectedPath, setSelectedPath] = useState(files[0]?.path ?? '');

  useEffect(() => {
    setSelectedPath(files[0]?.path ?? '');
    // Reset only when the artifact changes, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact.id]);

  useEffect(() => {
    if (files.length === 0) return;
    if (!files.some(file => file.path === selectedPath)) {
      setSelectedPath(files[0].path);
    }
  }, [files, selectedPath]);

  if (!content.trim()) {
    return (
      <PreviewSurface artifact={artifact} scrollRef={scrollRef}>
        {artifact.streaming ? (
          <div className="artp-skeleton" aria-label="Generating artifact">
            <div className="artp-skeleton-head">
              <span className="artp-skeleton-pulse" aria-hidden="true" />
              Generating {ARTIFACT_TYPE_LABEL[artifact.type].toLowerCase()}…
            </div>
            <span className="artp-skeleton-line" />
            <span className="artp-skeleton-line is-short" />
            <span className="artp-skeleton-line" />
            <span className="artp-skeleton-line is-medium" />
          </div>
        ) : (
          <div className="artp-placeholder">
            <span>No content yet</span>
          </div>
        )}
      </PreviewSurface>
    );
  }

  if (viewMode === 'code') {
    return (
      <PreviewSurface artifact={artifact} scrollRef={scrollRef}>
        <HighlightedCode code={previewContent} language={sourceLang} />
      </PreviewSurface>
    );
  }

  if (artifact.type === 'multi-file') {
    const selected = files.find(file => file.path === selectedPath) ?? files[0];
    return (
      <PreviewSurface
        artifact={artifact}
        scrollRef={scrollRef}
        className="artifact-preview--multi"
      >
        <div className="artp-multi">
          <div className="artp-multi-tree">
            <ArtifactFileTree
              files={files}
              selectedPath={selected?.path ?? ''}
              onSelect={setSelectedPath}
            />
          </div>
          <div className="artp-multi-body">
            {selected ? filePreview(selected, artifact.title) : null}
          </div>
        </div>
      </PreviewSurface>
    );
  }

  if (artifact.type === 'code-file') {
    const file = files[0];
    return (
      <PreviewSurface artifact={artifact} scrollRef={scrollRef}>
        <HighlightedCode
          code={file?.content ?? previewContent}
          language={file?.language ?? artifact.language}
        />
      </PreviewSurface>
    );
  }

  if (artifact.type === 'html') {
    return (
      <PreviewSurface artifact={artifact} scrollRef={scrollRef}>
        <iframe
          className="artifact-frame"
          title={artifact.title}
          sandbox="allow-scripts allow-forms allow-modals allow-popups"
          srcDoc={singleFile ?? previewContent}
        />
      </PreviewSurface>
    );
  }

  if (artifact.type === 'svg') {
    return (
      <PreviewSurface artifact={artifact} scrollRef={scrollRef}>
        <iframe
          className="artifact-frame"
          title={artifact.title}
          sandbox=""
          srcDoc={svgDocument(singleFile ?? previewContent)}
        />
      </PreviewSurface>
    );
  }

  if (artifact.type === 'mermaid') {
    return (
      <PreviewSurface artifact={artifact} scrollRef={scrollRef}>
        <MermaidPreview code={singleFile ?? previewContent} />
      </PreviewSurface>
    );
  }

  if (
    artifact.type === 'markdown' ||
    artifact.type === 'document' ||
    artifact.type === 'table' ||
    artifact.type === 'slide-outline'
  ) {
    return (
      <PreviewSurface artifact={artifact} scrollRef={scrollRef}>
        <div
          className={`artifact-markdown artifact-markdown--${artifact.type}`}
          dangerouslySetInnerHTML={{ __html: formatMarkdown(previewContent) }}
        />
      </PreviewSurface>
    );
  }

  return (
    <PreviewSurface artifact={artifact} scrollRef={scrollRef}>
      <HighlightedCode code={previewContent} language={sourceLang} />
    </PreviewSurface>
  );
}

export default memo(ArtifactPreview, (previous, next) => {
  return (
    previous.content === next.content &&
    previous.viewMode === next.viewMode &&
    previous.scrollRef === next.scrollRef &&
    previous.artifact.id === next.artifact.id &&
    previous.artifact.type === next.artifact.type &&
    previous.artifact.language === next.artifact.language &&
    previous.artifact.title === next.artifact.title &&
    previous.artifact.streaming === next.artifact.streaming &&
    previous.artifact.content === next.artifact.content &&
    previous.artifact.files === next.artifact.files
  );
});
