# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Meridyen Sandbox, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

### How to Report

Send an email to: **security@meridyen.ai**

Include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment:** within 48 hours
- **Initial assessment:** within 5 business days
- **Fix timeline:** depends on severity, typically within 30 days

### What to Expect

1. We will acknowledge your report promptly
2. We will investigate and validate the issue
3. We will develop and test a fix
4. We will release the fix and credit you (unless you prefer anonymity)

### Scope

The following are in scope:

- SQL injection or query escape bypasses
- Python sandbox escapes (RestrictedPython bypasses)
- Authentication or authorization bypasses
- Data leakage between tenants or sessions
- gRPC or REST API vulnerabilities
- Container escape vectors
- mTLS certificate validation issues

### Out of Scope

- Vulnerabilities in third-party dependencies (report upstream, but let us know)
- Issues requiring physical access
- Social engineering

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | Yes       |
| < 1.0   | No        |

## Security Best Practices for Deployers

- Always use mTLS in production
- Rotate API keys regularly
- Use the air-gapped deployment mode for sensitive environments
- Keep Docker images up to date
- Review `config/sandbox.yaml` for secure defaults
