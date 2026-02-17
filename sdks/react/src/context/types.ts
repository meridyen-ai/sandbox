import type {
  HandlerInfo,
  Connection,
  ConnectionConfig,
  SelectedSchema,
  SchemaData,
} from '../types'

export interface FileUploadResult {
  success: boolean
  message: string
  connection_id: string
  connections?: Array<{ connection_id: string; name: string; sheet_name: string; row_count: number }>
  row_count: number
  column_count?: number
  file_path: string
  sheets?: string[]
}

export interface SheetInfo {
  name: string
  columns: string[]
  preview_rows: number
}

// Query Explorer types
export interface QueryColumn {
  name: string
  type: string
}

export interface QueryResult {
  columns: QueryColumn[]
  rows: any[]
  row_count: number
  total_rows_available?: number
}

export interface QueryExecutionResponse {
  status: 'success' | 'error'
  data?: QueryResult
  message?: string
}

export interface ConnectionWithSchema {
  id: string
  name: string
  db_type: string
  host: string
  port: number
  database: string
  tables: Array<{
    name: string
    columns: Array<{ name: string; data_type: string }>
  }>
}

export interface AIGenerateQueryResponse {
  success: boolean
  sql_query?: string
  explanation?: string
  error?: string
}

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
  files?: {
    upload: (file: File, name: string, options: {
      delimiter?: string
      hasHeader?: boolean
      selectedSheets?: string[]
    }) => Promise<FileUploadResult>
    getSheets: (file: File) => Promise<{ sheets: SheetInfo[] }>
    uploadGoogleSheet?: (params: {
      name: string
      spreadsheet_id: string
      credentials_json: string
      worksheet_name?: string
    }) => Promise<FileUploadResult>
  }
  query?: {
    fullSync: () => Promise<{ connections: ConnectionWithSchema[] }>
    executeSql: (connectionId: string, sql: string) => Promise<QueryExecutionResponse>
  }
  ai?: {
    generateQuery: (connectionId: string, userQuery: string) => Promise<AIGenerateQueryResponse>
  }
}

export interface SandboxUIConfig {
  api: SandboxUIApi
  iconBasePath: string
  t: (key: string, params?: Record<string, string>) => string
  onNavigate?: (path: string) => void
}
