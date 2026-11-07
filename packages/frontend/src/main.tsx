import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import { AppProvider } from './AppContext'
import { ThemeProvider } from './design/ThemeProvider'
import { ConfirmProvider } from './components/ConfirmDialog'
import ErrorBoundary from './components/ErrorBoundary'
import App from './App'
// Cascade order matters: Tailwind/shadcn defaults first, then Palimind's
// tokens and component layers so the design system always wins.
import './index.css'
import './App.css'
import './components/activity/activity.css'
// Last: the pixel interface style overrides geometry/type/motion when active.
import './design/pixel-theme.css'

const ActivityPlayground = lazy(() => import('./components/activity/playground/Playground'))
const ComputerUsePanel = lazy(() => import('./features/desktop/ComputerUsePanel'))
const ScreenRegionOverlay = lazy(() => import('./features/desktop/ScreenRegionOverlay'))
const GhostCursorOverlay = lazy(() => import('./features/desktop/GhostCursorOverlay'))
const playground = import.meta.env.DEV && window.location.hash.startsWith('#/activity')
const secondaryWindow = new URLSearchParams(window.location.search).get('window')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <AppProvider>
        <ConfirmProvider>
          <ErrorBoundary>
            {playground ? (
              <Suspense fallback={null}>
                <ActivityPlayground />
              </Suspense>
            ) : secondaryWindow === 'computer-use' ? (
              <Suspense fallback={null}>
                <ComputerUsePanel />
              </Suspense>
            ) : secondaryWindow === 'region-overlay' ? (
              <Suspense fallback={null}>
                <ScreenRegionOverlay />
              </Suspense>
            ) : secondaryWindow === 'cursor-ghost' ? (
              <Suspense fallback={null}>
                <GhostCursorOverlay />
              </Suspense>
            ) : (
              <App />
            )}
          </ErrorBoundary>
        </ConfirmProvider>
      </AppProvider>
    </ThemeProvider>
  </StrictMode>,
)
