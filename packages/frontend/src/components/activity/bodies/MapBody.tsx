import { useEffect, useRef, useState } from 'react';
import 'leaflet/dist/leaflet.css';

export default function MapBody({
  lat,
  lng,
  label,
  height = 210,
}: {
  lat: number;
  lng: number;
  label?: string;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let map: import('leaflet').Map | null = null;
    let cancelled = false;
    void import('leaflet')
      .then((module) => {
        if (cancelled || !container.current) return;
        const leaflet = module.default;
        map = leaflet.map(container.current, {
          zoomControl: false,
          attributionControl: false,
          scrollWheelZoom: false,
        }).setView([lat, lng], 11);
        leaflet
          .tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 })
          .addTo(map);
        leaflet.circleMarker([lat, lng], {
          radius: 5,
          color: '#d7d7d7',
          fillColor: '#d7d7d7',
          fillOpacity: 0.8,
          weight: 2,
        }).addTo(map);
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      map?.remove();
      map = null;
    };
  }, [lat, lng]);

  if (failed) {
    return (
      <div className="act-body act-body--flush">
        <div className="act-empty">
          <span className="act-row__label">{label ?? 'Map'}</span>
          <span className="act-mono act-muted">
            {lat.toFixed(3)}, {lng.toFixed(3)}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="act-map"
      ref={container}
      role="img"
      aria-label={label ? `Map for ${label}` : 'Map'}
      style={{ height, filter: 'grayscale(1) contrast(0.9)' }}
    />
  );
}
