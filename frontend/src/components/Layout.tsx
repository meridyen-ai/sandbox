import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { Database, Settings, LogOut, Key } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

export function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout, apiKey } = useAuth()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center space-x-8">
              <h1 className="text-xl font-bold text-gray-900 dark:text-white">
                Meridyen Sandbox
              </h1>
              <nav className="flex space-x-4">
                <Link
                  to="/connections"
                  className={`px-3 py-2 rounded-md text-sm font-medium ${
                    location.pathname.startsWith('/connections')
                      ? 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white'
                      : 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'
                  }`}
                >
                  <Database className="inline-block w-4 h-4 mr-1" />
                  Connections
                </Link>
              </nav>
            </div>
            <div className="flex items-center space-x-4">
              {/* API Key Indicator */}
              <div className="hidden md:flex items-center space-x-2 px-3 py-1 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
                <Key className="w-4 h-4 text-green-600 dark:text-green-400" />
                <span className="text-xs font-medium text-green-700 dark:text-green-300">
                  {apiKey?.substring(0, 10)}...
                </span>
              </div>

              <button
                onClick={handleLogout}
                className="flex items-center space-x-2 px-3 py-2 rounded-md text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
                title="Logout"
              >
                <LogOut className="w-4 h-4" />
                <span className="hidden sm:inline">Logout</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
