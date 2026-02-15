import { SandboxError, SandboxAuthError, SandboxTimeoutError } from './errors'
import type {
  SandboxClientConfig,
  SQLExecutionRequest,
  SQLExecutionResult,
  PythonExecutionRequest,
  PythonExecutionResult,
  VisualizationRequest,
  VisualizationResult,
  Connection,
  ConnectionConfig,
  ConnectionTestResult,
  SchemaData,
  SchemaSyncOptions,
  FullSyncResult,
  TableSampleData,
  HealthResponse,
  CapabilitiesResponse,
  HandlerInfo,
} from './types'

export class SandboxClient {
  private baseUrl: string
  private apiKey: string
  private timeout: number
  private headers: Record<string, string>

  constructor(config: SandboxClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '')
    this.apiKey = config.apiKey ?? ''
    this.timeout = config.timeout ?? 30000
    this.headers = config.headers ?? {}
  }

  // ========================================================================
  // Execution
  // ========================================================================

  /** Execute a SQL query against a database connection. */
  async executeSQL(request: SQLExecutionRequest): Promise<SQLExecutionResult> {
    return this.post('/api/v1/execute/sql', request)
  }

  /** Execute Python code in a secure sandbox. */
  async executePython(request: PythonExecutionRequest): Promise<PythonExecutionResult> {
    return this.post('/api/v1/execute/python', request)
  }

  /** Generate a Plotly visualization from data. */
  async createVisualization(request: VisualizationRequest): Promise<VisualizationResult> {
    return this.post('/api/v1/visualize', request)
  }

  // ========================================================================
  // Connections
  // ========================================================================

  /** List all configured database connections. */
  async listConnections(): Promise<Connection[]> {
    const data = await this.get<{ connections: Connection[] }>('/api/v1/connections')
    return data.connections
  }

  /** Create a new database connection. */
  async createConnection(config: ConnectionConfig): Promise<{ id: string; name: string }> {
    return this.post('/api/v1/connections', config)
  }

  /** Update an existing database connection. */
  async updateConnection(id: string, config: ConnectionConfig): Promise<void> {
    await this.put(`/api/v1/connections/${id}`, config)
  }

  /** Delete a database connection. */
  async deleteConnection(id: string): Promise<void> {
    await this.delete(`/api/v1/connections/${id}`)
  }

  /** Test a database connection. */
  async testConnection(config: ConnectionConfig): Promise<ConnectionTestResult> {
    return this.post('/api/v1/connections/test', config)
  }

  // ========================================================================
  // Schema
  // ========================================================================

  /** Sync schema metadata from a database connection. */
  async syncSchema(connectionId: string, options?: SchemaSyncOptions): Promise<SchemaData> {
    const params = new URLSearchParams({ connection_id: connectionId })
    if (options?.include_samples !== undefined) {
      params.set('include_samples', String(options.include_samples))
    }
    if (options?.sample_limit !== undefined) {
      params.set('sample_limit', String(options.sample_limit))
    }
    const data = await this.get<{ data: SchemaData }>(`/api/v1/schema/sync?${params}`)
    return data.data
  }

  /** Bulk sync all connections with schemas. */
  async fullSync(options?: SchemaSyncOptions): Promise<FullSyncResult> {
    const params = new URLSearchParams()
    if (options?.include_samples !== undefined) {
      params.set('include_samples', String(options.include_samples))
    }
    if (options?.sample_limit !== undefined) {
      params.set('sample_limit', String(options.sample_limit))
    }
    const query = params.toString()
    return this.get(`/api/v1/schema/full-sync${query ? `?${query}` : ''}`)
  }

  /** Get sample data from a specific table. */
  async getTableSamples(
    connectionId: string,
    tableName: string,
    limit: number = 10,
  ): Promise<TableSampleData> {
    const params = new URLSearchParams({
      connection_id: connectionId,
      limit: String(limit),
    })
    return this.get(`/api/v1/schema/table/${encodeURIComponent(tableName)}/samples?${params}`)
  }

  // ========================================================================
  // Health & Capabilities
  // ========================================================================

  /** Check sandbox health status. */
  async health(): Promise<HealthResponse> {
    return this.get('/health')
  }

  /** Get sandbox capabilities and resource limits. */
  async capabilities(): Promise<CapabilitiesResponse> {
    return this.get('/capabilities')
  }

  /** List available database handlers. */
  async listHandlers(): Promise<HandlerInfo[]> {
    const data = await this.get<{ handlers: HandlerInfo[] }>('/api/v1/handlers')
    return data.handlers
  }

  // ========================================================================
  // HTTP helpers (zero dependencies — uses native fetch)
  // ========================================================================

  private async get<T = unknown>(path: string): Promise<T> {
    return this.request('GET', path)
  }

  private async post<T = unknown>(path: string, body?: unknown): Promise<T> {
    return this.request('POST', path, body)
  }

  private async put<T = unknown>(path: string, body?: unknown): Promise<T> {
    return this.request('PUT', path, body)
  }

  private async delete<T = unknown>(path: string): Promise<T> {
    return this.request('DELETE', path)
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const url = `${this.baseUrl}${path}`
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...this.headers,
    }

    if (this.apiKey) {
      headers['X-API-Key'] = this.apiKey
    }

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), this.timeout)

    try {
      const response = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      })

      if (!response.ok) {
        if (response.status === 401) {
          throw new SandboxAuthError()
        }

        let details: unknown
        try {
          details = await response.json()
        } catch {
          details = await response.text()
        }

        throw new SandboxError(
          `Request failed: ${response.status} ${response.statusText}`,
          response.status,
          details,
        )
      }

      return (await response.json()) as T
    } catch (error) {
      if (error instanceof SandboxError) throw error

      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new SandboxTimeoutError()
      }

      throw new SandboxError(
        `Network error: ${error instanceof Error ? error.message : String(error)}`,
      )
    } finally {
      clearTimeout(timeoutId)
    }
  }
}
