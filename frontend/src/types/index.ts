export interface Connection {
  id: string
  name: string
  db_type: string
  host: string
  port: number
  database: string
  schema?: string
  is_default?: boolean
  created_at?: string
  updated_at?: string
}

export interface ConnectionConfig {
  id?: string
  name: string
  db_type: string
  host: string
  port: number
  database: string
  username: string
  password: string
  schema_name?: string
  ssl_enabled: boolean
}

export interface TableColumn {
  name: string
  data_type: string
  is_nullable?: boolean
  is_primary_key?: boolean
}

export interface TableSampleData {
  columns: string[]
  rows: Record<string, unknown>[]
  total_rows: number
}

export interface Table {
  name: string
  columns: TableColumn[]
  sample_data?: TableSampleData | null
}

export interface SchemaData {
  connection_id: string
  connection_name: string
  database: string
  db_type: string
  schema?: string
  tables: Table[]
}
