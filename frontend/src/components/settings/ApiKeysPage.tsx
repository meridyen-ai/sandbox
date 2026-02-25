import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Key, Copy, Check, Trash2, Shield, ExternalLink, Save } from 'lucide-react'
import { apiKeyApi, type ApiKeyStatus } from '../../utils/api'
import { useTranslation } from '../../hooks/useTranslation'

export function ApiKeysPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [apiKeyInput, setApiKeyInput] = useState('')
  const [copied, setCopied] = useState(false)
  const [showRemove, setShowRemove] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const { data: keyStatus, isLoading } = useQuery({
    queryKey: ['api-key'],
    queryFn: apiKeyApi.get,
  })

  const saveMutation = useMutation({
    mutationFn: (key: string) => apiKeyApi.save(key),
    onSuccess: () => {
      setApiKeyInput('')
      setSaveError(null)
      queryClient.invalidateQueries({ queryKey: ['api-key'] })
    },
    onError: (error: any) => {
      setSaveError(error?.response?.data?.detail || t('apiKeys.saveError'))
    },
  })

  const removeMutation = useMutation({
    mutationFn: apiKeyApi.remove,
    onSuccess: () => {
      setShowRemove(false)
      queryClient.invalidateQueries({ queryKey: ['api-key'] })
    },
  })

  const handleSave = () => {
    const trimmed = apiKeyInput.trim()
    if (!trimmed) return
    if (!trimmed.startsWith('sb_')) {
      setSaveError(t('apiKeys.invalidPrefix'))
      return
    }
    setSaveError(null)
    saveMutation.mutate(trimmed)
  }

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const hasKey = keyStatus?.configured

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
          {t('apiKeys.title')}
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {t('apiKeys.subtitle')}
        </p>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="p-6">
            {hasKey ? (
              <>
                {/* Current key info */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <div className="p-2 bg-green-50 dark:bg-green-900/20 rounded-lg">
                      <Key className="w-5 h-5 text-green-600 dark:text-green-400" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-white">
                        {t('apiKeys.configured')}
                      </p>
                      <div className="flex items-center space-x-2 mt-0.5">
                        <code className="text-sm text-gray-500 dark:text-gray-400 font-mono">
                          {keyStatus.key_prefix}...
                        </code>
                        <button
                          onClick={() => handleCopy(keyStatus.key_prefix + '...')}
                          className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
                          title="Copy prefix"
                        >
                          {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                        </button>
                        <span className="text-xs text-gray-400 dark:text-gray-500">
                          {keyStatus.created_at && `Added ${new Date(keyStatus.created_at).toLocaleDateString()}`}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Remove button */}
                  {showRemove ? (
                    <div className="flex items-center space-x-2 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg border border-red-200 dark:border-red-800">
                      <span className="text-xs text-red-700 dark:text-red-300">{t('apiKeys.removeWarning')}</span>
                      <button
                        onClick={() => removeMutation.mutate()}
                        disabled={removeMutation.isPending}
                        className="px-2 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700 disabled:opacity-50"
                      >
                        {t('common.confirm')}
                      </button>
                      <button
                        onClick={() => setShowRemove(false)}
                        className="px-2 py-1 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded text-xs font-medium hover:bg-gray-50 dark:hover:bg-gray-700"
                      >
                        {t('common.cancel')}
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setShowRemove(true)}
                      className="flex items-center space-x-1.5 px-3 py-2 text-sm font-medium text-red-600 dark:text-red-400 border border-red-300 dark:border-red-700 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                      <span>{t('apiKeys.remove')}</span>
                    </button>
                  )}
                </div>

                {/* Replace key */}
                <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                    {t('apiKeys.replaceHint')}
                  </p>
                  <div className="flex items-center space-x-3">
                    <input
                      type="password"
                      value={apiKeyInput}
                      onChange={(e) => { setApiKeyInput(e.target.value); setSaveError(null) }}
                      placeholder="sb_..."
                      className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                    <button
                      onClick={handleSave}
                      disabled={!apiKeyInput.trim() || saveMutation.isPending}
                      className="flex items-center space-x-1.5 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
                    >
                      <Save className="w-4 h-4" />
                      <span>{saveMutation.isPending ? t('common.saving') : t('apiKeys.replace')}</span>
                    </button>
                  </div>
                  {saveError && (
                    <p className="mt-2 text-sm text-red-600 dark:text-red-400">{saveError}</p>
                  )}
                </div>
              </>
            ) : (
              /* No key — paste one */
              <div className="text-center py-8">
                <div className="mx-auto w-12 h-12 flex items-center justify-center bg-gray-100 dark:bg-gray-700 rounded-full">
                  <Shield className="w-6 h-6 text-gray-400 dark:text-gray-500" />
                </div>
                <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">
                  {t('apiKeys.emptyTitle')}
                </h3>
                <p className="mt-2 text-sm text-gray-500 dark:text-gray-400 max-w-sm mx-auto">
                  {t('apiKeys.emptyDescription')}
                </p>

                <div className="mt-6 max-w-md mx-auto">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 text-left mb-1">
                    {t('apiKeys.inputLabel')}
                  </label>
                  <div className="flex items-center space-x-3">
                    <input
                      type="password"
                      value={apiKeyInput}
                      onChange={(e) => { setApiKeyInput(e.target.value); setSaveError(null) }}
                      placeholder="sb_..."
                      className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                    <button
                      onClick={handleSave}
                      disabled={!apiKeyInput.trim() || saveMutation.isPending}
                      className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
                    >
                      <Key className="w-4 h-4" />
                      <span>{saveMutation.isPending ? t('common.saving') : t('common.save')}</span>
                    </button>
                  </div>
                  {saveError && (
                    <p className="mt-2 text-sm text-red-600 dark:text-red-400">{saveError}</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Where to get your key */}
      <div className="mt-6 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-700">
        <div className="flex items-start space-x-3">
          <ExternalLink className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5 flex-shrink-0" />
          <div>
            <h4 className="text-sm font-medium text-blue-800 dark:text-blue-200">
              {t('apiKeys.whereToGet')}
            </h4>
            <p className="mt-1 text-sm text-blue-600 dark:text-blue-400">
              {t('apiKeys.whereToGetDescription')}
            </p>
          </div>
        </div>
      </div>

      {/* Usage hint */}
      <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          {t('apiKeys.usageTitle')}
        </h4>
        <code className="block text-xs text-gray-600 dark:text-gray-400 font-mono bg-white dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-700">
          curl -H &quot;X-API-Key: sb_your-key-here&quot; {window.location.origin}/api/v1/connections
        </code>
      </div>
    </div>
  )
}
