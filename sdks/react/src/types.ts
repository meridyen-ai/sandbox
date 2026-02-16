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
  type: string
  nullable: boolean
  default?: string | null
  max_length?: number | null
  precision?: number | null
  scale?: number | null
  is_primary_key?: boolean
  is_unique?: boolean
  is_foreign_key?: boolean
  foreign_table?: string | null
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

export interface ConnectionArgOption {
  value: string
  label: string
}

export interface ConnectionArgDependsOn {
  field: string
  values: string[]
}

export interface ConnectionArg {
  name: string
  type: string
  description: string
  required: boolean
  label: string
  secret?: boolean
  default?: unknown
  options?: ConnectionArgOption[]
  depends_on?: ConnectionArgDependsOn
}

export interface HandlerInfo {
  name: string
  type: string
  title: string
  description: string
  icon?: string
  available: boolean
  error?: string
  connection_args: ConnectionArg[]
}

export interface ColumnInfo {
  name: string
  data_type: string
  nullable: boolean
  default_value?: string | null
  sample_data?: string | null
}

export interface TableWithColumns {
  schema_name: string
  table_name: string
  table_type: string
  full_name: string
  columns: ColumnInfo[]
}

export interface SelectedSchema {
  [tableFullName: string]: {
    selected: boolean
    columns: string[]
  }
}
