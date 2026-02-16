import type {
  HandlerInfo,
  Connection,
  ConnectionConfig,
  SelectedSchema,
  SchemaData,
} from '../types'

export interface SandboxUIApi {
  handlers: {
    list: () => Promise<HandlerInfo[]>
  }
  connections: {
    list: () => Promise<Connection[]>
    create: (config: ConnectionConfig) => Promise<{ id: string; name: string }>
    update: (id: string, config: ConnectionConfig) => Promise<void>
    delete: (id: string) => Promise<void>
    test: (config: ConnectionConfig) => Promise<{ success: boolean; message: string }>
    getSelectedTables: (connectionId: string) => Promise<SelectedSchema>
    saveSelectedTables: (connectionId: string, tables: SelectedSchema) => Promise<void>
  }
  schema: {
    sync: (connectionId: string, includeSamples?: boolean, sampleLimit?: number) => Promise<SchemaData>
  }
}

export interface SandboxUIConfig {
  api: SandboxUIApi
  iconBasePath: string
  t: (key: string, params?: Record<string, string>) => string
  onNavigate?: (path: string) => void
}
