# Meridyen Sandbox UI

Web-based user interface for managing database connections and viewing datasets in the Meridyen Sandbox.

## Features

- **Connection Management**: Create, test, and manage database connections
- **Dataset Viewer**: Browse tables, view columns, and preview sample data
- **Dark Mode Support**: Fully responsive with dark/light theme
- **Real-time Sync**: Fetch schema and sample data from databases

## Development

### Prerequisites

- Node.js 18+ and npm
- Meridyen Sandbox backend running on http://localhost:8080

### Install Dependencies

```bash
npm install
```

### Run Development Server

```bash
npm run dev
```

The UI will be available at http://localhost:3000

### Build for Production

```bash
npm run build
```

The build output will be in the `dist/` directory.

## Architecture

- **Framework**: React 18 + TypeScript
- **Routing**: React Router v6
- **State Management**: TanStack Query (React Query)
- **Styling**: Tailwind CSS
- **HTTP Client**: Axios
- **Build Tool**: Vite

## API Integration

The UI communicates with the Sandbox REST API:

- `GET /api/v1/connections` - List connections
- `POST /api/v1/connections` - Create connection
- `PUT /api/v1/connections/:id` - Update connection
- `DELETE /api/v1/connections/:id` - Delete connection
- `POST /api/v1/connections/test` - Test connection
- `GET /api/v1/schema/sync` - Sync schema with sample data
- `GET /api/v1/schema/table/:name/samples` - Get table samples

## Authentication

The UI uses token-based authentication. Set your sandbox token in localStorage:

```javascript
localStorage.setItem('sandbox_token', 'your-token-here')
```

For development, a demo token is used by default.
