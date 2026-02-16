/**
 * Connection Form - Dynamic form for connecting to a selected data source.
 */

import React, { useState, useEffect } from 'react'
import {
  CheckCircle,
  XCircle,
  Loader2,
  Eye,
  EyeOff,
  Database,
  ChevronRight,
} from 'lucide-react'
import { useSandboxUI } from '../context/SandboxUIContext'
import type { HandlerInfo, ConnectionArg } from '../types'

interface ConnectionFormProps {
  handler: HandlerInfo
  onBack: () => void
  onSuccess?: (connectionId: string, connectionName: string) => void
  existingConnectionName?: string
}

export const ConnectionForm: React.FC<ConnectionFormProps> = ({
  handler,
  onBack,
  onSuccess,
  existingConnectionName,
}) => {
  const { api, t } = useSandboxUI()
  const [connectionName, setConnectionName] = useState(
    existingConnectionName || ''
  )
  const [description, setDescription] = useState('')
  const [formValues, setFormValues] = useState<
    Record<string, string | number | boolean>
  >({})
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(false)
  const [testResult, setTestResult] = useState<{
    success: boolean
    message: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connectionArgs, setConnectionArgs] = useState<ConnectionArg[]>([])

  useEffect(() => {
    const args = handler.connection_args || []
    setConnectionArgs(args)

    const initialValues: Record<string, string | number | boolean> = {}
    args.forEach((arg) => {
      if (arg.default !== undefined && arg.default !== null) {
        initialValues[arg.name] = String(arg.default)
      } else if (arg.type === 'integer') {
        initialValues[arg.name] = ''
      } else if (arg.type === 'boolean') {
        initialValues[arg.name] = false
      } else {
        initialValues[arg.name] = ''
      }
    })
    setFormValues(initialValues)
    setTestResult(null)
    setError(null)
  }, [handler])

  const handleInputChange = (
    name: string,
    value: string | number | boolean
  ) => {
    setFormValues((prev) => ({ ...prev, [name]: value }))
    setTestResult(null)
    setError(null)
  }

  const toggleSecretVisibility = (name: string) => {
    setShowSecrets((prev) => ({ ...prev, [name]: !prev[name] }))
  }

  const isFieldVisible = (arg: ConnectionArg): boolean => {
    if (!arg.depends_on) return true
    const { field, values } = arg.depends_on
    const currentValue = formValues[field]
    return values.includes(currentValue as string)
  }

  const validateForm = (): boolean => {
    if (!connectionName.trim()) {
      setError(
        t('dataSources.errors.nameRequired') || 'Connection name is required'
      )
      return false
    }

    for (const arg of connectionArgs) {
      if (arg.required && isFieldVisible(arg)) {
        const value = formValues[arg.name]
        if (value === undefined || value === '' || value === null) {
          setError(
            t('dataSources.errors.fieldRequired', { field: arg.label }) ||
              `${arg.label} is required`
          )
          return false
        }
      }
    }

    return true
  }

  const buildConnectionArgs = (): Record<string, unknown> => {
    const args: Record<string, unknown> = {}
    connectionArgs.forEach((arg) => {
      if (!isFieldVisible(arg)) return

      const value = formValues[arg.name]
      if (value !== undefined && value !== '' && value !== null) {
        if (arg.type === 'integer') {
          args[arg.name] = parseInt(value as string, 10)
        } else {
          args[arg.name] = value
        }
      }
    })
    return args
  }

  const handleSave = async () => {
    if (!validateForm()) return

    setLoading(true)
    setError(null)

    try {
      const connArgs = buildConnectionArgs()

      const connectionConfig = {
        name: connectionName,
        db_type: handler.name,
        host: (connArgs.host as string) || '',
        port: parseInt((connArgs.port as string) || '5432'),
        database: (connArgs.database as string) || '',
        username:
          (connArgs.user as string) || (connArgs.username as string) || '',
        password: (connArgs.password as string) || '',
        schema_name:
          (connArgs.schema as string) || (connArgs.schema_name as string),
        ssl_enabled: (connArgs.ssl_enabled as boolean) ?? true,
      }

      const result = await api.connections.create(connectionConfig)

      if (result.id) {
        setTestResult({
          success: true,
          message:
            t('dataSources.connectionSuccess') || 'Connection successful!',
        })
        setTimeout(() => {
          onSuccess?.(result.id, connectionName)
        }, 1000)
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t('dataSources.errors.saveFailed') || 'Failed to save connection'
      )
    } finally {
      setLoading(false)
    }
  }

  const renderField = (arg: ConnectionArg) => {
    if (!isFieldVisible(arg)) {
      return null
    }

    const value = formValues[arg.name] ?? ''
    const isSecret = arg.secret
    const showSecret = showSecrets[arg.name]

    // Handle select type (dropdown)
    if (arg.type === 'select' && arg.options) {
      return (
        <div key={arg.name} className="space-y-1.5">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            {arg.label}
            {arg.required && <span className="text-red-500 ml-1">*</span>}
          </label>
          <select
            value={value as string}
            onChange={(e) => handleInputChange(arg.name, e.target.value)}
            className="w-full px-3 py-2.5 bg-white dark:bg-dashboard-elevated border border-slate-200 dark:border-dashboard-border rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          >
            {arg.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      )
    }

    if (arg.type === 'boolean') {
      return (
        <div
          key={arg.name}
          className="flex items-center justify-between py-3 border-b border-slate-100 dark:border-dashboard-border last:border-0"
        >
          <div>
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
              {arg.label}
              {arg.required && <span className="text-red-500 ml-1">*</span>}
            </label>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              {arg.description}
            </p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => handleInputChange(arg.name, e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer dark:bg-dashboard-subtle peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-slate-600 peer-checked:bg-blue-600" />
          </label>
        </div>
      )
    }

    // Handle multiline text for JSON/credentials or text type
    if (
      arg.type === 'text' ||
      arg.name.includes('json') ||
      arg.name.includes('credentials') ||
      arg.name.includes('private_key')
    ) {
      return (
        <div key={arg.name} className="space-y-1.5">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            {arg.label}
            {arg.required && <span className="text-red-500 ml-1">*</span>}
          </label>
          <textarea
            value={value as string}
            onChange={(e) => handleInputChange(arg.name, e.target.value)}
            placeholder={arg.description}
            rows={4}
            className="w-full px-3 py-2.5 bg-white dark:bg-dashboard-elevated border border-slate-200 dark:border-dashboard-border rounded-lg text-slate-900 dark:text-white placeholder-slate-400 font-mono text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
      )
    }

    return (
      <div key={arg.name} className="space-y-1.5">
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
          {arg.label}
          {arg.required && <span className="text-red-500 ml-1">*</span>}
        </label>
        <div className="relative">
          <input
            type={
              isSecret && !showSecret
                ? 'password'
                : arg.type === 'integer'
                  ? 'number'
                  : 'text'
            }
            value={value as string}
            onChange={(e) => handleInputChange(arg.name, e.target.value)}
            placeholder={arg.description}
            className="w-full px-3 py-2.5 bg-white dark:bg-dashboard-elevated border border-slate-200 dark:border-dashboard-border rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent pr-10"
          />
          {isSecret && (
            <button
              type="button"
              onClick={() => toggleSecretVisibility(arg.name)}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
            >
              {showSecret ? (
                <EyeOff className="w-4 h-4" />
              ) : (
                <Eye className="w-4 h-4" />
              )}
            </button>
          )}
        </div>
      </div>
    )
  }

  const requiredFields: ConnectionArg[] = connectionArgs.filter(
    (arg: ConnectionArg) => arg.required
  )
  const optionalFields: ConnectionArg[] = connectionArgs.filter(
    (arg: ConnectionArg) => !arg.required
  )

  return (
    <div className="min-h-full flex flex-col">
      {/* Header */}
      <div className="mb-6">
        <p className="text-sm text-slate-500 dark:text-slate-400 mb-1">
          {t('dataSources.createConnection') || 'Create connection'}
        </p>
        <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
          {t('dataSources.nameAndConfigure') ||
            'Name and configure your connection'}
        </h2>
      </div>

      {/* Error message */}
      {error && (
        <div className="flex items-center gap-2 p-3 mb-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 text-sm">
          <XCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Test result */}
      {testResult && (
        <div
          className={`flex items-center gap-2 p-3 mb-4 rounded-lg text-sm ${
            testResult.success
              ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-green-700 dark:text-green-400'
              : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400'
          }`}
        >
          {testResult.success ? (
            <CheckCircle className="w-4 h-4 flex-shrink-0" />
          ) : (
            <XCircle className="w-4 h-4 flex-shrink-0" />
          )}
          <span>{testResult.message}</span>
        </div>
      )}

      <div className="flex-1 space-y-6">
        {/* Name and describe the connection */}
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400">
            {t('dataSources.nameAndDescribe') ||
              'Name and describe the connection'}
          </h3>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                {t('dataSources.name') || 'Name'}
                <span className="text-red-500 ml-1">*</span>
              </label>
              <input
                type="text"
                value={connectionName}
                onChange={(e) => {
                  setConnectionName(e.target.value)
                  setError(null)
                }}
                placeholder={
                  t('dataSources.connectionNamePlaceholder') ||
                  'e.g., production-db, analytics-warehouse'
                }
                className="w-full px-3 py-2.5 bg-white dark:bg-dashboard-elevated border border-slate-200 dark:border-dashboard-border rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                {t('dataSources.description') || 'Description'}
                <span className="text-slate-400 font-normal ml-1">
                  ({t('common.optional') || 'Optional'})
                </span>
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={
                  t('dataSources.descriptionPlaceholder') ||
                  'Describe this connection...'
                }
                rows={2}
                className="w-full px-3 py-2.5 bg-white dark:bg-dashboard-elevated border border-slate-200 dark:border-dashboard-border rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
              />
            </div>
          </div>
        </div>

        {/* Required Connection Fields */}
        {requiredFields.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-dashboard-subtle flex items-center justify-center">
                <Database className="w-4 h-4 text-slate-600 dark:text-slate-400" />
              </div>
              <h3 className="text-sm font-medium text-slate-900 dark:text-white">
                {handler.title}
              </h3>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {requiredFields.map((arg) => renderField(arg))}
            </div>
          </div>
        )}

        {/* Optional Fields */}
        {optionalFields.length > 0 && (
          <div className="space-y-4">
            <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400">
              {t('dataSources.optionalSettings') || 'Optional Settings'}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {optionalFields.map((arg) => renderField(arg))}
            </div>
          </div>
        )}
      </div>

      {/* Footer with actions */}
      <div className="flex items-center justify-between pt-6 mt-6 border-t border-slate-200 dark:border-dashboard-border">
        <button
          onClick={onBack}
          className="text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 text-sm font-medium transition-colors"
        >
          {t('common.cancel') || 'Cancel'}
        </button>
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="px-4 py-2 border border-slate-200 dark:border-slate-600 rounded-lg text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-dashboard-subtle transition-colors"
          >
            {t('common.back') || 'Back'}
          </button>
          <button
            onClick={handleSave}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <>
                {t('dataSources.saveConnection') || 'Save Connection'}
                <ChevronRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
