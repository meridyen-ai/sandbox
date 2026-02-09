/**
 * Table and Column Selector Component (Sandbox version)
 *
 * Adapted from the MVP's TableColumnSelector to work with the sandbox's
 * schema API. Provides a ThoughtSpot-style UI for selecting which tables
 * and columns should be synced to the MVP.
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
} from 'lucide-react'
import { schemaApi } from '../../utils/api'
import type { TableWithColumns, SelectedSchema, SchemaData } from '../../types'

interface TableColumnSelectorProps {
  connectionId: string
  connectionName: string
  initialSelectedSchema?: SelectedSchema
  onBack: () => void
  onConfirm: (selectedSchema: SelectedSchema) => void
  loading?: boolean
}

// Group tables by database and schema
interface SchemaGroup {
  schemaName: string
  tables: TableWithColumns[]
}

interface DatabaseGroup {
  databaseName: string
  schemas: SchemaGroup[]
}

type TabType = 'all' | 'selected'

/**
 * Convert sandbox SchemaData (from schemaApi.sync) to TableWithColumns[]
 * that matches the MVP's format.
 */
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

export const TableColumnSelector: React.FC<TableColumnSelectorProps> = ({
  connectionId,
  connectionName,
  initialSelectedSchema,
  onBack,
  onConfirm,
  loading: externalLoading,
}) => {
  const [schema, setSchema] = useState<TableWithColumns[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [columnSearchQuery, setColumnSearchQuery] = useState('')
  const [expandedDatabases, setExpandedDatabases] = useState<Set<string>>(new Set())
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(new Set())
  const [selectedTable, setSelectedTable] = useState<TableWithColumns | null>(null)
  const [selectedSchema, setSelectedSchema] = useState<SelectedSchema>(
    initialSelectedSchema || {}
  )
  const [activeTab, setActiveTab] = useState<TabType>('all')

  // Load schema on mount
  useEffect(() => {
    loadSchema()
  }, [connectionId])

  const loadSchema = async () => {
    setLoading(true)
    setError(null)
    try {
      // Use sandbox's schemaApi.sync instead of MVP's getConnectionSchema
      const schemaData = await schemaApi.sync(connectionId, true, 10)
      const data = schemaDataToTableWithColumns(schemaData)
      setSchema(data)

      // If no initial selection, start with nothing selected (empty)
      if (!initialSelectedSchema || Object.keys(initialSelectedSchema).length === 0) {
        const defaultSelection: SelectedSchema = {}
        data.forEach((table) => {
          defaultSelection[table.full_name] = {
            selected: false,
            columns: [],
          }
        })
        setSelectedSchema(defaultSelection)
      }

      // Auto-expand first database and schema, select first table
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
          : 'Failed to load database schema'
      )
    } finally {
      setLoading(false)
    }
  }

  // Get tables that have at least one selected column
  const tablesWithSelections = useMemo(() => {
    return schema.filter((table) => {
      const selection = selectedSchema[table.full_name]
      return selection && selection.columns.length > 0
    })
  }, [schema, selectedSchema])

  // Group tables by database (connection name) and schema
  const groupedTables = useMemo((): DatabaseGroup[] => {
    const schemaMap = new Map<string, TableWithColumns[]>()

    // Use filtered tables based on active tab
    const baseTables = activeTab === 'selected' ? tablesWithSelections : schema

    // Filter tables based on search
    const filteredSchema = searchQuery
      ? baseTables.filter(
          (table) =>
            table.table_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            table.schema_name.toLowerCase().includes(searchQuery.toLowerCase())
        )
      : baseTables

    filteredSchema.forEach((table) => {
      const key = table.schema_name || 'public'
      if (!schemaMap.has(key)) {
        schemaMap.set(key, [])
      }
      schemaMap.get(key)!.push(table)
    })

    const schemas: SchemaGroup[] = Array.from(schemaMap.entries()).map(([schemaName, tables]) => ({
      schemaName,
      tables: tables.sort((a, b) => a.table_name.localeCompare(b.table_name)),
    }))

    return [
      {
        databaseName: connectionName,
        schemas: schemas.sort((a, b) => a.schemaName.localeCompare(b.schemaName)),
      },
    ]
  }, [schema, connectionName, searchQuery, activeTab, tablesWithSelections])

  // Calculate selection stats
  const selectionStats = useMemo(() => {
    const totalTables = schema.length
    const selectedTables = Object.values(selectedSchema).filter(
      (s) => s.selected && s.columns.length > 0
    ).length
    const totalColumns = schema.reduce((sum, t) => sum + t.columns.length, 0)
    const selectedColumns = Object.values(selectedSchema).reduce(
      (sum, s) => sum + (s.columns?.length || 0),
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
    const allSelected = currentSelection?.columns.length === selectedTable.columns.length

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

  // Toggle all columns for a specific table (used from left sidebar checkbox)
  const handleToggleTableColumns = (table: TableWithColumns, e: React.MouseEvent) => {
    e.stopPropagation()

    const currentSelection = selectedSchema[table.full_name]
    const allSelected = currentSelection?.columns.length === table.columns.length

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

  const getTableSelectionState = (table: TableWithColumns): 'all' | 'some' | 'none' => {
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

  // Filter columns based on search
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

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Loader2 className="w-10 h-10 animate-spin text-blue-500 mb-4" />
        <p className="text-gray-500 dark:text-gray-400">
          Loading database schema...
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
          onClick={loadSchema}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium"
        >
          <RefreshCw className="w-4 h-4" />
          Retry
        </button>
      </div>
    )
  }

  const currentTableSelection = selectedTable ? selectedSchema[selectedTable.full_name] : null
  const selectedColumnNames = currentTableSelection?.columns || []
  const headerCheckboxState = getHeaderCheckboxState()

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="mb-4">
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">
          Create connection
        </p>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
          Select tables
        </h2>
      </div>

      {/* Main Content - Two Column Layout */}
      <div className="flex-1 flex gap-4 min-h-0 overflow-hidden">
        {/* Left Sidebar - Tree View */}
        <div className="w-72 flex flex-col border border-gray-200 dark:border-gray-700 rounded-xl bg-white dark:bg-gray-800 overflow-hidden">
          {/* Connection Header */}
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-blue-600" />
              <span className="font-medium text-gray-900 dark:text-white text-sm truncate">
                {connectionName}
              </span>
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
              All
            </button>
            <button
              onClick={() => setActiveTab('selected')}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors flex items-center justify-center gap-1 ${
                activeTab === 'selected'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              Selected
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
                placeholder="Search tables..."
                className="w-full pl-9 pr-3 py-2 text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          </div>

          {/* Tree View */}
          <div className="flex-1 overflow-y-auto">
            {groupedTables.map((db) => (
              <div key={db.databaseName}>
                {/* Database Level */}
                <div
                  className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
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

                {/* Schemas */}
                {expandedDatabases.has(db.databaseName) &&
                  db.schemas.map((schemaGroup) => {
                    const schemaKey = `${db.databaseName}.${schemaGroup.schemaName}`
                    return (
                      <div key={schemaKey}>
                        {/* Schema Level */}
                        <div
                          className="flex items-center gap-2 px-3 py-2 pl-7 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
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

                        {/* Tables */}
                        {expandedSchemas.has(schemaKey) &&
                          schemaGroup.tables.map((table) => {
                            const isSelected = selectedTable?.full_name === table.full_name
                            const selectionState = getTableSelectionState(table)

                            return (
                              <div
                                key={table.full_name}
                                className={`flex items-center gap-2 px-3 py-2 pl-14 cursor-pointer transition-colors ${
                                  isSelected
                                    ? 'bg-blue-50 dark:bg-blue-900/20 border-l-2 border-blue-600'
                                    : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                                }`}
                                onClick={() => setSelectedTable(table)}
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

            {activeTab === 'selected' && tablesWithSelections.length === 0 && (
              <div className="flex flex-col items-center justify-center py-8 text-center px-4">
                <Square className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  No tables selected yet
                </p>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  Select columns from the All tab
                </p>
              </div>
            )}

            {activeTab === 'all' && groupedTables[0]?.schemas.length === 0 && (
              <div className="flex flex-col items-center justify-center py-8 text-center px-4">
                <Table2 className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {searchQuery
                    ? 'No tables match your search'
                    : 'No tables found'}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Right Panel - Column Details */}
        <div className="flex-1 flex flex-col border border-gray-200 dark:border-gray-700 rounded-xl bg-white dark:bg-gray-800 overflow-hidden">
          {selectedTable ? (
            <>
              {/* Table Header */}
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                <h3 className="font-semibold text-gray-900 dark:text-white">
                  {selectedTable.table_name}
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {selectedColumnNames.length}/{selectedTable.columns.length}{' '}
                  columns selected
                </p>
              </div>

              {/* Search Columns */}
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
                <div className="relative">
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

              {/* Column Table Header with Select All checkbox */}
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
                  Column name ({selectedColumnNames.length}/
                  {selectedTable.columns.length} selected)
                </div>
                <div className="col-span-3">Data type</div>
                <div className="col-span-3">Nullable</div>
              </div>

              {/* Column Rows */}
              <div className="flex-1 overflow-y-auto">
                {filteredColumns.map((column) => {
                  const isSelected = selectedColumnNames.includes(column.name)
                  return (
                    <div
                      key={column.name}
                      className={`grid grid-cols-12 gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-700 cursor-pointer transition-colors ${
                        isSelected
                          ? 'bg-blue-50 dark:bg-blue-900/10'
                          : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                      }`}
                      onClick={() => handleToggleColumn(column.name)}
                    >
                      {/* Checkbox */}
                      <div className="col-span-1 flex items-center">
                        {isSelected ? (
                          <CheckSquare className="w-4 h-4 text-blue-600" />
                        ) : (
                          <Square className="w-4 h-4 text-gray-400" />
                        )}
                      </div>

                      {/* Column Name */}
                      <div className="col-span-5 flex items-center gap-2">
                        <span
                          className={`text-sm ${
                            isSelected
                              ? 'text-gray-900 dark:text-white font-medium'
                              : 'text-gray-600 dark:text-gray-400'
                          }`}
                        >
                          {column.name}
                        </span>
                      </div>

                      {/* Data Type */}
                      <div className="col-span-3 flex items-center">
                        <span className="text-xs font-mono px-2 py-0.5 bg-gray-200 dark:bg-gray-700 rounded text-gray-600 dark:text-gray-400 uppercase">
                          {column.data_type}
                        </span>
                      </div>

                      {/* Nullable */}
                      <div className="col-span-3 flex items-center">
                        <span className={`text-sm ${column.nullable ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}`}>
                          {column.nullable ? 'Yes' : 'No'}
                        </span>
                      </div>
                    </div>
                  )
                })}

                {filteredColumns.length === 0 && columnSearchQuery && (
                  <div className="flex flex-col items-center justify-center py-8 text-center">
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      No columns match your search
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
                  Select a table to view its columns
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Footer with Actions */}
      <div className="flex items-center justify-between pt-4 mt-4 border-t border-gray-200 dark:border-gray-700">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 text-sm font-medium transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <button
          onClick={handleConfirm}
          disabled={selectionStats.selectedColumns === 0 || externalLoading}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {externalLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Check className="w-4 h-4" />
          )}
          Save Selection
        </button>
      </div>
    </div>
  )
}
