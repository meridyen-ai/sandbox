/**
 * Connections Page - Full connection management UI.
 * Orchestrates DataSourceSelector, ConnectionForm, and TableColumnSelector.
 * No external dependencies (react-query, react-router removed).
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Plus,
  Database,
  Trash2,
  ArrowLeft,
  Search,
  Loader2,
  CheckCircle,
  XCircle,
  RefreshCw,
  Settings2,
} from 'lucide-react'
import { useSandboxUI } from '../context/SandboxUIContext'
import { DataSourceSelector } from './DataSourceSelector'
import { ConnectionForm } from './ConnectionForm'
import { TableColumnSelector } from './TableColumnSelector'
import type { HandlerInfo, Connection, SelectedSchema } from '../types'

type ViewState = 'list' | 'select-type' | 'configure' | 'select-tables'

const DB_TYPE_COLORS: Record<string, string> = {
  postgresql:
    'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  postgres:
    'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  mysql:
    'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  snowflake:
    'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400',
  bigquery:
    'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  redshift: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  databricks: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  mssql:
    'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  oracle: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  csv: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
}

function formatRelativeDate(dateStr?: string) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / (1000 * 60))
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export function ConnectionsPage() {
  const { api, t, onNavigate } = useSandboxUI()
  const [viewState, setViewState] = useState<ViewState>('list')
  const [selectedHandler, setSelectedHandler] = useState<HandlerInfo | null>(
    null
  )
  const [searchQuery, setSearchQuery] = useState('')
  const [testingConnection, setTestingConnection] = useState<string | null>(
    null
  )
  const [connectionStatuses, setConnectionStatuses] = useState<
    Record<string, { connected: boolean; error?: string }>
  >({})
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [connectionToDelete, setConnectionToDelete] =
    useState<Connection | null>(null)
  const [newConnectionId, setNewConnectionId] = useState<string | null>(null)
  const [newConnectionName, setNewConnectionName] = useState<string>('')
  const [savingSelection, setSavingSelection] = useState(false)
  const [initialSelectedSchema, setInitialSelectedSchema] = useState<
    SelectedSchema | undefined
  >(undefined)

  // Connection list state (replaces react-query)
  const [connections, setConnections] = useState<Connection[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isDeleting, setIsDeleting] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const loadConnections = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await api.connections.list()
      setConnections(data)
    } catch (err) {
      console.error('Failed to load connections:', err)
    } finally {
      setIsLoading(false)
    }
  }, [api])

  useEffect(() => {
    loadConnections()
  }, [loadConnections, refreshKey])

  const refreshConnections = () => setRefreshKey((k) => k + 1)

  const handleDelete = (connection: Connection) => {
    setConnectionToDelete(connection)
    setDeleteModalOpen(true)
  }

  const confirmDelete = async () => {
    if (!connectionToDelete) return
    setIsDeleting(true)
    try {
      await api.connections.delete(connectionToDelete.id)
      setDeleteModalOpen(false)
      setConnectionToDelete(null)
      refreshConnections()
    } catch (err) {
      console.error('Failed to delete connection:', err)
    } finally {
      setIsDeleting(false)
    }
  }

  const handleTestConnection = async (connection: Connection) => {
    setTestingConnection(connection.id)
    try {
      const result = await api.connections.test({
        name: connection.name,
        db_type: connection.db_type,
        host: connection.host,
        port: connection.port,
        database: connection.database,
        username: '',
        password: '',
        ssl_enabled: false,
      })
      setConnectionStatuses((prev) => ({
        ...prev,
        [connection.id]: {
          connected: result.success,
          error: result.message,
        },
      }))
    } catch (err) {
      setConnectionStatuses((prev) => ({
        ...prev,
        [connection.id]: {
          connected: false,
          error: err instanceof Error ? err.message : 'Test failed',
        },
      }))
    } finally {
      setTestingConnection(null)
    }
  }

  const handleRowClick = (connectionId: string) => {
    onNavigate?.(`/dataset/${connectionId}`)
  }

  const handleNewConnection = () => {
    setViewState('select-type')
    setSelectedHandler(null)
  }

  const handleHandlerSelect = (handler: HandlerInfo) => {
    setSelectedHandler(handler)
    setViewState('configure')
  }

  const handleBackToList = () => {
    setViewState('list')
    setSelectedHandler(null)
  }

  const handleBackToSelector = () => {
    setViewState('select-type')
    setSelectedHandler(null)
  }

  const handleConnectionSuccess = (
    connectionId: string,
    connectionName: string
  ) => {
    setNewConnectionId(connectionId)
    setNewConnectionName(connectionName)
    setInitialSelectedSchema(undefined)
    setViewState('select-tables')
    setSelectedHandler(null)
  }

  const handleTableSelectionConfirm = async (
    selectedSchema: SelectedSchema
  ) => {
    if (!newConnectionId) return

    setSavingSelection(true)
    try {
      await api.connections.saveSelectedTables(newConnectionId, selectedSchema)
      setViewState('list')
      setNewConnectionId(null)
      setNewConnectionName('')
      refreshConnections()
    } catch (err) {
      console.error('Failed to save table selection:', err)
    } finally {
      setSavingSelection(false)
    }
  }

  const handleTableSelectionBack = () => {
    setViewState('list')
    setNewConnectionId(null)
    setNewConnectionName('')
    refreshConnections()
  }

  const handleEditTables = async (connection: Connection) => {
    setNewConnectionId(connection.id)
    setNewConnectionName(connection.name)
    try {
      const existing = await api.connections.getSelectedTables(connection.id)
      setInitialSelectedSchema(
        existing && Object.keys(existing).length > 0 ? existing : undefined
      )
    } catch {
      setInitialSelectedSchema(undefined)
    }
    setViewState('select-tables')
  }

  const filteredConnections = connections.filter((conn) => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      conn.name.toLowerCase().includes(query) ||
      conn.db_type.toLowerCase().includes(query) ||
      (conn.host && conn.host.toLowerCase().includes(query)) ||
      (conn.database && conn.database.toLowerCase().includes(query))
    )
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    )
  }

  // View: Select database type
  if (viewState === 'select-type') {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6">
          <button
            onClick={handleBackToList}
            className="inline-flex items-center text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white mb-4"
          >
            <ArrowLeft className="w-4 h-4 mr-1" />
            {t('connections.backToConnections')}
          </button>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            {t('connections.newConnection')}
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {t('connections.selectDatabaseToConnect')}
          </p>
        </div>

        <DataSourceSelector
          onSelect={handleHandlerSelect}
          selectedHandler={selectedHandler?.name}
        />
      </div>
    )
  }

  // View: Configure connection
  if (viewState === 'configure' && selectedHandler) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <ConnectionForm
          handler={selectedHandler}
          onBack={handleBackToSelector}
          onSuccess={handleConnectionSuccess}
        />
      </div>
    )
  }

  // View: Select tables after connection creation
  if (viewState === 'select-tables' && newConnectionId) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 h-[calc(100vh-4rem)]">
        <TableColumnSelector
          connectionId={newConnectionId}
          connectionName={newConnectionName}
          initialSelectedSchema={initialSelectedSchema}
          onBack={handleTableSelectionBack}
          onConfirm={handleTableSelectionConfirm}
          loading={savingSelection}
        />
      </div>
    )
  }

  // View: List connections
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              {t('connections.title')}
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              {t('connections.subtitle')}
            </p>
          </div>
          <button
            onClick={handleNewConnection}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t('connections.newConnection')}
          </button>
        </div>

        {/* Search */}
        <div className="flex items-center gap-4">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder={t('common.search') || 'Search'}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-800 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Empty state */}
        {filteredConnections.length === 0 ? (
          <div className="text-center py-12 bg-gray-50 dark:bg-gray-800/50 rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700">
            <Database className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <h4 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              {searchQuery
                ? 'No matching connections'
                : t('connections.noConnections')}
            </h4>
            <p className="text-gray-500 dark:text-gray-400 mb-6 max-w-sm mx-auto">
              {searchQuery
                ? 'Try a different search term'
                : t('connections.getStarted')}
            </p>
            {!searchQuery && (
              <button
                onClick={handleNewConnection}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
              >
                <Plus className="w-4 h-4" />
                {t('connections.newConnection')}
              </button>
            )}
          </div>
        ) : (
          /* Connections Table */
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            {/* Table header */}
            <div className="grid grid-cols-12 gap-4 px-4 py-3 bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              <div className="col-span-1"></div>
              <div className="col-span-3">
                {t('common.name') || 'Connection name'}
              </div>
              <div className="col-span-3">Source</div>
              <div className="col-span-2">Status</div>
              <div className="col-span-2">Modified</div>
              <div className="col-span-1"></div>
            </div>

            {/* Table rows */}
            {filteredConnections.map((connection) => {
              const status = connectionStatuses[connection.id]
              const isTesting = testingConnection === connection.id
              const currentlyDeleting =
                isDeleting && connectionToDelete?.id === connection.id
              const dbTypeColor =
                DB_TYPE_COLORS[connection.db_type.toLowerCase()] ||
                'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'

              return (
                <div
                  key={connection.id}
                  onClick={() => handleRowClick(connection.id)}
                  className="group grid grid-cols-12 gap-4 px-4 py-3 border-b border-gray-100 dark:border-gray-700 last:border-b-0 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-colors"
                >
                  <div className="col-span-1 flex items-center">
                    <div className="w-8 h-8 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
                      <Database className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                    </div>
                  </div>

                  <div className="col-span-3 flex items-center">
                    <div>
                      <span className="font-medium text-blue-600 dark:text-blue-400 hover:underline">
                        {connection.name}
                      </span>
                      {connection.is_default && (
                        <span className="ml-2 text-xs bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 px-2 py-0.5 rounded">
                          {t('connections.default')}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="col-span-3 flex items-center gap-2">
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded uppercase ${dbTypeColor}`}
                    >
                      {connection.db_type}
                    </span>
                    {connection.host && (
                      <span className="text-sm text-gray-500 dark:text-gray-400 truncate">
                        {connection.host}
                        {connection.port && `:${connection.port}`}
                      </span>
                    )}
                  </div>

                  <div className="col-span-2 flex items-center">
                    {isTesting ? (
                      <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Testing...
                      </span>
                    ) : status ? (
                      <span
                        className={`inline-flex items-center gap-1 text-xs ${
                          status.connected
                            ? 'text-green-600 dark:text-green-400'
                            : 'text-red-600 dark:text-red-400'
                        }`}
                      >
                        {status.connected ? (
                          <>
                            <CheckCircle className="w-3 h-3" />
                            Connected
                          </>
                        ) : (
                          <>
                            <XCircle className="w-3 h-3" />
                            Disconnected
                          </>
                        )}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">-</span>
                    )}
                  </div>

                  <div className="col-span-2 flex items-center">
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {formatRelativeDate(
                        connection.updated_at || connection.created_at
                      )}
                    </span>
                  </div>

                  <div className="col-span-1 flex items-center justify-end gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleEditTables(connection)
                      }}
                      className="p-1.5 text-gray-400 hover:text-blue-600 rounded opacity-0 group-hover:opacity-100 hover:bg-gray-100 dark:hover:bg-gray-600 transition-all"
                      title="Edit table selection"
                    >
                      <Settings2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleTestConnection(connection)
                      }}
                      disabled={isTesting || currentlyDeleting}
                      className="p-1.5 text-gray-400 hover:text-blue-600 rounded opacity-0 group-hover:opacity-100 hover:bg-gray-100 dark:hover:bg-gray-600 transition-all"
                      title="Test connection"
                    >
                      <RefreshCw
                        className={`w-4 h-4 ${isTesting ? 'animate-spin' : ''}`}
                      />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(connection)
                      }}
                      disabled={isTesting || currentlyDeleting}
                      className="p-1.5 text-gray-400 hover:text-red-500 rounded opacity-0 group-hover:opacity-100 hover:bg-gray-100 dark:hover:bg-gray-600 transition-all"
                      title={t('common.delete')}
                    >
                      {currentlyDeleting ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Trash2 className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {filteredConnections.length > 0 && (
          <div className="text-sm text-gray-500 dark:text-gray-400">
            Showing {filteredConnections.length} of {connections.length}{' '}
            connections
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {deleteModalOpen && connectionToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
              Delete Connection
            </h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              Are you sure you want to delete{' '}
              <strong>"{connectionToDelete.name}"</strong>? This action cannot
              be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => {
                  setDeleteModalOpen(false)
                  setConnectionToDelete(null)
                }}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={isDeleting}
                className="px-4 py-2 text-sm text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors disabled:opacity-50"
              >
                {isDeleting ? (
                  <Loader2 className="w-4 h-4 animate-spin inline mr-1" />
                ) : null}
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
