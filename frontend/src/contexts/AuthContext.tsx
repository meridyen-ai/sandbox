import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import axios from 'axios'

interface AuthContextType {
  username: string | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [username, setUsername] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Check existing session on mount
  useEffect(() => {
    const checkSession = async () => {
      try {
        const response = await axios.get('/api/v1/auth/me', {
          withCredentials: true,
        })
        if (response.data.authenticated) {
          setUsername(response.data.username)
        }
      } catch {
        // Not authenticated — that's fine
      } finally {
        setIsLoading(false)
      }
    }
    checkSession()
  }, [])

  const login = useCallback(async (user: string, password: string) => {
    const response = await axios.post(
      '/api/v1/auth/login',
      { username: user, password },
      { withCredentials: true }
    )
    if (response.status === 200) {
      setUsername(response.data.username)
    } else {
      throw new Error('Login failed')
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      await axios.post('/api/v1/auth/logout', {}, { withCredentials: true })
    } catch {
      // Ignore errors on logout
    }
    setUsername(null)
  }, [])

  const value = {
    username,
    isAuthenticated: !!username,
    isLoading,
    login,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
