import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { Database, Key, AlertCircle } from 'lucide-react'
import { useTranslation } from '../../hooks/useTranslation'

export function LoginPage() {
  const { t } = useTranslation()
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState('')
  const [isValidating, setIsValidating] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!apiKey.trim()) {
      setError(t('login.errors.emptyKey'))
      return
    }

    if (!apiKey.startsWith('sb_')) {
      setError(t('login.errors.invalidFormat'))
      return
    }

    setIsValidating(true)

    try {
      // Validate the API key by making a test request to the sandbox health endpoint
      const response = await fetch('http://localhost:8081/health', {
        headers: {
          'X-API-Key': apiKey,
        },
      })

      if (response.ok) {
        login(apiKey)
        navigate('/connections')
      } else {
        setError(t('login.errors.validationFailed'))
      }
    } catch (err) {
      setError(t('login.errors.connectionFailed'))
    } finally {
      setIsValidating(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800 flex items-center justify-center p-4">
      <div className="max-w-md w-full">
        {/* Logo and Title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-2xl mb-4">
            <Database className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
            {t('login.title')}
          </h1>
          <p className="text-gray-600 dark:text-gray-400">
            {t('login.subtitle')}
          </p>
        </div>

        {/* Login Form */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label
                htmlFor="apiKey"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                {t('login.apiKeyLabel')}
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Key className="h-5 w-5 text-gray-400" />
                </div>
                <input
                  id="apiKey"
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="block w-full pl-10 pr-3 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                  placeholder={t('login.apiKeyPlaceholder')}
                  autoComplete="off"
                  disabled={isValidating}
                />
              </div>
              <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                {t('login.apiKeyHelp')}
              </p>
            </div>

            {error && (
              <div className="flex items-start space-x-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={isValidating}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-3 px-4 rounded-lg transition-colors duration-200 disabled:cursor-not-allowed"
            >
              {isValidating ? t('login.validating') : t('login.continue')}
            </button>
          </form>

          {/* Help Text */}
          <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
            <p className="text-sm text-gray-600 dark:text-gray-400 text-center">
              {t('login.noApiKey')}{' '}
              <a
                href="http://localhost:13000"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
              >
                {t('login.createApiKey')}
              </a>
            </p>
          </div>
        </div>

        {/* Additional Info */}
        <div className="mt-6 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {t('login.apiKeyPrefix')} <code className="px-2 py-1 bg-gray-200 dark:bg-gray-700 rounded">sb_</code>
          </p>
        </div>
      </div>
    </div>
  )
}
