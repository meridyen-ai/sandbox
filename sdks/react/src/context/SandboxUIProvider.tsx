import React from 'react'
import { SandboxUIContext } from './SandboxUIContext'
import type { SandboxUIApi, SandboxUIConfig } from './types'
import { defaultT } from '../i18n/defaultTranslations'

export interface SandboxUIProviderProps {
  api: SandboxUIApi
  iconBasePath?: string
  t?: (key: string, params?: Record<string, string>) => string
  onNavigate?: (path: string) => void
  children: React.ReactNode
}

export const SandboxUIProvider: React.FC<SandboxUIProviderProps> = ({
  children,
  api,
  iconBasePath = '/icons/databases',
  t,
  onNavigate,
}) => {
  const config: SandboxUIConfig = {
    api,
    iconBasePath,
    t: t || defaultT,
    onNavigate,
  }

  return (
    <SandboxUIContext.Provider value={config}>
      {children}
    </SandboxUIContext.Provider>
  )
}
