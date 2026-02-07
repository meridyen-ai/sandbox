import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, RefreshCw, Table as TableIcon } from 'lucide-react'
import { schemaApi } from '../../utils/api'
import { TableView } from './TableView'

export function DatasetPage() {
  const { connectionId } = useParams<{ connectionId: string }>()
  const navigate = useNavigate()
  const [selectedTable, setSelectedTable] = useState<string | null>(null)

  const {
    data: schema,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['schema', connectionId],
    queryFn: () => schemaApi.sync(connectionId!, true, 10),
    enabled: !!connectionId,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500 dark:text-gray-400">Loading schema...</div>
      </div>
    )
  }

  if (!schema) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="text-center">
          <p className="text-gray-500 dark:text-gray-400">Failed to load schema</p>
        </div>
      </div>
    )
  }

  const currentTable = schema.tables.find((t) => t.name === selectedTable)

  return (
    <div className="h-[calc(100vh-4rem)] flex">
      {/* Left Sidebar - Table List */}
      <div className="w-80 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 overflow-y-auto">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <button
            onClick={() => navigate('/connections')}
            className="flex items-center text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white mb-4"
          >
            <ArrowLeft className="w-4 h-4 mr-1" />
            Back to Connections
          </button>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {schema.connection_name}
            </h2>
            <button
              onClick={() => refetch()}
              className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              title="Refresh schema"
            >
              <RefreshCw className="w-4 h-4 text-gray-600 dark:text-gray-400" />
            </button>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {schema.database}
            {schema.schema && ` / ${schema.schema}`}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {schema.tables.length} tables
          </p>
        </div>

        <div className="p-2">
          <div className="space-y-1">
            {schema.tables.map((table) => (
              <button
                key={table.name}
                onClick={() => setSelectedTable(table.name)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm flex items-center ${
                  selectedTable === table.name
                    ? 'bg-blue-50 dark:bg-blue-900 text-blue-700 dark:text-blue-200'
                    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                <TableIcon className="w-4 h-4 mr-2" />
                <span className="flex-1 truncate">{table.name}</span>
                <span className="text-xs text-gray-400">
                  {table.columns.length}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Right Panel - Table Details */}
      <div className="flex-1 overflow-hidden">
        {selectedTable && currentTable ? (
          <TableView
            connectionId={connectionId!}
            table={currentTable}
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <TableIcon className="mx-auto h-12 w-12 text-gray-400" />
              <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                No table selected
              </h3>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                Select a table from the left to view its data
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
