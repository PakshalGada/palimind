import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppProvider } from './AppContext'
import { ThemeProvider } from './design/ThemeProvider'
import { ConfirmProvider } from './components/ConfirmDialog'
import ErrorBoundary from './components/ErrorBoundary'
import App from './App'
import './App.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <AppProvider>
        <ConfirmProvider>
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
        </ConfirmProvider>
      </AppProvider>
    </ThemeProvider>
  </StrictMode>,
)
