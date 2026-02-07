import axios from 'axios'
import type { Connection, ConnectionConfig, SchemaData, TableSampleData } from '../types'

const API_BASE_URL = '/api/v1'

// For now, using a demo token. In production, this should come from authentication
const DEMO_TOKEN = 'demo-token'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add authorization header to all requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('sandbox_token') || DEMO_TOKEN
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export const connectionsApi = {
  // List all connections
  list: async (): Promise<Connection[]> => {
    const response = await api.get('/connections')
    return response.data.connections
  },

  // Create a new connection
  create: async (connection: ConnectionConfig): Promise<{ id: string; name: string }> => {
    const response = await api.post('/connections', connection)
    return response.data
  },

  // Update an existing connection
  update: async (id: string, connection: ConnectionConfig): Promise<void> => {
    await api.put(`/connections/${id}`, connection)
  },

  // Delete a connection
  delete: async (id: string): Promise<void> => {
    await api.delete(`/connections/${id}`)
  },

  // Test a connection
  test: async (connection: ConnectionConfig): Promise<{ success: boolean; message: string }> => {
    const response = await api.post('/connections/test', connection)
    return response.data
  },
}

export const schemaApi = {
  // Sync schema from a connection
  sync: async (
    connectionId: string,
    includeSamples: boolean = true,
    sampleLimit: number = 10
  ): Promise<SchemaData> => {
    const response = await api.get('/schema/sync', {
      params: {
        connection_id: connectionId,
        include_samples: includeSamples,
        sample_limit: sampleLimit,
      },
    })
    return response.data.data
  },

  // Get table samples
  getTableSamples: async (
    connectionId: string,
    tableName: string,
    limit: number = 10
  ): Promise<TableSampleData> => {
    const response = await api.get(`/schema/table/${tableName}/samples`, {
      params: {
        connection_id: connectionId,
        limit,
      },
    })
    return response.data
  },
}

export const executionApi = {
  // Execute SQL query
  executeSQL: async (
    connectionId: string,
    query: string,
    parameters?: Record<string, unknown>
  ) => {
    const response = await api.post('/execute/sql', {
      context: {
        connection_id: connectionId,
      },
      query,
      parameters,
    })
    return response.data
  },

  // Execute Python code
  executePython: async (code: string, inputData?: Record<string, unknown>) => {
    const response = await api.post('/execute/python', {
      context: {},
      code,
      input_data: inputData,
    })
    return response.data
  },
}
