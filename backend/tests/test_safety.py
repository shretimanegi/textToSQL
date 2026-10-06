import pytest

from app.safety import MAX_ROWS, UnsafeSQL, validate_sql


def test_simple_select_gets_limit():
    assert validate_sql("SELECT * FROM data.album").endswith(f"LIMIT {MAX_ROWS}")


def test_trailing_semicolon_ok():
    assert validate_sql("SELECT 1;").endswith(f"LIMIT {MAX_ROWS}")


def test_unqualified_data_table_ok():
    validate_sql("SELECT * FROM album")


def test_small_limit_kept():
    assert validate_sql("SELECT * FROM data.album LIMIT 10").endswith("LIMIT 10")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM data.album LIMIT 100000",
    "SELECT * FROM data.album LIMIT ALL",
    "SELECT * FROM data.album FETCH FIRST 9999 ROWS ONLY",
    "SELECT * FROM data.album LIMIT (SELECT 99999)",
])
def test_big_limit_capped(sql):
    out = validate_sql(sql)
    assert f"LIMIT {MAX_ROWS}" in out and "ALL" not in out and "9999" not in out


def test_offset_preserved():
    out = validate_sql("SELECT * FROM data.album OFFSET 5")
    assert "OFFSET 5" in out and f"LIMIT {MAX_ROWS}" in out


def test_union_gets_limit():
    assert validate_sql("SELECT 1 UNION SELECT 2").endswith(f"LIMIT {MAX_ROWS}")


def test_cte_select_ok():
    out = validate_sql("WITH t AS (SELECT * FROM data.track) SELECT count(*) FROM t")
    assert "WITH t AS" in out


def test_joins_aggregates_window_ok():
    validate_sql(
        "SELECT g.name, count(*) AS n, rank() OVER (ORDER BY count(*) DESC) "
        "FROM data.track t JOIN data.genre g ON g.genre_id = t.genre_id GROUP BY g.name ORDER BY n DESC"
    )


def test_normal_functions_ok():
    validate_sql("SELECT upper(name), length(name), coalesce(composer, 'n/a'), now() FROM data.track")


def test_semicolon_in_string_literal_ok():
    validate_sql("SELECT * FROM data.artist WHERE name = 'a; DROP TABLE x'")


def test_error_is_unsafe_sql_subclass_of_valueerror():
    with pytest.raises(ValueError):
        validate_sql("DROP TABLE x")
