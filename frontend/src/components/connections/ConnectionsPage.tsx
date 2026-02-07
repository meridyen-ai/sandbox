import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Plus, Database, Trash2, Eye, ArrowLeft } from 'lucide-react'
import { connectionsApi } from '../../utils/api'
import { DataSourceSelector } from './DataSourceSelector'
import { ConnectionForm } from './ConnectionForm'
import type { Connection, HandlerInfo } from '../../types'

type ViewState = 'list' | 'select-type' | 'configure'

export function ConnectionsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [viewState, setViewState] = useState<ViewState>('list')
  const [selectedHandler, setSelectedHandler] = useState<HandlerInfo | null>(null)

  const { data: connections, isLoading } = useQuery({
    queryKey: ['connections'],
    queryFn: connectionsApi.list,
  })

  const deleteMutation = useMutation({
    mutationFn: connectionsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['connections'] })
    },
  })

  const handleDelete = async (id: string) => {
    if (confirm('Are you sure you want to delete this connection?')) {
      await deleteMutation.mutateAsync(id)
    }
  }

  const handleViewDataset = (connectionId: string) => {
    navigate(`/dataset/${connectionId}`)
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

  const handleConnectionSuccess = () => {
    setViewState('list')
    setSelectedHandler(null)
    queryClient.invalidateQueries({ queryKey: ['connections'] })
  }

  const getDbTypeBadgeColor = (dbType: string) => {
    const colors: Record<string, string> = {
      postgresql: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
      postgres: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
      mysql: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
      snowflake: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200',
      bigquery: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    }
    return colors[dbType.toLowerCase()] || 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500 dark:text-gray-400">Loading connections...</div>
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
            Back to connections
          </button>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">New Connection</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Select a database or data warehouse to connect
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

  // View: List connections
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-6 flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Database Connections</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Manage your database connections and view datasets
          </p>
        </div>
        <button
          onClick={handleNewConnection}
          className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
        >
          <Plus className="w-4 h-4 mr-2" />
          New Connection
        </button>
      </div>

      {!connections || connections.length === 0 ? (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <Database className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-white">No connections</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Get started by creating a new database connection.
          </p>
          <div className="mt-6">
            <button
              onClick={handleNewConnection}
              className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
            >
              <Plus className="w-4 h-4 mr-2" />
              New Connection
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 shadow-sm rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Name
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Host
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Database
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
              {connections.map((connection) => (
                <tr key={connection.id} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center">
                      <Database className="w-5 h-5 text-gray-400 mr-3" />
                      <div className="text-sm font-medium text-gray-900 dark:text-white">
                        {connection.name}
                        {connection.is_default && (
                          <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                            Default
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${getDbTypeBadgeColor(connection.db_type)}`}>
                      {connection.db_type}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {connection.host}:{connection.port}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {connection.database}
                    {connection.schema && <span className="text-gray-400"> / {connection.schema}</span>}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button
                      onClick={() => handleViewDataset(connection.id)}
                      className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300 mr-3"
                      title="View Dataset"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(connection.id)}
                      className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
