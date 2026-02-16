/** Map handler names to icon file names in the icons/databases/ directory */
export const handlerIconMap: Record<string, string> = {
  postgres: 'postgres',
  mysql: 'mysql',
  sqlserver: 'sqlserver',
  mssql: 'sqlserver',
  snowflake: 'snowflake',
  bigquery: 'bigquery',
  redshift: 'redshift',
  oracle: 'oracle',
  databricks: 'databricks',
  trino: 'trino',
  presto: 'presto',
  azuresynapse: 'azuresynapse',
  azure_synapse: 'azuresynapse',
  saphana: 'saphana',
  sap_hana: 'saphana',
  athena: 'athena',
  dremio: 'dremio',
  starburst: 'starburst',
  teradata: 'teradata',
  singlestore: 'singlestore',
  mariadb: 'mariadb',
  cockroachdb: 'cockroachdb',
  clickhouse: 'clickhouse',
  csv: 'csv',
  google_sheets: 'google_sheets',
  googlesheets: 'google_sheets',
  looker: 'looker',
  denodo: 'denodo',
}

/** Group definitions for categorizing handlers in the selector grid */
export const handlerGroups: Record<string, { title: string; handlers: string[] }> = {
  cloudDataPlatforms: {
    title: 'Cloud Data Platforms',
    handlers: ['snowflake', 'databricks', 'redshift', 'bigquery', 'azuresynapse'],
  },
  queryEngines: {
    title: 'Query Engines',
    handlers: ['athena', 'dremio', 'presto', 'starburst', 'trino'],
  },
  databases: {
    title: 'Databases',
    handlers: [
      'postgres', 'mysql', 'sqlserver', 'oracle', 'saphana',
      'singlestore', 'teradata', 'mariadb', 'cockroachdb', 'clickhouse',
    ],
  },
  files: {
    title: 'Files',
    handlers: ['csv', 'google_sheets'],
  },
  other: {
    title: 'Other',
    handlers: ['looker', 'denodo'],
  },
}
