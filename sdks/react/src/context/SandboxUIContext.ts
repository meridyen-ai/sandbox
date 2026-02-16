import { createContext, useContext } from 'react'
import type { SandboxUIConfig } from './types'

export const SandboxUIContext = createContext<SandboxUIConfig | null>(null)

export function useSandboxUI(): SandboxUIConfig {
  const ctx = useContext(SandboxUIContext)
  if (!ctx) {
    throw new Error('useSandboxUI must be used within a <SandboxUIProvider>')
  }
  return ctx
}

export function useSandboxApi() {
  return useSandboxUI().api
}

export function useSandboxTranslation() {
  return { t: useSandboxUI().t }
}
