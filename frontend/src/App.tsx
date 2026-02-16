import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { SandboxUIProvider, ConnectionsPage } from '@meridyen/sandbox-ui'
import { Layout } from './components/Layout'
import { EmbedLayout } from './components/embed/EmbedLayout'
import { DatasetPage } from './components/dataset/DatasetPage'
import { ArchitecturePage } from './components/architecture/ArchitecturePage'
import { LoginPage } from './components/auth/LoginPage'
import { ProtectedRoute } from './components/auth/ProtectedRoute'
import { sandboxApi } from './utils/sandboxApiAdapter'
import { useTranslation } from './hooks/useTranslation'

function AppRoutes() {
  const navigate = useNavigate()
  const { t } = useTranslation()

  return (
    <SandboxUIProvider
      api={sandboxApi}
      iconBasePath="/icons/databases"
      t={t}
      onNavigate={(path) => navigate(path)}
    >
      <Routes>
        {/* ============================================= */}
        {/* Standalone mode (hybrid/self-hosted users)    */}
        {/* Full app with header, nav, and auth           */}
        {/* ============================================= */}
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/connections" replace />} />
          <Route path="connections" element={<ConnectionsPage />} />
          <Route path="dataset/:connectionId" element={<DatasetPage />} />
          <Route path="architecture" element={<ArchitecturePage />} />
        </Route>

        {/* ============================================= */}
        {/* Embed mode (loaded in host app iframe)         */}
        {/* No header/nav/auth - host app handles those   */}
        {/* ============================================= */}
        <Route path="/embed" element={<EmbedLayout />}>
          <Route index element={<Navigate to="/embed/connections" replace />} />
          <Route path="connections" element={<ConnectionsPage />} />
          <Route path="dataset/:connectionId" element={<DatasetPage />} />
          <Route path="architecture" element={<ArchitecturePage />} />
        </Route>
      </Routes>
    </SandboxUIProvider>
  )
}

function App() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <AppRoutes />
    </div>
  )
}

export default App
