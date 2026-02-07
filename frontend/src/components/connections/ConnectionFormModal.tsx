import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { connectionsApi } from '../../utils/api'
import type { Connection, ConnectionConfig } from '../../types'

interface ConnectionFormModalProps {
  connection: Connection | null
  onClose: () => void
  onSuccess: () => void
}

export function ConnectionFormModal({ connection, onClose, onSuccess }: ConnectionFormModalProps) {
  const [formData, setFormData] = useState<ConnectionConfig>({
    id: connection?.id,
    name: connection?.name || '',
    db_type: connection?.db_type || 'postgresql',
    host: connection?.host || 'localhost',
    port: connection?.port || 5432,
    database: connection?.database || '',
    username: '',
    password: '',
    schema_name: connection?.schema || '',
    ssl_enabled: true,
  })

  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const createMutation = useMutation({
    mutationFn: connectionsApi.create,
    onSuccess: () => {
      onSuccess()
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data: { id: string; config: ConnectionConfig }) =>
      connectionsApi.update(data.id, data.config),
    onSuccess: () => {
      onSuccess()
    },
  })

  const testMutation = useMutation({
    mutationFn: connectionsApi.test,
    onSuccess: (data) => {
      setTestResult(data)
    },
    onError: (error: any) => {
      setTestResult({
        success: false,
        message: error.response?.data?.message || 'Connection test failed',
      })
    },
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (connection?.id) {
      await updateMutation.mutateAsync({ id: connection.id, config: formData })
    } else {
      await createMutation.mutateAsync(formData)
    }
  }

  const handleTest = async () => {
    setTestResult(null)
    await testMutation.mutateAsync(formData)
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'number' ? parseInt(value) : type === 'checkbox' ? (e.target as HTMLInputElement).checked : value,
    }))
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
        <div className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75" onClick={onClose}></div>

        <div className="inline-block overflow-hidden text-left align-bottom transition-all transform bg-white dark:bg-gray-800 rounded-lg shadow-xl sm:my-8 sm:align-middle sm:max-w-lg sm:w-full">
          <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white">
                {connection ? 'Edit Connection' : 'New Connection'}
              </h3>
              <button
                onClick={onClose}
                className="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Connection Name
              </label>
              <input
                type="text"
                name="name"
                value={formData.name}
                onChange={handleChange}
                required
                className="mt-1 block w-full rounded-md border-gray-300 dark:border-gray-600 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:text-white sm:text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Database Type
              </label>
              <select
                name="db_type"
                value={formData.db_type}
                onChange={handleChange}
                className="mt-1 block w-full rounded-md border-gray-300 dark:border-gray-600 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:text-white sm:text-sm"
              >
                <option value="postgresql">PostgreSQL</option>
                <option value="mysql">MySQL</option>
                <option value="snowflake">Snowflake</option>
                <option value="bigquery">BigQuery</option>
              </select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Host
                </label>
                <input
                  type="text"
                  name="host"
                  value={formData.host}
                  onChange={handleChange}
                  required
                  className="mt-1 block w-full rounded-md border-gray-300 dark:border-gray-600 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:text-white sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Port
                </label>
                <input
                  type="number"
                  name="port"
                  value={formData.port}
                  onChange={handleChange}
                  required
                  className="mt-1 block w-full rounded-md border-gray-300 dark:border-gray-600 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:text-white sm:text-sm"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Database
              </label>
              <input
                type="text"
                name="database"
                value={formData.database}
                onChange={handleChange}
                required
                className="mt-1 block w-full rounded-md border-gray-300 dark:border-gray-600 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:text-white sm:text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Schema (optional)
              </label>
              <input
                type="text"
                name="schema_name"
                value={formData.schema_name}
                onChange={handleChange}
                className="mt-1 block w-full rounded-md border-gray-300 dark:border-gray-600 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:text-white sm:text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Username
              </label>
              <input
                type="text"
                name="username"
                value={formData.username}
                onChange={handleChange}
                required
                className="mt-1 block w-full rounded-md border-gray-300 dark:border-gray-600 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:text-white sm:text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Password
              </label>
              <input
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                required={!connection}
                placeholder={connection ? '••••••••' : ''}
                className="mt-1 block w-full rounded-md border-gray-300 dark:border-gray-600 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:text-white sm:text-sm"
              />
            </div>

            {testResult && (
              <div
                className={`p-3 rounded-md ${
                  testResult.success
                    ? 'bg-green-50 dark:bg-green-900 text-green-800 dark:text-green-200'
                    : 'bg-red-50 dark:bg-red-900 text-red-800 dark:text-red-200'
                }`}
              >
                {testResult.message}
              </div>
            )}

            <div className="flex justify-between pt-4 border-t border-gray-200 dark:border-gray-700">
              <button
                type="button"
                onClick={handleTest}
                disabled={testMutation.isPending}
                className="inline-flex justify-center px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                {testMutation.isPending ? 'Testing...' : 'Test Connection'}
              </button>
              <div className="space-x-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="inline-flex justify-center px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending || updateMutation.isPending}
                  className="inline-flex justify-center px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                >
                  {createMutation.isPending || updateMutation.isPending
                    ? 'Saving...'
                    : connection
                    ? 'Update'
                    : 'Create'}
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
