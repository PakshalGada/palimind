import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppProvider } from './AppContext'
import App from './App'
import './App.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>,
)
