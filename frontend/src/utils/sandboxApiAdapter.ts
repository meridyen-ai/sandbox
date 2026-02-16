import type { SandboxUIApi } from '@meridyen/sandbox-ui'
import { handlersApi, connectionsApi, schemaApi } from './api'

export const sandboxApi: SandboxUIApi = {
  handlers: {
    list: handlersApi.list,
  },
  connections: {
    list: connectionsApi.list,
    create: connectionsApi.create,
    update: connectionsApi.update,
    delete: connectionsApi.delete,
    test: connectionsApi.test,
    getSelectedTables: connectionsApi.getSelectedTables,
    saveSelectedTables: connectionsApi.saveSelectedTables,
  },
  schema: {
    sync: schemaApi.sync,
  },
}
