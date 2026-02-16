/**
 * Database Explorer Component (SDK)
 *
 * SQL query editor, result viewer, and AI query assistant.
 * Uses SandboxUIApi from the provider for all API calls.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Database, Play, X, Maximize2, Minimize2, ChevronRight, ChevronDown, Table, Columns, Wand2, Loader2, Copy, ArrowRight } from 'lucide-react';
import { useSandboxApi } from '../context/SandboxUIContext';
import type { ConnectionWithSchema, QueryResult } from '../context/types';

export interface DatabaseExplorerProps {
  connectionId?: string;
  onClose?: () => void;
  fullscreen?: boolean;
}

export function DatabaseExplorer({
  connectionId,
  onClose,
  fullscreen: initialFullscreen = false
}: DatabaseExplorerProps) {
  const api = useSandboxApi();
  const [isFullscreen, setIsFullscreen] = useState(initialFullscreen);
  const [connections, setConnections] = useState<ConnectionWithSchema[]>([]);
  const [selectedConnection, setSelectedConnection] = useState<string | undefined>(connectionId);
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<QueryResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isLoadingSchema, setIsLoadingSchema] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());
  const [executionTime, setExecutionTime] = useState<number | null>(null);
  const [aiQuery, setAiQuery] = useState('');
  const [aiResult, setAiResult] = useState<{ sql_query: string; explanation: string } | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const aiInputRef = useRef<HTMLInputElement>(null);

  const hasQueryApi = Boolean(api.query);
  const hasAiApi = Boolean(api.ai);

  // Load schema on mount
  useEffect(() => {
    loadSchema();
  }, []);

  const loadSchema = async () => {
    if (!api.query) {
      setLoadError('Query API not configured.');
      setIsLoadingSchema(false);
      return;
    }
    setIsLoadingSchema(true);
    setLoadError(null);
    try {
      const response = await api.query.fullSync();
      const conns = response?.connections ?? [];
      if (conns.length > 0) {
        setConnections(conns);
        if (!selectedConnection) {
          setSelectedConnection(conns[0].id);
        }
      } else {
        setLoadError('No database connections configured.');
      }
    } catch (err: any) {
      setLoadError(err?.message || 'Failed to load schema');
    } finally {
      setIsLoadingSchema(false);
    }
  };

  const executeQuery = useCallback(async () => {
    if (!query.trim() || !selectedConnection || isExecuting || !api.query) return;

    setIsExecuting(true);
    setQueryError(null);
    setResult(null);
    const startTime = performance.now();

    try {
      const response = await api.query.executeSql(selectedConnection, query.trim());

      setExecutionTime(Math.round(performance.now() - startTime));

      if (response?.status === 'success' && response?.data) {
        setResult({
          columns: response.data.columns || [],
          rows: response.data.rows || [],
          row_count: response.data.row_count || 0,
          total_rows_available: response.data.total_rows_available,
        });
      } else if (response?.status === 'error') {
        setQueryError(response?.message || 'Query execution failed');
      }
    } catch (err: any) {
      setExecutionTime(Math.round(performance.now() - startTime));
      setQueryError(err?.message || 'Query execution failed');
    } finally {
      setIsExecuting(false);
    }
  }, [query, selectedConnection, isExecuting, api.query]);

  // Ctrl+Enter to execute
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      executeQuery();
    }
  }, [executeQuery]);

  const toggleTable = (tableName: string) => {
    setExpandedTables(prev => {
      const next = new Set(prev);
      if (next.has(tableName)) next.delete(tableName);
      else next.add(tableName);
      return next;
    });
  };

  const insertTableQuery = (tableName: string) => {
    const conn = connections.find(c => c.id === selectedConnection);
    const table = conn?.tables.find(t => t.name === tableName);
    const cols = table?.columns.map(c => `"${c.name}"`).join(', ') || '*';
    setQuery(`SELECT ${cols}\nFROM "${tableName}"\nLIMIT 100`);
    textareaRef.current?.focus();
  };

  const generateSql = useCallback(async () => {
    if (!aiQuery.trim() || !selectedConnection || aiLoading || !api.ai) return;

    setAiLoading(true);
    setAiError(null);
    setAiResult(null);

    try {
      const response = await api.ai.generateQuery(selectedConnection, aiQuery.trim());

      if (response?.success && response?.sql_query) {
        setAiResult({
          sql_query: response.sql_query,
          explanation: response.explanation || '',
        });
      } else {
        const errMsg = response?.error || 'Failed to generate SQL';
        setAiError(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
      }
    } catch (err: any) {
      const errMsg = err?.message || 'Failed to generate SQL';
      setAiError(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
    } finally {
      setAiLoading(false);
    }
  }, [aiQuery, selectedConnection, aiLoading, api.ai]);

  const useGeneratedQuery = () => {
    if (aiResult?.sql_query) {
      setQuery(aiResult.sql_query);
      textareaRef.current?.focus();
    }
  };

  const currentConnection = connections.find(c => c.id === selectedConnection);

  const containerClass = isFullscreen
    ? 'fixed inset-0 z-50 bg-white flex flex-col'
    : 'relative h-full bg-white rounded-lg shadow-lg border border-gray-200 flex flex-col';

  if (isLoadingSchema) {
    return (
      <div className={containerClass}>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <Database className="w-8 h-8 text-blue-600 animate-pulse mx-auto mb-3" />
            <p className="text-gray-600">Loading database schema...</p>
          </div>
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className={containerClass}>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-md p-6">
            <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <X className="w-8 h-8 text-red-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Connection Error</h3>
            <p className="text-gray-600 mb-4">{loadError}</p>
            <button
              onClick={loadSchema}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
            >
              Try Again
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={containerClass}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50 shrink-0">
        <div className="flex items-center gap-3">
          <Database className="w-5 h-5 text-blue-600" />
          <h2 className="text-lg font-semibold text-gray-800">Query Explorer</h2>
          {connections.length > 0 && (
            <select
              value={selectedConnection}
              onChange={(e) => setSelectedConnection(e.target.value)}
              className="ml-2 px-3 py-1 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {connections.map((conn) => (
                <option key={conn.id} value={conn.id}>
                  {conn.name} ({conn.db_type})
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsFullscreen(!isFullscreen)}
            className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-md transition-colors"
            title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
          >
            {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
          {onClose && (
            <button onClick={onClose} className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-md transition-colors">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* AI Assistant Panel — shown only if ai API is available */}
      {hasAiApi && (
        <div className="shrink-0 border-b border-purple-200 bg-purple-50 px-4 py-3">
          <div className="flex items-center gap-2 mb-2">
            <Wand2 className="w-4 h-4 text-purple-600" />
            <span className="text-sm font-medium text-purple-800">AI Query Assistant</span>
            <span className="text-xs text-purple-500">Describe what you want to query in plain language</span>
          </div>
          <div className="flex gap-2">
            <input
              ref={aiInputRef}
              type="text"
              value={aiQuery}
              onChange={(e) => setAiQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  generateSql();
                }
              }}
              placeholder="e.g. Show top 10 customers by total order amount..."
              className="flex-1 px-3 py-2 text-sm text-gray-900 border border-purple-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500 bg-white cursor-text"
              style={{ caretColor: '#7c3aed' }}
              disabled={aiLoading}
            />
            <button
              onClick={generateSql}
              disabled={aiLoading || !aiQuery.trim() || !selectedConnection}
              className="flex items-center gap-1.5 px-4 py-2 bg-purple-600 text-white text-sm rounded-md hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
            >
              {aiLoading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Wand2 className="w-3.5 h-3.5" />
                  Generate
                </>
              )}
            </button>
          </div>

          {aiError && (
            <div className="mt-2 px-3 py-2 bg-red-50 border border-red-200 rounded-md">
              <p className="text-sm text-red-700">{aiError}</p>
            </div>
          )}

          {aiResult && (
            <div className="mt-2 bg-white border border-purple-200 rounded-md overflow-hidden">
              <div className="relative">
                <pre className="p-3 pr-32 text-sm font-mono text-gray-800 whitespace-pre-wrap bg-gray-50">{aiResult.sql_query}</pre>
                <div className="absolute top-2 right-2 flex gap-1">
                  <button
                    onClick={() => navigator.clipboard.writeText(aiResult.sql_query)}
                    className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded transition-colors"
                    title="Copy SQL"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={useGeneratedQuery}
                    className="flex items-center gap-1 px-2 py-1 text-xs bg-purple-600 text-white rounded hover:bg-purple-700 transition-colors"
                    title="Use this query in the editor"
                  >
                    <ArrowRight className="w-3 h-3" />
                    Use Query
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Main layout: sidebar + editor/results */}
      <div className="flex-1 flex overflow-hidden">
        {/* Schema Sidebar */}
        <div className="w-56 border-r border-gray-200 bg-gray-50 overflow-y-auto shrink-0">
          <div className="p-2">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-2 py-1">Tables</h3>
            {currentConnection?.tables?.length ? (
              currentConnection.tables.map((table) => (
                <div key={table.name}>
                  <button
                    onClick={() => toggleTable(table.name)}
                    onDoubleClick={() => insertTableQuery(table.name)}
                    className="w-full flex items-center gap-1 px-2 py-1 text-sm text-gray-700 hover:bg-gray-100 rounded transition-colors"
                    title="Double-click to generate SELECT query"
                  >
                    {expandedTables.has(table.name) ? (
                      <ChevronDown className="w-3 h-3 text-gray-400 shrink-0" />
                    ) : (
                      <ChevronRight className="w-3 h-3 text-gray-400 shrink-0" />
                    )}
                    <Table className="w-3.5 h-3.5 text-blue-500 shrink-0" />
                    <span className="truncate">{table.name}</span>
                  </button>
                  {expandedTables.has(table.name) && table.columns && (
                    <div className="ml-5 border-l border-gray-200">
                      {table.columns.map((col) => (
                        <div
                          key={col.name}
                          className="flex items-center gap-1 px-2 py-0.5 text-xs text-gray-600"
                          title={col.data_type}
                        >
                          <Columns className="w-3 h-3 text-gray-400 shrink-0" />
                          <span className="truncate">{col.name}</span>
                          <span className="text-gray-400 ml-auto text-[10px] shrink-0">{col.data_type}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))
            ) : (
              <p className="text-xs text-gray-400 px-2 py-2">No tables found</p>
            )}
          </div>
        </div>

        {/* Editor + Results */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* SQL Editor */}
          <div className="shrink-0 border-b border-gray-200">
            <div className="relative">
              <textarea
                ref={textareaRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Write your SQL query here... (Ctrl+Enter to execute)"
                className="w-full h-32 p-3 pr-24 font-mono text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset border-0"
                spellCheck={false}
              />
              <button
                onClick={executeQuery}
                disabled={isExecuting || !query.trim() || !hasQueryApi}
                className="absolute top-2 right-2 flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Play className="w-3.5 h-3.5" />
                {isExecuting ? 'Running...' : 'Run'}
              </button>
            </div>
          </div>

          {/* Results area */}
          <div className="flex-1 overflow-auto">
            {isExecuting && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center">
                  <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                  <p className="text-sm text-gray-500">Executing query...</p>
                </div>
              </div>
            )}

            {queryError && !isExecuting && (
              <div className="p-4">
                <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-red-800 mb-1">Query Error</h4>
                  <pre className="text-sm text-red-700 whitespace-pre-wrap font-mono">{queryError}</pre>
                </div>
              </div>
            )}

            {result && !isExecuting && (
              <div className="flex flex-col h-full">
                {/* Status bar */}
                <div className="shrink-0 flex items-center justify-between px-4 py-1.5 bg-gray-50 border-b border-gray-200 text-xs text-gray-500">
                  <span>
                    {result.row_count} row{result.row_count !== 1 ? 's' : ''} returned
                    {result.total_rows_available && result.total_rows_available > result.row_count
                      ? ` (${result.total_rows_available.toLocaleString()} total)`
                      : ''}
                  </span>
                  {executionTime !== null && <span>{executionTime}ms</span>}
                </div>

                {/* Results table */}
                <div className="flex-1 overflow-auto">
                  {result.columns.length > 0 ? (
                    <table className="min-w-full text-sm">
                      <thead className="bg-gray-50 sticky top-0">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 border-b border-r border-gray-200 bg-gray-100 w-10">#</th>
                          {result.columns.map((col, i) => (
                            <th
                              key={i}
                              className="px-3 py-2 text-left text-xs font-medium text-gray-700 border-b border-r border-gray-200 bg-gray-100 whitespace-nowrap"
                              title={col.type}
                            >
                              {col.name}
                              <span className="ml-1 text-gray-400 font-normal">{col.type}</span>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.rows.map((row, rowIdx) => (
                          <tr key={rowIdx} className="hover:bg-blue-50 transition-colors">
                            <td className="px-3 py-1.5 text-xs text-gray-400 border-b border-r border-gray-100 bg-gray-50">{rowIdx + 1}</td>
                            {Array.isArray(row) ? (
                              row.map((cell: any, colIdx: number) => (
                                <td key={colIdx} className="px-3 py-1.5 border-b border-r border-gray-100 font-mono text-xs text-gray-900 whitespace-nowrap max-w-xs truncate" title={cell != null ? String(cell) : 'NULL'}>
                                  {cell === null || cell === undefined ? <span className="text-gray-400 italic">NULL</span> : String(cell)}
                                </td>
                              ))
                            ) : (
                              result.columns.map((col, colIdx) => {
                                const val = row[col.name];
                                return (
                                  <td key={colIdx} className="px-3 py-1.5 border-b border-r border-gray-100 font-mono text-xs text-gray-900 whitespace-nowrap max-w-xs truncate" title={val != null ? String(val) : 'NULL'}>
                                    {val === null || val === undefined
                                      ? <span className="text-gray-400 italic">NULL</span>
                                      : String(val)}
                                  </td>
                                );
                              })
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="flex items-center justify-center h-full text-sm text-gray-500">
                      Query executed successfully (no results to display)
                    </div>
                  )}
                </div>
              </div>
            )}

            {!result && !queryError && !isExecuting && (
              <div className="flex items-center justify-center h-full text-gray-400">
                <div className="text-center">
                  <Database className="w-12 h-12 mx-auto mb-3 opacity-30" />
                  <p className="text-sm">Write a query and press <kbd className="px-1.5 py-0.5 bg-gray-100 border border-gray-300 rounded text-xs">Ctrl+Enter</kbd> to execute</p>
                  <p className="text-xs mt-1">Double-click a table name in the sidebar to generate a SELECT query</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
