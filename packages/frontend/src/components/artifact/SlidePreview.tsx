import { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, LayoutGrid } from 'lucide-react';
import { parseSlides } from '../../utils/slides';
import './SlidePreview.css';

/**
 * A real slide-deck preview: one 16:9 stage with keyboard/click navigation and
 * an overview grid. Export to PPTX uses the same heading/bullet structure.
 */
export default function SlidePreview({ content, title }: { content: string; title: string }) {
  const slides = useMemo(() => parseSlides(content), [content]);
  const [index, setIndex] = useState(0);
  const [overview, setOverview] = useState(false);

  useEffect(() => {
    setIndex(0);
  }, [title]);

  useEffect(() => {
    setIndex((current) => Math.min(current, Math.max(0, slides.length - 1)));
  }, [slides.length]);

  if (slides.length === 0) {
    return <div className="artp-placeholder">No slides yet</div>;
  }

  const slide = slides[index] ?? slides[0];

  const move = (delta: number) => {
    setIndex((current) => (current + delta + slides.length) % slides.length);
  };

  return (
    <div
      className="slide-deck"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'ArrowRight' || event.key === 'PageDown') {
          event.preventDefault();
          move(1);
        } else if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
          event.preventDefault();
          move(-1);
        }
      }}
    >
      <div className="slide-deck__bar">
        <span className="slide-deck__title" title={title}>
          {title}
        </span>
        <div className="slide-deck__controls">
          <button
            type="button"
            className="slide-deck__btn"
            onClick={() => move(-1)}
            aria-label="Previous slide"
            title="Previous slide"
          >
            <ChevronLeft size={15} />
          </button>
          <span className="slide-deck__count">
            {index + 1} / {slides.length}
          </span>
          <button
            type="button"
            className="slide-deck__btn"
            onClick={() => move(1)}
            aria-label="Next slide"
            title="Next slide"
          >
            <ChevronRight size={15} />
          </button>
          <button
            type="button"
            className={`slide-deck__btn${overview ? ' is-active' : ''}`}
            onClick={() => setOverview((value) => !value)}
            aria-label="Toggle slide overview"
            aria-pressed={overview}
            title="Slide overview"
          >
            <LayoutGrid size={14} />
          </button>
        </div>
      </div>

      {overview ? (
        <div className="slide-deck__overview">
          {slides.map((item, position) => (
            <button
              key={`${position}-${item.title}`}
              type="button"
              className={`slide-thumb${position === index ? ' is-current' : ''}`}
              onClick={() => {
                setIndex(position);
                setOverview(false);
              }}
            >
              <span className="slide-thumb__number">{position + 1}</span>
              <span className="slide-thumb__title">{item.title}</span>
              <span className="slide-thumb__bullets">{item.bullets.length} points</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="slide-stage">
          <article className="slide-canvas" aria-label={`Slide ${index + 1} of ${slides.length}`}>
            <span className="slide-canvas__badge">{index + 1}</span>
            <h2 className="slide-canvas__title">{slide.title}</h2>
            {slide.bullets.length > 0 ? (
              <ul className="slide-canvas__bullets">
                {slide.bullets.map((bullet, position) => (
                  <li key={`${position}-${bullet.slice(0, 24)}`}>{bullet}</li>
                ))}
              </ul>
            ) : (
              <p className="slide-canvas__empty">Add bullets below the slide heading.</p>
            )}
            <span className="slide-canvas__brand">Palimind</span>
          </article>
        </div>
      )}
    </div>
  );
}
