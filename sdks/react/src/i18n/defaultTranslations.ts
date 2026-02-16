const translations: Record<string, string> = {
  // common
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.close': 'Close',
  'common.cancel': 'Cancel',
  'common.save': 'Save',
  'common.saving': 'Saving...',
  'common.optional': 'Optional',
  'common.delete': 'Delete',
  'common.edit': 'Edit',
  'common.back': 'Back',
  'common.confirm': 'Confirm',
  'common.retry': 'Try again',
  'common.create': 'Create',
  'common.name': 'Name',
  'common.type': 'Type',
  'common.actions': 'Actions',
  'common.columns': 'columns',
  'common.tables': 'tables',
  'common.search': 'Search',

  // dataSources
  'dataSources.title': 'Data Sources',
  'dataSources.selectDataSource': 'Select Data Source',
  'dataSources.selectDescription': 'Choose a database or data warehouse to connect',
  'dataSources.searchPlaceholder': 'Search data sources...',
  'dataSources.failedToLoad': 'Failed to load data sources',
  'dataSources.cloudDataPlatforms': 'Cloud Data Platforms',
  'dataSources.queryEngines': 'Query Engines',
  'dataSources.databasesTitle': 'Databases',
  'dataSources.files': 'Files',
  'dataSources.other': 'Other',
  'dataSources.uncategorized': 'Other Sources',
  'dataSources.noResults': 'No data sources match your search',
  'dataSources.createConnection': 'Create connection',
  'dataSources.nameAndConfigure': 'Name and configure your connection',
  'dataSources.nameAndDescribe': 'Name and describe the connection',
  'dataSources.name': 'Name',
  'dataSources.connectionNamePlaceholder': 'e.g., production-db, analytics-warehouse',
  'dataSources.description': 'Description',
  'dataSources.descriptionPlaceholder': 'Describe this connection...',
  'dataSources.optionalSettings': 'Optional Settings',
  'dataSources.saveConnection': 'Save Connection',
  'dataSources.connectionSuccess': 'Connection successful!',
  'dataSources.errors.nameRequired': 'Connection name is required',
  'dataSources.errors.fieldRequired': '{{field}} is required',
  'dataSources.errors.saveFailed': 'Failed to save connection',
  'dataSources.errors.loadFailed': 'Failed to load connections',
  'dataSources.errors.deleteFailed': 'Failed to delete connection',
  'dataSources.errors.testFailed': 'Connection test failed',
  'dataSources.errors.schemaSaveFailed': 'Failed to save schema',
  'dataSources.errors.schemaLoadFailed': 'Failed to load schema',

  // connections
  'connections.title': 'Database Connections',
  'connections.subtitle': 'Manage your database connections and view datasets',
  'connections.newConnection': 'New Connection',
  'connections.backToConnections': 'Back to connections',
  'connections.selectDatabaseToConnect': 'Select a database or data warehouse to connect',
  'connections.loading': 'Loading connections...',
  'connections.noConnections': 'No connections',
  'connections.getStarted': 'Get started by creating a new database connection.',
  'connections.deleteConfirm': 'Are you sure you want to delete this connection?',
  'connections.default': 'Default',
}

export function defaultT(key: string, params?: Record<string, string>): string {
  let value = translations[key] || key
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      value = value.replace(`{{${k}}}`, v)
    })
  }
  return value
}
