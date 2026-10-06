from datetime import date
from decimal import Decimal

from app.charts import chart_spec


def test_category_and_number_is_bar():
    assert chart_spec(["genre", "tracks"], [["Rock", 10], ["Jazz", 4]]) == {"type": "bar", "x": "genre", "y": "tracks"}


def test_number_first_category_second_still_bar():
    assert chart_spec(["tracks", "genre"], [[10, "Rock"], [4, "Jazz"]])["type"] == "bar"


def test_date_column_is_line():
    spec = chart_spec(["day", "revenue"], [[date(2020, 1, 1), Decimal("5.5")], [date(2020, 1, 2), Decimal("7")]])
    assert spec == {"type": "line", "x": "day", "y": "revenue"}


def test_year_month_strings_are_line():
    assert chart_spec(["month", "n"], [["2012-01", 3], ["2012-02", 5]])["type"] == "line"


def test_integer_year_named_column_is_line():
    assert chart_spec(["year", "revenue"], [[2009, 449.5], [2010, 481.5]])["type"] == "line"


def test_integer_column_not_named_like_time_is_not_a_line_or_bar():
    assert chart_spec(["customer_id", "total"], [[1, 5.0], [2, 6.0]])["type"] == "none"


def test_two_numbers_none():
    assert chart_spec(["a", "b"], [[1, 2], [3, 4]])["type"] == "none"


def test_wrong_shapes_none():
    assert chart_spec(["a"], [[1], [2]])["type"] == "none"
    assert chart_spec(["a", "b", "c"], [["x", 1, 2], ["y", 3, 4]])["type"] == "none"
    assert chart_spec(["a", "b"], [["x", 1]])["type"] == "none"  # single point
    assert chart_spec(["a", "b"], [])["type"] == "none"


def test_too_many_categories_none():
    rows = [[f"c{i}", i] for i in range(60)]
    assert chart_spec(["c", "n"], rows)["type"] == "none"


def test_duplicate_categories_none():
    assert chart_spec(["c", "n"], [["a", 1], ["a", 2]])["type"] == "none"


def test_nulls_in_number_column_ok():
    assert chart_spec(["c", "n"], [["a", 1], ["b", None]])["type"] == "bar"


def test_identifier_column_is_not_a_measure():
    assert chart_spec(["title", "album_id"], [["A", 1], ["B", 2]])["type"] == "none"
    assert chart_spec(["name", "customer_id"], [["A", 10], ["B", 20]])["type"] == "none"


def test_measure_named_like_total_still_charts():
    assert chart_spec(["name", "total_sales"], [["A", 10], ["B", 20]])["type"] == "bar"
