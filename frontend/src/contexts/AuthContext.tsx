import React, { createContext, useContext, useState, useEffect } from 'react'

interface AuthContextType {
  apiKey: string | null
  isAuthenticated: boolean
  login: (key: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

const STORAGE_KEY = 'sandbox_api_key'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [apiKey, setApiKey] = useState<string | null>(null)

  // Load API key from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      setApiKey(stored)
    }
  }, [])

  const login = (key: string) => {
    localStorage.setItem(STORAGE_KEY, key)
    setApiKey(key)
  }

  const logout = () => {
    localStorage.removeItem(STORAGE_KEY)
    setApiKey(null)
  }

  const value = {
    apiKey,
    isAuthenticated: !!apiKey,
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
