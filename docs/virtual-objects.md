# Virtual objects: custom queries and stored procedures as tables

A **virtual object** is a named relation defined in the sandbox rather than in
the database. The catalog lists it and the schema sync describes and samples it.
Any SQL that references it by name is expanded before execution. Callers,
including an LLM writing SQL, see an ordinary table and never see the
definition behind it.

Virtual objects exist for databases where the sandbox login may not create
views. A typical case is a customer whose reporting lives in SQL Server stored
procedures and who grants only `SELECT` and `EXECUTE`.

| Kind | Backed by | Expanded as |
|------|-----------|-------------|
| `QUERY` | a `SELECT` written by an admin (any connector) | a derived table `(<definition>) AS <alias>`; CTEs in the definition are hoisted to the statement's `WITH` and renamed `mv<n>_<name>` |
| `PROCEDURE` (`pg_function`) | a PostgreSQL set-returning function | `schema.fn(CAST('…' AS type), …) AS <alias>` |
| `PROCEDURE` (`mssql_procedure`) | a SQL Server stored procedure | a session temp table `#mv_<id>_<n>`, filled before the query runs |

Views are listed as `VIEW` on every connector (Postgres also lists
materialized views, and HANA reads `SYS.VIEWS`). Views are queried directly, as
before. Catalog entries use the types `TABLE`, `VIEW`, `QUERY` and `PROCEDURE`.

## How execution works

`SQLExecutor.execute` (REST `/api/v1/execute/sql` and gRPC `ExecuteSQL`) runs
these steps:

1. **Validate** the caller's SQL with `SQLValidator`, exactly as before.
2. **Expand** it with `execution/virtual_objects/expander.expand`.
   - A regex pre-check skips queries that mention no object name. Those reach
     the database byte-for-byte unchanged and are never parsed.
   - Otherwise the query is parsed with sqlglot in the connection's dialect.
   - Every table reference that resolves to an object is replaced. A reference
     resolves when it is bare, qualified with the connection's schema, or
     qualified with database and schema; `[dbo.x]` also counts.
   - A CTE of the same name shadows an object, the same rule the data-analyst
     permission guard uses.
   - Objects may reference each other, up to 4 levels deep; cycles are
     rejected.
3. **Run** it with `connector.execute_plan`. For SQL Server procedures this
   happens in one function on the connection's own thread:
   1. `CREATE TABLE #mv_…`: string columns are `COLLATE DATABASE_DEFAULT`,
      which prevents both code-page corruption and collation conflicts in joins.
   2. `INSERT INTO #mv_… EXEC [s].[p] @a = …`.
   3. The rewritten query.
   4. `DROP` of the temp table, in a `finally` block.

   tempdb needs no permission on the user database.
4. **Scrub errors.** Procedure names, `#mv_…` and "INSERT EXEC" are rewritten
   back to the object's name. The caller never learns what backs the object.

`INSERT … EXEC` is not always possible: nested `INSERT EXEC` (8164),
`ROLLBACK` inside the procedure (3915), or a later result set
(`result_set_index > 0`). Those procedures use **client** materialization
instead. The sandbox runs `EXEC`, reads the chosen result set (up to
`SANDBOX_VO_CLIENT_MAX_ROWS`, default 200k) and bulk-inserts it into the temp
table. The mode is chosen at save time, and the sandbox falls back to client
mode at run time if a procedure starts refusing `INSERT EXEC`.

## Parameters

Procedure parameters are fixed per object. The same procedure can be
registered several times with different values, for example `sales_ytd` and
`sales_last_month`.

- A value is either a literal or one date token, such as `{{today}}`,
  `{{yesterday}}`, `{{start_of_month}}`, `{{end_of_prev_month}}`,
  `{{start_of_year-1y}}` or `{{today-7d}}`. The full list is in
  `GET /api/v1/virtual-objects/tokens`.
- Tokens are resolved on every execution in the connection's
  `extra_params.timezone`. If that is not set, `SANDBOX_DEFAULT_TIMEZONE` is
  used, and UTC after that.
- Values are rendered as typed literals. SQL Server dates are sent as
  `'YYYYMMDD'` / ISO-8601, which login languages cannot misread.
- A parameter marked `omit` is left out of the call, so the procedure's own
  default applies.

## Result cache

A SQL Server procedure object with `cache_ttl_seconds > 0` keeps its rows in an
in-process LRU cache (64 entries, at most 50k rows each).

- The cache key is the object's definition hash plus the resolved parameters,
  so `{{today}}` misses the cache once the day changes.
- The Prometheus counter is `sandbox_virtual_object_cache_lookups_total{result}`.

## Saving validates against the live database

Every create, update and refresh runs these checks. Nothing is stored unless
all of them pass.

- **Name:** an identifier that passes the SQL validator (for example, it must
  not contain `sp_`), is not a reserved word, and is not taken by a table or
  view in the schema.
- **Custom query:** exactly one `SELECT` or set operation, with no
  `INTO`/locking/variables. Every output column must have a unique name.
  Comments are stripped, and the result must pass `SQLValidator`. On T-SQL,
  `ORDER BY` is only allowed together with `TOP`/`OFFSET`.
- **Procedure:** it must exist and the login must hold `EXECUTE` on it (it has
  to appear in `list_routines`). Columns come from
  `sys.dm_exec_describe_first_result_set_for_object`. If that metadata is not
  available (temp tables, dynamic SQL), the procedure is run once and the types
  are inferred; an admin can edit inferred types.
- **Shape changes:** if a procedure's output changes later, queries fail with a
  "refresh its definition" error. `POST …/refresh` re-describes the object.

## API

The sandbox exposes these endpoints. All require the sandbox token.

| Method & path | Purpose |
|---|---|
| `GET/POST /api/v1/connections/{cid}/virtual-objects` | list / create |
| `GET/PUT/DELETE /api/v1/connections/{cid}/virtual-objects/{id}` | read / update (name and kind are immutable) / delete |
| `POST /api/v1/connections/{cid}/virtual-objects/preview` | validate, describe and return sample rows; stores nothing |
| `POST /api/v1/connections/{cid}/virtual-objects/{id}/refresh` | re-describe after the source changed |
| `GET /api/v1/connections/{cid}/procedures?search=&schema=` | procedures (SQL Server) and set-returning functions (Postgres) the login can execute |
| `GET /api/v1/virtual-objects/tokens?connection_id=` | date tokens with their current values |

Definitions are stored in the `virtual_objects` table of the sandbox DB. The
table has `ON DELETE CASCADE` from `connections`.

**data-analyst** does not expose these endpoints through its generic sandbox
proxy. It serves admin-gated wrappers under
`/api/data-connectors/{space}/connections/{id}/virtual-objects`. The wrappers
also:

- write the object into the schema cache (kind, columns, samples);
- add it to the connection's selection;
- sync the default DataObject.

A virtual object is like a view: whoever can query it gets its data, whatever
the rules on the underlying tables. That is why only admins can define one.

## Limits

- Procedures are supported on SQL Server and PostgreSQL. On MySQL and HANA,
  only custom queries are available; HANA uses sqlglot's generic dialect, so
  treat it as beta.
- SQL Pad connects to the database directly and does not see virtual objects.
- An object's name cannot change, because selections, instructions, saved SQL
  and dashboards refer to it by name. To rename one, create a new object and
  delete the old one.

## Tests

```bash
# inside the sandbox container
python -m pytest tests/unit/virtual_objects -o asyncio_mode=auto -o addopts=""
```
