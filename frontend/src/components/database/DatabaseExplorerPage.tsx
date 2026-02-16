/**
 * Database Explorer Page
 *
 * Full-page view for the database query explorer using SQL Pad.
 */

import { DatabaseExplorer } from './DatabaseExplorer';

export function DatabaseExplorerPage() {
  return (
    <div className="h-screen flex flex-col bg-gray-50">
      <div className="flex-1 p-4">
        <DatabaseExplorer fullscreen={false} />
      </div>
    </div>
  );
}
