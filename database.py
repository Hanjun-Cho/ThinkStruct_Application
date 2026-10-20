import json
import re
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).parent / "patents.db"
DATA_DIRECTORY = Path(__file__).parent / "data"


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
    if terms:
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

    parameters.extend([limit, offset])
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            f"""
            SELECT
                patents.title,
                patents.doc_number,
                patents.classification,
                snippet(patent_search, 0, '<mark>', '</mark>', '...', 12)
                    AS title_snippet,
                snippet(patent_search, 2, '<mark>', '</mark>', '...', 30)
                    AS claims_snippet,
                snippet(patent_search, 3, '<mark>', '</mark>', '...', 30)
                    AS description_snippet,
                bm25(patent_search, 5.0, 3.0, 2.0, 1.0) AS relevance
            FROM patent_search
            JOIN patents ON patents.id = patent_search.rowid
            WHERE {' AND '.join(filters)}
            ORDER BY relevance
            LIMIT ?
            OFFSET ?
            """,
            parameters,
        ).fetchall()

    return [
        {
            "title": row[0],
            "doc_number": row[1],
            "classification": row[2],
            "title_snippet": row[3],
            "claims_snippet": row[4],
            "description_snippet": row[5],
            "relevance": row[6],
        }
        for row in rows
    ]