import { useEffect } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { embedBridge } from '../../lib/embedBridge'

/**
 * Layout for embed mode (no header, no sidebar, no auth wall).
 * Used when sandbox is loaded inside an iframe in the MVP UI.
 *
 * - No navigation chrome (MVP provides its own)
 * - Listens for navigation commands from parent
 * - Reports route changes to parent
 * - Auto-resizes to content height
 */
export function EmbedLayout() {
  const location = useLocation()
  const navigate = useNavigate()

  // Initialize embed bridge and listen for MVP messages
  useEffect(() => {
    // Handle init message from MVP (token, theme, locale)
    const unsubInit = embedBridge.on('mvp:init', (data) => {
      const { token, theme } = data as { token?: string; theme?: string }

      // Store the auth token for API calls
      if (token) {
        localStorage.setItem('sandbox_api_key', token)
      }

      // Apply theme
      if (theme === 'dark') {
        document.documentElement.classList.add('dark')
      } else {
        document.documentElement.classList.remove('dark')
      }
    })

    // Handle navigation commands from MVP
    const unsubNav = embedBridge.on('mvp:navigate', (data) => {
      const { path } = data as { path: string }
      if (path) {
        navigate(path)
      }
    })

    // Handle theme changes from MVP
    const unsubTheme = embedBridge.on('mvp:theme-changed', (data) => {
      const { theme } = data as { theme: string }
      if (theme === 'dark') {
        document.documentElement.classList.add('dark')
      } else {
        document.documentElement.classList.remove('dark')
      }
    })

    return () => {
      unsubInit()
      unsubNav()
      unsubTheme()
    }
  }, [navigate])

  // Notify parent when route changes inside the iframe
  useEffect(() => {
    // Strip the /embed prefix before sending to parent
    const embedPath = location.pathname.replace(/^\/embed/, '')
    embedBridge.notifyNavigate(embedPath || '/')
  }, [location.pathname])

  return (
    <div className="embed-container min-h-0">
      <Outlet />
    </div>
  )
}
