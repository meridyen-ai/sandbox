import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ConnectionsPage } from './components/connections/ConnectionsPage'
import { DatasetPage } from './components/dataset/DatasetPage'
import { LoginPage } from './components/auth/LoginPage'
import { ProtectedRoute } from './components/auth/ProtectedRoute'

function App() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <Routes>
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
        </Route>
      </Routes>
    </div>
  )
}

export default App
