import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";

const API_BASE = (import.meta.env.VITE_API_BASE || "/api").replace(/\/$/, "");
const PROVIDERS = [
  ["ollama", "Ollama · Local"],
  ["openai", "OpenAI"],
  ["gemini", "Gemini"],
  ["deepseek", "DeepSeek"],
  ["claude", "Claude"],
] as const;
const EXAMPLES = [
  "Show sales by city for the last quarter",
  "List the top 10 product categories by revenue",
  "How many orders were placed each month?",
];
const NAV_ITEMS = [
  ["overview", "Overview", "⌂"],
  ["ask", "Ask Data", "◉"],
  ["history", "Query History", "◷"],
  ["saved", "Saved Insights", "♧"],
  ["sources", "Data Sources", "▤"],
  ["admin", "Administration", "⚙"],
] as const;

type Page = (typeof NAV_ITEMS)[number][0];
type Tab = "visualization" | "table" | "sql" | "details";
type QueryResult = {
  sql: string;
  results: Record<string, unknown>[];
  row_count: number;
  correlation_id: string;
};
type HistoryItem = {
  id: string;
  query: string;
  provider: string;
  createdAt: string;
  result: QueryResult;
  durationMs: number;
};
type SchemaColumn = {
  name: string;
  type?: string;
  data_type?: string;
  nullable?: boolean;
  primary_key?: boolean;
};
type SchemaTable = { name: string; description?: string; columns?: SchemaColumn[] };
type DatabaseSchema = {
  database_name?: string;
  database?: { type?: string };
  tables?: SchemaTable[];
  schemas?: { name: string; tables?: SchemaTable[] }[];
};
type Health = { status?: string; postgres?: string };

function readStored<T>(key: string, fallback: T): { value: T; error?: string } {
  try {
    const value = localStorage.getItem(key);
    if (!value) return { value: fallback };
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      return { value: fallback, error: `Could not read ${key}: stored data has an invalid format.` };
    }
    return { value: parsed as T };
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : "Unknown browser storage error.";
    return { value: fallback, error: `Could not read ${key}: ${detail}` };
  }
}

function writeStored<T>(key: string, value: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    throw new Error("Browser storage is full or unavailable. Remove saved items and try again.");
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new Error("Could not reach the API. Check that the backend is running and try again.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `The API returned ${response.status} ${response.statusText}.`);
  }
  return response.json() as Promise<T>;
}

function Icon({ children }: { children: ReactNode }) {
  return <span className="nav-icon" aria-hidden="true">{children}</span>;
}

function App() {
  const [page, setPage] = useState<Page>("ask");
  const [question, setQuestion] = useState("");
  const [provider, setProvider] = useState<string>("ollama");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [activeQuery, setActiveQuery] = useState("");
  const [activeProvider, setActiveProvider] = useState("ollama");
  const [storedHistory] = useState(() => readStored<HistoryItem[]>("nl2sql-history", []));
  const [storedSaved] = useState(() => readStored<HistoryItem[]>("nl2sql-saved", []));
  const [history, setHistory] = useState<HistoryItem[]>(storedHistory.value);
  const [saved, setSaved] = useState<HistoryItem[]>(storedSaved.value);
  const [health, setHealth] = useState<Health | null>(null);
  const [schema, setSchema] = useState<DatabaseSchema | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(storedHistory.error || storedSaved.error || "");
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState<Tab>("visualization");
  const [inspectionTab, setInspectionTab] = useState<"sql" | "validation" | "execution">("sql");
  const [inspectionOpen, setInspectionOpen] = useState(() => window.matchMedia("(min-width: 981px)").matches);
  const [filter, setFilter] = useState("");
  const [sortColumn, setSortColumn] = useState("");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [pageNumber, setPageNumber] = useState(1);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [adminBusy, setAdminBusy] = useState("");
  const [exportOpen, setExportOpen] = useState(false);

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await api<Health>("/health"));
    } catch (cause) {
      setHealth(null);
      setError(cause instanceof Error ? cause.message : "Could not retrieve backend health.");
    }
  }, []);

  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(""), 3200);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  const runQuery = async (event?: FormEvent<HTMLFormElement>, query = question) => {
    event?.preventDefault();
    if (!query.trim()) {
      setError("Enter a question before running the query.");
      return;
    }
    setError("");
    setNotice("");
    setLoading(true);
    setPage("ask");
    setQuestion(query);
    const startedAt = performance.now();
    try {
      const response = await api<QueryResult>("/query", {
        method: "POST",
        body: JSON.stringify({ query: query.trim(), provider }),
      });
      const item: HistoryItem = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        query: query.trim(),
        provider,
        createdAt: new Date().toISOString(),
        result: response,
        durationMs: Math.round(performance.now() - startedAt),
      };
      setResult(response);
      setActiveQuery(query.trim());
      setActiveProvider(provider);
      setTab("visualization");
      setPageNumber(1);
      setFilter("");
      setSortColumn("");
      const nextHistory = [item, ...history].slice(0, 20);
      try {
        writeStored("nl2sql-history", nextHistory);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not store query history.");
      }
      setHistory(nextHistory);
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "The query could not be completed.");
    } finally {
      setLoading(false);
    }
  };

  const openHistoryItem = (item: HistoryItem) => {
    setResult(item.result);
    setActiveQuery(item.query);
    setActiveProvider(item.provider);
    setQuestion(item.query);
    setPage("ask");
    setError("");
    setTab("visualization");
  };

  const saveInsight = () => {
    if (!result) return;
    const entry: HistoryItem = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      query: activeQuery,
      provider: activeProvider,
      createdAt: new Date().toISOString(),
      result,
      durationMs: 0,
    };
    const next = [entry, ...saved.filter((item) => item.query !== activeQuery)];
    try {
      writeStored("nl2sql-saved", next);
      setSaved(next);
      setNotice("Insight saved to this browser.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this insight.");
    }
  };

  const removeSaved = (id: string) => {
    const next = saved.filter((item) => item.id !== id);
    try {
      writeStored("nl2sql-saved", next);
      setSaved(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update saved insights.");
    }
  };

  const exportCsv = () => {
    if (!result?.results.length) return;
    const columns = Object.keys(result.results[0]);
    const quote = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const csv = [columns.map(quote).join(","), ...result.results.map((row) => columns.map((key) => quote(row[key])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "query-results.csv";
    link.click();
    URL.revokeObjectURL(url);
    setExportOpen(false);
  };

  const loadSchema = async () => {
    setError("");
    try {
      setSchema(await api<DatabaseSchema>("/schema"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load the database schema.");
    }
  };

  const runAdminAction = async (action: "refresh" | "clear" | "warmup") => {
    setAdminBusy(action);
    setError("");
    try {
      const response = await api<{ message?: string }>(`/admin/cache/${action}`, { method: "POST" });
      setNotice(response.message || `Cache ${action} completed.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Cache ${action} failed.`);
    } finally {
      setAdminBusy("");
    }
  };

  useEffect(() => {
    if (page === "sources" && !schema) void loadSchema();
  }, [page, schema]);

  const tables = useMemo(() => {
    if (!schema) return [];
    if (schema.tables?.length) return schema.tables;
    return (schema.schemas || []).flatMap((entry) => entry.tables || []);
  }, [schema]);

  const columns = result?.results.length ? Object.keys(result.results[0]) : [];
  const numericColumns = columns.filter((column) =>
    result?.results.some((row) => typeof row[column] === "number" || (typeof row[column] === "string" && row[column] !== "" && Number.isFinite(Number(row[column])))),
  );
  const categoryColumn = columns.find((column) => !numericColumns.includes(column));
  const measureColumn = numericColumns[0];
  const chartRows = useMemo(() => {
    if (!result || !measureColumn) return [];
    const grouped = new Map<string, number>();
    result.results.forEach((row, index) => {
      const label = categoryColumn ? String(row[categoryColumn] ?? "Not specified") : `Row ${index + 1}`;
      const amount = Number(row[measureColumn]);
      if (Number.isFinite(amount)) grouped.set(label, (grouped.get(label) || 0) + amount);
    });
    return [...grouped.entries()].slice(0, 8).map(([label, value]) => ({ label, value }));
  }, [categoryColumn, measureColumn, result]);
  const visibleRows = useMemo(() => {
    let rows = result?.results || [];
    if (filter.trim()) {
      const term = filter.toLocaleLowerCase();
      rows = rows.filter((row) => Object.values(row).some((value) => String(value ?? "").toLocaleLowerCase().includes(term)));
    }
    if (sortColumn) {
      rows = [...rows].sort((left, right) => {
        const a = left[sortColumn];
        const b = right[sortColumn];
        const comparison = typeof a === "number" && typeof b === "number"
          ? a - b
          : String(a ?? "").localeCompare(String(b ?? ""), undefined, { numeric: true });
        return sortDirection === "asc" ? comparison : -comparison;
      });
    }
    return rows;
  }, [filter, result, sortColumn, sortDirection]);
  const totalPages = Math.max(1, Math.ceil(visibleRows.length / rowsPerPage));
  const pageRows = visibleRows.slice((pageNumber - 1) * rowsPerPage, pageNumber * rowsPerPage);

  const switchPage = (nextPage: Page) => {
    setPage(nextPage);
    setError("");
    setNotice("");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => switchPage("overview")} aria-label="Go to overview">
          <span className="brand-mark">✦</span>
          <span className="brand-name">Inference Engine<span>DATA WORKSPACE</span></span>
        </button>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="navigation" aria-label="Main navigation">
          {NAV_ITEMS.map(([id, label, icon]) => (
            <button key={id} className={`nav-item ${page === id ? "active" : ""}`} onClick={() => switchPage(id)}>
              <Icon>{icon}</Icon><span>{label}</span>
              {id === "saved" && saved.length > 0 && <span className="nav-count">{saved.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="pro-tip">
          <span className="tip-sparkle">✦</span><strong>Pro tip</strong>
          <p>Ask a follow-up question to refine your results, or save an insight for later.</p>
          <button onClick={() => setNotice("Try a specific question, such as “Show sales by city this quarter”.")}>Got it</button>
        </div>
        <div className="sidebar-footer"><span className="online-dot" /> API {health?.status === "healthy" ? "connected" : "status unknown"}<span>v1.0.0</span></div>
      </aside>

      <main className={`main-area ${inspectionOpen && page === "ask" ? "with-inspector" : ""}`}>
        <header className="mobile-header">
          <button className="mobile-brand" onClick={() => switchPage("ask")}><span className="brand-mark">✦</span> Inference Engine</button>
          <select aria-label="Navigate" value={page} onChange={(event) => switchPage(event.target.value as Page)}>
            {NAV_ITEMS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </header>
        {error && <div className="alert alert-error" role="alert"><span>!</span>{error}<button onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
        {notice && <div className="alert alert-success" role="status"><span>✓</span>{notice}<button onClick={() => setNotice("")} aria-label="Dismiss notification">×</button></div>}
        {page === "ask" && (
          <AskPage
            activeQuery={activeQuery}
            chartRows={chartRows}
            columns={columns}
            error={error}
            exportCsv={exportCsv}
            exportOpen={exportOpen}
            filter={filter}
            historyCount={history.length}
            loading={loading}
            measureColumn={measureColumn}
            onExportToggle={() => setExportOpen(!exportOpen)}
            onFilterChange={(value) => { setFilter(value); setPageNumber(1); }}
            onInspect={() => setInspectionOpen(!inspectionOpen)}
            onPageChange={setPageNumber}
            onProviderChange={setProvider}
            onQueryChange={setQuestion}
            onRowsPerPageChange={setRowsPerPage}
            onRun={runQuery}
            onSave={saveInsight}
            onSelectTab={setTab}
            onSort={(column) => {
              setSortDirection(sortColumn === column && sortDirection === "asc" ? "desc" : "asc");
              setSortColumn(column);
            }}
            pageNumber={pageNumber}
            pageRows={pageRows}
            provider={provider}
            result={result}
            rowsPerPage={rowsPerPage}
            saved={saved.some((item) => item.query === activeQuery)}
            sortColumn={sortColumn}
            sortDirection={sortDirection}
            tab={tab}
            totalPages={totalPages}
            visibleRowCount={visibleRows.length}
            question={question}
            activeProvider={activeProvider}
          />
        )}
        {page === "overview" && <OverviewPage health={health} history={history} onAsk={() => switchPage("ask")} onOpen={openHistoryItem} savedCount={saved.length} />}
        {page === "history" && <CollectionPage title="Query History" subtitle="Your recent questions, saved in this browser." items={history} empty="Run a query to see it here." onOpen={openHistoryItem} />}
        {page === "saved" && <CollectionPage title="Saved Insights" subtitle="Results you have kept for quick access." items={saved} empty="Save an insight from a query result to find it here." onOpen={openHistoryItem} onRemove={removeSaved} />}
        {page === "sources" && <SourcesPage health={health} schema={schema} tables={tables} onReload={() => void loadSchema()} />}
        {page === "admin" && <AdminPage busy={adminBusy} health={health} onAction={runAdminAction} onRefreshHealth={() => void loadHealth()} />}
      </main>

      {page === "ask" && inspectionOpen && (
        <InspectionPanel
          activeProvider={activeProvider}
          duration={history.find((item) => item.query === activeQuery)?.durationMs}
          inspectionTab={inspectionTab}
          onClose={() => setInspectionOpen(false)}
          onTab={setInspectionTab}
          result={result}
        />
      )}
    </div>
  );
}

type AskPageProps = {
  activeQuery: string; chartRows: { label: string; value: number }[]; columns: string[];
  error: string; exportCsv: () => void; exportOpen: boolean; filter: string;
  historyCount: number; loading: boolean; measureColumn?: string; onExportToggle: () => void;
  onFilterChange: (value: string) => void; onInspect: () => void; onPageChange: (page: number) => void;
  onRowsPerPageChange: (rows: number) => void;
  onProviderChange: (provider: string) => void; onQueryChange: (query: string) => void;
  onRun: (event?: FormEvent<HTMLFormElement>, query?: string) => Promise<void>; onSave: () => void;
  onSelectTab: (tab: Tab) => void; onSort: (column: string) => void; pageNumber: number;
  pageRows: Record<string, unknown>[]; provider: string; result: QueryResult | null;
  rowsPerPage: number; saved: boolean; sortColumn: string; sortDirection: "asc" | "desc";
  tab: Tab; totalPages: number; visibleRowCount: number; question: string; activeProvider: string;
};

function AskPage(props: AskPageProps) {
  const {
    activeQuery, chartRows, columns, exportCsv, exportOpen, filter, historyCount, loading, measureColumn,
    onExportToggle,     onFilterChange, onInspect, onPageChange, onProviderChange, onQueryChange, onRowsPerPageChange,
    onRun, onSave, onSelectTab, onSort, pageNumber, pageRows, provider, result, rowsPerPage,
    saved, sortColumn, sortDirection, tab, totalPages, visibleRowCount, question, activeProvider,
  } = props;
  const maxBar = Math.max(1, ...chartRows.map((item) => item.value));
  const providerName = PROVIDERS.find(([value]) => value === (result ? activeProvider : provider))?.[1] || "Ollama · Local";
  return (
    <div className="ask-content">
      <div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>Ask Data</strong></div>
      <div className="ask-heading">
        <div className="heading-icon">◉</div>
        <div className="heading-copy"><h1>{result ? activeQuery : "What would you like to know?"}</h1><p>{result ? <><span className="status-pill"><i /> Completed</span><span className="meta-dot">·</span>{historyCount > 0 ? "Ready to explore" : "Query complete"}<span className="meta-dot">·</span>{result.row_count.toLocaleString()} rows returned</> : "Ask a question in plain language and explore your data."}</p></div>
        {result && <div className="heading-actions"><button className={`button button-outline ${saved ? "is-saved" : ""}`} onClick={onSave}><span>♧</span>{saved ? "Saved" : "Save"}</button><div className="export-wrap"><button className="button button-primary" onClick={onExportToggle}><span>⇩</span>Export</button>{exportOpen && <div className="export-menu"><button onClick={exportCsv}>Download CSV</button></div>}</div><button className="icon-button" onClick={onInspect} aria-label="Toggle SQL inspection">⋮</button></div>}
      </div>

      <section className="query-composer">
        <div className="composer-topline"><div><span className="composer-label">Ask your data</span><span className="composer-hint">Natural language to SQL</span></div><div className="composer-controls"><button className="inspector-launch" onClick={onInspect}>⌕ SQL Inspection</button><label className="provider-select">Model<select value={provider} onChange={(event) => onProviderChange(event.target.value)}>{PROVIDERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div></div>
        <form onSubmit={(event) => void onRun(event)}>
          <textarea value={question} onChange={(event) => onQueryChange(event.target.value)} placeholder="Ask anything about your data…" rows={2} maxLength={2000} aria-label="Ask a data question" />
          <div className="composer-footer"><span className="privacy-note"><span>♧</span> Queries are validated for safety before execution</span><button className="button button-primary run-button" disabled={loading}><span>{loading ? "◌" : "➤"}</span>{loading ? "Running query…" : "Run query"}<kbd>↵</kbd></button></div>
        </form>
        {!result && <div className="example-queries"><span>TRY ASKING</span>{EXAMPLES.map((example) => <button key={example} onClick={() => { onQueryChange(example); void onRun(undefined, example); }}>{example}<span>↗</span></button>)}</div>}
      </section>

      {loading && <div className="loading-state"><span className="spinner" /><div><strong>Working on your question</strong><p>Generating SQL, validating it, and retrieving your results…</p></div></div>}
      {result && !loading && (
        <>
          <div className="result-tabs">
            {([["visualization", "▥", "Visualization"], ["table", "▦", "Table"], ["sql", "</>", "SQL"], ["details", "ⓘ", "Details"]] as [Tab, string, string][]).map(([id, icon, label]) => (
              <button key={id} className={tab === id ? "selected" : ""} onClick={() => onSelectTab(id)}><span>{icon}</span>{label}</button>
            ))}
            <button className="inspection-toggle" onClick={onInspect}>SQL Inspection <span>↗</span></button>
          </div>
          {tab === "visualization" && (
            <div className="visual-grid">
              <section className="card chart-card">
                <div className="card-heading"><div><h2>{measureColumn ? `${formatLabel(measureColumn)} by ${columns.find((item) => item !== measureColumn) ? formatLabel(columns.find((item) => item !== measureColumn)! ) : "row"}` : "Query results"}</h2><p>Based on {result.results.length.toLocaleString()} returned records</p></div><span className="chart-type">▥ &nbsp;Bar chart⌄</span></div>
                {chartRows.length ? (
                  <div className="chart" role="img" aria-label={`Bar chart of ${measureColumn}`}>
                    <div className="chart-axis">{[100, 75, 50, 25, 0].map((value) => <span key={value}>{formatNumber(maxBar * value / 100)}</span>)}</div>
                    <div className="chart-bars">{chartRows.map(({ label, value }) => (
                      <div className="bar-column" key={label}><span className="bar-value">{formatNumber(value)}</span><div className="bar-track"><div className="bar" style={{ height: `${Math.max(4, value / maxBar * 100)}%` }} /></div><span className="bar-label" title={label}>{label}</span></div>
                    ))}</div>
                  </div>
                ) : <div className="empty-chart"><span>▥</span><strong>No chartable results</strong><p>Return numeric data to see a visualization.</p></div>}
                <div className="chart-legend"><span />{measureColumn ? formatLabel(measureColumn) : "Results"}</div>
              </section>
              <section className="card metrics-card"><h2>Key metrics</h2><Metric icon="◉" tint="green" label="Rows returned" value={result.row_count.toLocaleString()} /><Metric icon="▦" tint="blue" label="Columns" value={columns.length.toString()} /><Metric icon="◷" tint="purple" label="Model" value={providerName} /></section>
            </div>
          )}
          {tab === "table" && (
            <section className="card table-card">
              <div className="table-header"><div><h2>Query results</h2><p>{visibleRowCount.toLocaleString()} {filter ? "matching " : ""}records</p></div><div className="table-tools"><label className="table-search"><span>⌕</span><input value={filter} onChange={(event) => onFilterChange(event.target.value)} placeholder="Filter results" /></label><button className="button button-outline small-button" onClick={exportCsv}>⇩ Export</button></div></div>
              <div className="table-scroll"><table><thead><tr><th className="row-number">#</th>{columns.map((column) => <th key={column}><button onClick={() => onSort(column)}>{formatLabel(column)}<span className="sort-arrow">{sortColumn === column ? (sortDirection === "asc" ? "↑" : "↓") : "↕"}</span></button></th>)}</tr></thead><tbody>{pageRows.map((row, index) => <tr key={`${pageNumber}-${index}`}><td className="row-number">{(pageNumber - 1) * rowsPerPage + index + 1}</td>{columns.map((column) => <td key={column} title={String(row[column] ?? "")}>{formatCell(row[column])}</td>)}</tr>)}</tbody></table>{pageRows.length === 0 && <div className="table-empty">No matching records.</div>}</div>
              <div className="pagination"><label>Rows per page <select value={rowsPerPage} onChange={(event) => { onRowsPerPageChange(Number(event.target.value)); onPageChange(1); }}><option value={10}>10</option><option value={25}>25</option><option value={50}>50</option></select></label><span>{visibleRowCount ? `${(pageNumber - 1) * rowsPerPage + 1}–${Math.min(pageNumber * rowsPerPage, visibleRowCount)} of ${visibleRowCount}` : "0 results"}</span><div><button disabled={pageNumber <= 1} onClick={() => onPageChange(pageNumber - 1)}>‹</button><span className="current-page">{pageNumber}</span><span>of {totalPages}</span><button disabled={pageNumber >= totalPages} onClick={() => onPageChange(pageNumber + 1)}>›</button></div></div>
            </section>
          )}
          {tab === "sql" && <section className="card sql-view"><div className="card-heading"><div><h2>Generated SQL</h2><p>Returned by the API after server-side safety validation</p></div><span className="safe-label"><i />Validated</span></div><pre><code>{result.sql}</code></pre></section>}
          {tab === "details" && <section className="card details-view"><h2>Query details</h2><Detail label="Question" value={activeQuery} /><Detail label="Provider" value={providerName} /><Detail label="Rows returned" value={result.row_count.toLocaleString()} /><Detail label="Request reference" value={result.correlation_id || "Not provided"} /><p className="safety-note">The backend returns query results only after the generated SQL passes its safety validation.</p></section>}
        </>
      )}
      {!result && !loading && <div className="welcome-footer"><span>✦</span> Ask a question to start exploring your data.</div>}
    </div>
  );
}

function InspectionPanel({ activeProvider, duration, inspectionTab, onClose, onTab, result }: {
  activeProvider: string; duration?: number; inspectionTab: "sql" | "validation" | "execution";
  onClose: () => void; onTab: (tab: "sql" | "validation" | "execution") => void; result: QueryResult | null;
}) {
  const providerName = PROVIDERS.find(([value]) => value === activeProvider)?.[1] || activeProvider;
  return (
    <aside className="inspection-panel">
      <div className="inspection-header"><h2>SQL Inspection</h2><button onClick={onClose} aria-label="Close SQL inspection">×</button></div>
      <div className="inspection-tabs">{([["sql", "</>", "SQL Query"], ["validation", "♧", "Validation"], ["execution", "▷", "Execution"]] as const).map(([id, icon, label]) => <button key={id} className={inspectionTab === id ? "selected" : ""} onClick={() => onTab(id)}><span>{icon}</span>{label}</button>)}</div>
      {inspectionTab === "sql" && (
        <><div className={`validation-banner ${result ? "passed" : "pending"}`}><span>{result ? "✓" : "i"}</span>{result ? "Validated & Safe" : "Run a query to inspect SQL"}</div><div className="code-window"><div className="line-numbers">{(result?.sql || "-- Generated SQL will appear here").split("\n").map((_, index) => <span key={index}>{index + 1}</span>)}</div><pre>{result?.sql || "-- Generated SQL will appear here"}</pre></div></>
      )}
      {inspectionTab === "validation" && <div className="inspection-copy"><span className={`validation-banner ${result ? "passed" : "pending"}`}>{result ? "✓ SQL validated by the backend" : "No query to validate"}</span><p>{result ? "The API executed this query and returned results after server-side SQL safety validation." : "Generated SQL is checked by the backend before it is executed."}</p><p>Validation rules are enforced by the API; this interface does not execute SQL directly.</p></div>}
      {inspectionTab === "execution" && <div className="inspection-copy"><div className="execution-status"><span className={result ? "online-dot" : "offline-dot"} />{result ? "Completed" : "Waiting for query"}</div><Detail label="Provider" value={result ? providerName : "—"} /><Detail label="Rows returned" value={result ? result.row_count.toLocaleString() : "—"} /><Detail label="Request reference" value={result?.correlation_id || "—"} /></div>}
      <div className="inspection-section"><h3><span>⌄</span> Query metadata</h3><Detail label="Model" value={result ? providerName : "—"} /><Detail label="Request time" value={duration !== undefined ? `${(duration / 1000).toFixed(1)}s` : "—"} /><Detail label="Validation status" value={result ? "Passed" : "—"} /><Detail label="Rows returned" value={result ? result.row_count.toLocaleString() : "—"} /></div>
      <div className="inspection-section"><h3>Database</h3><Detail label="Connection" value="PostgreSQL" /><Detail label="Schema" value="Configured database" /><Detail label="Read only" value="Yes" /><div className="read-only-note"><span>♧</span><p>This query was validated by the backend before execution.</p></div></div>
    </aside>
  );
}

function OverviewPage({ health, history, onAsk, onOpen, savedCount }: {
  health: Health | null; history: HistoryItem[]; onAsk: () => void;
  onOpen: (item: HistoryItem) => void; savedCount: number;
}) {
  return <div className="page-content"><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>Overview</strong></div><div className="page-title-row"><div><h1>Your data workspace</h1><p>Ask questions, explore results, and keep useful insights close.</p></div><button className="button button-primary" onClick={onAsk}>＋ Ask Data</button></div><div className="overview-metrics"><Metric icon="◉" tint="blue" label="Backend" value={health?.status === "healthy" ? "Online" : "Unavailable"} /><Metric icon="▦" tint="green" label="Queries this session" value={history.length.toString()} /><Metric icon="♧" tint="purple" label="Saved insights" value={savedCount.toString()} /></div><section className="card recent-card"><div className="table-header"><div><h2>Recent queries</h2><p>Your latest questions and results</p></div><button className="text-button" onClick={onAsk}>New question →</button></div>{history.length ? history.slice(0, 5).map((item) => <button className="list-row" key={item.id} onClick={() => onOpen(item)}><span className="list-icon">◉</span><span className="list-main"><strong>{item.query}</strong><small>{new Date(item.createdAt).toLocaleString()} · {item.result.row_count} rows</small></span><span className="list-arrow">↗</span></button>) : <div className="empty-state"><span>◉</span><strong>No queries yet</strong><p>Start by asking a question about your data.</p></div>}</section><div className="getting-started"><span>✦</span><div><strong>Ask in plain language</strong><p>Your generated SQL is validated by the backend before the results are returned.</p></div><button className="text-button" onClick={onAsk}>Ask a question →</button></div></div>;
}

function CollectionPage({ title, subtitle, items, empty, onOpen, onRemove }: {
  title: string; subtitle: string; items: HistoryItem[]; empty: string;
  onOpen: (item: HistoryItem) => void; onRemove?: (id: string) => void;
}) {
  return <div className="page-content"><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{title}</strong></div><div className="page-title-row"><div><h1>{title}</h1><p>{subtitle}</p></div><span className="count-chip">{items.length} {items.length === 1 ? "item" : "items"}</span></div><section className="card collection-card">{items.length ? items.map((item) => <div className="collection-row" key={item.id}><button className="list-icon" onClick={() => onOpen(item)} aria-label="Open query">◉</button><button className="list-main" onClick={() => onOpen(item)}><strong>{item.query}</strong><small>{new Date(item.createdAt).toLocaleString()} · {item.result.row_count.toLocaleString()} rows · {PROVIDERS.find(([value]) => value === item.provider)?.[1] || item.provider}</small></button><button className="button button-outline small-button" onClick={() => onOpen(item)}>Open</button>{onRemove && <button className="icon-button remove-button" onClick={() => onRemove(item.id)} aria-label="Remove saved insight">×</button>}</div>) : <div className="empty-state"><span>{title === "Query History" ? "◷" : "♧"}</span><strong>Nothing here yet</strong><p>{empty}</p></div>}</section></div>;
}

function SourcesPage({ health, schema, tables, onReload }: {
  health: Health | null; schema: DatabaseSchema | null; tables: SchemaTable[]; onReload: () => void;
}) {
  return <div className="page-content"><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>Data Sources</strong></div><div className="page-title-row"><div><h1>Data Sources</h1><p>Database connection status and available schema.</p></div><button className="button button-outline" onClick={onReload}>↻ Refresh schema</button></div><div className="overview-metrics"><Metric icon="▤" tint="blue" label="Database" value={schema?.database?.type || schema?.database_name || "PostgreSQL"} /><Metric icon="◉" tint={health?.postgres === "connected" ? "green" : "purple"} label="Connection" value={health?.postgres === "connected" ? "Connected" : "Not confirmed"} /><Metric icon="▦" tint="purple" label="Tables" value={tables.length.toString()} /></div><section className="card source-card"><div className="table-header"><div><h2>Database schema</h2><p>Tables and columns made available to the query assistant.</p></div></div>{tables.length ? <div className="schema-list">{tables.map((table) => <details className="schema-table" key={table.name}><summary><span className="schema-table-icon">▤</span><strong>{table.name}</strong><span className="schema-column-count">{table.columns?.length || 0} columns</span><span className="schema-chevron">⌄</span></summary>{table.description && <p className="schema-description">{table.description}</p>}<div className="schema-columns">{table.columns?.map((column) => <div key={column.name}><span>{column.name}</span><code>{column.type || column.data_type || "unknown"}</code>{column.primary_key && <em>PK</em>}</div>)}</div></details>)}</div> : <div className="empty-state"><span>▤</span><strong>{schema ? "No tables found" : "Schema not loaded"}</strong><p>{schema ? "No tables were returned by the schema endpoint." : "Refresh the schema to load available tables."}</p><button className="button button-outline" onClick={onReload}>Load schema</button></div>}</section></div>;
}

function AdminPage({ busy, health, onAction, onRefreshHealth }: {
  busy: string; health: Health | null; onAction: (action: "refresh" | "clear" | "warmup") => void;
  onRefreshHealth: () => void;
}) {
  return <div className="page-content"><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>Administration</strong></div><div className="page-title-row"><div><h1>Administration</h1><p>Monitor API availability and manage the model context cache.</p></div><button className="button button-outline" onClick={onRefreshHealth}>↻ Check health</button></div><section className="card admin-status"><div className="admin-status-icon">◉</div><div><strong>Backend {health?.status === "healthy" ? "is online" : "status unavailable"}</strong><p>Database: {health?.postgres || "Not confirmed"} · API: {health?.status || "Not confirmed"}</p></div><span className={`health-chip ${health?.status === "healthy" ? "healthy" : ""}`}>{health?.status === "healthy" ? "Operational" : "Unknown"}</span></section><section className="card admin-card"><h2>Model context cache</h2><p>Cache operations call the existing backend administration endpoints.</p><AdminAction title="Refresh context" text="Rebuild the schema context and warm up the model cache." action="refresh" busy={busy} onAction={onAction} /><AdminAction title="Warm up model" text="Warm up the Ollama model cache for the configured schema." action="warmup" busy={busy} onAction={onAction} /><AdminAction title="Clear cache" text="Clear the combined context cache and trigger a fresh build." action="clear" busy={busy} onAction={onAction} /></section></div>;
}

function AdminAction({ title, text, action, busy, onAction }: {
  title: string; text: string; action: "refresh" | "clear" | "warmup"; busy: string;
  onAction: (action: "refresh" | "clear" | "warmup") => void;
}) {
  return <div className="admin-action"><div><strong>{title}</strong><p>{text}</p></div><button className={action === "clear" ? "button button-outline danger-button" : "button button-outline"} disabled={Boolean(busy)} onClick={() => onAction(action)}>{busy === action ? "Working…" : action === "refresh" ? "Refresh" : action === "warmup" ? "Warm up" : "Clear cache"}</button></div>;
}

function Metric({ icon, tint, label, value }: { icon: string; tint: string; label: string; value: string }) {
  return <div className="metric"><span className={`metric-icon ${tint}`}>{icon}</span><span className="metric-copy"><span>{label}</span><strong>{value}</strong></span></div>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="detail-row"><span className="detail-icon">◷</span><span>{label}</span><strong title={value}>{value}</strong></div>;
}

function formatLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatNumber(value: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1, notation: Math.abs(value) >= 10000 ? "compact" : "standard" }).format(value);
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default App;
