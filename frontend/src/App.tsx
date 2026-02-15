import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { EmbedLayout } from './components/embed/EmbedLayout'
import { ConnectionsPage } from './components/connections/ConnectionsPage'
import { DatasetPage } from './components/dataset/DatasetPage'
import { ArchitecturePage } from './components/architecture/ArchitecturePage'
import { LoginPage } from './components/auth/LoginPage'
import { ProtectedRoute } from './components/auth/ProtectedRoute'

function App() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
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
    </div>
  )
}

export default App
