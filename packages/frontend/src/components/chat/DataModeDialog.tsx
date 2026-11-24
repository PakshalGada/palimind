import { useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  Download,
  FileSpreadsheet,
  Loader2,
  Play,
  Sparkles,
  Table2,
} from 'lucide-react';
import { useApp } from '../../AppContext';
import { api } from '../../api';
import { Dialog } from '../../ui/primitives';
import { saveToVault } from '../../utils/artifactVault';
import { fileToBase64 } from '../../utils/capture';
import type { DeckChart } from '../../utils/deckPlan';
import SlideChart from '../deck/SlideChart';
import '../deck/DeckPreview.css';
import './DataModeDialog.css';

type Profile = Awaited<ReturnType<typeof api.data.profile>>;

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function DataTable({
  columns,
  rows,
  empty,
}: {
  columns: string[];
  rows: unknown[][];
  empty?: string;
}) {
  if (columns.length === 0) {
    return <p className="data-mode__empty">{empty || 'No rows returned.'}</p>;
  }
  return (
    <div className="data-mode__table-wrap">
      <table className="data-mode__table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((value, position) => (
                <td key={position}>{value == null ? '—' : String(value)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DataModeDialog({
  file,
  onClose,
}: {
  file: File | null;
  onClose: () => void;
}) {
  const { addToast, openArtifactLibrary } = useApp();
  const [uploadId, setUploadId] = useState('');
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [queryBusy, setQueryBusy] = useState(false);
  const [queryResult, setQueryResult] = useState<{
    sql: string;
    columns: string[];
    rows: unknown[][];
  } | null>(null);
  const [chartType, setChartType] = useState('bar');
  const [chartX, setChartX] = useState('');
  const [chartY, setChartY] = useState('');
  const [chart, setChart] = useState<DeckChart | null>(null);
  const [chartBusy, setChartBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState<'csv' | 'xlsx' | 'dashboard' | null>(null);

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setProfile(null);
    setUploadId('');
    setQueryResult(null);
    setChart(null);
    void (async () => {
      try {
        const base64 = await fileToBase64(file);
        const uploaded = await api.uploads.create(file.name, file.type, base64);
        if (cancelled) return;
        if (uploaded.error || !uploaded.upload?.id) {
          setError(uploaded.error || 'Could not upload the file.');
          return;
        }
        setUploadId(uploaded.upload.id);
        const result = await api.data.profile(uploaded.upload.id);
        if (cancelled) return;
        setProfile(result);
        setChartY(result.numeric_columns[0] || '');
        setChartX(result.categorical_columns[0] || '');
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not open the data file.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [file]);

  const columns = useMemo(
    () => profile?.column_profile.map((item) => item.name) ?? [],
    [profile],
  );

  const runQuery = async (text?: string) => {
    if (!uploadId) return;
    const prompt = (text ?? question).trim();
    if (!prompt) return;
    setQuestion(prompt);
    setQueryBusy(true);
    try {
      const result = await api.data.query({ uploadId, question: prompt });
      setQueryResult(result);
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Could not query the data.', { tone: 'error' });
    } finally {
      setQueryBusy(false);
    }
  };

  const runChart = async () => {
    if (!uploadId) return;
    setChartBusy(true);
    try {
      const result = await api.data.chart({
        uploadId,
        chartType,
        x: chartX,
        y: chartY,
      });
      setChart(result.chart);
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Could not build the chart.', { tone: 'error' });
    } finally {
      setChartBusy(false);
    }
  };

  const exportData = async (format: 'csv' | 'xlsx') => {
    if (!uploadId) return;
    setExportBusy(format);
    try {
      const result = await api.data.exportFile({ uploadId, cleaned: true, format });
      downloadBlob(result.blob, result.filename);
      addToast(`Cleaned ${format.toUpperCase()} downloaded`, { tone: 'success' });
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Could not export the data.', { tone: 'error' });
    } finally {
      setExportBusy(null);
    }
  };

  const makeDashboard = async () => {
    if (!uploadId) return;
    setExportBusy('dashboard');
    try {
      const result = await api.data.dashboard({
        uploadId,
        title: profile?.upload.name.replace(/\.[^.]+$/, '') || 'Data',
      });
      await saveToVault(
        {
          id: `data-dashboard-${Date.now()}`,
          type: 'html',
          language: 'html',
          title: result.title,
          content: result.html,
        },
        'Created from data mode',
      );
      addToast('Dashboard artifact created', { tone: 'success' });
      openArtifactLibrary();
      onClose();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Could not create the dashboard.', { tone: 'error' });
    } finally {
      setExportBusy(null);
    }
  };

  return (
    <Dialog
      open={Boolean(file)}
      onClose={onClose}
      title="Data mode"
      subtitle={file ? `${file.name} · profile, query, chart and export locally` : undefined}
      width={940}
    >
      <div className="data-mode">
        {loading && (
          <div className="data-mode__loading">
            <Loader2 size={18} className="spin" />
            Profiling the file…
          </div>
        )}
        {error && <div className="data-mode__error">{error}</div>}

        {profile && (
          <>
            <div className="data-mode__stats">
              <div><strong>{profile.rows.toLocaleString()}</strong><span>rows</span></div>
              <div><strong>{profile.columns}</strong><span>columns</span></div>
              <div><strong>{profile.numeric_columns.length}</strong><span>numeric</span></div>
              <div><strong>{profile.quality.missing_cells}</strong><span>missing cells</span></div>
              <div><strong>{profile.quality.duplicate_rows}</strong><span>duplicates</span></div>
            </div>

            {profile.quality.missing_cells > 0 && (
              <p className="data-mode__hint">
                This file has {profile.quality.missing_cells.toLocaleString()} missing cells. The cleaned export removes duplicates and empty rows.
              </p>
            )}

            <section className="data-mode__section">
              <h3><Table2 size={14} /> Columns</h3>
              <div className="data-mode__table-wrap">
                <table className="data-mode__table">
                  <thead>
                    <tr><th>Name</th><th>Type</th><th>Missing</th><th>Unique</th><th>Sample</th></tr>
                  </thead>
                  <tbody>
                    {profile.column_profile.map((column) => (
                      <tr key={column.name}>
                        <td>{column.name}</td>
                        <td>{column.dtype}</td>
                        <td>{column.missing}</td>
                        <td>{column.unique}</td>
                        <td>{column.sample == null ? '—' : String(column.sample)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="data-mode__section">
              <h3><Table2 size={14} /> Preview</h3>
              <DataTable
                columns={columns}
                rows={profile.preview.map((row) => columns.map((column) => row[column]))}
              />
            </section>

            <section className="data-mode__section">
              <h3><Sparkles size={14} /> Ask the data</h3>
              <div className="data-mode__ask">
                <input
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void runQuery();
                  }}
                  placeholder="e.g. Which region has the highest revenue?"
                  aria-label="Ask a question about the data"
                />
                <button type="button" onClick={() => void runQuery()} disabled={queryBusy || !question.trim()}>
                  {queryBusy ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
                  Run
                </button>
              </div>
              <div className="data-mode__suggestions">
                {profile.suggested_questions.map((item) => (
                  <button key={item} type="button" onClick={() => void runQuery(item)}>
                    {item}
                  </button>
                ))}
              </div>
              {queryResult && (
                <div className="data-mode__query-result">
                  <div className="data-mode__sql">
                    <span>SQL</span>
                    <pre>{queryResult.sql}</pre>
                  </div>
                  <DataTable columns={queryResult.columns} rows={queryResult.rows} />
                </div>
              )}
            </section>

            <section className="data-mode__section">
              <h3><BarChart3 size={14} /> Chart</h3>
              <div className="data-mode__controls">
                <label>
                  Type
                  <select value={chartType} onChange={(event) => setChartType(event.target.value)}>
                    <option value="bar">Bar</option>
                    <option value="line">Line</option>
                    <option value="area">Area</option>
                    <option value="pie">Pie</option>
                    <option value="donut">Donut</option>
                  </select>
                </label>
                <label>
                  X
                  <select value={chartX} onChange={(event) => setChartX(event.target.value)}>
                    <option value="">Row number</option>
                    {columns.map((column) => <option key={column} value={column}>{column}</option>)}
                  </select>
                </label>
                <label>
                  Y
                  <select value={chartY} onChange={(event) => setChartY(event.target.value)}>
                    {profile.numeric_columns.map((column) => <option key={column} value={column}>{column}</option>)}
                  </select>
                </label>
                <button type="button" onClick={() => void runChart()} disabled={chartBusy || !chartY}>
                  {chartBusy ? <Loader2 size={14} className="spin" /> : <BarChart3 size={14} />}
                  Build chart
                </button>
              </div>
              {chart && (
                <div className="data-mode__chart">
                  <SlideChart chart={chart} />
                </div>
              )}
            </section>

            <section className="data-mode__section">
              <h3><Download size={14} /> Export</h3>
              <div className="data-mode__exports">
                <button type="button" onClick={() => void exportData('csv')} disabled={exportBusy !== null}>
                  {exportBusy === 'csv' ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
                  Cleaned CSV
                </button>
                <button type="button" onClick={() => void exportData('xlsx')} disabled={exportBusy !== null}>
                  {exportBusy === 'xlsx' ? <Loader2 size={14} className="spin" /> : <FileSpreadsheet size={14} />}
                  Cleaned XLSX
                </button>
                <button type="button" onClick={() => void makeDashboard()} disabled={exportBusy !== null}>
                  {exportBusy === 'dashboard' ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
                  Create dashboard artifact
                </button>
              </div>
            </section>
          </>
        )}
      </div>
    </Dialog>
  );
}
