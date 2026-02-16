/**
 * Database Explorer Page
 *
 * Full-page view wrapping the SDK's DatabaseExplorer component.
 */

import { DatabaseExplorer, SandboxUIProvider } from '@meridyen/sandbox-ui';
import { useSandboxApiAdapter } from '../../hooks/useSandboxApiAdapter';

export function DatabaseExplorerPage() {
  const api = useSandboxApiAdapter();

  return (
    <SandboxUIProvider api={api} iconBasePath="/icons/databases">
      <div className="h-screen flex flex-col bg-gray-50">
        <div className="flex-1 p-4">
          <DatabaseExplorer fullscreen={false} />
        </div>
      </div>
    </SandboxUIProvider>
  );
}
