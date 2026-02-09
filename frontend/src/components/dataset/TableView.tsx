import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Columns, Database } from 'lucide-react'
import { schemaApi } from '../../utils/api'
import type { Table } from '../../types'
import { useTranslation } from '../../hooks/useTranslation'

interface TableViewProps {
  connectionId: string
  table: Table
}

type TabType = 'columns' | 'samples'

export function TableView({ connectionId, table }: TableViewProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<TabType>('columns')

  const { data: samples, isLoading: samplesLoading } = useQuery({
    queryKey: ['table-samples', connectionId, table.name],
    queryFn: () => schemaApi.getTableSamples(connectionId, table.name, 10),
    enabled: activeTab === 'samples',
  })

  return (
    <div className="h-full flex flex-col bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
          <Database className="w-5 h-5 mr-2" />
          {table.name}
        </h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          {table.columns.length} {t('common.columns')}
        </p>
      </div>

      {/* Tabs */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <nav className="flex space-x-8 px-6" aria-label="Tabs">
          <button
            onClick={() => setActiveTab('columns')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'columns'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <Columns className="w-4 h-4 inline-block mr-2" />
            {t('dataset.columns')}
          </button>
          <button
            onClick={() => setActiveTab('samples')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'samples'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <Database className="w-4 h-4 inline-block mr-2" />
            {t('dataset.dataSamples')}
          </button>
        </nav>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'columns' && (
          <div className="bg-white dark:bg-gray-800 shadow-sm rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    {t('dataset.columnName')}
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    {t('dataset.dataType')}
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    {t('dataset.nullable')}
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    {t('dataset.key')}
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                {table.columns.map((column) => {
                  let typeDisplay = column.type
                  if (column.max_length) {
                    typeDisplay = `${column.type}(${column.max_length})`
                  } else if (column.precision != null && column.scale != null) {
                    typeDisplay = `${column.type}(${column.precision},${column.scale})`
                  } else if (column.precision != null) {
                    typeDisplay = `${column.type}(${column.precision})`
                  }
                  return (
                    <tr key={column.name} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                        {column.name}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                        <span className="px-2 py-1 text-xs font-mono bg-gray-100 dark:bg-gray-700 rounded">
                          {typeDisplay}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                        {column.nullable ? (
                          <span className="text-green-600 dark:text-green-400">{t('common.yes')}</span>
                        ) : (
                          <span className="text-gray-400">{t('common.no')}</span>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                        <div className="flex items-center gap-1">
                          {column.is_primary_key && (
                            <span className="px-2 py-1 text-xs font-medium bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded">
                              PK
                            </span>
                          )}
                          {column.is_foreign_key && (
                            <span className="px-2 py-1 text-xs font-medium bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 rounded" title={column.foreign_table || undefined}>
                              FK
                            </span>
                          )}
                          {column.is_unique && !column.is_primary_key && (
                            <span className="px-2 py-1 text-xs font-medium bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 rounded">
                              UQ
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'samples' && (
          <div className="bg-white dark:bg-gray-800 shadow-sm rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            {samplesLoading ? (
              <div className="p-8 text-center text-gray-500 dark:text-gray-400">
                {t('dataset.loadingSamples')}
              </div>
            ) : samples && samples.rows.length > 0 ? (
              <>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                    <thead className="bg-gray-50 dark:bg-gray-900">
                      <tr>
                        {samples.columns.map((column) => (
                          <th
                            key={column}
                            className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
                          >
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                      {samples.rows.map((row, idx) => (
                        <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                          {samples.columns.map((column) => (
                            <td
                              key={column}
                              className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-300"
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
                </div>
                <div className="px-6 py-3 bg-gray-50 dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400">
                  {t('dataset.showingRows', { count: samples.rows.length, total: samples.total_rows })}
                </div>
              </>
            ) : (
              <div className="p-8 text-center text-gray-500 dark:text-gray-400">
                {t('dataset.noSampleData')}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
