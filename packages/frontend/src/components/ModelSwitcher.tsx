import { useState, useEffect, useRef, useCallback } from 'react';
import { useApp } from '../AppContext';
import { api } from '../api';
import type { ModelItem, Recommendation, HardwareData } from '../types';
import LoadingSpinner from './LoadingSpinner';

export default function ModelSwitcher() {
  const { currentModel, setCurrentModel, addToast, activeView } = useApp();
  const scope = activeView === 'chat' ? 'chat' : 'field';
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'models' | 'cookbook'>('models');
  const [models, setModels] = useState<ModelItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const [hwData, setHwData] = useState<HardwareData | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [hwLoading, setHwLoading] = useState(false);
  const [recLoading, setRecLoading] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const filteredModels = searchQuery.trim()
    ? models.filter(m => {
        const q = searchQuery.toLowerCase();
        return (m.model_id?.toLowerCase().includes(q) ||
                m.family?.toLowerCase().includes(q) ||
                m.display_name?.toLowerCase().includes(q));
      })
    : models;

  const fetchModels = useCallback(async () => {
    setModelsLoading(true);
    setModelsError('');
    try {
      const data = await api.models.list();
      if (data.models) setModels(data.models);
      if (data.current_model) {
        setCurrentModel(data.current_model);
      }
      if (data.status === 'offline') {
        setModelsError('Ollama is offline');
      } else if (!data.models?.length) {
        setModelsError('No models installed');
      }
    } catch {
      setModelsError('Could not reach backend');
    }
    setModelsLoading(false);
  }, [setCurrentModel]);

  const fetchHardware = useCallback(async () => {
    setHwLoading(true);
    try {
      const data = await api.cookbook.hardware();
      if (!('error' in data)) setHwData(data as HardwareData);
    } catch { setHwData(null); }
    setHwLoading(false);
  }, []);

  const fetchRecommendations = useCallback(async () => {
    setRecLoading(true);
    try {
      const data = await api.cookbook.recommendations();
      if (data.recommendations) setRecommendations(data.recommendations);
    } catch { setRecommendations([]); }
    setRecLoading(false);
  }, []);

  const selectModel = async (modelId: string) => {
    if (modelId === currentModel) { setIsOpen(false); return; }
    setCurrentModel(modelId);
    setIsOpen(false);
    try {
      const data = await api.config.setModel(modelId, scope);
      if (data.error) {
        addToast('Model switch failed: ' + data.error);
      } else {
        addToast('Switched to ' + modelId);
      }
    } catch {
      addToast('Failed to switch model');
    }
  };

  const open = useCallback(() => {
    setIsOpen(true);
    setActiveTab('models');
    setSearchQuery('');
    setHighlightIdx(-1);
    fetchModels();
    setTimeout(() => searchRef.current?.focus(), 50);
  }, [fetchModels]);

  const close = useCallback(() => {
    setIsOpen(false);
    setHighlightIdx(-1);
  }, []);

  useEffect(() => {
    if (isOpen) {
      const handler = (e: MouseEvent) => {
        if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
          close();
        }
      };
      document.addEventListener('click', handler);
      return () => document.removeEventListener('click', handler);
    }
  }, [isOpen, close]);

  const handleKeyboard = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { close(); return; }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIdx(prev => Math.min(prev + 1, filteredModels.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIdx(prev => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter' && highlightIdx >= 0 && highlightIdx < filteredModels.length) {
      e.preventDefault();
      selectModel(filteredModels[highlightIdx].model_id);
    }
  };

  const switchTab = (tab: 'models' | 'cookbook') => {
    setActiveTab(tab);
    if (tab === 'cookbook') {
      fetchHardware();
      fetchRecommendations();
    }
  };

  const fitClass = (fit: string) => {
    switch (fit) {
      case 'FITS_PERFECTLY': return 'fits';
      case 'FITS_TIGHT': return 'tight';
      case 'CPU_FALLBACK': return 'cpu';
      default: return 'too-large';
    }
  };
  const fitLabel = (fit: string) => {
    switch (fit) {
      case 'FITS_PERFECTLY': return 'FITS';
      case 'FITS_TIGHT': return 'TIGHT';
      case 'CPU_FALLBACK': return 'CPU';
      default: return 'TOO BIG';
    }
  };

  return (
    <div className="model-switcher-area" id="model-switcher-area">
      <button
        id="model-switcher-pill"
        className={`model-switcher-pill${isOpen ? ' open' : ''}`}
        title="Switch Model"
        aria-label="Switch model"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={(e) => { e.stopPropagation(); isOpen ? close() : open(); }}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        <span id="model-switcher-name">{currentModel}</span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {isOpen && (
        <div
          id="model-switcher-dropdown"
          className="model-switcher-dropdown"
          role="dialog"
          aria-label="Model selection"
          ref={dropdownRef}
        >
          <div className="ms-tab-bar" role="tablist">
            <button
              className={`ms-tab ${activeTab === 'models' ? 'active' : ''}`}
              data-tab="models"
              role="tab"
              aria-selected={activeTab === 'models'}
              onClick={() => switchTab('models')}
            >
              Models
            </button>
            <button
              className={`ms-tab ${activeTab === 'cookbook' ? 'active' : ''}`}
              data-tab="cookbook"
              role="tab"
              aria-selected={activeTab === 'cookbook'}
              onClick={() => switchTab('cookbook')}
            >
              Cookbook
            </button>
          </div>

          {activeTab === 'models' && (
            <div id="ms-panel-models" className="ms-panel" role="tabpanel">
              <div className="model-search-container">
                <input
                  ref={searchRef}
                  type="text"
                  className="model-search-input"
                  placeholder="Search models..."
                  autoComplete="off"
                  aria-label="Search models"
                  value={searchQuery}
                  onChange={(e) => { setSearchQuery(e.target.value); setHighlightIdx(-1); }}
                  onKeyDown={handleKeyboard}
                />
              </div>
              <div id="model-list" className="model-list" role="listbox">
                {modelsLoading && <LoadingSpinner text="Loading available models..." className="model-list-loading" />}
                {modelsError && !modelsLoading && (
                  <div className="model-empty-state">
                    <span className="model-empty-msg">{modelsError}</span>
                    <span className="model-empty-hint">{modelsError.includes('Ollama') ? 'Start Ollama and retry' : 'Run: ollama pull llama3.2'}</span>
                    <button className="model-retry-btn" onClick={fetchModels}>Retry</button>
                  </div>
                )}
                {!modelsLoading && !modelsError && filteredModels.length === 0 && (
                  <div className="model-list-loading">No models found</div>
                )}
                {filteredModels.map((m, idx) => (
                  <div
                    key={m.model_id}
                    className={`model-list-item${m.model_id === currentModel ? ' active-model' : ''}${highlightIdx === idx ? ' keyboard-highlight' : ''}`}
                    role="option"
                    aria-selected={m.model_id === currentModel}
                    tabIndex={-1}
                    onClick={() => selectModel(m.model_id)}
                  >
                    {m.model_id === currentModel && <span className="model-active-dot" />}
                    <span className="model-list-item-name">{m.display_name || m.model_id}</span>
                    <span className="model-list-item-meta">{m.parameter_size || ''} {m.size_gb ? m.size_gb + 'GB' : ''}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'cookbook' && (
            <div id="ms-panel-cookbook" className="ms-panel" role="tabpanel">
              <div id="hw-card" className="hw-summary-card">
                {hwLoading ? (
                  <LoadingSpinner size="sm" text="Detecting hardware..." inline />
                ) : hwData ? (
                  <>
                    {hwData.gpus && hwData.gpus.length > 0
                      ? hwData.gpus.map((g, i) => (
                          <span key={i} className="hw-gpu-name">{g.name}</span>
                        ))
                      : <span className="hw-gpu-name">No GPU detected (CPU only)</span>}
                    {hwData.gpus?.map((g, i) => (
                      <span key={`vram-${i}`}>VRAM: <span className="hw-vram">{(g.vram_mb / 1024).toFixed(1)} GB</span></span>
                    ))}
                    <span>RAM: {hwData.total_ram_mb ? (hwData.total_ram_mb / 1024).toFixed(0) : '?'} GB · {hwData.os_platform || '?'}</span>
                    <span>Engines: {hwData.serve_engines_available?.join(', ') || 'none'}</span>
                  </>
                ) : (
                  <span className="model-menu-state error">Hardware detection failed</span>
                )}
              </div>
              <div className="ms-rec-header">
                <span className="ms-rec-title">Recommended for your hardware</span>
              </div>
              <div id="rec-grid" className="recommendation-grid">
                {recLoading ? (
                  <LoadingSpinner size="sm" text="Loading recommendations..." className="model-menu-state" />
                ) : recommendations.length === 0 ? (
                  <div className="model-menu-state empty">No recommendations</div>
                ) : (
                  recommendations.map((rec, i) => (
                    <div key={i} className="rec-card">
                      <span className="rec-card-name">{rec.name}</span>
                      <span className="rec-card-size">{rec.params_b}B · {rec.file_size_gb}GB</span>
                      <span className={`fit-badge ${fitClass(rec.fit)}`}>{fitLabel(rec.fit)}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
