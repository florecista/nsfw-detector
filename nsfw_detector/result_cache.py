import json
import sqlite3
from pathlib import Path

from nsfw_detector.model_store import application_data_directory


SCHEMA_VERSION = 1


def default_cache_path():
    return application_data_directory() / "cache" / "classification.sqlite3"


class ResultCache:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS classification_results (
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                model_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (path, size, mtime_ns, model_id, model_version)
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def file_identity(path):
        resolved = Path(path).resolve()
        stat = resolved.stat()
        return str(resolved), stat.st_size, stat.st_mtime_ns

    def get(self, path, model_id, model_version):
        resolved, size, mtime_ns = self.file_identity(path)
        row = self.connection.execute(
            """
            SELECT result_json
            FROM classification_results
            WHERE path = ? AND size = ? AND mtime_ns = ?
              AND model_id = ? AND model_version = ? AND schema_version = ?
            """,
            (resolved, size, mtime_ns, model_id, model_version, SCHEMA_VERSION),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            self.delete(resolved, size, mtime_ns, model_id, model_version)
            return None

    def put(self, path, model_id, model_version, result):
        resolved, size, mtime_ns = self.file_identity(path)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO classification_results (
                path, size, mtime_ns, model_id, model_version,
                schema_version, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved,
                size,
                mtime_ns,
                model_id,
                model_version,
                SCHEMA_VERSION,
                json.dumps(result, separators=(",", ":"), sort_keys=True),
            ),
        )

    def delete(self, path, size, mtime_ns, model_id, model_version):
        self.connection.execute(
            """
            DELETE FROM classification_results
            WHERE path = ? AND size = ? AND mtime_ns = ?
              AND model_id = ? AND model_version = ?
            """,
            (path, size, mtime_ns, model_id, model_version),
        )
        self.connection.commit()

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.commit()
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
