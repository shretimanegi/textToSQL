from datetime import date
from decimal import Decimal

from eval.compare import gold_is_ordered, results_match
from eval.make_subset import pick


def test_order_insensitive_by_default():
    assert results_match([[2, "b"], [1, "a"]], [[1, "a"], [2, "b"]])


def test_order_matters_when_gold_ordered():
    assert not results_match([[2], [1]], [[1], [2]], ordered=True)
    assert results_match([[1], [2]], [[1], [2]], ordered=True)


def test_different_values_mismatch():
    assert not results_match([[1]], [[2]])


def test_different_row_sets_mismatch():
    assert not results_match([[1], [2]], [[1]])


def test_numeric_types_equivalent():
    assert results_match([[Decimal("1.50"), 3]], [[1.5, 3.0]])


def test_float_rounding_tolerance():
    assert results_match([[0.33333333]], [[0.3333333333]])
    assert not results_match([[0.33]], [[0.34]])


def test_null_handling():
    assert results_match([[None, 1]], [[None, 1]])
    assert not results_match([[None]], [[0]])


def test_empty_results_match_each_other_only():
    assert results_match([], [])
    assert not results_match([], [[1]])


def test_column_order_is_positional():
    assert not results_match([["a", 1]], [[1, "a"]])


def test_dates_compare_as_text():
    assert results_match([[date(2020, 1, 2)]], [["2020-01-02"]])


def test_duplicates_ignored_when_unordered_like_bird():
    assert results_match([[1], [1], [2]], [[1], [2]])


def test_gold_is_ordered_detection():
    assert gold_is_ordered('SELECT a FROM t ORDER BY a DESC LIMIT 1')
    assert not gold_is_ordered("SELECT a FROM t WHERE b = 1")
    assert not gold_is_ordered("SELECT a FROM (SELECT a FROM t ORDER BY a) x")


def _pool():
    out = []
    for i in range(1000):
        d = "simple" if i < 600 else "moderate" if i < 900 else "challenging"
        out.append({"question_id": i, "difficulty": d})
    return out


def test_subset_size_stratified_and_deterministic():
    ids = pick(_pool(), n=200, seed=42)
    assert len(ids) == len(set(ids)) == 200
    assert pick(_pool(), n=200, seed=42) == ids
    assert pick(_pool(), n=200, seed=7) != ids
    simple = sum(i < 600 for i in ids)
    assert simple == 120


from eval.gold import normalize, translate

CAT = {"schools": ["CDSCode", "School", "County"], "satscores": ["cds", "NumTstTakr"]}


def test_normalize_resolves_case_and_quotes():
    out = normalize("SELECT T1.cdscode FROM SCHOOLS AS T1 WHERE T1.county = 'x'", CAT, read="postgres")
    assert '"schools"' in out and '"CDSCode"' in out and '"County"' in out


def test_normalize_leaves_aliases_and_unknown_names():
    out = normalize("SELECT count(*) AS total FROM schools AS T1 ORDER BY total", CAT, read="postgres")
    assert '"T1"' in out and '"total"' in out


def test_translate_sqlite_backticks_and_cast():
    out = translate("SELECT `School` FROM schools WHERE county = 'A' LIMIT 1", CAT)
    assert '"School"' in out and '"County"' in out and "`" not in out


def test_normalize_does_not_touch_string_literals():
    out = normalize("SELECT 1 FROM schools WHERE County = 'cdscode'", CAT, read="postgres")
    assert "'cdscode'" in out
