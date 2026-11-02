import { lazy, Suspense, useMemo, useState } from 'react';
import type { ToolStep } from '../model';
import { Icon } from '../icons';
import { weatherOf } from '../toolOutput';

const MapBody = lazy(() => import('./MapBody'));

function coordinates(args: unknown): { lat: number; lng: number } | null {
  if (!args || typeof args !== 'object') return null;
  const record = args as Record<string, unknown>;
  const lat = Number(record.latitude ?? record.lat);
  const lng = Number(record.longitude ?? record.lng ?? record.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat, lng };
}

export default function WeatherBody({ step }: { step: ToolStep }) {
  const [showMap, setShowMap] = useState(false);
  const weather = useMemo(() => weatherOf(step.output, step.args), [step.output, step.args]);
  const coords = useMemo(() => coordinates(step.args), [step.args]);
  const max = Math.max(...weather.hours.map((hour) => hour.value), 1);
  return (
    <div className="act-weather">
      <div className="act-weather__now">
        <Icon name="cloud-sun" size={18} />
        <span className="act-weather__temp">
          {weather.temperature != null ? Math.round(weather.temperature) : '--'}
          <span className="act-muted" style={{ fontSize: 13 }}>
            °{weather.unit}
          </span>
        </span>
        <span className="act-row__label">{weather.location}</span>
        {weather.condition && <span className="act-muted">{weather.condition}</span>}
      </div>
      {weather.hours.length > 0 && (
        <div className="act-weather__hours" aria-hidden="true">
          {weather.hours.map((hour) => (
            <span
              key={hour.label}
              className="act-weather__bar"
              style={{ height: 36, transform: `scaleY(${Math.max(0.08, hour.value / max)})` }}
              title={`${hour.label} · ${Math.round(hour.value)}°`}
            />
          ))}
        </div>
      )}
      {coords && (
        <div>
          <button
            type="button"
            className="act-btn act-btn--ghost"
            onClick={() => setShowMap((value) => !value)}
          >
            <Icon name="map-pin" size={13} />
            {showMap ? 'Hide map' : 'Show map'}
          </button>
          {showMap && (
            <Suspense fallback={<div className="act-empty">Loading map</div>}>
              <MapBody lat={coords.lat} lng={coords.lng} label={weather.location} />
            </Suspense>
          )}
        </div>
      )}
    </div>
  );
}
