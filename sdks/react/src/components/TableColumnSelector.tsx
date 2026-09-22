/**
 * Table and Column Selector — an object explorer for choosing which relations
 * and columns a connection exposes.
 *
 * Laid out like a database IDE's object explorer: the connection, then one
 * folder per kind of relation — Tables, Views, Stored Procedures, Custom
 * Queries — each with its own count, loaded lazily and selectable as a whole.
 * Every kind behaves the same once selected (columns, samples, SQL); the
 * folders only make the difference visible.
 */

import React, { useState, useEffect, useMemo, useRef } from 'react'
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
  X,
  Eye,
  Workflow,
  FileCode2,
  Plus,
  Pencil,
  ListChecks,
} from 'lucide-react'
import { useSandboxApi, useSandboxTranslation } from '../context/SandboxUIContext'
import { TABLE_KINDS, normalizeTableKind } from '../context/types'
import type { TableKind } from '../context/types'
import type { TableWithColumns, SelectedSchema, SchemaData } from '../types'

/**
 * Per-instance overrides for a few controls, kept for backwards compatibility
 * with hosts that localized this component before it spoke `t()` itself.
 *
 * Prefer passing a `t` to `<SandboxUIProvider>`: it covers the whole component
 * rather than these strings. Anything set here still wins over `t()`, and
 * anything left out falls through to `t()` — so the two can be mixed.
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
  /**
   * Offer "add a custom SQL query" / "add a stored procedure" on their folders.
   * The host owns the editor; after it saves, remount this component (change
   * its `key`) so the new object is listed.
   */
  onAddCustomQuery?: () => void
  onAddProcedure?: () => void
  /** Offer "Edit definition" on custom queries and procedures. */
  onEditVirtualObject?: (table: VirtualObjectRef) => void
}

/** A custom query / stored procedure row, as handed to `onEditVirtualObject`. */
export interface VirtualObjectRef {
  schemaName: string
  tableName: string
  fullName: string
  kind: TableKind
}

const KIND_ICONS: Record<TableKind, React.ComponentType<{ className?: string }>> = {
  TABLE: Table2,
  VIEW: Eye,
  PROCEDURE: Workflow,
  QUERY: FileCode2,
}

const KIND_ICON_CLASS: Record<TableKind, string> = {
  TABLE: 'text-sky-600 dark:text-sky-400',
  VIEW: 'text-teal-600 dark:text-teal-400',
  PROCEDURE: 'text-violet-600 dark:text-violet-400',
  QUERY: 'text-amber-600 dark:text-amber-400',
}

/** How many columns the right-hand panel lists before "show all". */
const COLUMN_PREVIEW_COUNT = 200

/** Rows a folder shows (non-paginated) or fetches first (paginated). */
const FOLDER_PAGE = 100

/** Rows each further "load more" fetches. Capped at 200 by the server. */
const FOLDER_PAGE_MORE = 200

const kindOf = (t: { table_type?: string }) => normalizeTableKind(t.table_type)

function schemaDataToTableWithColumns(data: SchemaData): TableWithColumns[] {
  const schemaName = data.schema || 'public'
  return data.tables.map((table) => ({
    schema_name: schemaName,
    table_name: table.name,
    table_type: table.type || 'TABLE',
    full_name: `${schemaName}.${table.name}`,
    columns: table.columns.map((col) => ({
      name: col.name,
      data_type: col.type,
      nullable: col.nullable ?? true,
      default_value: null,
      sample_data: null,
    })),
    column_count: table.columns.length,
    columns_loaded: true,
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
      // The dict shape carries a per-column `selected` flag; every key would
      // re-check columns the user deliberately unchecked.
      cols = Object.entries(entry.columns as Record<string, unknown>)
        .filter(([, meta]) =>
          meta && typeof meta === 'object'
            ? (meta as { selected?: boolean }).selected !== false
            : meta !== false
        )
        .map(([name]) => name)
    } else {
      cols = []
    }
    out[key] = { selected: entry.selected ?? false, columns: cols }
  }
  return out
}

type SelectionState = 'all' | 'some' | 'none'

const CheckIcon: React.FC<{ state: SelectionState; className?: string }> = ({ state, className = 'w-3.5 h-3.5' }) =>
  state === 'all' ? (
    <CheckSquare className={`${className} text-blue-600 dark:text-blue-400`} />
  ) : state === 'some' ? (
    <MinusSquare className={`${className} text-blue-600 dark:text-blue-400`} />
  ) : (
    <Square className={`${className} text-gray-400 dark:text-gray-500`} />
  )

interface FolderMeta {
  total: number
  loading: boolean
  loaded: boolean
}

const emptyFolders = (): Record<TableKind, FolderMeta> => ({
  TABLE: { total: 0, loading: false, loaded: false },
  VIEW: { total: 0, loading: false, loaded: false },
  PROCEDURE: { total: 0, loading: false, loaded: false },
  QUERY: { total: 0, loading: false, loaded: false },
})

export const TableColumnSelector: React.FC<TableColumnSelectorProps> = ({
  connectionId,
  connectionName,
  initialSelectedSchema,
  onBack,
  onConfirm,
  loading: externalLoading,
  labels,
  onRemoveMissingTables,
  onAddCustomQuery,
  onAddProcedure,
  onEditVirtualObject,
}) => {
  const api = useSandboxApi()
  const { t } = useSandboxTranslation()
  const [schema, setSchema] = useState<TableWithColumns[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [columnSearchQuery, setColumnSearchQuery] = useState('')
  const [selectedTable, setSelectedTable] = useState<TableWithColumns | null>(null)
  const [selectedSchema, setSelectedSchema] = useState<SelectedSchema>(
    initialSelectedSchema ? normalizeSchema(initialSelectedSchema) : {}
  )
  const [refreshing, setRefreshing] = useState(false)
  const [showAllColumns, setShowAllColumns] = useState(false)

  // Explorer state: which folders are open, which kinds are shown, and whether
  // only the current selection is listed.
  const [expandedDb, setExpandedDb] = useState(true)
  const [expandedFolders, setExpandedFolders] = useState<Set<TableKind>>(new Set(['TABLE']))
  const [hiddenKinds, setHiddenKinds] = useState<Set<TableKind>>(new Set())
  const [selectedOnly, setSelectedOnly] = useState(false)
  // Non-paginated folders cap how many rows they draw until asked for more.
  const [expandedFolderLimits, setExpandedFolderLimits] = useState<Set<TableKind>>(new Set())

  /**
   * Server-side pagination, when the host offers it.
   *
   * Without it this component asks for the whole schema up front — every table
   * with every column. With it, each folder fetches its own kind a page at a
   * time when opened, each table's `columns` stays empty until it is opened,
   * and search and the selected-only filter are resolved by the server.
   */
  const paginated = Boolean(api.schema.listTables)
  const [folders, setFolders] = useState<Record<TableKind, FolderMeta>>(emptyFolders)
  const [serverTypeCounts, setServerTypeCounts] = useState<Partial<Record<TableKind, number>>>({})
  // How many relations the connection has in total, independent of filters.
  const [serverTableTotal, setServerTableTotal] = useState(0)
  const [serverMissing, setServerMissing] = useState<string[]>([])
  // Tables whose columns are being fetched right now.
  const [loadingColumns, setLoadingColumns] = useState<Set<string>>(new Set())
  const [syncRunning, setSyncRunning] = useState(false)
  const [syncProgress, setSyncProgress] = useState<{ done: number; total: number } | null>(null)
  // Debounced copy of searchQuery — every keystroke must not be a request.
  const [committedSearch, setCommittedSearch] = useState('')
  const firstLoadDone = useRef(false)
  // Filters of the request in flight; a response for stale filters is dropped.
  const requestKey = useRef('')

  useEffect(() => {
    setShowAllColumns(false)
    setColumnSearchQuery('')
  }, [selectedTable?.full_name])

  useEffect(() => {
    loadSchema()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId])

  useEffect(() => {
    if (!paginated) return
    const id = setTimeout(() => setCommittedSearch(searchQuery), 250)
    return () => clearTimeout(id)
  }, [searchQuery, paginated])

  // Search and the selected-only filter are resolved server-side: start over.
  useEffect(() => {
    if (!paginated || !firstLoadDone.current) return
    void reloadFolders()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committedSearch, selectedOnly])

  /**
   * A sync still filling the cache. The catalog lands first, so the list is
   * already worth drawing while columns are still arriving — poll until it
   * settles rather than holding a spinner over the whole thing.
   */
  useEffect(() => {
    if (!paginated || !api.schema.status || !syncRunning) return
    const id = setInterval(async () => {
      try {
        const st = await api.schema.status!(connectionId)
        setSyncProgress({ done: st.tables_done ?? 0, total: st.tables_total ?? 0 })
        if (!st.in_progress) {
          setSyncRunning(false)
          void reloadFolders()
        }
      } catch {
        // A failed poll is not worth surfacing; the next one may succeed.
      }
    }, 2000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paginated, syncRunning, connectionId])

  const tableSummaryToRow = (row: {
    schema_name: string
    table_name: string
    full_name: string
    table_type: string
    column_count: number
  }): TableWithColumns => ({
    schema_name: row.schema_name,
    table_name: row.table_name,
    table_type: row.table_type,
    full_name: row.full_name,
    columns: [],
    column_count: row.column_count,
    columns_loaded: false,
  })

  const filterKey = () => `${committedSearch}\u0000${selectedOnly}`

  /** Fetch one page of one folder. Returns the per-kind counts it reported. */
  const loadFolder = async (
    kind: TableKind,
    offset: number
  ): Promise<Partial<Record<TableKind, number>> | null> => {
    if (!api.schema.listTables) return null
    const key = filterKey()
    setFolders((prev) => ({ ...prev, [kind]: { ...prev[kind], loading: true } }))
    try {
      const page = await api.schema.listTables(connectionId, {
        search: committedSearch || undefined,
        offset,
        limit: offset === 0 ? FOLDER_PAGE : FOLDER_PAGE_MORE,
        selectedOnly,
        types: [kind],
      })
      if (key !== requestKey.current) return null // filters changed meanwhile
      const rows = page.tables.map(tableSummaryToRow)
      setFolders((prev) => ({ ...prev, [kind]: { total: page.total, loading: false, loaded: true } }))
      if (page.type_counts) {
        setServerTypeCounts(page.type_counts)
        if (!committedSearch && !selectedOnly) {
          setServerTableTotal(
            TABLE_KINDS.reduce((sum, k) => sum + (page.type_counts?.[k] || 0), 0)
          )
        }
      }
      setSyncRunning(Boolean(page.in_progress))
      if (page.tables_total !== undefined) {
        setSyncProgress({ done: page.tables_done ?? 0, total: page.tables_total })
      }
      if (offset === 0 && Array.isArray(page.missing_selections)) {
        setServerMissing(page.missing_selections)
      }
      setSchema((prev) => {
        const byName = new Map(prev.map((row) => [row.full_name, row]))
        rows.forEach((row) => {
          if (!byName.has(row.full_name)) byName.set(row.full_name, row)
        })
        return Array.from(byName.values())
      })
      setError(null)
      return page.type_counts ?? null
    } catch (err) {
      setFolders((prev) => ({ ...prev, [kind]: { ...prev[kind], loading: false } }))
      setError(err instanceof Error ? err.message : t('tableSelector.errors.schemaLoadFailed'))
      return null
    }
  }

  /** Start the explorer over for the current filters. */
  const reloadFolders = async () => {
    requestKey.current = filterKey()
    setSchema([])
    setFolders(emptyFolders())
    setLoading(!firstLoadDone.current)
    try {
      // The first folder also reports every kind's count, which decides what
      // opens by default: the first kind that has anything in it.
      const counts = await loadFolder('TABLE', 0)
      let open = expandedFolders
      if (!firstLoadDone.current && counts) {
        const first = TABLE_KINDS.find((k) => (counts[k] || 0) > 0)
        open = new Set(first ? [first] : ['TABLE'])
        setExpandedFolders(open)
      }
      await Promise.all(
        Array.from(open)
          .filter((k) => k !== 'TABLE')
          .map((k) => loadFolder(k, 0))
      )
    } finally {
      firstLoadDone.current = true
      setLoading(false)
    }
  }

  /**
   * Make sure these tables have their columns loaded, and hand them back.
   * Batched at 25, the server's per-request cap.
   */
  const ensureColumns = async (tables: TableWithColumns[]): Promise<TableWithColumns[]> => {
    if (!paginated || !api.schema.getTableColumns) return tables
    const cold = tables.filter((row) => !row.columns_loaded)
    if (cold.length === 0) return tables

    setLoadingColumns((prev) => {
      const next = new Set(prev)
      cold.forEach((row) => next.add(row.full_name))
      return next
    })

    const loaded = new Map<string, TableWithColumns>()
    try {
      for (let i = 0; i < cold.length; i += 25) {
        const batch = cold.slice(i, i + 25)
        try {
          const fetched = await api.schema.getTableColumns(
            connectionId,
            batch.map((row) => row.full_name)
          )
          fetched.forEach((f) => {
            const known = batch.find((b) => b.full_name === f.full_name)
            loaded.set(f.full_name, {
              ...f,
              // The columns endpoint does not know the kind; keep the list's.
              table_type: known?.table_type ?? f.table_type,
              column_count: f.columns.length,
              columns_loaded: true,
            })
          })
        } catch (err) {
          setError(err instanceof Error ? err.message : t('tableSelector.errors.schemaLoadFailed'))
        }
      }
    } finally {
      setLoadingColumns((prev) => {
        const next = new Set(prev)
        cold.forEach((row) => next.delete(row.full_name))
        return next
      })
    }
    if (loaded.size === 0) return tables

    setSchema((prev) => prev.map((row) => loaded.get(row.full_name) ?? row))
    setSelectedTable((cur) => (cur ? loaded.get(cur.full_name) ?? cur : cur))
    return tables.map((row) => loaded.get(row.full_name) ?? row)
  }

  const openTable = (table: TableWithColumns) => {
    setSelectedTable(table)
    void ensureColumns([table])
  }

  // Open the first listed relation once there is something to show.
  useEffect(() => {
    if (selectedTable || schema.length === 0) return
    const first = [...schema].sort(
      (a, b) =>
        TABLE_KINDS.indexOf(kindOf(a)) - TABLE_KINDS.indexOf(kindOf(b)) ||
        a.table_name.localeCompare(b.table_name)
    )[0]
    if (first) openTable(first)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema, selectedTable])

  const loadSchema = async (forceRefresh?: boolean) => {
    if (paginated) {
      if (forceRefresh) {
        setRefreshing(true)
        try {
          // Re-introspect first, then re-read the (now fresh) folders.
          await api.schema.sync(connectionId, false, 10, true)
        } catch (err) {
          setError(err instanceof Error ? err.message : t('tableSelector.errors.schemaLoadFailed'))
        } finally {
          setRefreshing(false)
        }
      }
      await reloadFolders()
      return
    }

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
      if (!initialSelectedSchema || Object.keys(initialSelectedSchema).length === 0) {
        const defaultSelection: SelectedSchema = {}
        data.forEach((table) => {
          defaultSelection[table.full_name] = { selected: false, columns: [] }
        })
        setSelectedSchema(defaultSelection)
      }
      const first = TABLE_KINDS.find((k) => data.some((row) => kindOf(row) === k))
      if (first) setExpandedFolders(new Set([first]))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('tableSelector.errors.schemaLoadFailed'))
    } finally {
      firstLoadDone.current = true
      setLoading(false)
      setRefreshing(false)
    }
  }

  /** Total column count for a table, whether or not its columns are loaded. */
  const columnTotal = (table: TableWithColumns) => table.column_count ?? table.columns.length

  const isSelected = (table: TableWithColumns) =>
    (selectedSchema[table.full_name]?.columns.length || 0) > 0

  /**
   * Relations of each folder as the tree draws them. Paginated: the server
   * already applied search and selected-only. Otherwise filtered here.
   */
  const rowsByKind = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    const out: Record<TableKind, TableWithColumns[]> = { TABLE: [], VIEW: [], PROCEDURE: [], QUERY: [] }
    schema.forEach((row) => {
      if (!paginated) {
        if (selectedOnly && !isSelected(row)) return
        if (q && !row.table_name.toLowerCase().includes(q) && !row.schema_name.toLowerCase().includes(q)) {
          return
        }
      }
      out[kindOf(row)].push(row)
    })
    TABLE_KINDS.forEach((k) =>
      out[k].sort(
        (a, b) => a.schema_name.localeCompare(b.schema_name) || a.table_name.localeCompare(b.table_name)
      )
    )
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema, searchQuery, selectedOnly, paginated, selectedSchema])

  /** How many relations each folder holds under the current filters. */
  const folderTotal = (kind: TableKind): number => {
    if (!paginated) return rowsByKind[kind].length
    // Before a folder has been opened, the counts come from any response.
    return folders[kind].loaded ? folders[kind].total : serverTypeCounts[kind] || 0
  }

  /** Per-kind totals for the filter toggles (ignoring the kind toggles themselves). */
  const kindTotals = useMemo((): Record<TableKind, number> => {
    const out = { TABLE: 0, VIEW: 0, PROCEDURE: 0, QUERY: 0 } as Record<TableKind, number>
    TABLE_KINDS.forEach((k) => {
      out[k] = paginated ? serverTypeCounts[k] || 0 : rowsByKind[k].length
    })
    return out
  }, [paginated, serverTypeCounts, rowsByKind])

  // A folder is worth drawing when it has something, or when it is where new
  // objects of its kind are added.
  const addHandler = (kind: TableKind): (() => void) | undefined =>
    kind === 'PROCEDURE' ? onAddProcedure : kind === 'QUERY' ? onAddCustomQuery : undefined
  const visibleFolders = TABLE_KINDS.filter(
    (k) => !hiddenKinds.has(k) && (folderTotal(k) > 0 || Boolean(addHandler(k)))
  )

  /** Rows the tree actually shows (open folders, loaded rows, caps applied). */
  const folderRows = (kind: TableKind): TableWithColumns[] => {
    const rows = rowsByKind[kind]
    if (paginated || expandedFolderLimits.has(kind)) return rows
    return rows.slice(0, FOLDER_PAGE)
  }

  /** Every row bulk actions apply to: whatever the open folders list. */
  const visibleTables = useMemo(
    () => visibleFolders.filter((k) => expandedFolders.has(k)).flatMap((k) => rowsByKind[k]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rowsByKind, expandedFolders, hiddenKinds, schema]
  )

  const selectionStateOf = (table: TableWithColumns): SelectionState => {
    const selection = selectedSchema[table.full_name]
    if (!selection || selection.columns.length === 0) return 'none'
    if (selection.columns.length >= columnTotal(table)) return 'all'
    return 'some'
  }

  const groupState = (tables: TableWithColumns[]): SelectionState => {
    if (tables.length === 0) return 'none'
    const states = tables.map(selectionStateOf)
    if (states.every((s) => s === 'all')) return 'all'
    if (states.some((s) => s !== 'none')) return 'some'
    return 'none'
  }

  const selectTables = async (tables: TableWithColumns[]) => {
    // Selecting a table means selecting its columns by name, so they have to
    // be fetched first. Bounded by what is loaded, not by the database.
    const withCols = await ensureColumns(tables)
    setSelectedSchema((prev) => {
      const next = { ...prev }
      withCols.forEach((table) => {
        next[table.full_name] = { selected: true, columns: table.columns.map((c) => c.name) }
      })
      return next
    })
  }

  const clearTables = (tables: TableWithColumns[]) => {
    setSelectedSchema((prev) => {
      const next = { ...prev }
      tables.forEach((table) => {
        next[table.full_name] = { selected: false, columns: [] }
      })
      return next
    })
  }

  const toggleGroup = (tables: TableWithColumns[]) =>
    groupState(tables) === 'all' ? clearTables(tables) : void selectTables(tables)

  /**
   * Selections pointing at relations the database no longer has — typically a
   * view that was dropped and recreated under another name. They are shown so
   * the user can clear them; left alone they would still be handed to the AI.
   */
  const missingSelections = useMemo(() => {
    if (paginated) return serverMissing
    if (schema.length === 0) return []
    const known = new Set(schema.map((row) => row.full_name))
    return Object.entries(selectedSchema)
      .filter(
        ([key, sel]) =>
          !key.startsWith('_') && sel?.selected && (sel.columns?.length || 0) > 0 && !known.has(key)
      )
      .map(([key]) => key)
      .sort((a, b) => a.localeCompare(b))
  }, [schema, selectedSchema, paginated, serverMissing])

  /**
   * Whether this connection arrived with a selection. Saving an empty selection
   * is meaningless when creating a connection, but it is exactly what removing
   * the last stale table means when editing one.
   */
  const hadInitialSelection = useMemo(
    () =>
      Object.entries(initialSelectedSchema || {}).some(
        ([key, value]) =>
          !key.startsWith('_') && Boolean((value as { selected?: boolean } | undefined)?.selected)
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
        setRemoveError(err instanceof Error ? err.message : t('tableSelector.errors.removeFailed'))
        setRemoving(false)
        return
      }
      setRemoving(false)
    }

    setSelectedSchema((prev) => {
      const next = { ...prev }
      keys.forEach((key) => delete next[key])
      return next
    })
    setPendingRemoval(null)
  }

  const selectionStats = useMemo(() => {
    const entries = Object.entries(selectedSchema).filter(
      ([key, s]) => !key.startsWith('_') && s.selected && s.columns.length > 0
    )
    const selectedColumns = entries.reduce((sum, [, s]) => sum + (s.columns?.length || 0), 0)
    const gone = new Set(missingSelections)
    return {
      totalTables: paginated ? serverTableTotal : schema.length,
      selectedTables: entries.filter(([key]) => !gone.has(key)).length,
      selectedColumns,
    }
  }, [schema, selectedSchema, paginated, serverTableTotal, missingSelections])

  const toggleFolder = (kind: TableKind) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) {
        next.delete(kind)
      } else {
        next.add(kind)
        if (paginated && !folders[kind].loaded && !folders[kind].loading) void loadFolder(kind, 0)
      }
      return next
    })
  }

  const toggleKindVisible = (kind: TableKind) => {
    setHiddenKinds((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
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
      return { ...prev, [tableKey]: { selected: columns.length > 0, columns } }
    })
  }

  const handleToggleAllColumns = () => {
    if (!selectedTable) return
    const allSelected =
      (selectedSchema[selectedTable.full_name]?.columns.length || 0) >= selectedTable.columns.length &&
      selectedTable.columns.length > 0
    setSelectedSchema((prev) => ({
      ...prev,
      [selectedTable.full_name]: allSelected
        ? { selected: false, columns: [] }
        : { selected: true, columns: selectedTable.columns.map((c) => c.name) },
    }))
  }

  const handleToggleTable = async (table: TableWithColumns, e: React.MouseEvent) => {
    e.stopPropagation()
    if (selectionStateOf(table) === 'all' && columnTotal(table) > 0) {
      clearTables([table])
    } else {
      await selectTables([table])
    }
  }

  const handleConfirm = () => {
    const cleanedSchema: SelectedSchema = {}
    Object.entries(selectedSchema).forEach(([key, value]) => {
      if (value.selected && value.columns.length > 0) cleanedSchema[key] = value
    })
    onConfirm(cleanedSchema)
  }

  const filteredColumns = useMemo(() => {
    if (!selectedTable) return []
    if (!columnSearchQuery) return selectedTable.columns
    const query = columnSearchQuery.toLowerCase()
    return selectedTable.columns.filter(
      (col) => col.name.toLowerCase().includes(query) || col.data_type.toLowerCase().includes(query)
    )
  }, [selectedTable, columnSearchQuery])

  const visibleColumns = showAllColumns ? filteredColumns : filteredColumns.slice(0, COLUMN_PREVIEW_COUNT)
  const hiddenColumnCount = filteredColumns.length - visibleColumns.length

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-blue-500 mb-3" />
        <p className="text-sm text-gray-500 dark:text-gray-400">{t('tableSelector.loadingSchema')}</p>
      </div>
    )
  }

  if (error && schema.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <AlertCircle className="w-8 h-8 text-red-500 mb-3" />
        <p className="text-sm text-red-600 dark:text-red-400 mb-4">{error}</p>
        <button
          onClick={() => loadSchema(true)}
          className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium"
        >
          <RefreshCw className="w-4 h-4" />
          {t('common.retry')}
        </button>
      </div>
    )
  }

  const selectedColumnNames = selectedTable ? selectedSchema[selectedTable.full_name]?.columns || [] : []
  const headerCheckboxState: SelectionState = selectedTable ? selectionStateOf(selectedTable) : 'none'
  const selectedKind = selectedTable ? kindOf(selectedTable) : 'TABLE'
  const SelectedKindIcon = KIND_ICONS[selectedKind]
  const canEditSelected =
    Boolean(onEditVirtualObject) && (selectedKind === 'PROCEDURE' || selectedKind === 'QUERY')

  return (
    <div className="flex flex-col flex-1 h-full min-h-0 text-gray-800 dark:text-gray-200">
      {/* Title bar */}
      <div className="flex items-center gap-3 px-1 pb-2">
        <button
          onClick={onBack}
          className="p-1.5 rounded-md text-gray-500 hover:text-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 dark:hover:text-white"
          title={t('common.back')}
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wide text-gray-500 dark:text-gray-400 leading-none">
            {labels?.eyebrow ?? t('tableSelector.eyebrow')}
          </p>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white truncate">
            {t('tableSelector.title')}
            <span className="ml-2 font-normal text-gray-400">· {connectionName}</span>
          </h2>
        </div>
        <span className="ml-auto text-xs text-gray-500 dark:text-gray-400 tabular-nums">
          {selectionStats.selectedTables}/{selectionStats.totalTables}
        </span>
        <button
          onClick={handleConfirm}
          disabled={(selectionStats.selectedColumns === 0 && !hadInitialSelection) || externalLoading}
          className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 rounded-md text-sm font-medium text-white disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {externalLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
          {t('tableSelector.saveSelection')}
        </button>
      </div>

      <div className="flex-1 flex min-h-0 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden bg-white dark:bg-gray-900">
        {/* ============ Object explorer ============ */}
        <div className="w-[340px] xl:w-[380px] shrink-0 flex flex-col border-r border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-900">
          {/* Toolbar: search + filters */}
          <div className="px-2 pt-2 pb-1.5 border-b border-gray-200 dark:border-gray-700 space-y-1.5">
            <div className="flex items-center gap-1">
              <div className="relative flex-1">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t('tableSelector.searchTables')}
                  className="w-full h-7 pl-7 pr-6 text-[13px] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
              <button
                onClick={() => loadSchema(true)}
                disabled={refreshing}
                className="h-7 w-7 flex items-center justify-center rounded text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
                title={t('tableSelector.reloadSchema')}
              >
                <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
              </button>
            </div>

            {/* Kind toggles + selected-only */}
            <div className="flex flex-wrap items-center gap-1">
              {TABLE_KINDS.map((kind) => {
                const Icon = KIND_ICONS[kind]
                const shown = !hiddenKinds.has(kind)
                const count = kindTotals[kind]
                if (count === 0 && !addHandler(kind)) return null
                return (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => toggleKindVisible(kind)}
                    title={t(`tableSelector.kind.${kind}`)}
                    className={`flex items-center gap-1 h-6 px-1.5 rounded border text-[11px] transition-colors ${
                      shown
                        ? 'bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'
                        : 'border-transparent text-gray-400 line-through opacity-70'
                    }`}
                  >
                    <Icon className={`w-3 h-3 ${shown ? KIND_ICON_CLASS[kind] : 'text-gray-400'}`} />
                    <span className="tabular-nums">{count}</span>
                  </button>
                )
              })}
              <button
                type="button"
                onClick={() => setSelectedOnly((v) => !v)}
                className={`ml-auto flex items-center gap-1 h-6 px-1.5 rounded border text-[11px] ${
                  selectedOnly
                    ? 'bg-blue-600 border-blue-600 text-white'
                    : 'border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-white dark:hover:bg-gray-800'
                }`}
                title={t('tableSelector.tabSelected')}
              >
                <ListChecks className="w-3 h-3" />
                {t('tableSelector.tabSelected')}
                <span className="tabular-nums">{selectionStats.selectedTables}</span>
              </button>
            </div>

            <div className="flex items-center gap-2 text-[11px]">
              <button
                type="button"
                onClick={() => void selectTables(visibleTables)}
                disabled={visibleTables.length === 0 || groupState(visibleTables) === 'all'}
                className="text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-40 disabled:no-underline"
              >
                {labels?.selectAll ?? t('tableSelector.selectAll')}
              </button>
              <button
                type="button"
                onClick={() => clearTables(visibleTables)}
                disabled={visibleTables.length === 0 || groupState(visibleTables) === 'none'}
                className="text-gray-600 dark:text-gray-400 hover:underline disabled:opacity-40 disabled:no-underline"
              >
                {labels?.clearSelection ?? t('tableSelector.clearSelection')}
              </button>
            </div>
          </div>

          {paginated && syncRunning && (
            <div className="px-2.5 py-1.5 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-100 dark:border-blue-900/40">
              <div className="flex items-center gap-2 text-[11px] text-blue-800 dark:text-blue-200">
                <Loader2 className="w-3 h-3 animate-spin shrink-0" />
                <span className="font-medium">{t('tableSelector.syncingSchema')}</span>
                <span className="ml-auto tabular-nums">
                  {syncProgress && syncProgress.total > 0
                    ? t('tableSelector.syncingTables')
                        .replace('{done}', String(syncProgress.done))
                        .replace('{total}', String(syncProgress.total))
                    : t('tableSelector.syncingCounting')}
                </span>
              </div>
            </div>
          )}

          {error && (
            <div className="px-2.5 py-1.5 text-[11px] text-red-600 dark:text-red-400 border-b border-red-100 dark:border-red-900/40">
              {error}
            </div>
          )}

          {/* Tree */}
          <div className="flex-1 overflow-y-auto py-1 select-none text-[13px]">
            {missingSelections.length > 0 && (
              <div className="mx-1 mb-1 rounded border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-900/10">
                <div className="flex items-center gap-1.5 px-2 py-1">
                  <AlertCircle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-500 shrink-0" />
                  <span className="text-[11px] font-medium text-amber-800 dark:text-amber-300 flex-1">
                    {(labels?.missingTablesTitle ?? t('tableSelector.missingTablesTitle')).replace(
                      '{count}',
                      String(missingSelections.length)
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPendingRemoval(missingSelections)}
                    className="text-[11px] font-medium text-amber-700 dark:text-amber-400 hover:underline shrink-0"
                  >
                    {labels?.removeAll ?? t('tableSelector.removeAll')}
                  </button>
                </div>
                <p className="px-2 pb-1 text-[10px] text-amber-700/80 dark:text-amber-400/70">
                  {labels?.missingTablesHint ?? t('tableSelector.missingTablesHint')}
                </p>
                {missingSelections.map((tableKey) => (
                  <div key={tableKey} className="flex items-center gap-1.5 h-6 px-2 pl-6 hover:bg-amber-100/60 dark:hover:bg-amber-900/20">
                    <span className="text-[12px] text-amber-900 dark:text-amber-200 line-through truncate flex-1" title={tableKey}>
                      {tableKey}
                    </span>
                    <button
                      type="button"
                      onClick={() => setPendingRemoval([tableKey])}
                      title={labels?.remove ?? t('tableSelector.remove')}
                      className="p-0.5 rounded hover:bg-amber-200 dark:hover:bg-amber-800/40 shrink-0"
                    >
                      <X className="w-3 h-3 text-amber-700 dark:text-amber-400" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Connection node */}
            <div
              className="flex items-center gap-1 h-6 px-1.5 cursor-pointer hover:bg-gray-200/60 dark:hover:bg-gray-800"
              onClick={() => setExpandedDb((v) => !v)}
            >
              {expandedDb ? <ChevronDown className="w-3.5 h-3.5 text-gray-500" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-500" />}
              <Database className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
              <span className="font-medium truncate">{connectionName}</span>
            </div>

            {expandedDb &&
              visibleFolders.map((kind) => {
                const Icon = KIND_ICONS[kind]
                const open = expandedFolders.has(kind)
                const meta = folders[kind]
                const rows = folderRows(kind)
                const total = folderTotal(kind)
                const state = groupState(rowsByKind[kind])
                const onAdd = addHandler(kind)
                return (
                  <div key={kind}>
                    {/* Folder */}
                    <div
                      className="group flex items-center gap-1 h-6 pl-5 pr-1.5 cursor-pointer hover:bg-gray-200/60 dark:hover:bg-gray-800"
                      onClick={() => toggleFolder(kind)}
                    >
                      {open ? <ChevronDown className="w-3.5 h-3.5 text-gray-500" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-500" />}
                      <span
                        className="shrink-0"
                        onClick={(e) => {
                          e.stopPropagation()
                          if (rowsByKind[kind].length > 0) toggleGroup(rowsByKind[kind])
                        }}
                        title={labels?.selectAll ?? t('tableSelector.selectAll')}
                      >
                        <CheckIcon state={state} className="w-3.5 h-3.5" />
                      </span>
                      <Icon className={`w-3.5 h-3.5 ${KIND_ICON_CLASS[kind]}`} />
                      <span className="font-medium">{t(`tableSelector.kind.${kind}`)}</span>
                      <span className="text-[11px] text-gray-400 tabular-nums">{total}</span>
                      {meta.loading && <Loader2 className="w-3 h-3 animate-spin text-gray-400" />}
                      {onAdd && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            onAdd()
                          }}
                          title={t(kind === 'PROCEDURE' ? 'tableSelector.addProcedure' : 'tableSelector.addCustomQuery')}
                          className="ml-auto p-0.5 rounded text-gray-400 hover:text-blue-600 hover:bg-gray-300/60 dark:hover:bg-gray-700 opacity-70 group-hover:opacity-100"
                        >
                          <Plus className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>

                    {/* Rows */}
                    {open && (
                      <div className="relative">
                        <div className="absolute left-[27px] top-0 bottom-0 border-l border-gray-200 dark:border-gray-700" />
                        {rows.length === 0 && !meta.loading && (
                          <div className="h-6 pl-10 flex items-center text-[12px] text-gray-400 italic">
                            {searchQuery ? t('tableSelector.noTablesMatch') : t('tableSelector.noTablesFound')}
                          </div>
                        )}
                        {rows.map((table) => {
                          const active = selectedTable?.full_name === table.full_name
                          return (
                            <div
                              key={table.full_name}
                              onClick={() => openTable(table)}
                              className={`flex items-center gap-1.5 h-6 pl-9 pr-2 cursor-pointer ${
                                active
                                  ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-900 dark:text-blue-100'
                                  : 'hover:bg-gray-200/60 dark:hover:bg-gray-800'
                              }`}
                              title={table.full_name}
                            >
                              <span onClick={(e) => handleToggleTable(table, e)} className="shrink-0">
                                <CheckIcon state={selectionStateOf(table)} />
                              </span>
                              <Icon className={`w-3.5 h-3.5 shrink-0 ${KIND_ICON_CLASS[kind]}`} />
                              <span className="truncate">
                                <span className="text-gray-400">{table.schema_name}.</span>
                                {table.table_name}
                              </span>
                              {columnTotal(table) > 0 && (
                                <span className="ml-auto pl-2 text-[11px] text-gray-400 tabular-nums shrink-0">
                                  {columnTotal(table)}
                                </span>
                              )}
                            </div>
                          )
                        })}
                        {paginated && meta.loaded && rows.length < meta.total && (
                          <button
                            type="button"
                            disabled={meta.loading}
                            onClick={() => void loadFolder(kind, rows.length)}
                            className="h-6 pl-9 text-[12px] text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-50"
                          >
                            {t('tableSelector.tablesShown')
                              .replace('{shown}', String(rows.length))
                              .replace('{total}', String(meta.total))}
                            {' · '}
                            {t('tableSelector.showMoreTables')}
                          </button>
                        )}
                        {!paginated && rowsByKind[kind].length > FOLDER_PAGE && (
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedFolderLimits((prev) => {
                                const next = new Set(prev)
                                if (next.has(kind)) next.delete(kind)
                                else next.add(kind)
                                return next
                              })
                            }
                            className="h-6 pl-9 text-[12px] text-blue-600 dark:text-blue-400 hover:underline"
                          >
                            {expandedFolderLimits.has(kind)
                              ? labels?.showFewerColumns ?? t('tableSelector.showFewer')
                              : (labels?.showAllTables ?? t('tableSelector.showAllTables')).replace(
                                  '{count}',
                                  String(rowsByKind[kind].length)
                                )}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}

            {expandedDb && visibleFolders.length === 0 && (
              <div className="px-4 py-6 text-center text-[12px] text-gray-400">
                {selectedOnly ? t('tableSelector.noTablesSelected') : t('tableSelector.noTablesFound')}
              </div>
            )}
          </div>
        </div>

        {/* ============ Details ============ */}
        <div className="flex-1 min-w-0 flex flex-col">
          {selectedTable ? (
            <>
              <div className="flex items-center gap-2 px-3 h-10 border-b border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-900">
                <SelectedKindIcon className={`w-4 h-4 shrink-0 ${KIND_ICON_CLASS[selectedKind]}`} />
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                  <span className="font-normal text-gray-400">{selectedTable.schema_name}.</span>
                  {selectedTable.table_name}
                </h3>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide bg-gray-200/70 dark:bg-gray-800 text-gray-600 dark:text-gray-300 shrink-0">
                  {t(`tableSelector.kindBadge.${selectedKind}`)}
                </span>
                <span className="text-[11px] text-gray-500 dark:text-gray-400 tabular-nums shrink-0">
                  {t('tableSelector.columnsSelected')
                    .replace('{selected}', String(selectedColumnNames.length))
                    .replace('{total}', String(columnTotal(selectedTable)))}
                </span>
                {canEditSelected && (
                  <button
                    type="button"
                    onClick={() =>
                      onEditVirtualObject?.({
                        schemaName: selectedTable.schema_name,
                        tableName: selectedTable.table_name,
                        fullName: selectedTable.full_name,
                        kind: selectedKind,
                      })
                    }
                    className="ml-auto flex items-center gap-1 px-2 py-1 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded shrink-0"
                  >
                    <Pencil className="w-3 h-3" />
                    {t('tableSelector.editDefinition')}
                  </button>
                )}
                <div className={`relative w-56 shrink-0 ${canEditSelected ? '' : 'ml-auto'}`}>
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                  <input
                    type="text"
                    value={columnSearchQuery}
                    onChange={(e) => setColumnSearchQuery(e.target.value)}
                    placeholder={t('tableSelector.searchColumns')}
                    className="w-full h-7 pl-7 pr-2 text-[13px] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div className="flex-1 overflow-auto">
                <table className="w-full table-fixed text-[13px]">
                  <thead className="sticky top-0 z-10 bg-gray-50 dark:bg-gray-900 text-[11px] uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    <tr className="border-b border-gray-200 dark:border-gray-700">
                      <th className="w-9 px-3 py-1.5 text-left">
                        <span className="cursor-pointer" onClick={handleToggleAllColumns}>
                          <CheckIcon state={headerCheckboxState} />
                        </span>
                      </th>
                      <th className="px-2 py-1.5 text-left font-medium">
                        {t('tableSelector.colColumnName')
                          .replace('{selected}', String(selectedColumnNames.length))
                          .replace('{total}', String(selectedTable.columns.length))}
                      </th>
                      <th className="px-2 py-1.5 text-left font-medium w-48">{t('tableSelector.colDataType')}</th>
                      <th className="px-2 py-1.5 text-left font-medium w-24">{t('tableSelector.colNullable')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loadingColumns.has(selectedTable.full_name) && selectedTable.columns.length === 0 && (
                      <tr>
                        <td colSpan={4} className="py-10 text-center text-sm text-gray-500">
                          <Loader2 className="inline w-4 h-4 animate-spin mr-2" />
                          {t('tableSelector.loadingSchema')}
                        </td>
                      </tr>
                    )}
                    {visibleColumns.map((column) => {
                      const checked = selectedColumnNames.includes(column.name)
                      return (
                        <tr
                          key={column.name}
                          onClick={() => handleToggleColumn(column.name)}
                          className={`h-7 cursor-pointer border-b border-gray-100 dark:border-gray-800 ${
                            checked ? 'bg-blue-50/60 dark:bg-blue-900/10' : 'hover:bg-gray-50 dark:hover:bg-gray-800/60'
                          }`}
                        >
                          <td className="px-3">
                            {checked ? (
                              <CheckSquare className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                            ) : (
                              <Square className="w-3.5 h-3.5 text-gray-400" />
                            )}
                          </td>
                          <td
                            className={`px-2 truncate ${checked ? 'text-gray-900 dark:text-white' : 'text-gray-600 dark:text-gray-400'}`}
                            title={column.name}
                          >
                            {column.name}
                          </td>
                          <td className="px-2 truncate">
                            <span className="font-mono text-[11px] text-gray-500 dark:text-gray-400 uppercase">{column.data_type}</span>
                          </td>
                          <td className="px-2 text-[12px] text-gray-500">
                            {column.nullable ? t('common.yes') : t('common.no')}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>

                {(hiddenColumnCount > 0 || showAllColumns) && filteredColumns.length > COLUMN_PREVIEW_COUNT && (
                  <button
                    type="button"
                    onClick={() => setShowAllColumns((v) => !v)}
                    className="w-full py-2 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20"
                  >
                    {showAllColumns
                      ? labels?.showFewerColumns ?? t('tableSelector.showFewer')
                      : (labels?.showAllColumns ?? t('tableSelector.showAllColumns')).replace(
                          '{count}',
                          String(filteredColumns.length)
                        )}
                  </button>
                )}

                {filteredColumns.length === 0 && columnSearchQuery && (
                  <p className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
                    {t('tableSelector.noColumnsMatch')}
                  </p>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-center">
              <div>
                <Table2 className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-2" />
                <p className="text-sm text-gray-500 dark:text-gray-400">{t('tableSelector.selectTableHint')}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Confirm removing selections whose table is gone. */}
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
                  {labels?.removeMissingConfirmTitle ?? t('tableSelector.removeMissingConfirmTitle')}
                </h3>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  {(labels?.removeMissingConfirmBody ?? t('tableSelector.removeMissingConfirmBody')).replace(
                    '{count}',
                    String(pendingRemoval.length)
                  )}
                </p>
                <ul className="mt-2 max-h-32 overflow-y-auto text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
                  {pendingRemoval.map((key) => (
                    <li key={key} className="truncate" title={key}>
                      {key}
                    </li>
                  ))}
                </ul>
                {removeError && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{removeError}</p>}
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingRemoval(null)}
                disabled={removing}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg disabled:opacity-50"
              >
                {labels?.cancel ?? t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={confirmRemoval}
                disabled={removing}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg disabled:opacity-50"
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
