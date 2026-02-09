import React, { useState, useMemo, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Database,
  Loader2,
  Search,
  RefreshCw,
  Table2,
  ChevronDown,
  ChevronRight,
  Folder,
  CheckSquare,
  Square,
  MinusSquare,
  Columns,
  Save,
  Check,
} from 'lucide-react'
import { connectionsApi, schemaApi } from '../../utils/api'
import { useTranslation } from '../../hooks/useTranslation'
import type { Table, SelectedSchema } from '../../types'

type RightPanelTab = 'columns' | 'samples'
type SidebarTab = 'all' | 'selected'

export function DatasetPage() {
  const { t } = useTranslation()
  const { connectionId } = useParams<{ connectionId: string }>()
  const navigate = useNavigate()
  const [tableSearchQuery, setTableSearchQuery] = useState('')
  const [columnSearchQuery, setColumnSearchQuery] = useState('')
  const [selectedTable, setSelectedTable] = useState<Table | null>(null)
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(new Set())
  const [expandedDb, setExpandedDb] = useState(true)
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>('columns')
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('all')
  const [selectedSchema, setSelectedSchema] = useState<SelectedSchema>({})
  const [selectionLoaded, setSelectionLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  // Fetch connection info
  const { data: connections } = useQuery({
    queryKey: ['connections'],
    queryFn: connectionsApi.list,
  })

  const connection = connections?.find((c) => c.id === connectionId)

  // Fetch schema with tables
  const {
    data: schema,
    isLoading,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['schema', connectionId],
    queryFn: () => schemaApi.sync(connectionId!, true, 10),
    enabled: !!connectionId,
  })

  // Load saved table/column selections
  const { data: savedSelection, isSuccess: selectionSuccess, isError: selectionError } = useQuery({
    queryKey: ['selected-tables', connectionId],
    queryFn: () => connectionsApi.getSelectedTables(connectionId!),
    enabled: !!connectionId && !selectionLoaded,
  })

  useEffect(() => {
    if (selectionSuccess && savedSelection) {
      if (Object.keys(savedSelection).length > 0) {
        setSelectedSchema(savedSelection)
      }
      setSelectionLoaded(true)
    }
  }, [selectionSuccess, savedSelection])

  useEffect(() => {
    if (selectionError) {
      setSelectionLoaded(true)
    }
  }, [selectionError])

  // Fetch sample data for selected table
  const { data: samples, isLoading: samplesLoading } = useQuery({
    queryKey: ['table-samples', connectionId, selectedTable?.name],
    queryFn: () => schemaApi.getTableSamples(connectionId!, selectedTable!.name, 10),
    enabled: !!connectionId && !!selectedTable && rightPanelTab === 'samples',
  })

  // Tables that have at least one selected column
  const tablesWithSelections = useMemo(() => {
    const tables = schema?.tables || []
    const schemaName = schema?.schema || 'public'
    return tables.filter((t) => {
      const fullName = `${schemaName}.${t.name}`
      const sel = selectedSchema[fullName]
      return sel && sel.columns.length > 0
    })
  }, [schema, selectedSchema])

  // Group tables by schema, filtered by sidebar tab
  const groupedTables = useMemo(() => {
    const baseTables = sidebarTab === 'selected' ? tablesWithSelections : (schema?.tables || [])
    const filtered = tableSearchQuery
      ? baseTables.filter((t) =>
          t.name.toLowerCase().includes(tableSearchQuery.toLowerCase())
        )
      : baseTables

    const schemaName = schema?.schema || 'public'
    return {
      schemaName,
      tables: [...filtered].sort((a, b) => a.name.localeCompare(b.name)),
    }
  }, [schema, tableSearchQuery, sidebarTab, tablesWithSelections])

  // Auto-expand schema on first load
  useEffect(() => {
    if (schema && expandedSchemas.size === 0) {
      const schemaName = schema.schema || 'public'
      setExpandedSchemas(new Set([schemaName]))
      // Auto-select first table
      if (schema.tables.length > 0 && !selectedTable) {
        setSelectedTable(schema.tables[0])
      }
    }
  }, [schema])

  // Selection helpers
  const getTableFullName = (table: Table) => {
    const schemaName = schema?.schema || 'public'
    return `${schemaName}.${table.name}`
  }

  const getTableSelectionState = (table: Table): 'all' | 'some' | 'none' => {
    const fullName = getTableFullName(table)
    const selection = selectedSchema[fullName]
    if (!selection || selection.columns.length === 0) return 'none'
    if (selection.columns.length === table.columns.length) return 'all'
    return 'some'
  }

  const handleToggleTableColumns = (table: Table, e: React.MouseEvent) => {
    e.stopPropagation()
    const fullName = getTableFullName(table)
    const currentSelection = selectedSchema[fullName]
    const allSelected = currentSelection?.columns.length === table.columns.length

    if (allSelected) {
      setSelectedSchema((prev) => ({
        ...prev,
        [fullName]: { selected: false, columns: [] },
      }))
    } else {
      setSelectedSchema((prev) => ({
        ...prev,
        [fullName]: {
          selected: true,
          columns: table.columns.map((c) => c.name),
        },
      }))
    }
  }

  const handleToggleColumn = (columnName: string) => {
    if (!selectedTable) return
    const fullName = getTableFullName(selectedTable)

    setSelectedSchema((prev) => {
      const current = prev[fullName] || { selected: false, columns: [] }
      const columns = current.columns.includes(columnName)
        ? current.columns.filter((c) => c !== columnName)
        : [...current.columns, columnName]
      return {
        ...prev,
        [fullName]: { selected: columns.length > 0, columns },
      }
    })
  }

  const handleToggleAllColumns = () => {
    if (!selectedTable) return
    const fullName = getTableFullName(selectedTable)
    const currentSelection = selectedSchema[fullName]
    const allSelected = currentSelection?.columns.length === selectedTable.columns.length

    if (allSelected) {
      setSelectedSchema((prev) => ({
        ...prev,
        [fullName]: { selected: false, columns: [] },
      }))
    } else {
      setSelectedSchema((prev) => ({
        ...prev,
        [fullName]: {
          selected: true,
          columns: selectedTable.columns.map((c) => c.name),
        },
      }))
    }
  }

  const getHeaderCheckboxState = (): 'all' | 'some' | 'none' => {
    if (!selectedTable) return 'none'
    const fullName = getTableFullName(selectedTable)
    const selection = selectedSchema[fullName]
    if (!selection || selection.columns.length === 0) return 'none'
    if (selection.columns.length === selectedTable.columns.length) return 'all'
    return 'some'
  }

  const handleSaveSelection = async () => {
    if (!connectionId) return
    setSaving(true)
    setSaveSuccess(false)
    try {
      // Only save entries that have selections
      const cleanedSchema: SelectedSchema = {}
      Object.entries(selectedSchema).forEach(([key, value]) => {
        if (value.selected && value.columns.length > 0) {
          cleanedSchema[key] = value
        }
      })
      await connectionsApi.saveSelectedTables(connectionId, cleanedSchema)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
    } catch (err) {
      console.error('Failed to save selection:', err)
    } finally {
      setSaving(false)
    }
  }

  // Selection stats
  const selectionStats = useMemo(() => {
    const totalTables = schema?.tables.length || 0
    const selectedTables = Object.values(selectedSchema).filter(
      (s) => s.selected && s.columns.length > 0
    ).length
    const totalColumns = (schema?.tables || []).reduce(
      (sum, t) => sum + t.columns.length,
      0
    )
    const selectedColumns = Object.values(selectedSchema).reduce(
      (sum, s) => sum + (s.columns?.length || 0),
      0
    )
    return { totalTables, selectedTables, totalColumns, selectedColumns }
  }, [schema, selectedSchema])

  // Filter columns based on search
  const filteredColumns = useMemo(() => {
    if (!selectedTable) return []
    if (!columnSearchQuery) return selectedTable.columns
    const query = columnSearchQuery.toLowerCase()
    return selectedTable.columns.filter(
      (col) =>
        col.name.toLowerCase().includes(query) ||
        col.type.toLowerCase().includes(query)
    )
  }, [selectedTable, columnSearchQuery])

  const currentTableSelection = selectedTable
    ? selectedSchema[getTableFullName(selectedTable)]
    : null
  const selectedColumnNames = currentTableSelection?.columns || []
  const headerCheckboxState = getHeaderCheckboxState()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    )
  }

  if (!schema) {
    return (
      <div className="flex flex-col items-center justify-center h-full">
        <p className="text-red-500 mb-4">{t('dataset.failedToLoad')}</p>
        <button
          onClick={() => refetch()}
          className="px-4 py-2 text-sm text-blue-600 hover:text-blue-700"
        >
          Try again
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-3 flex-shrink-0">
        {/* Back button */}
        <div className="flex items-center gap-3 mb-2">
          <button
            onClick={() => navigate('/connections')}
            className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
          >
            <ArrowLeft className="w-4 h-4" />
            {t('dataset.backToConnections')}
          </button>
        </div>

        {/* Title row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-900/30">
              <Database className="w-6 h-6 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-gray-800 dark:text-white">
                {schema.connection_name}
              </h1>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {connection?.db_type || schema.db_type} @ {connection?.host || 'remote'}
                {connection?.port ? `:${connection.port}` : ''}
                {' - '}
                {schema.database}
                {schema.schema && ` / ${schema.schema}`}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Selection stats */}
            <span className="text-xs text-gray-500 dark:text-gray-400 mr-2">
              {selectionStats.selectedTables}/{selectionStats.totalTables} tables,{' '}
              {selectionStats.selectedColumns}/{selectionStats.totalColumns} columns
            </span>

            {/* Save button */}
            <button
              onClick={handleSaveSelection}
              disabled={saving}
              className={`flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                saveSuccess
                  ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                  : 'bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50'
              }`}
            >
              {saving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : saveSuccess ? (
                <Check className="w-4 h-4" />
              ) : (
                <Save className="w-4 h-4" />
              )}
              {saveSuccess ? 'Saved' : 'Save Selection'}
            </button>

            {/* Refresh button */}
            <button
              onClick={() => refetch()}
              disabled={isRefetching}
              className="flex items-center gap-2 px-3 py-1.5 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${isRefetching ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Main Content - Two Panel Layout */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Left Sidebar - Table Tree */}
        <div className="w-72 flex flex-col border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex-shrink-0">
          {/* Tabs: All / Selected */}
          <div className="flex border-b border-gray-200 dark:border-gray-700">
            <button
              onClick={() => setSidebarTab('all')}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
                sidebarTab === 'all'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setSidebarTab('selected')}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors flex items-center justify-center gap-1 ${
                sidebarTab === 'selected'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              Selected
              {tablesWithSelections.length > 0 && (
                <span className="bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs px-1.5 py-0.5 rounded-full">
                  {tablesWithSelections.length}
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
                value={tableSearchQuery}
                onChange={(e) => setTableSearchQuery(e.target.value)}
                placeholder="Search tables..."
                className="w-full pl-9 pr-3 py-2 text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          </div>

          {/* Tree View */}
          <div className="flex-1 overflow-y-auto">
            {/* Database Level */}
            <div
              className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              onClick={() => setExpandedDb(!expandedDb)}
            >
              {expandedDb ? (
                <ChevronDown className="w-4 h-4 text-gray-400" />
              ) : (
                <ChevronRight className="w-4 h-4 text-gray-400" />
              )}
              <Database className="w-4 h-4 text-gray-500" />
              <span className="text-sm text-gray-700 dark:text-gray-300 truncate font-medium">
                {schema.connection_name}
              </span>
            </div>

            {/* Schema Level */}
            {expandedDb && (
              <div>
                <div
                  className="flex items-center gap-2 px-3 py-2 pl-7 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                  onClick={() => {
                    const name = groupedTables.schemaName
                    setExpandedSchemas((prev) => {
                      const next = new Set(prev)
                      if (next.has(name)) next.delete(name)
                      else next.add(name)
                      return next
                    })
                  }}
                >
                  {expandedSchemas.has(groupedTables.schemaName) ? (
                    <ChevronDown className="w-4 h-4 text-gray-400" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-gray-400" />
                  )}
                  <Folder className="w-4 h-4 text-yellow-500" />
                  <span className="text-sm text-gray-700 dark:text-gray-300 truncate">
                    {groupedTables.schemaName}
                  </span>
                  <span className="text-xs text-gray-400 ml-auto">
                    {groupedTables.tables.length}
                  </span>
                </div>

                {/* Tables */}
                {expandedSchemas.has(groupedTables.schemaName) &&
                  groupedTables.tables.map((table) => {
                    const isSelected = selectedTable?.name === table.name
                    const selectionState = getTableSelectionState(table)

                    return (
                      <div
                        key={table.name}
                        className={`flex items-center gap-2 px-3 py-2 pl-14 cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-blue-50 dark:bg-blue-900/20 border-l-2 border-blue-600'
                            : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                        }`}
                        onClick={() => {
                          setSelectedTable(table)
                          setColumnSearchQuery('')
                          setRightPanelTab('columns')
                        }}
                      >
                        <div
                          onClick={(e) => handleToggleTableColumns(table, e)}
                          className="flex-shrink-0 hover:scale-110 transition-transform"
                        >
                          {selectionState === 'all' && (
                            <CheckSquare className="w-4 h-4 text-blue-600" />
                          )}
                          {selectionState === 'some' && (
                            <MinusSquare className="w-4 h-4 text-blue-600" />
                          )}
                          {selectionState === 'none' && (
                            <Square className="w-4 h-4 text-gray-400 hover:text-blue-500" />
                          )}
                        </div>
                        <Table2 className="w-4 h-4 text-gray-500 flex-shrink-0" />
                        <span
                          className={`text-sm truncate ${
                            isSelected
                              ? 'text-blue-700 dark:text-blue-300 font-medium'
                              : 'text-gray-700 dark:text-gray-300'
                          }`}
                        >
                          {table.name}
                        </span>
                        <span className="text-xs text-gray-400 ml-auto flex-shrink-0">
                          {table.columns.length}
                        </span>
                      </div>
                    )
                  })}

                {groupedTables.tables.length === 0 && (
                  <div className="flex flex-col items-center justify-center py-8 text-center px-4">
                    <Square className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {sidebarTab === 'selected'
                        ? 'No tables selected yet'
                        : tableSearchQuery
                          ? 'No tables match your search'
                          : 'No tables found'}
                    </p>
                    {sidebarTab === 'selected' && (
                      <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                        Select columns from the All tab
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Sidebar Footer */}
          <div className="px-3 py-2 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-400">
            {schema.tables.length} tables total
          </div>
        </div>

        {/* Right Panel - Table Detail */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {selectedTable ? (
            <>
              {/* Tabs */}
              <div className="flex items-center border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4">
                <div className="flex items-center gap-2 mr-4 py-3">
                  <Table2 className="w-4 h-4 text-gray-500" />
                  <span className="font-semibold text-gray-900 dark:text-white text-sm">
                    {selectedTable.name}
                  </span>
                  <span className="text-xs text-gray-400">
                    ({selectedColumnNames.length}/{selectedTable.columns.length} selected)
                  </span>
                </div>

                <nav className="flex space-x-4 ml-auto" aria-label="Tabs">
                  <button
                    onClick={() => setRightPanelTab('columns')}
                    className={`py-3 px-2 border-b-2 font-medium text-sm transition-colors ${
                      rightPanelTab === 'columns'
                        ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400'
                    }`}
                  >
                    <Columns className="w-4 h-4 inline-block mr-1.5" />
                    Columns
                  </button>
                  <button
                    onClick={() => setRightPanelTab('samples')}
                    className={`py-3 px-2 border-b-2 font-medium text-sm transition-colors ${
                      rightPanelTab === 'samples'
                        ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400'
                    }`}
                  >
                    <Database className="w-4 h-4 inline-block mr-1.5" />
                    Data Samples
                  </button>
                </nav>
              </div>

              {/* Columns Tab */}
              {rightPanelTab === 'columns' && (
                <div className="flex-1 flex flex-col overflow-hidden">
                  {/* Column search */}
                  <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                    <div className="relative max-w-md">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                      <input
                        type="text"
                        value={columnSearchQuery}
                        onChange={(e) => setColumnSearchQuery(e.target.value)}
                        placeholder="Search columns..."
                        className="w-full pl-9 pr-3 py-2 text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                    </div>
                  </div>

                  {/* Column table */}
                  <div className="flex-1 overflow-auto">
                    <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                      <thead className="bg-gray-50 dark:bg-gray-900 sticky top-0">
                        <tr>
                          <th className="w-10 px-3 py-2 text-left">
                            <div
                              className="cursor-pointer"
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
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Column name
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Data type
                          </th>
                          <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Nullable
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Key
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Default
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                        {filteredColumns.map((column) => {
                          const isSelected = selectedColumnNames.includes(column.name)
                          // Build full type display (e.g. "character varying(255)", "numeric(10,2)")
                          let typeDisplay = column.type
                          if (column.max_length) {
                            typeDisplay = `${column.type}(${column.max_length})`
                          } else if (column.precision != null && column.scale != null) {
                            typeDisplay = `${column.type}(${column.precision},${column.scale})`
                          } else if (column.precision != null) {
                            typeDisplay = `${column.type}(${column.precision})`
                          }

                          return (
                            <tr
                              key={column.name}
                              className={`cursor-pointer transition-colors ${
                                isSelected
                                  ? 'bg-blue-50 dark:bg-blue-900/10'
                                  : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                              }`}
                              onClick={() => handleToggleColumn(column.name)}
                            >
                              {/* Checkbox */}
                              <td className="w-10 px-3 py-2.5">
                                {isSelected ? (
                                  <CheckSquare className="w-4 h-4 text-blue-600" />
                                ) : (
                                  <Square className="w-4 h-4 text-gray-400" />
                                )}
                              </td>

                              {/* Column Name */}
                              <td className="px-3 py-2.5">
                                <span
                                  className={`text-sm ${
                                    isSelected
                                      ? 'text-gray-900 dark:text-white font-medium'
                                      : 'text-gray-700 dark:text-gray-300'
                                  }`}
                                >
                                  {column.name}
                                </span>
                              </td>

                              {/* Data Type */}
                              <td className="px-3 py-2.5">
                                <span className="text-xs font-mono px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-gray-600 dark:text-gray-400">
                                  {typeDisplay}
                                </span>
                              </td>

                              {/* Nullable */}
                              <td className="px-3 py-2.5 text-center">
                                <span
                                  className={`text-sm ${
                                    column.nullable
                                      ? 'text-green-600 dark:text-green-400'
                                      : 'text-red-500 dark:text-red-400'
                                  }`}
                                >
                                  {column.nullable ? 'Yes' : 'No'}
                                </span>
                              </td>

                              {/* Key */}
                              <td className="px-3 py-2.5">
                                <div className="flex items-center gap-1 flex-wrap">
                                  {column.is_primary_key && (
                                    <span className="px-1.5 py-0.5 text-xs font-medium bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded" title="Primary Key">
                                      PK
                                    </span>
                                  )}
                                  {column.is_foreign_key && (
                                    <span
                                      className="px-1.5 py-0.5 text-xs font-medium bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 rounded"
                                      title={column.foreign_table ? `References ${column.foreign_table}` : 'Foreign Key'}
                                    >
                                      FK
                                    </span>
                                  )}
                                  {column.is_unique && !column.is_primary_key && (
                                    <span className="px-1.5 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 rounded" title="Unique">
                                      UQ
                                    </span>
                                  )}
                                </div>
                              </td>

                              {/* Default */}
                              <td className="px-3 py-2.5">
                                {column.default ? (
                                  <span className="text-xs font-mono text-gray-500 dark:text-gray-400 truncate max-w-[150px] inline-block" title={column.default}>
                                    {column.default}
                                  </span>
                                ) : (
                                  <span className="text-xs text-gray-300 dark:text-gray-600">-</span>
                                )}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>

                    {filteredColumns.length === 0 && columnSearchQuery && (
                      <div className="flex flex-col items-center justify-center py-8 text-center">
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          No columns match your search
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Samples Tab */}
              {rightPanelTab === 'samples' && (() => {
                // Filter sample columns to only show selected ones
                const displayColumns = samples
                  ? (selectedColumnNames.length > 0
                      ? samples.columns.filter((c) => selectedColumnNames.includes(c))
                      : samples.columns)
                  : []

                return (
                  <div className="flex-1 overflow-auto">
                    {samplesLoading ? (
                      <div className="flex items-center justify-center py-16">
                        <Loader2 className="w-6 h-6 animate-spin text-blue-500 mr-2" />
                        <span className="text-gray-500 dark:text-gray-400">
                          Loading sample data...
                        </span>
                      </div>
                    ) : selectedColumnNames.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-16">
                        <Square className="w-10 h-10 text-gray-300 dark:text-gray-600 mb-3" />
                        <p className="text-gray-500 dark:text-gray-400">
                          No columns selected
                        </p>
                        <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                          Select columns from the Columns tab to see their sample data
                        </p>
                      </div>
                    ) : samples && samples.rows.length > 0 && displayColumns.length > 0 ? (
                      <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                          <thead className="bg-gray-50 dark:bg-gray-900 sticky top-0">
                            <tr>
                              {displayColumns.map((column) => (
                                <th
                                  key={column}
                                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider whitespace-nowrap"
                                >
                                  {column}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                            {samples.rows.map((row, idx) => (
                              <tr
                                key={idx}
                                className="hover:bg-gray-50 dark:hover:bg-gray-700"
                              >
                                {displayColumns.map((column) => (
                                  <td
                                    key={column}
                                    className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-300 max-w-xs truncate"
                                  >
                                    {row[column] === null ? (
                                      <span className="italic text-gray-400">null</span>
                                    ) : typeof row[column] === 'object' ? (
                                      JSON.stringify(row[column])
                                    ) : (
                                      String(row[column])
                                    )}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="px-4 py-3 bg-gray-50 dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400">
                          Showing {samples.rows.length} of{' '}
                          {samples.total_rows?.toLocaleString() || '?'} rows
                          {' · '}{displayColumns.length} of {samples.columns.length} columns
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center py-16">
                        <Database className="w-10 h-10 text-gray-300 dark:text-gray-600 mb-3" />
                        <p className="text-gray-500 dark:text-gray-400">
                          No sample data available
                        </p>
                      </div>
                    )}
                  </div>
                )
              })()}
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Table2 className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
                <p className="text-gray-500 dark:text-gray-400">
                  Select a table from the sidebar to view its columns and data
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
