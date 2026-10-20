import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from database import DATABASE_PATH, DATA_DIRECTORY, build_database


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate(path: Path) -> int:
    with path.open(encoding="utf-8") as patent_file:
        records = json.load(patent_file)

    if not isinstance(records, list):
        raise ValueError("expected the JSON root to be a list")
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("every patent record must be an object")
    return len(records)


def _create_status_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_jobs (
            file_path TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            status TEXT NOT NULL,
            records_indexed INTEGER DEFAULT 0,
            error_message TEXT,
            started_at TEXT,
            completed_at TEXT
        )
        """
    )


def run_ingestion() -> dict[str, int]:
    files = sorted(DATA_DIRECTORY.rglob("patents_ipa*.json"))
    changed_files: list[tuple[Path, str, int]] = []
    failed = 0

    with sqlite3.connect(DATABASE_PATH) as connection:
        _create_status_table(connection)

        for path in files:
            checksum = _checksum(path)
            previous = connection.execute(
                "SELECT checksum, status FROM ingestion_jobs WHERE file_path = ?",
                (str(path),),
            ).fetchone()
            if previous == (checksum, "indexed"):
                continue

            connection.execute(
                """
                INSERT INTO ingestion_jobs (
                    file_path, checksum, status, error_message, started_at
                ) VALUES (?, ?, 'processing', NULL, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    checksum = excluded.checksum,
                    status = 'processing',
                    error_message = NULL,
                    started_at = excluded.started_at
                """,
                (str(path), checksum, _now()),
            )
            try:
                record_count = _validate(path)
                changed_files.append((path, checksum, record_count))
            except (OSError, json.JSONDecodeError, ValueError) as error:
                failed += 1
                connection.execute(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'failed', error_message = ?, completed_at = ?
                    WHERE file_path = ?
                    """,
                    (str(error), _now(), str(path)),
                )

        connection.commit()

    if failed == 0 and changed_files:
        try:
            build_database()
        except Exception as error:
            with sqlite3.connect(DATABASE_PATH) as connection:
                for path, _, _ in changed_files:
                    connection.execute(
                        """
                        UPDATE ingestion_jobs
                        SET status = 'failed', error_message = ?, completed_at = ?
                        WHERE file_path = ?
                        """,
                        (str(error), _now(), str(path)),
                    )
                connection.commit()
            failed = len(changed_files)
        else:
            with sqlite3.connect(DATABASE_PATH) as connection:
                for path, checksum, record_count in changed_files:
                    connection.execute(
                        """
                        UPDATE ingestion_jobs
                        SET status = 'indexed', checksum = ?,
                            records_indexed = ?, error_message = NULL,
                            completed_at = ?
                        WHERE file_path = ?
                        """,
                        (checksum, record_count, _now(), str(path)),
                    )
                connection.commit()

    return {
        "files_seen": len(files),
        "files_indexed": len(changed_files) if failed == 0 else 0,
        "files_failed": failed,
    }


if __name__ == "__main__":
    print(run_ingestion())