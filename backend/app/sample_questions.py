"""Clickable example questions for the sidebar. The SQL is only used by tests, to prove each one is answerable."""

SAMPLES = [
    ("How many customers are there in each country?",
     "SELECT country, count(*) AS customers FROM data.customer GROUP BY country ORDER BY customers DESC"),
    ("Which 10 artists have the most albums?",
     "SELECT a.name, count(*) AS albums FROM data.album al JOIN data.artist a ON a.artist_id = al.artist_id "
     "GROUP BY a.name ORDER BY albums DESC LIMIT 10"),
    ("What is the total revenue per year?",
     "SELECT extract(year FROM invoice_date)::int AS year, sum(total) AS revenue FROM data.invoice GROUP BY 1 ORDER BY 1"),
    ("Which genres have the most tracks?",
     "SELECT g.name, count(*) AS tracks FROM data.track t JOIN data.genre g ON g.genre_id = t.genre_id "
     "GROUP BY g.name ORDER BY tracks DESC"),
    ("What are the top 5 best-selling tracks?",
     "SELECT t.name, sum(il.quantity) AS sold FROM data.invoice_line il JOIN data.track t ON t.track_id = il.track_id "
     "GROUP BY t.name ORDER BY sold DESC LIMIT 5"),
    ("Which sales rep has the highest total sales?",
     "SELECT e.first_name || ' ' || e.last_name AS rep, sum(i.total) AS sales FROM data.employee e "
     "JOIN data.customer c ON c.support_rep_id = e.employee_id JOIN data.invoice i ON i.customer_id = c.customer_id "
     "GROUP BY 1 ORDER BY sales DESC LIMIT 1"),
    ("What is the average track length in minutes by media type?",
     "SELECT m.name, round(avg(t.milliseconds) / 60000.0, 2) AS minutes FROM data.track t "
     "JOIN data.media_type m ON m.media_type_id = t.media_type_id GROUP BY m.name"),
    ("How many invoices were there each month in 2023?",
     "SELECT to_char(invoice_date, 'YYYY-MM') AS month, count(*) AS invoices FROM data.invoice "
     "WHERE extract(year FROM invoice_date) = 2023 GROUP BY 1 ORDER BY 1"),
]
