"""LLM_PROVIDER=mock: canned answers for local UI/e2e testing without an API key or quota."""

from app.sample_questions import SAMPLES

DEFAULT_SQL = ("SELECT g.name AS genre, count(*) AS tracks FROM data.track t "
               "JOIN data.genre g ON g.genre_id = t.genre_id GROUP BY g.name ORDER BY tracks DESC")


def mock_complete(system: str, user: str) -> str:
    if "one-sentence answers" in system:  # the answer-summary call
        return "Here is a plain-English summary of the result (mock LLM)."
    for question, sql in SAMPLES:
        if f"Question: {question}" in user:
            return sql
    low = user.lower()
    if "by total revenue" in low:
        return ("SELECT c.first_name || ' ' || c.last_name AS customer, sum(i.total) AS revenue FROM data.customer c "
                "JOIN data.invoice i ON i.customer_id = c.customer_id GROUP BY 1 ORDER BY revenue DESC LIMIT 5")
    if "best customers" in low and "previous question" not in low:
        return "CLARIFY: What does best mean? | By total revenue | By number of orders"
    if "drop" in low:
        return "DROP TABLE data.album"
    if "broken" in low:
        return "SELECT nope FROM data.album"
    return DEFAULT_SQL
