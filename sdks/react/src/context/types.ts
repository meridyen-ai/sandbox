import type {
  HandlerInfo,
  Connection,
  ConnectionConfig,
  SelectedSchema,
  SchemaData,
  TableWithColumns,
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

/** A table as the paginated list reports it: identity and counts, no columns. */
export interface TableSummary {
  schema_name: string
  table_name: string
  full_name: string
  table_type: string
  column_count: number
  has_columns: boolean
  has_samples?: boolean
  selected: boolean
}

export interface TablePage {
  total: number
  offset: number
  limit: number
  tables: TableSummary[]
  sync_status?: string
  sync_phase?: string
  sync_error?: string | null
  tables_total?: number
  tables_done?: number
}

export interface SchemaSyncStatus {
  sync_status: string
  sync_phase?: string
  sync_error?: string | null
  table_count?: number
  tables_total?: number
  tables_done?: number
  in_progress?: boolean
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
    sync: (connectionId: string, includeSamples?: boolean, sampleLimit?: number, forceRefresh?: boolean) => Promise<SchemaData>
    /**
     * One page of table names, resolved server-side.
     *
     * Optional: a host that does not implement it gets the old behaviour,
     * where `sync` returns every table with every column and the picker slices
     * the list itself. Implement it and the picker stops asking for tens of
     * thousands of columns it will not draw.
     */
    listTables?: (
      connectionId: string,
      opts: { search?: string; offset?: number; limit?: number; selectedOnly?: boolean },
    ) => Promise<TablePage>
    /** Columns for the tables named — what `listTables` deliberately omits. */
    getTableColumns?: (
      connectionId: string,
      tableNames: string[],
    ) => Promise<TableWithColumns[]>
    /** Progress of a sync that is still running, for the picker's status line. */
    status?: (connectionId: string) => Promise<SchemaSyncStatus>
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
