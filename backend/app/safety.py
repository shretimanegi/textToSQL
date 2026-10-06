"""Safety layer, parser check and limits (layers 2 and 3 of SPEC.md).

validate_sql() returns a normalized, LIMIT-capped SELECT or raises UnsafeSQL.
The DB role and the read-only transaction (executor.py) are independent
layers behind this one.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

MAX_ROWS = 500
DEFAULT_SCHEMA = "data"

# Function names blocked outright, plus blocked name prefixes (pg_*, lo_*, ...).
BLOCKED_FUNCTIONS = {
    "set_config", "current_setting", "dblink", "dblink_exec", "dblink_connect",
    "query_to_xml", "table_to_xml", "cursor_to_xml", "database_to_xml",
    "schema_to_xml", "query_to_xml_and_xmlschema", "table_to_xml_and_xmlschema",
    "schema_to_xml_and_xmlschema", "xmlforest_query", "ts_stat",
    "nextval", "setval", "currval", "lastval", "version",
}
BLOCKED_PREFIXES = ("pg_", "lo_", "txid_", "dblink", "current_setting", "set_config")

# Any of these node types anywhere in the tree means the statement is not a pure read.
BLOCKED_NODES = (
    exp.DML, exp.DDL, exp.Command, exp.Into, exp.Set, exp.Transaction,
    exp.Commit, exp.Rollback, exp.Use, exp.Pragma, exp.Copy, exp.Lock,
    exp.Grant, exp.Revoke,
)


class UnsafeSQL(ValueError):
    """The SQL was rejected by the safety layer."""


def _func_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return (node.sql_name() or "").lower()


def _check_function(node: exp.Func) -> None:
    name = _func_name(node)
    if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_PREFIXES):
        raise UnsafeSQL(f"function not allowed: {name}")


def _check_table(node: exp.Table, allowed: set[str]) -> None:
    schema = (node.args.get("db") and node.args["db"].name or "").lower()
    if node.args.get("catalog"):
        raise UnsafeSQL("cross-database references are not allowed")
    if schema not in allowed:
        raise UnsafeSQL(f"schema not allowed: {schema}")
    name = node.name.lower()
    if name.startswith("pg_") or name == "information_schema":
        raise UnsafeSQL(f"system relation not allowed: {name}")
    # Table-valued functions (FROM pg_sleep(1), FROM dblink(...)) show up as Table(this=Func).
    if isinstance(node.this, exp.Func):
        _check_function(node.this)


def _cap_limit(tree: exp.Expression, max_rows: int) -> exp.Expression:
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(max_rows)

    if isinstance(limit, exp.Fetch):
        count = limit.args.get("count")
    else:
        count = limit.expression
    if isinstance(count, exp.Literal) and not count.is_string:
        try:
            if int(count.name) <= max_rows:
                return tree
        except ValueError:
            pass
    # Larger, non-numeric (LIMIT ALL, expressions) or FETCH without a usable count.
    tree.set("limit", None)
    return tree.limit(max_rows)


def validate_sql(sql: str, schema: str = DEFAULT_SCHEMA, max_rows: int = MAX_ROWS) -> str:
    """Return the safe, normalized SQL to execute, or raise UnsafeSQL.

    `schema` is the one schema the query may touch (chosen by server code, never by the user).
    `max_rows` is 500 for the product; the eval harness raises it so gold comparisons are not truncated.
    """
    if not sql or not sql.strip():
        raise UnsafeSQL("empty query")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as e:
        raise UnsafeSQL(f"could not parse SQL: {e}") from e

    if len(statements) != 1:
        raise UnsafeSQL("exactly one statement is allowed")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise UnsafeSQL(f"only SELECT is allowed, got {type(tree).__name__}")

    allowed = {"", schema.lower()}
    cte_names = {c.alias.lower() for c in tree.find_all(exp.CTE)}

    for node in tree.walk():
        if isinstance(node, BLOCKED_NODES):
            raise UnsafeSQL(f"{type(node).__name__} is not allowed")
        if isinstance(node, exp.Func):
            _check_function(node)
        if isinstance(node, exp.Table) and node.name.lower() not in cte_names:
            _check_table(node, allowed)
        elif isinstance(node, exp.Table):
            # A CTE reference may not carry a schema qualifier trick.
            if node.args.get("db"):
                _check_table(node, allowed)

    return _cap_limit(tree, max_rows).sql(dialect="postgres")
