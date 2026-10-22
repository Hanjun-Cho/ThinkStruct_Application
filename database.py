import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path


DATABASE_PATH = Path(__file__).parent / "patents.db"
DATA_DIRECTORY = Path(__file__).parent / "data"
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

@lru_cache(maxsize=1)
def _cross_encoder():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(CROSS_ENCODER_MODEL, max_length=128)

def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)

def _read_patents() -> list[dict]:
    patents = []
    for json_path in sorted(DATA_DIRECTORY.rglob("patents_ipa*.json")):
        with json_path.open(encoding="utf-8") as patent_file:
            records = json.load(patent_file)

        for record in records:
            patents.append(
                {
                    "title": record.get("title", ""),
                    "doc_number": record.get("doc_number", ""),
                    "abstract": record.get("abstract", ""),
                    "detailed_description": _as_text(record.get("detailed_description")),
                    "claims": _as_text(record.get("claims")),
                    "bibtex": record.get("bibtex", ""),
                    "classification": record.get("classification", ""),
                }
            )
    return patents

def build_database() -> None:
    patents = _read_patents()
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executescript(
            """
            DROP TABLE IF EXISTS patent_search;
            DROP TABLE IF EXISTS patents;
            CREATE TABLE patents (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                doc_number TEXT NOT NULL,
                abstract TEXT NOT NULL,
                detailed_description TEXT NOT NULL,
                claims TEXT NOT NULL,
                bibtex TEXT NOT NULL,
                classification TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE patent_search USING fts5(
                title,
                abstract,
                claims,
                detailed_description,
                content='patents',
                content_rowid='id'
            );
            CREATE INDEX idx_patents_classification
                ON patents(classification);
            CREATE INDEX idx_patents_title
                ON patents(title);
            """
        )
        connection.executemany(
            """
            INSERT INTO patents (
                title, doc_number, abstract, detailed_description,
                claims, bibtex, classification
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    patent["title"],
                    patent["doc_number"],
                    patent["abstract"],
                    patent["detailed_description"],
                    patent["claims"],
                    patent["bibtex"],
                    patent["classification"],
                )
                for patent in patents
            ],
        )
        connection.execute(
            "INSERT INTO patent_search(patent_search) VALUES ('rebuild')"
        )

def ensure_database() -> None:
    if not DATABASE_PATH.exists():
        build_database()
    else:
        with sqlite3.connect(DATABASE_PATH) as connection:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_patents_classification "
                "ON patents(classification)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_patents_title ON patents(title)"
            )

def patent_count() -> int:
    ensure_database()
    with sqlite3.connect(DATABASE_PATH) as connection:
        return connection.execute("SELECT COUNT(*) FROM patents").fetchone()[0]

def search_patents(
    query: str,
    limit: int = 10,
    offset: int = 0,
    classification_prefix: str = "",
    title_keyword: str = "",
    abstract_keyword: str = "",
    exact_title: str = "",
    hybrid: bool = True,
    candidate_limit: int = 100,
    rerank: bool = True,
) -> list[dict]:
    normalized_query = query.strip()
    ensure_database()
    if normalized_query:
        with sqlite3.connect(DATABASE_PATH) as connection:
            direct_match = connection.execute(
                """
                SELECT title, doc_number, classification, claims, detailed_description
                FROM patents
                WHERE doc_number = ?
                LIMIT 1 OFFSET ?
                """,
                (normalized_query, offset),
            ).fetchone()

            if direct_match:
                return [
                    {
                        "title": direct_match[0],
                        "doc_number": direct_match[1],
                        "classification": direct_match[2],
                        "title_snippet": direct_match[0],
                        "claims_snippet": direct_match[3],
                        "description_snippet": direct_match[4],
                        "relevance": 0,
                    }
                ]

    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    filters = []
    parameters: list[object] = []
    if terms and rerank:
        filters.append("patent_search MATCH ?")
        parameters.append(" OR ".join(f'"{term}"' for term in terms))
    if hybrid:
        if classification_prefix.strip():
            filters.append("patents.classification LIKE ?")
            parameters.append(f"{classification_prefix.strip()}%")
        if title_keyword.strip():
            filters.append("lower(patents.title) LIKE lower(?)")
            parameters.append(f"%{title_keyword.strip()}%")
        if abstract_keyword.strip():
            filters.append("lower(patents.abstract) LIKE lower(?)")
            parameters.append(f"%{abstract_keyword.strip()}%")
        if exact_title.strip():
            filters.append("lower(patents.title) = lower(?)")
            parameters.append(exact_title.strip())
    if not filters:
        filters.append("1 = 1")

    parameters.append(candidate_limit)
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            f"""
            SELECT
                patent_search.rowid,
                patents.title,
                patents.doc_number,
                patents.classification,
                bm25(patent_search, 5.0, 3.0, 2.0, 1.0) AS relevance,
                substr(patents.abstract, 1, 2000),
                substr(patents.claims, 1, 4000),
                substr(patents.detailed_description, 1, 2000)
            FROM patent_search
            JOIN patents ON patents.id = patent_search.rowid
            WHERE {' AND '.join(filters)}
            ORDER BY relevance
            LIMIT ?
            """,
            parameters,
        ).fetchall()

    candidates = [
        {
            "id": row[0],
            "title": row[1],
            "doc_number": row[2],
            "classification": row[3],
            "bm25_relevance": row[4],
            "abstract_text": row[5],
            "claims_text": row[6],
            "description_text": row[7],
            "title_snippet": row[1],
            "claims_snippet": "",
            "description_snippet": "",
        }
        for row in rows
    ]

    if terms and rerank:
        pairs = [
            (
                normalized_query,
                "Title: "
                + candidate["title"]
                + "\nAbstract: "
                + candidate["abstract_text"]
                + "\nClaims: "
                + candidate["claims_text"][:4000]
                + "\nDescription: "
                + candidate["description_text"][:2000],
            )
            for candidate in candidates
        ]
        scores = _cross_encoder().predict(
            pairs, batch_size=16, show_progress_bar=False
        )
        for candidate, score in zip(candidates, scores):
            candidate["relevance"] = float(score)
    else:
        for candidate in candidates:
            candidate["relevance"] = -float(candidate["bm25_relevance"])

    candidates.sort(key=lambda candidate: candidate["relevance"], reverse=True)
    page = candidates[offset : offset + limit]

    if terms and page:
        ids = [candidate["id"] for candidate in page]
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(DATABASE_PATH) as connection:
            snippets = connection.execute(
                f"""
                SELECT
                    rowid,
                    snippet(patent_search, 0, '<mark>', '</mark>', '...', 12),
                    snippet(patent_search, 2, '<mark>', '</mark>', '...', 30),
                    snippet(patent_search, 3, '<mark>', '</mark>', '...', 30)
                FROM patent_search
                WHERE rowid IN ({placeholders})
                """,
                ids,
            ).fetchall()
        snippet_by_id = {row[0]: row[1:] for row in snippets}
        for candidate in page:
            title_snippet, claims_snippet, description_snippet = snippet_by_id[
                candidate["id"]
            ]
            candidate["title_snippet"] = title_snippet
            candidate["claims_snippet"] = claims_snippet
            candidate["description_snippet"] = description_snippet

    return page
