import { useEffect, useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import { api } from '../../api';
import { planDeckLocal, type DeckPlan, type DeckSlide } from '../../utils/deckPlan';
import SlideCanvas from './SlideCanvas';
import './DeckPreview.css';

function coverSlide(plan: DeckPlan): DeckSlide {
  return {
    title: plan.title || 'Presentation',
    subtitle: plan.subtitle ?? '',
    bullets: [],
    layout: 'cover',
    chart: null,
  };
}

export default function DeckPreview({ content, title }: { content: string; title: string }) {
  const localPlan = useMemo(() => planDeckLocal(title, content), [title, content]);
  const [plan, setPlan] = useState<DeckPlan>(localPlan);
  const [index, setIndex] = useState(0);
  const [overview, setOverview] = useState(false);
  const [presenting, setPresenting] = useState(false);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    setPlan(localPlan);
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setUpdating(true);
      api.office
        .deckPlan({ title, content })
        .then((result) => {
          if (!cancelled && result?.plan?.slides) setPlan(result.plan);
        })
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) setUpdating(false);
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [content, title, localPlan]);

  const slides = useMemo(() => [coverSlide(plan), ...(plan.slides ?? [])], [plan]);

  useEffect(() => {
    setIndex((current) => Math.min(current, Math.max(0, slides.length - 1)));
  }, [slides.length]);

  useEffect(() => {
    setIndex(0);
  }, [title]);

  const move = (delta: number) => {
    setIndex((current) => (current + delta + slides.length) % slides.length);
  };

  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === 'ArrowRight' || event.key === 'PageDown') {
      event.preventDefault();
      move(1);
    } else if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
      event.preventDefault();
      move(-1);
    } else if (event.key === 'g' || event.key === 'G') {
      event.preventDefault();
      setOverview((value) => !value);
    } else if (event.key === 'Escape' && presenting) {
      setPresenting(false);
    }
  };

  useEffect(() => {
    if (!presenting) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPresenting(false);
      if (event.key === 'ArrowRight' || event.key === 'PageDown') {
        event.preventDefault();
        setIndex((current) => (current + 1) % slides.length);
      }
      if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
        event.preventDefault();
        setIndex((current) => (current - 1 + slides.length) % slides.length);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [presenting, slides.length]);

  const slide = slides[index] ?? slides[0];

  return (
    <div className="deck-preview" tabIndex={0} onKeyDown={onKeyDown}>
      <div className="deck-preview__bar">
        <span className="deck-preview__title" title={title}>
          {title}
          {updating && <span className="deck-preview__updating" title="Updating preview" />}
        </span>
        <div className="deck-preview__controls">
          <button
            type="button"
            className="deck-preview__btn"
            onClick={() => move(-1)}
            aria-label="Previous slide"
            title="Previous slide"
          >
            <ChevronLeft size={15} />
          </button>
          <span className="deck-preview__count">
            {index + 1} / {slides.length}
          </span>
          <button
            type="button"
            className="deck-preview__btn"
            onClick={() => move(1)}
            aria-label="Next slide"
            title="Next slide"
          >
            <ChevronRight size={15} />
          </button>
          <button
            type="button"
            className={`deck-preview__btn${overview ? ' is-active' : ''}`}
            onClick={() => setOverview((value) => !value)}
            aria-label="Toggle slide overview"
            aria-pressed={overview}
            title="Slide overview (G)"
          >
            <LayoutGrid size={14} />
          </button>
          <button
            type="button"
            className="deck-preview__btn"
            onClick={() => setPresenting(true)}
            aria-label="Present slides"
            title="Present"
          >
            <Maximize2 size={14} />
          </button>
        </div>
      </div>

      {overview ? (
        <div className="deck-preview__overview">
          {slides.map((item, position) => (
            <button
              key={`${position}-${item.title}`}
              type="button"
              className={`deck-thumb${position === index ? ' is-current' : ''}`}
              onClick={() => {
                setIndex(position);
                setOverview(false);
              }}
            >
              <span className="deck-thumb__canvas">
                <SlideCanvas
                  slide={item}
                  index={position}
                  total={slides.length}
                  deckTitle={plan.title}
                  compact
                />
              </span>
              <span className="deck-thumb__meta">
                <span className="deck-thumb__number">{position + 1}</span>
                <span className="deck-thumb__title">{item.title}</span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="deck-preview__stage">
          <div className="deck-slide-frame">
            <SlideCanvas
              slide={slide}
              index={index}
              total={slides.length}
              deckTitle={plan.title}
            />
          </div>
        </div>
      )}

      {presenting && (
        <div className="deck-present" role="dialog" aria-modal="true" aria-label="Slide presentation">
          <div className="deck-present__stage">
            <SlideCanvas
              slide={slide}
              index={index}
              total={slides.length}
              deckTitle={plan.title}
            />
          </div>
          <div className="deck-present__controls">
            <button type="button" onClick={() => move(-1)} aria-label="Previous slide">
              <ChevronLeft size={18} />
            </button>
            <span>
              {index + 1} / {slides.length}
            </span>
            <button type="button" onClick={() => move(1)} aria-label="Next slide">
              <ChevronRight size={18} />
            </button>
            <button
              type="button"
              className="deck-present__close"
              onClick={() => setPresenting(false)}
              aria-label="Exit presentation"
            >
              <Minimize2 size={18} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
