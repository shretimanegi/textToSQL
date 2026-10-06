import pytest

from app import baseline, retrieval
from app.config import settings
from app.db import admin_pool
from app.index_schema import doc_text

STRUCT = {
    "account": {"columns": [("account_id", "int"), ("district_id", "int")], "pk": [], "raw_fks": [],
                "fks": [{"columns": ["district_id"], "ref_table": "district", "ref_columns": ["district_id"]}]},
    "district": {"columns": [("district_id", "int")], "pk": [], "fks": [], "raw_fks": []},
    "client": {"columns": [("client_id", "int")], "pk": [], "fks": [], "raw_fks": []},
    "disp": {"columns": [("disp_id", "int")], "pk": [], "raw_fks": [], "fks": [
        {"columns": ["account_id"], "ref_table": "account", "ref_columns": ["account_id"]},
        {"columns": ["client_id"], "ref_table": "client", "ref_columns": ["client_id"]}]},
    "unrelated": {"columns": [("x", "int")], "pk": [], "fks": [], "raw_fks": []},
}


def test_expand_adds_bridge_table_between_two_hits():
    assert retrieval.expand_tables({"account", "client"}, STRUCT) == {"account", "client", "disp"}


def test_expand_no_bridge_for_single_hit():
    assert retrieval.expand_tables({"account"}, STRUCT) == {"account"}


def test_expand_ignores_unrelated_tables():
    assert "unrelated" not in retrieval.expand_tables({"account", "client", "district"}, STRUCT)


def test_expand_reads_chinook_style_raw_fks():
    s = {"album": {"columns": [], "pk": [], "fks": [], "raw_fks": ["FOREIGN KEY (artist_id) REFERENCES data.artist(artist_id)"]},
         "artist": {"columns": [], "pk": [], "fks": [], "raw_fks": []},
         "track": {"columns": [], "pk": [], "fks": [], "raw_fks": ["FOREIGN KEY (album_id) REFERENCES data.album(album_id)"]}}
    assert retrieval.expand_tables({"artist", "track"}, s) == {"artist", "track", "album"}


def test_render_schema_filters_tables_and_dangling_fks():
    text = baseline.render_schema(STRUCT, "bird_x", only={"account"})
    assert 'TABLE "account"' in text and 'TABLE "district"' not in text and "FOREIGN KEY" not in text
    both = baseline.render_schema(STRUCT, "bird_x", only={"account", "district"})
    assert 'REFERENCES "district"' in both


def test_doc_text_contains_table_column_description_and_samples():
    t = doc_text("loan", "status", "text", "Loan repayment status.", ["A", "B"])
    assert t == "loan.status (text): Loan repayment status. Examples: A, B."


async def _indexed(db_key: str) -> int:
    async with admin_pool.connection() as conn:
        return (await (await conn.execute("SELECT count(*) FROM app.schema_docs WHERE db_id=%s", (db_key,))).fetchone())[0]


@pytest.mark.skipif(not settings.gemini_api_key, reason="needs Gemini key for query embeddings")
async def test_retrieval_finds_relevant_columns_and_filters_by_db():
    if await _indexed("financial") == 0:
        pytest.skip("run `python -m app.index_schema --all` first")
    try:
        r = await retrieval.retrieve("financial", "bird_financial", "What is the average loan amount by status?")
    except RuntimeError as e:
        if "quota" in str(e):
            pytest.skip("Gemini embedding free-tier daily quota exhausted")
        raise
    assert any(t == "loan" for t, _, _ in r.columns)
    assert "loan" in r.tables
    assert len(r.columns) == retrieval.TOP_K_COLUMNS
    dists = [d for _, _, d in r.columns]
    assert dists == sorted(dists)
    all_tables = set((await baseline.get_schema("bird_financial")).keys())
    assert r.tables <= all_tables  # never leaks tables from another database


async def test_schema_docs_has_one_row_per_column_and_embedding():
    if await _indexed("financial") == 0:
        pytest.skip("run `python -m app.index_schema --all` first")
    structure = await baseline.get_schema("bird_financial")
    n_cols = sum(len(t["columns"]) for t in structure.values())
    assert await _indexed("financial") == n_cols
    async with admin_pool.connection() as conn:
        nulls = (await (await conn.execute(
            "SELECT count(*) FROM app.schema_docs WHERE db_id='financial' AND (embedding IS NULL OR description IS NULL)")).fetchone())[0]
    assert nulls == 0
