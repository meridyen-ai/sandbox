# Contributing to Meridyen Sandbox

Thank you for your interest in contributing! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Commit Messages](#commit-messages)
- [Issue Guidelines](#issue-guidelines)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to [conduct@meridyen.ai](mailto:conduct@meridyen.ai).

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/sandbox.git
   cd sandbox
   ```
3. **Add upstream remote:**
   ```bash
   git remote add upstream https://github.com/meridyen-ai/sandbox.git
   ```
4. **Create a branch** for your work:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### With Docker (recommended)

```bash
make dev-full
```

This starts the backend and frontend with hot reload. See [DEVELOPMENT.md](DEVELOPMENT.md) for details.

### Without Docker

```bash
# Install Python dependencies
pip install -e ".[dev]"

# Install frontend dependencies
cd frontend && npm install && cd ..

# Run locally
make dev-local
```

### Running Tests

```bash
make test           # Full test suite with coverage
make test-quick     # Quick test run (stops on first failure)
```

### Linting and Formatting

```bash
make lint           # Check code style (ruff + mypy)
make format         # Auto-format (black + ruff fix)
```

## How to Contribute

### Reporting Bugs

- Check [existing issues](https://github.com/meridyen-ai/sandbox/issues) first
- Use the **Bug Report** issue template
- Include steps to reproduce, expected vs actual behavior, and environment details

### Suggesting Features

- Use the **Feature Request** issue template
- Explain the use case and why it would be valuable
- Be open to discussion about alternative approaches

### Submitting Code

1. Pick an issue (or create one first for larger changes)
2. Comment on the issue to let others know you're working on it
3. Follow the [Pull Request Process](#pull-request-process) below

### Good First Issues

Look for issues labeled [`good first issue`](https://github.com/meridyen-ai/sandbox/labels/good%20first%20issue) — these are specifically chosen to be approachable for newcomers.

## Pull Request Process

1. **Sync with upstream** before starting work:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Make your changes** in a feature branch

3. **Write/update tests** for your changes

4. **Ensure all checks pass:**
   ```bash
   make test
   make lint
   ```

5. **Push your branch:**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Open a Pull Request** against `main` with:
   - A clear title describing the change
   - A description explaining **what** and **why**
   - Reference to related issues (e.g., `Closes #42`)

7. **Address review feedback** — maintainers may request changes

8. Once approved, a maintainer will merge your PR

### PR Requirements

- All CI checks must pass
- At least one maintainer approval required
- No merge conflicts with `main`
- Tests added/updated for new functionality

## Coding Standards

### Python (Backend)

- **Python 3.11+** required
- **Formatter:** Black (line length 100)
- **Linter:** Ruff
- **Type checker:** mypy (strict mode)
- Use type hints for all function signatures
- Use `structlog` for logging
- Use `pydantic` for data validation

### TypeScript (Frontend)

- **TypeScript** strict mode
- **React 18** with functional components and hooks
- **TanStack Query** for server state
- **Tailwind CSS** for styling
- Keep components small and focused

### General

- Write clear, self-documenting code
- Add comments only where logic is non-obvious
- Keep functions focused on a single responsibility
- Avoid premature abstraction

## Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no logic change |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `chore` | Build process, tooling, dependencies |
| `perf` | Performance improvement |

### Examples

```
feat(connectors): add Snowflake connector support
fix(execution): prevent SQL injection in parameterized queries
docs: update development setup instructions
test(handlers): add unit tests for PostgreSQL handler
```

## Issue Guidelines

- **Search first** — your issue may already exist
- **One issue per bug/feature** — don't bundle multiple topics
- **Be specific** — vague issues are hard to act on
- **Include context** — OS, Docker version, Python version, error logs

## Branch Naming

```
feature/description     # New features
fix/description         # Bug fixes
docs/description        # Documentation
refactor/description    # Refactoring
test/description        # Test additions
```

## Questions?

- Open a [Discussion](https://github.com/meridyen-ai/sandbox/discussions) for general questions
- Tag maintainers in issues if you're stuck

Thank you for contributing!
