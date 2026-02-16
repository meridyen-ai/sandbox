/**
 * Adapter hook that wraps the sandbox's useApi() into the SandboxUIApi shape
 * required by @meridyen/sandbox-ui SDK components (e.g. DatabaseExplorer).
 */

import { useMemo } from 'react'
import { useApi } from './useApi'
import type { SandboxUIApi } from '@meridyen/sandbox-ui'

export function useSandboxApiAdapter(): SandboxUIApi {
  const { callApi } = useApi()

  return useMemo((): SandboxUIApi => ({
    handlers: {
      list: async () => {
        const response = await callApi('/api/v1/handlers', { method: 'GET' })
        return response?.handlers ?? response ?? []
      },
    },
    connections: {
      list: async () => {
        const response = await callApi('/api/v1/connections', { method: 'GET' })
        return response?.connections ?? response ?? []
      },
      create: async (config) => {
        const response = await callApi('/api/v1/connections', {
          method: 'POST',
          data: config,
        })
        return { id: String(response?.id ?? ''), name: config.name }
      },
      update: async (id, config) => {
        await callApi(`/api/v1/connections/${id}`, {
          method: 'PUT',
          data: config,
        })
      },
      delete: async (id) => {
        await callApi(`/api/v1/connections/${id}`, { method: 'DELETE' })
      },
      test: async (config) => {
        const response = await callApi('/api/v1/connections/test', {
          method: 'POST',
          data: config,
        })
        return { success: response?.success ?? false, message: response?.message ?? '' }
      },
      getSelectedTables: async (connectionId) => {
        const response = await callApi(`/api/v1/connections/${connectionId}/selected-tables`, { method: 'GET' })
        return response?.selected_schema ?? {}
      },
      saveSelectedTables: async (connectionId, tables) => {
        await callApi(`/api/v1/connections/${connectionId}/selected-tables`, {
          method: 'PUT',
          data: { selected_schema: tables },
        })
      },
    },
    schema: {
      sync: async (connectionId, includeSamples, sampleLimit) => {
        const params: Record<string, any> = {}
        if (includeSamples !== undefined) params.include_samples = includeSamples
        if (sampleLimit !== undefined) params.sample_limit = sampleLimit
        const response = await callApi(`/api/v1/schema/sync/${connectionId}`, {
          method: 'GET',
          params,
        })
        return response as any
      },
    },
    query: {
      fullSync: async () => {
        const response = await callApi('/api/v1/schema/full-sync', { method: 'GET' })
        return { connections: response?.connections ?? response?.data ?? [] }
      },
      executeSql: async (connectionId, sql) => {
        const response = await callApi('/api/v1/execute/sql', {
          method: 'POST',
          data: {
            context: { connection_id: connectionId },
            query: sql,
          },
        })
        return {
          status: response?.status === 'success' ? 'success' as const : 'error' as const,
          data: response?.data,
          message: response?.message,
        }
      },
    },
    ai: {
      generateQuery: async (connectionId, userQuery) => {
        const response = await callApi('/api/v1/ai/generate-query', {
          method: 'POST',
          data: {
            connection_id: connectionId,
            user_query: userQuery,
          },
        })
        return {
          success: response?.success ?? false,
          sql_query: response?.sql_query,
          explanation: response?.explanation,
          error: response?.error,
        }
      },
    },
  }), [callApi])
}
