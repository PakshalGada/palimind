import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import GlanceApp from './GlanceApp';
import './glance.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <GlanceApp />
  </StrictMode>,
);
