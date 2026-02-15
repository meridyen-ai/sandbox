export class SandboxError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public details?: unknown,
  ) {
    super(message)
    this.name = 'SandboxError'
  }
}

export class SandboxAuthError extends SandboxError {
  constructor(message: string = 'Authentication failed') {
    super(message, 401)
    this.name = 'SandboxAuthError'
  }
}

export class SandboxTimeoutError extends SandboxError {
  constructor(message: string = 'Request timed out') {
    super(message, 408)
    this.name = 'SandboxTimeoutError'
  }
}
