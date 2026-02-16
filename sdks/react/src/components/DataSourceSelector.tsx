/**
 * Data Source Selector - Grid of database types to select from.
 * Fetches available handlers dynamically via the SandboxUI API context.
 */

import React, { useEffect, useState } from 'react'
import { Loader2, AlertCircle, Search, Database } from 'lucide-react'
import { useSandboxUI } from '../context/SandboxUIContext'
import { handlerIconMap, handlerGroups } from '../icons/handlerIconMap'
import type { HandlerInfo } from '../types'

interface DataSourceSelectorProps {
  onSelect: (handler: HandlerInfo) => void
  selectedHandler?: string
}

// Icons that only have SVG versions (no PNG available)
const svgOnlyIcons = ['default']

export const DataSourceSelector: React.FC<DataSourceSelectorProps> = ({
  onSelect,
  selectedHandler,
}) => {
  const { api, t, iconBasePath } = useSandboxUI()
  const [handlers, setHandlers] = useState<HandlerInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    loadHandlers()
  }, [])

  const loadHandlers = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.handlers.list()
      setHandlers(data)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t('dataSources.failedToLoad') || 'Failed to load data sources'
      )
    } finally {
      setLoading(false)
    }
  }

  const filteredHandlers = handlers.filter((h) => {
    const query = searchQuery.toLowerCase()
    return (
      h.title.toLowerCase().includes(query) ||
      h.name.toLowerCase().includes(query) ||
      h.description.toLowerCase().includes(query)
    )
  })

  const getIconPath = (handlerName: string): string => {
    const iconName = handlerIconMap[handlerName] || 'default'
    const extension = svgOnlyIcons.includes(iconName) ? 'svg' : 'png'
    return `${iconBasePath}/${iconName}.${extension}`
  }

  // Group handlers by category
  const getGroupedHandlers = () => {
    const grouped: Record<string, HandlerInfo[]> = {
      cloudDataPlatforms: [],
      queryEngines: [],
      databases: [],
      files: [],
      other: [],
      uncategorized: [],
    }

    filteredHandlers.forEach((handler) => {
      let placed = false
      for (const [groupKey, groupDef] of Object.entries(handlerGroups)) {
        if (groupDef.handlers.includes(handler.name)) {
          grouped[groupKey].push(handler)
          placed = true
          break
        }
      }
      if (!placed) {
        grouped.uncategorized.push(handler)
      }
    })

    return grouped
  }

  const renderHandlerCard = (handler: HandlerInfo) => {
    const iconPath = getIconPath(handler.name)
    const isSelected = selectedHandler === handler.name
    const isDisabled = !handler.available

    return (
      <button
        key={handler.name}
        onClick={() => !isDisabled && onSelect(handler)}
        disabled={isDisabled}
        className={`
          relative flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all min-h-[120px]
          ${
            isSelected
              ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 ring-2 ring-blue-500/30'
              : 'border-slate-200 dark:border-dashboard-border bg-white dark:bg-dashboard-elevated hover:border-slate-300 dark:hover:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-750'
          }
          ${isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
        `}
        title={handler.description}
      >
        <div className="w-12 h-12 mb-3 flex items-center justify-center">
          <img
            src={iconPath}
            alt={handler.title}
            className="w-10 h-10 object-contain"
            onError={(e) => {
              (e.target as HTMLImageElement).src = `${iconBasePath}/default.png`
            }}
          />
        </div>
        <span
          className={`text-sm font-medium text-center ${
            isSelected
              ? 'text-blue-700 dark:text-blue-300'
              : 'text-slate-700 dark:text-slate-300'
          }`}
        >
          {handler.title}
        </span>
        {!handler.available && (
          <span className="absolute top-2 right-2 text-xs px-1.5 py-0.5 bg-slate-100 dark:bg-dashboard-subtle text-slate-500 dark:text-slate-400 rounded">
            N/A
          </span>
        )}
      </button>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    )
  }

  const groupedHandlers = getGroupedHandlers()

  const groupEntries: Array<{ key: string; label: string }> = [
    { key: 'cloudDataPlatforms', label: t('dataSources.cloudDataPlatforms') || 'Cloud data platforms' },
    { key: 'queryEngines', label: t('dataSources.queryEngines') || 'Query engines' },
    { key: 'databases', label: t('dataSources.databasesTitle') || 'Databases' },
    { key: 'files', label: t('dataSources.files') || 'Files' },
    { key: 'other', label: t('dataSources.other') || 'Other' },
    { key: 'uncategorized', label: t('dataSources.uncategorized') || 'Other Sources' },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
            {t('dataSources.selectDataSource') || 'Select a data source'}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t('dataSources.selectDescription') ||
              'Choose a database or data warehouse to connect'}
          </p>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={
            t('dataSources.searchPlaceholder') || 'Search data source'
          }
          className="w-full pl-10 pr-4 py-2.5 bg-white dark:bg-dashboard-elevated border border-slate-200 dark:border-dashboard-border rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>

      {/* Error message */}
      {error && (
        <div className="flex items-center gap-2 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg text-amber-700 dark:text-amber-400 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Data source groups */}
      {groupEntries.map(
        ({ key, label }) =>
          groupedHandlers[key]?.length > 0 && (
            <div key={key} className="space-y-3">
              <h4 className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {label}
              </h4>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                {groupedHandlers[key].map(renderHandlerCard)}
              </div>
            </div>
          )
      )}

      {/* Empty state */}
      {filteredHandlers.length === 0 && (
        <div className="text-center py-12">
          <Database className="w-12 h-12 text-slate-300 dark:text-slate-600 mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">
            {t('dataSources.noResults') ||
              'No data sources match your search'}
          </p>
        </div>
      )}
    </div>
  )
}
