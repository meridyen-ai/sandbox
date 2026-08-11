/**
 * Table and Column Selector Component
 *
 * Provides a UI for selecting which tables and columns should be
 * synced to the host platform via the schema sync API.
 */

import React, { useState, useEffect, useMemo } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Search,
  Check,
  Loader2,
  Table2,
  Database,
  AlertCircle,
  CheckSquare,
  Square,
  MinusSquare,
  ArrowLeft,
  RefreshCw,
  Folder,
  X,
} from 'lucide-react'
import { useSandboxApi, useSandboxTranslation } from '../context/SandboxUIContext'
import type { TableWithColumns, SelectedSchema, SchemaData } from '../types'

/**
 * Per-instance overrides for a few controls, kept for backwards compatibility
 * with hosts that localized this component before it spoke `t()` itself.
 *
 * Prefer passing a `t` to `<SandboxUIProvider>`: it covers the whole component
 * rather than these twelve strings. Anything set here still wins over `t()`,
 * and anything left out falls through to `t()` — so the two can be mixed.
 */
export interface TableColumnSelectorLabels {
  /**
   * The small line above the title. Defaults to "Create connection", which is
   * wrong when the host mounts this to EDIT an existing connection — pass the
   * right wording for the flow you are in.
   */
  eyebrow?: string
  selectAll?: string
  clearSelection?: string
  /** `{count}` is replaced with the total number of columns. */
  showAllColumns?: string
  /** `{count}` is replaced with the total number of tables. */
  showAllTables?: string
  showFewerColumns?: string
  /** `{count}` is replaced with the number of missing tables. */
  missingTablesTitle?: string
  missingTablesHint?: string
  removeAll?: string
  remove?: string
  removeMissingConfirmTitle?: string
  /** `{count}` is replaced with how many tables are being removed. */
  removeMissingConfirmBody?: string
  cancel?: string
}

interface TableColumnSelectorProps {
  connectionId: string
  connectionName: string
  initialSelectedSchema?: SelectedSchema
  onBack: () => void
  onConfirm: (selectedSchema: SelectedSchema) => void
  loading?: boolean
  labels?: TableColumnSelectorLabels
  /**
   * Persist the removal of tables that no longer exist, immediately — without
   * waiting for the user to save the rest of their selection. Clearing dead
   * entries is a repair, not an edit, so it should not sit in a pending state
   * alongside in-progress checkbox changes. Omit it and removal stays local
   * until the user saves.
   */
  onRemoveMissingTables?: (tableKeys: string[]) => Promise<void>
}

interface SchemaGroup {
  schemaName: string
  tables: TableWithColumns[]
}

interface DatabaseGroup {
  databaseName: string
  schemas: SchemaGroup[]
}

type TabType = 'all' | 'selected'

/** How many columns the right-hand panel lists before "show all". */
const COLUMN_PREVIEW_COUNT = 20

/** How many tables the tree lists before "show all". */
const TABLE_PREVIEW_COUNT = 50

function schemaDataToTableWithColumns(data: SchemaData): TableWithColumns[] {
  const schemaName = data.schema || 'public'
  return data.tables.map((table) => ({
    schema_name: schemaName,
    table_name: table.name,
    table_type: 'table',
    full_name: `${schemaName}.${table.name}`,
    columns: table.columns.map((col) => ({
      name: col.name,
      data_type: col.type,
      nullable: col.nullable ?? true,
      default_value: null,
      sample_data: null,
    })),
  }))
}

/** Ensure every entry's `columns` is a string[] (backend may store as a dict). */
function normalizeSchema(raw: Record<string, unknown>): SelectedSchema {
  const out: SelectedSchema = {}
  for (const [key, value] of Object.entries(raw)) {
    if (key.startsWith('_')) continue
    const entry = value as { selected?: boolean; columns?: unknown }
    let cols: string[]
    if (Array.isArray(entry.columns)) {
      cols = entry.columns
    } else if (entry.columns && typeof entry.columns === 'object') {
      cols = Object.keys(entry.columns)
    } else {
      cols = []
    }
    out[key] = { selected: entry.selected ?? false, columns: cols }
  }
  return out
}

export const TableColumnSelector: React.FC<TableColumnSelectorProps> = ({
  connectionId,
  connectionName,
  initialSelectedSchema,
  onBack,
  onConfirm,
  loading: externalLoading,
  labels,
  onRemoveMissingTables,
}) => {
  const api = useSandboxApi()
  const { t } = useSandboxTranslation()
  const [schema, setSchema] = useState<TableWithColumns[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [columnSearchQuery, setColumnSearchQuery] = useState('')
  const [expandedDatabases, setExpandedDatabases] = useState<Set<string>>(
    new Set()
  )
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(
    new Set()
  )
  const [selectedTable, setSelectedTable] = useState<TableWithColumns | null>(
    null
  )
  const [selectedSchema, setSelectedSchema] = useState<SelectedSchema>(
    initialSelectedSchema ? normalizeSchema(initialSelectedSchema) : {}
  )
  const [activeTab, setActiveTab] = useState<TabType>('all')
  const [refreshing, setRefreshing] = useState(false)
  const [showAllColumns, setShowAllColumns] = useState(false)
  const [showAllTables, setShowAllTables] = useState(false)

  // Collapse back to the preview whenever a different table is opened — an
  // expanded 300-column list should not carry over to the next table.
  useEffect(() => {
    setShowAllColumns(false)
  }, [selectedTable?.full_name])

  // Likewise, a new search or tab starts from the short list.
  useEffect(() => {
    setShowAllTables(false)
  }, [searchQuery, activeTab])

  useEffect(() => {
    loadSchema()
  }, [connectionId])

  const loadSchema = async (forceRefresh?: boolean) => {
    if (forceRefresh) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError(null)
    try {
      const schemaData = await api.schema.sync(connectionId, true, 10, forceRefresh)
      const data = schemaDataToTableWithColumns(schemaData)
      setSchema(data)

      if (
        !initialSelectedSchema ||
        Object.keys(initialSelectedSchema).length === 0
      ) {
        const defaultSelection: SelectedSchema = {}
        data.forEach((table) => {
          defaultSelection[table.full_name] = {
            selected: false,
            columns: [],
          }
        })
        setSelectedSchema(defaultSelection)
      }

      if (data.length > 0) {
        const firstTable = data[0]
        const dbName = connectionName
        const schemaKey = `${dbName}.${firstTable.schema_name}`
        setExpandedDatabases(new Set([dbName]))
        setExpandedSchemas(new Set([schemaKey]))
        setSelectedTable(firstTable)
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t('tableSelector.errors.schemaLoadFailed')
      )
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const tablesWithSelections = useMemo(() => {
    return schema.filter((table) => {
      const selection = selectedSchema[table.full_name]
      return selection && selection.columns.length > 0
    })
  }, [schema, selectedSchema])

  const groupedTables = useMemo((): DatabaseGroup[] => {
    const schemaMap = new Map<string, TableWithColumns[]>()

    const baseTables =
      activeTab === 'selected' ? tablesWithSelections : schema

    const filteredSchema = searchQuery
      ? baseTables.filter(
          (table) =>
            table.table_name
              .toLowerCase()
              .includes(searchQuery.toLowerCase()) ||
            table.schema_name
              .toLowerCase()
              .includes(searchQuery.toLowerCase())
        )
      : baseTables

    filteredSchema.forEach((table) => {
      const key = table.schema_name || 'public'
      if (!schemaMap.has(key)) {
        schemaMap.set(key, [])
      }
      schemaMap.get(key)!.push(table)
    })

    const schemas: SchemaGroup[] = Array.from(schemaMap.entries()).map(
      ([schemaName, tables]) => ({
        schemaName,
        tables: tables.sort((a, b) =>
          a.table_name.localeCompare(b.table_name)
        ),
      })
    )

    return [
      {
        databaseName: connectionName,
        schemas: schemas.sort((a, b) =>
          a.schemaName.localeCompare(b.schemaName)
        ),
      },
    ]
  }, [schema, connectionName, searchQuery, activeTab, tablesWithSelections])

  /**
   * The tables the tree is actually showing right now — already narrowed by the
   * active tab and the search box. Bulk actions work on exactly this set: a
   * "select all" that also picked up tables filtered out by the user's search
   * would be a trap, since nothing on screen would show what it did.
   */
  const visibleTables = useMemo(
    () => groupedTables.flatMap((db) => db.schemas.flatMap((s) => s.tables)),
    [groupedTables]
  )

  /**
   * Keys of the tables the tree actually renders. Capped until the user asks
   * for the rest — a few hundred rows is a scroll, not a browse. Bulk
   * select/clear deliberately stay on the whole filtered set (`visibleTables`),
   * because "search, then select all" should act on the search, not on however
   * many rows happen to be painted.
   */
  const renderedTableKeys = useMemo(() => {
    if (showAllTables || visibleTables.length <= TABLE_PREVIEW_COUNT) return null
    return new Set(
      visibleTables.slice(0, TABLE_PREVIEW_COUNT).map((t) => t.full_name)
    )
  }, [visibleTables, showAllTables])

  const visibleAllSelected = useMemo(
    () =>
      visibleTables.length > 0 &&
      visibleTables.every(
        (table) =>
          selectedSchema[table.full_name]?.columns.length ===
          table.columns.length
      ),
    [visibleTables, selectedSchema]
  )

  const visibleAnySelected = useMemo(
    () =>
      visibleTables.some(
        (table) => (selectedSchema[table.full_name]?.columns.length || 0) > 0
      ),
    [visibleTables, selectedSchema]
  )

  const handleSelectAllVisible = () => {
    setSelectedSchema((prev) => {
      const next = { ...prev }
      visibleTables.forEach((table) => {
        next[table.full_name] = {
          selected: true,
          columns: table.columns.map((c) => c.name),
        }
      })
      return next
    })
  }

  const handleClearVisible = () => {
    setSelectedSchema((prev) => {
      const next = { ...prev }
      visibleTables.forEach((table) => {
        next[table.full_name] = { selected: false, columns: [] }
      })
      return next
    })
  }

  /**
   * Selections pointing at tables the database no longer has — typically a view
   * that was dropped and recreated under another name.
   *
   * These used to be invisible: the tree only lists tables present in the live
   * schema, so a stale entry could not be seen or removed, yet it still rode
   * along in every save and was handed to the AI as a queryable table. Surfacing
   * them is the only way the user can clear them.
   *
   * Only meaningful once a schema has actually loaded — against an empty schema
   * every selection would look missing.
   */
  const missingSelections = useMemo(() => {
    if (schema.length === 0) return []
    const known = new Set(schema.map((t) => t.full_name))
    return Object.entries(selectedSchema)
      .filter(
        ([key, sel]) =>
          !key.startsWith('_') &&
          sel?.selected &&
          (sel.columns?.length || 0) > 0 &&
          !known.has(key)
      )
      .map(([key]) => key)
      .sort((a, b) => a.localeCompare(b))
  }, [schema, selectedSchema])

  /**
   * Whether this connection arrived with a selection. Saving an empty selection
   * is meaningless when creating a connection, but it is exactly what removing
   * the last stale table means when editing one — so the "pick something first"
   * guard must not apply there.
   */
  const hadInitialSelection = useMemo(
    () =>
      Object.entries(initialSelectedSchema || {}).some(
        ([key, value]) =>
          !key.startsWith('_') &&
          Boolean((value as { selected?: boolean } | undefined)?.selected)
      ),
    [initialSelectedSchema]
  )

  // Keys awaiting confirmation in the removal dialog; null = dialog closed.
  const [pendingRemoval, setPendingRemoval] = useState<string[] | null>(null)
  const [removing, setRemoving] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const confirmRemoval = async () => {
    if (!pendingRemoval) return
    const keys = pendingRemoval
    setRemoveError(null)

    if (onRemoveMissingTables) {
      setRemoving(true)
      try {
        await onRemoveMissingTables(keys)
      } catch (err) {
        setRemoveError(
          err instanceof Error ? err.message : t('tableSelector.errors.removeFailed')
        )
        setRemoving(false)
        return
      }
      setRemoving(false)
    }

    // Drop them locally too, whether they were persisted just now or will be
    // written with the rest of the selection on save.
    setSelectedSchema((prev) => {
      const next = { ...prev }
      keys.forEach((key) => delete next[key])
      return next
    })
    setPendingRemoval(null)
  }

  const selectionStats = useMemo(() => {
    const known = new Set(schema.map((t) => t.full_name))
    const totalTables = schema.length
    const entries = Object.entries(selectedSchema).filter(
      ([key, s]) => !key.startsWith('_') && s.selected && s.columns.length > 0
    )
    // Count only what the tree can actually show, so the tab badge and the list
    // below it can never disagree.
    const selectedTables =
      schema.length === 0
        ? entries.length
        : entries.filter(([key]) => known.has(key)).length
    const totalColumns = schema.reduce((sum, t) => sum + t.columns.length, 0)
    const selectedColumns = entries.reduce(
      (sum, [, s]) => sum + (s.columns?.length || 0),
      0
    )
    return { totalTables, selectedTables, totalColumns, selectedColumns }
  }, [schema, selectedSchema])

  const toggleDatabase = (dbName: string) => {
    setExpandedDatabases((prev) => {
      const next = new Set(prev)
      if (next.has(dbName)) {
        next.delete(dbName)
      } else {
        next.add(dbName)
      }
      return next
    })
  }

  const toggleSchema = (schemaKey: string) => {
    setExpandedSchemas((prev) => {
      const next = new Set(prev)
      if (next.has(schemaKey)) {
        next.delete(schemaKey)
      } else {
        next.add(schemaKey)
      }
      return next
    })
  }

  const handleToggleColumn = (columnName: string) => {
    if (!selectedTable) return

    setSelectedSchema((prev) => {
      const tableKey = selectedTable.full_name
      const current = prev[tableKey] || { selected: false, columns: [] }
      const columns = current.columns.includes(columnName)
        ? current.columns.filter((c) => c !== columnName)
        : [...current.columns, columnName]

      return {
        ...prev,
        [tableKey]: {
          selected: columns.length > 0,
          columns,
        },
      }
    })
  }

  const handleToggleAllColumns = () => {
    if (!selectedTable) return

    const currentSelection = selectedSchema[selectedTable.full_name]
    const allSelected =
      currentSelection?.columns.length === selectedTable.columns.length

    if (allSelected) {
      setSelectedSchema((prev) => ({
        ...prev,
        [selectedTable.full_name]: {
          selected: false,
          columns: [],
        },
      }))
    } else {
      setSelectedSchema((prev) => ({
        ...prev,
        [selectedTable.full_name]: {
          selected: true,
          columns: selectedTable.columns.map((c) => c.name),
        },
      }))
    }
  }

  const handleToggleTableColumns = (
    table: TableWithColumns,
    e: React.MouseEvent
  ) => {
    e.stopPropagation()

    const currentSelection = selectedSchema[table.full_name]
    const allSelected =
      currentSelection?.columns.length === table.columns.length

    if (allSelected) {
      setSelectedSchema((prev) => ({
        ...prev,
        [table.full_name]: {
          selected: false,
          columns: [],
        },
      }))
    } else {
      setSelectedSchema((prev) => ({
        ...prev,
        [table.full_name]: {
          selected: true,
          columns: table.columns.map((c) => c.name),
        },
      }))
    }
  }

  const getTableSelectionState = (
    table: TableWithColumns
  ): 'all' | 'some' | 'none' => {
    const selection = selectedSchema[table.full_name]
    if (!selection || selection.columns.length === 0) return 'none'
    if (selection.columns.length === table.columns.length) return 'all'
    return 'some'
  }

  const getHeaderCheckboxState = (): 'all' | 'some' | 'none' => {
    if (!selectedTable) return 'none'
    const selection = selectedSchema[selectedTable.full_name]
    if (!selection || selection.columns.length === 0) return 'none'
    if (selection.columns.length === selectedTable.columns.length) return 'all'
    return 'some'
  }

  const handleConfirm = () => {
    const cleanedSchema: SelectedSchema = {}
    Object.entries(selectedSchema).forEach(([key, value]) => {
      if (value.selected && value.columns.length > 0) {
        cleanedSchema[key] = value
      }
    })
    onConfirm(cleanedSchema)
  }

  const filteredColumns = useMemo(() => {
    if (!selectedTable) return []
    if (!columnSearchQuery) return selectedTable.columns
    const query = columnSearchQuery.toLowerCase()
    return selectedTable.columns.filter(
      (col) =>
        col.name.toLowerCase().includes(query) ||
        col.data_type.toLowerCase().includes(query)
    )
  }, [selectedTable, columnSearchQuery])

  /**
   * Wide tables (300+ columns) made this list unusable — a wall of rows to
   * scroll past before reaching anything else. Show a screenful by default and
   * let the user ask for the rest.
   */
  const visibleColumns = showAllColumns
    ? filteredColumns
    : filteredColumns.slice(0, COLUMN_PREVIEW_COUNT)

  const hiddenColumnCount = filteredColumns.length - visibleColumns.length

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Loader2 className="w-10 h-10 animate-spin text-blue-500 mb-4" />
        <p className="text-gray-500 dark:text-gray-400">
          {t('tableSelector.loadingSchema')}
        </p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <AlertCircle className="w-10 h-10 text-red-500 mb-4" />
        <p className="text-red-600 dark:text-red-400 mb-4">{error}</p>
        <button
          // Not `onClick={loadSchema}`: that handed the click event to the
          // forceRefresh parameter, which broke the dts build (and only
          // happened to do the right thing because an event object is truthy).
          onClick={() => loadSchema(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium"
        >
          <RefreshCw className="w-4 h-4" />
          {t('common.retry')}
        </button>
      </div>
    )
  }

  const currentTableSelection = selectedTable
    ? selectedSchema[selectedTable.full_name]
    : null
  const selectedColumnNames = currentTableSelection?.columns || []
  const headerCheckboxState = getHeaderCheckboxState()

  return (
    <div className="flex flex-col h-full">
      {/* Header — the actions live up here rather than under the lists, which
          on a wide schema meant scrolling past hundreds of rows to save. */}
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">
            {labels?.eyebrow ?? t('tableSelector.eyebrow')}
          </p>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
            {t('tableSelector.title')}
          </h2>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={onBack}
            className="flex items-center gap-2 px-3 py-2 text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 text-sm font-medium transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            {t('common.back')}
          </button>
          <button
            onClick={handleConfirm}
            disabled={
              (selectionStats.selectedColumns === 0 && !hadInitialSelection) ||
              externalLoading
            }
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {externalLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Check className="w-4 h-4" />
            )}
            {t('tableSelector.saveSelection')}
          </button>
        </div>
      </div>

      {/* Main Content - Two Column Layout */}
      <div className="flex-1 flex gap-4 min-h-0 overflow-hidden">
        {/* Left Sidebar - Tree View */}
        <div className="w-72 flex flex-col border border-gray-200 dark:border-gray-700 rounded-xl bg-white dark:bg-gray-800 overflow-hidden">
          {/* Connection Header */}
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-blue-600" />
              <span className="font-medium text-gray-900 dark:text-white text-sm truncate flex-1">
                {connectionName}
              </span>
              <button
                onClick={() => loadSchema(true)}
                disabled={refreshing}
                className="p-1 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition-colors disabled:opacity-50"
                title={t('tableSelector.reloadSchema')}
              >
                <RefreshCw className={`w-4 h-4 text-gray-500 hover:text-blue-600 ${refreshing ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-200 dark:border-gray-700">
            <button
              onClick={() => setActiveTab('all')}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
                activeTab === 'all'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              {t('tableSelector.tabAll')}
            </button>
            <button
              onClick={() => setActiveTab('selected')}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors flex items-center justify-center gap-1 ${
                activeTab === 'selected'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              {t('tableSelector.tabSelected')}
              {selectionStats.selectedTables > 0 && (
                <span className="bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs px-1.5 py-0.5 rounded-full">
                  {selectionStats.selectedTables}
                </span>
              )}
            </button>
          </div>

          {/* Search */}
          <div className="p-3 border-b border-gray-200 dark:border-gray-700">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('tableSelector.searchTables')}
                className="w-full pl-9 pr-3 py-2 text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            {/* Bulk actions over the tables currently listed below */}
            <div className="flex items-center gap-2 mt-2">
              <button
                type="button"
                onClick={handleSelectAllVisible}
                disabled={visibleTables.length === 0 || visibleAllSelected}
                className="px-2 py-1 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded transition-colors disabled:opacity-40 disabled:hover:bg-transparent"
              >
                {labels?.selectAll ?? t('tableSelector.selectAll')}
              </button>
              <button
                type="button"
                onClick={handleClearVisible}
                disabled={visibleTables.length === 0 || !visibleAnySelected}
                className="px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors disabled:opacity-40 disabled:hover:bg-transparent"
              >
                {labels?.clearSelection ?? t('tableSelector.clearSelection')}
              </button>
              {/* Wordless on purpose: needs no translation */}
              <span className="ml-auto text-xs text-gray-400 tabular-nums">
                {selectionStats.selectedTables}/{selectionStats.totalTables}
              </span>
            </div>
          </div>

          {/* Tree View */}
          <div className="flex-1 overflow-y-auto">
            {/* Selections whose table is gone from the database. Shown on both
                tabs and above the tree: it is a problem to resolve, not a
                branch to browse, and it vanishes once cleared. */}
            {missingSelections.length > 0 && (
              <div className="border-b border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-900/10">
                <div className="flex items-center gap-2 px-3 py-2">
                  <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-500 shrink-0" />
                  <span className="text-xs font-medium text-amber-800 dark:text-amber-300 flex-1">
                    {(
                      labels?.missingTablesTitle ??
                      t('tableSelector.missingTablesTitle')
                    ).replace('{count}', String(missingSelections.length))}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPendingRemoval(missingSelections)}
                    className="text-xs font-medium text-amber-700 dark:text-amber-400 hover:underline shrink-0"
                  >
                    {labels?.removeAll ?? t('tableSelector.removeAll')}
                  </button>
                </div>
                <p className="px-3 pb-2 text-[11px] text-amber-700/80 dark:text-amber-400/70">
                  {labels?.missingTablesHint ?? t('tableSelector.missingTablesHint')}
                </p>
                {missingSelections.map((tableKey) => (
                  <div
                    key={tableKey}
                    className="flex items-center gap-2 px-3 py-1 pl-7 hover:bg-amber-100/60 dark:hover:bg-amber-900/20"
                  >
                    <Table2 className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                    <span
                      className="text-xs text-amber-900 dark:text-amber-200 line-through truncate flex-1"
                      title={tableKey}
                    >
                      {tableKey}
                    </span>
                    <button
                      type="button"
                      onClick={() => setPendingRemoval([tableKey])}
                      title={labels?.remove ?? t('tableSelector.remove')}
                      className="p-0.5 rounded hover:bg-amber-200 dark:hover:bg-amber-800/40 shrink-0"
                    >
                      <X className="w-3.5 h-3.5 text-amber-700 dark:text-amber-400" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {groupedTables.map((db) => (
              <div key={db.databaseName}>
                <div
                  className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                  onClick={() => toggleDatabase(db.databaseName)}
                >
                  {expandedDatabases.has(db.databaseName) ? (
                    <ChevronDown className="w-4 h-4 text-gray-400" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-gray-400" />
                  )}
                  <Database className="w-4 h-4 text-gray-500" />
                  <span className="text-sm text-gray-700 dark:text-gray-300 truncate">
                    {db.databaseName}
                  </span>
                </div>

                {expandedDatabases.has(db.databaseName) &&
                  db.schemas.map((schemaGroup) => {
                    const schemaKey = `${db.databaseName}.${schemaGroup.schemaName}`
                    return (
                      <div key={schemaKey}>
                        <div
                          className="flex items-center gap-2 px-3 py-1.5 pl-7 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                          onClick={() => toggleSchema(schemaKey)}
                        >
                          {expandedSchemas.has(schemaKey) ? (
                            <ChevronDown className="w-4 h-4 text-gray-400" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-gray-400" />
                          )}
                          <Folder className="w-4 h-4 text-yellow-500" />
                          <span className="text-sm text-gray-700 dark:text-gray-300 truncate">
                            {schemaGroup.schemaName}
                          </span>
                        </div>

                        {expandedSchemas.has(schemaKey) &&
                          schemaGroup.tables
                            .filter(
                              (t) =>
                                !renderedTableKeys ||
                                renderedTableKeys.has(t.full_name)
                            )
                            .map((table) => {
                            const isSelected =
                              selectedTable?.full_name === table.full_name
                            const selectionState =
                              getTableSelectionState(table)

                            return (
                              <div
                                key={table.full_name}
                                className={`flex items-center gap-2 px-3 py-1 pl-12 cursor-pointer transition-colors ${
                                  isSelected
                                    ? 'bg-blue-50 dark:bg-blue-900/20 border-l-2 border-blue-600'
                                    : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                                }`}
                                onClick={() => setSelectedTable(table)}
                              >
                                <div
                                  onClick={(e) =>
                                    handleToggleTableColumns(table, e)
                                  }
                                  className="flex-shrink-0 hover:scale-110 transition-transform"
                                >
                                  {selectionState === 'all' && (
                                    <CheckSquare className="w-3.5 h-3.5 text-blue-600" />
                                  )}
                                  {selectionState === 'some' && (
                                    <MinusSquare className="w-3.5 h-3.5 text-blue-600" />
                                  )}
                                  {selectionState === 'none' && (
                                    <Square className="w-3.5 h-3.5 text-gray-400 hover:text-blue-500" />
                                  )}
                                </div>
                                <Table2 className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                                <span
                                  className={`text-xs truncate ${
                                    isSelected
                                      ? 'text-blue-700 dark:text-blue-300 font-medium'
                                      : 'text-gray-700 dark:text-gray-300'
                                  }`}
                                  title={table.table_name}
                                >
                                  {table.table_name}
                                </span>
                              </div>
                            )
                          })}
                      </div>
                    )
                  })}
              </div>
            ))}

            {activeTab === 'selected' &&
              tablesWithSelections.length === 0 && (
                <div className="flex flex-col items-center justify-center py-8 text-center px-4">
                  <Square className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {t('tableSelector.noTablesSelected')}
                  </p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                    {t('tableSelector.noTablesSelectedHint')}
                  </p>
                </div>
              )}

            {activeTab === 'all' &&
              groupedTables[0]?.schemas.length === 0 && (
                <div className="flex flex-col items-center justify-center py-8 text-center px-4">
                  <Table2 className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {searchQuery
                      ? t('tableSelector.noTablesMatch')
                      : t('tableSelector.noTablesFound')}
                  </p>
                </div>
              )}

            {visibleTables.length > TABLE_PREVIEW_COUNT && (
              <button
                type="button"
                onClick={() => setShowAllTables((v) => !v)}
                className="w-full px-3 py-2 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 border-t border-gray-100 dark:border-gray-700 transition-colors"
              >
                {showAllTables
                  ? labels?.showFewerColumns ?? t('tableSelector.showFewer')
                  : (labels?.showAllTables ?? t('tableSelector.showAllTables')).replace(
                      '{count}',
                      String(visibleTables.length)
                    )}
              </button>
            )}
          </div>
        </div>

        {/* Right Panel - Column Details */}
        <div className="flex-1 flex flex-col border border-gray-200 dark:border-gray-700 rounded-xl bg-white dark:bg-gray-800 overflow-hidden">
          {selectedTable ? (
            <>
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                <h3 className="font-semibold text-gray-900 dark:text-white">
                  {selectedTable.table_name}
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {t('tableSelector.columnsSelected')
                    .replace('{selected}', String(selectedColumnNames.length))
                    .replace('{total}', String(selectedTable.columns.length))}
                </p>
              </div>

              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    value={columnSearchQuery}
                    onChange={(e) => setColumnSearchQuery(e.target.value)}
                    placeholder={t('tableSelector.searchColumns')}
                    className="w-full pl-9 pr-3 py-2 text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
              </div>

              <div className="grid grid-cols-12 gap-2 px-4 py-2 border-b border-gray-200 dark:border-gray-700 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider bg-gray-50 dark:bg-gray-900">
                <div
                  className="col-span-1 flex items-center cursor-pointer"
                  onClick={handleToggleAllColumns}
                >
                  {headerCheckboxState === 'all' && (
                    <CheckSquare className="w-4 h-4 text-blue-600" />
                  )}
                  {headerCheckboxState === 'some' && (
                    <MinusSquare className="w-4 h-4 text-blue-600" />
                  )}
                  {headerCheckboxState === 'none' && (
                    <Square className="w-4 h-4 text-gray-400 hover:text-gray-600" />
                  )}
                </div>
                <div className="col-span-5">
                  {t('tableSelector.colColumnName')
                    .replace('{selected}', String(selectedColumnNames.length))
                    .replace('{total}', String(selectedTable.columns.length))}
                </div>
                <div className="col-span-3">{t('tableSelector.colDataType')}</div>
                <div className="col-span-3">{t('tableSelector.colNullable')}</div>
              </div>

              <div className="flex-1 overflow-y-auto">
                {visibleColumns.map((column) => {
                  const isSelected = selectedColumnNames.includes(column.name)
                  return (
                    <div
                      key={column.name}
                      className={`grid grid-cols-12 gap-2 px-4 py-1 border-b border-gray-100 dark:border-gray-700 cursor-pointer transition-colors ${
                        isSelected
                          ? 'bg-blue-50 dark:bg-blue-900/10'
                          : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                      }`}
                      onClick={() => handleToggleColumn(column.name)}
                    >
                      <div className="col-span-1 flex items-center">
                        {isSelected ? (
                          <CheckSquare className="w-3.5 h-3.5 text-blue-600" />
                        ) : (
                          <Square className="w-3.5 h-3.5 text-gray-400" />
                        )}
                      </div>
                      <div className="col-span-5 flex items-center gap-2 min-w-0">
                        <span
                          className={`text-xs truncate ${
                            isSelected
                              ? 'text-gray-900 dark:text-white font-medium'
                              : 'text-gray-600 dark:text-gray-400'
                          }`}
                          title={column.name}
                        >
                          {column.name}
                        </span>
                      </div>
                      <div className="col-span-3 flex items-center min-w-0">
                        <span className="text-[11px] font-mono px-1.5 py-0 bg-gray-200 dark:bg-gray-700 rounded text-gray-600 dark:text-gray-400 uppercase truncate">
                          {column.data_type}
                        </span>
                      </div>
                      <div className="col-span-3 flex items-center">
                        <span
                          className={`text-xs ${column.nullable ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}`}
                        >
                          {column.nullable ? t('common.yes') : t('common.no')}
                        </span>
                      </div>
                    </div>
                  )
                })}

                {(hiddenColumnCount > 0 || showAllColumns) &&
                  filteredColumns.length > COLUMN_PREVIEW_COUNT && (
                    <button
                      type="button"
                      onClick={() => setShowAllColumns((v) => !v)}
                      className="w-full px-4 py-2 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
                    >
                      {showAllColumns
                        ? labels?.showFewerColumns ?? t('tableSelector.showFewer')
                        : (
                            labels?.showAllColumns ?? t('tableSelector.showAllColumns')
                          ).replace('{count}', String(filteredColumns.length))}
                    </button>
                  )}

                {filteredColumns.length === 0 && columnSearchQuery && (
                  <div className="flex flex-col items-center justify-center py-8 text-center">
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {t('tableSelector.noColumnsMatch')}
                    </p>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Table2 className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
                <p className="text-gray-500 dark:text-gray-400">
                  {t('tableSelector.selectTableHint')}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Confirm removing selections whose table is gone. Destructive and
          applied immediately, so it asks first. */}
      {pendingRemoval && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => !removing && setPendingRemoval(null)}
        >
          <div
            className="w-full max-w-md rounded-xl bg-white dark:bg-gray-800 shadow-xl border border-gray-200 dark:border-gray-700 p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                  {labels?.removeMissingConfirmTitle ??
                    t('tableSelector.removeMissingConfirmTitle')}
                </h3>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  {(
                    labels?.removeMissingConfirmBody ??
                    t('tableSelector.removeMissingConfirmBody')
                  ).replace('{count}', String(pendingRemoval.length))}
                </p>
                <ul className="mt-2 max-h-32 overflow-y-auto text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
                  {pendingRemoval.map((key) => (
                    <li key={key} className="truncate" title={key}>
                      {key}
                    </li>
                  ))}
                </ul>
                {removeError && (
                  <p className="mt-2 text-xs text-red-600 dark:text-red-400">
                    {removeError}
                  </p>
                )}
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingRemoval(null)}
                disabled={removing}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
              >
                {labels?.cancel ?? t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={confirmRemoval}
                disabled={removing}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors disabled:opacity-50"
              >
                {removing && <Loader2 className="w-4 h-4 animate-spin" />}
                {labels?.remove ?? t('tableSelector.remove')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
