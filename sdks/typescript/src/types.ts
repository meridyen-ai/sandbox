// ============================================================================
// Configuration
// ============================================================================

export interface SandboxClientConfig {
  /** Base URL of the sandbox REST API (e.g., "http://localhost:8080") */
  baseUrl: string
  /** API key for authentication (sb_xxx) */
  apiKey?: string
  /** Request timeout in milliseconds (default: 30000) */
  timeout?: number
  /** Additional headers to send with every request */
  headers?: Record<string, string>
}

// ============================================================================
// Execution
// ============================================================================

export interface ExecutionContext {
  /** Unique request identifier (auto-generated if not provided) */
  request_id?: string
  /** Workspace ID */
  workspace_id?: string
  /** Database connection ID (required for SQL execution) */
  connection_id?: string
  /** User ID */
  user_id?: string
  /** Maximum rows to return */
  max_rows?: number
  /** Execution timeout in seconds */
  timeout_seconds?: number
}

export interface SQLExecutionRequest {
  context: ExecutionContext
  query: string
  parameters?: Record<string, unknown>
}

export interface PythonExecutionRequest {
  context: ExecutionContext
  code: string
  input_data?: Record<string, unknown>
  variables?: Record<string, unknown>
}

export interface ExecutionMetrics {
  duration_ms: number
  rows_processed?: number
  memory_used_mb?: number
}

export interface SQLExecutionResult {
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  metrics?: ExecutionMetrics
}

export interface PythonExecutionResult {
  stdout: string
  stderr: string
  result_data?: unknown
  metrics?: ExecutionMetrics
}

// ============================================================================
// Visualization
// ============================================================================

export type ChartType =
  | 'auto'
  | 'line'
  | 'bar'
  | 'pie'
  | 'scatter'
  | 'heatmap'
  | 'table'
  | 'area'
  | 'histogram'

export interface VisualizationRequest {
  context: ExecutionContext
  instruction: string
  data: Record<string, unknown>[]
  chart_type?: ChartType
  title?: string
}

export interface VisualizationResult {
  plotly_spec: Record<string, unknown>
  insight?: string
}

// ============================================================================
// Connections
// ============================================================================

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
  ssl_enabled?: boolean
}

export interface ConnectionTestResult {
  success: boolean
  message: string
}

// ============================================================================
// Schema
// ============================================================================

export interface TableColumn {
  name: string
  data_type: string
  nullable?: boolean
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

export interface SchemaSyncOptions {
  include_samples?: boolean
  sample_limit?: number
}

export interface FullSyncResult {
  connections: SchemaData[]
}

// ============================================================================
// Health & Capabilities
// ============================================================================

export interface HealthResponse {
  status: string
  version: string
  uptime_seconds: number
  components?: Record<string, unknown>
}

export interface CapabilitiesResponse {
  sandbox_id?: string
  supported_databases: string[]
  supported_packages: string[]
  resource_limits: Record<string, unknown>
  has_local_llm: boolean
}

export interface HandlerInfo {
  name: string
  type: string
  title: string
  description: string
  icon?: string
  available: boolean
  error?: string
}
