from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from .text import chunk_document, count_words, fold_text, fts_query, normalize_display_text, normalize_text, search_terms


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Storage:
    backend_name = "sqlite"
    search_backend_name = "sqlite-fts5"

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.search_mirror: Any | None = None
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def attach_search_mirror(self, search_backend: Any) -> None:
        self.search_mirror = search_backend

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER,
                    url TEXT NOT NULL UNIQUE,
                    canonical_url TEXT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'website',
                    text_content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    text_content TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    folded_text TEXT NOT NULL,
                    token_count INTEGER NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                    normalized_text,
                    folded_text,
                    content='chunks',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );

                CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunk_fts(rowid, normalized_text, folded_text)
                    VALUES (new.id, new.normalized_text, new.folded_text);
                END;

                CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunk_fts(chunk_fts, rowid, normalized_text, folded_text)
                    VALUES ('delete', old.id, old.normalized_text, old.folded_text);
                END;

                CREATE TABLE IF NOT EXISTS crawl_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    domain TEXT NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    discovered_from TEXT,
                    next_attempt_at TEXT,
                    last_attempt_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS crawl_queue_status_idx
                ON crawl_queue(status, id);

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER,
                    user_id INTEGER,
                    title TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    similarity_percent INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER,
                    user_id INTEGER,
                    title TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    word_count INTEGER NOT NULL,
                    index_for_comparison INTEGER NOT NULL DEFAULT 0,
                    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    version_number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    word_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_id, version_number),
                    UNIQUE(source_id, content_hash)
                );

                CREATE INDEX IF NOT EXISTS source_versions_source_idx
                ON source_versions(source_id, version_number DESC);

                CREATE TABLE IF NOT EXISTS organizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'instructor', 'student')),
                    password_hash TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS auth_sessions_user_idx
                ON auth_sessions(user_id);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(connection, "sources", "organization_id", "INTEGER")
            self._ensure_column(connection, "reports", "organization_id", "INTEGER")
            self._ensure_column(connection, "reports", "user_id", "INTEGER")
            self._ensure_column(connection, "submissions", "organization_id", "INTEGER")
            self._ensure_column(connection, "submissions", "user_id", "INTEGER")
            self._ensure_column(connection, "crawl_queue", "next_attempt_at", "TEXT")
            self._ensure_column(connection, "crawl_queue", "last_attempt_at", "TEXT")
            self._ensure_column(connection, "crawl_queue", "completed_at", "TEXT")
            self._ensure_column(connection, "users", "password_hash", "TEXT")
            self._backfill_source_versions(connection)
            self._seed_demo_identities(connection)

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _backfill_source_versions(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO source_versions(
                source_id, version_number, title, text_content, content_hash,
                word_count, metadata_json, fetched_at, created_at
            )
            SELECT sources.id, 1, sources.title, sources.text_content, sources.content_hash,
                   sources.word_count, sources.metadata_json, sources.fetched_at, sources.created_at
            FROM sources
            WHERE NOT EXISTS (
                SELECT 1 FROM source_versions WHERE source_versions.source_id = sources.id
            )
            """
        )

    @staticmethod
    def _seed_demo_identities(connection: sqlite3.Connection) -> None:
        now = utc_now()
        connection.execute(
            "INSERT OR IGNORE INTO organizations(slug, name, created_at) VALUES ('demo-school', 'Trường Minh Chứng', ?)",
            (now,),
        )
        organization_id = connection.execute(
            "SELECT id FROM organizations WHERE slug = 'demo-school'"
        ).fetchone()["id"]
        users = [
            ("demo-admin", "Minh Anh", "admin"),
            ("demo-instructor", "Cô Lan", "instructor"),
            ("demo-student", "Sinh viên An", "student"),
        ]
        for username, display_name, role in users:
            connection.execute(
                """
                INSERT OR IGNORE INTO users(organization_id, username, display_name, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (organization_id, username, display_name, role, now),
            )

    def upsert_source(
        self,
        *,
        url: str,
        title: str,
        text_content: str,
        source_type: str = "website",
        canonical_url: str | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: int | None = None,
    ) -> int:
        title = normalize_display_text(title)
        text_content = normalize_display_text(text_content)
        now = utc_now()
        digest = hashlib.sha256(text_content.encode("utf-8")).hexdigest()
        words = count_words(text_content)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self.connect() as connection:
            existing = connection.execute("SELECT id, content_hash FROM sources WHERE url = ?", (url,)).fetchone()
            if existing:
                source_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE sources
                    SET organization_id = ?, canonical_url = ?, title = ?, source_type = ?, text_content = ?,
                        content_hash = ?, word_count = ?, metadata_json = ?, fetched_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        organization_id,
                        canonical_url,
                        title,
                        source_type,
                        text_content,
                        digest,
                        words,
                        metadata_json,
                        now,
                        now,
                        source_id,
                    ),
                )
                if existing["content_hash"] == digest:
                    return source_id
                connection.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO sources (
                        organization_id, url, canonical_url, title, source_type, text_content, content_hash,
                        word_count, metadata_json, fetched_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        organization_id,
                        url,
                        canonical_url,
                        title,
                        source_type,
                        text_content,
                        digest,
                        words,
                        metadata_json,
                        now,
                        now,
                        now,
                    ),
                )
                source_id = int(cursor.lastrowid)

            self._insert_source_version(
                connection,
                source_id=source_id,
                title=title,
                text_content=text_content,
                content_hash=digest,
                word_count=words,
                metadata_json=metadata_json,
                fetched_at=now,
            )
            for position, chunk in enumerate(chunk_document(text_content)):
                connection.execute(
                    """
                    INSERT INTO chunks (
                        source_id, position, text_content, normalized_text, folded_text, token_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        position,
                        chunk,
                        normalize_text(chunk),
                        fold_text(chunk),
                        count_words(chunk),
                    ),
                )
        if self.search_mirror:
            self.search_mirror.replace_source(source_id, self.get_source_search_documents(source_id))
        return source_id

    @staticmethod
    def _insert_source_version(
        connection: sqlite3.Connection,
        *,
        source_id: int,
        title: str,
        text_content: str,
        content_hash: str,
        word_count: int,
        metadata_json: str,
        fetched_at: str,
    ) -> None:
        next_version = connection.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS version_number FROM source_versions WHERE source_id = ?",
            (source_id,),
        ).fetchone()["version_number"]
        connection.execute(
            """
            INSERT OR IGNORE INTO source_versions(
                source_id, version_number, title, text_content, content_hash,
                word_count, metadata_json, fetched_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                int(next_version),
                title,
                text_content,
                content_hash,
                word_count,
                metadata_json,
                fetched_at,
                utc_now(),
            ),
        )

    def search_chunks(self, text: str, limit: int = 100, organization_id: int | None = None) -> list[dict[str, Any]]:
        terms = search_terms(text)
        query = fts_query(terms)
        if not query:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT chunks.id, chunks.text_content, chunks.token_count,
                       sources.id AS source_id, COALESCE(sources.canonical_url, sources.url) AS url,
                       sources.title, sources.source_type, sources.organization_id
                FROM chunk_fts
                JOIN chunks ON chunks.id = chunk_fts.rowid
                JOIN sources ON sources.id = chunks.source_id
                WHERE chunk_fts MATCH ?
                  AND (sources.organization_id IS NULL OR sources.organization_id = ?)
                ORDER BY bm25(chunk_fts)
                LIMIT ?
                """,
                (query, organization_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_search_source_ids(self) -> list[int]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id FROM sources ORDER BY id").fetchall()
        return [int(row["id"]) for row in rows]

    def get_source_search_documents(self, source_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT chunks.id AS chunk_id, chunks.text_content, chunks.normalized_text,
                       chunks.folded_text, chunks.token_count, sources.id AS source_id,
                       COALESCE(sources.canonical_url, sources.url) AS url,
                       sources.title, sources.source_type, sources.organization_id
                FROM chunks
                JOIN sources ON sources.id = chunks.source_id
                WHERE sources.id = ?
                ORDER BY chunks.position
                """,
                (source_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.organization_id, users.username, users.display_name,
                       users.role, organizations.name AS organization_name
                FROM users
                JOIN organizations ON organizations.id = users.organization_id
                WHERE users.username = ?
                """,
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def list_users(self, organization_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT users.id, users.organization_id, users.username, users.display_name,
                       users.role, organizations.name AS organization_name
                FROM users
                JOIN organizations ON organizations.id = users.organization_id
                WHERE CAST(? AS BIGINT) IS NULL OR users.organization_id = ?
                ORDER BY users.id
                """,
                (organization_id, organization_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_password_user(
        self,
        *,
        username: str,
        display_name: str,
        password_hash: str,
        organization_name: str,
        role: str = "student",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO organizations(slug, name, created_at)
                VALUES ('main-workspace', ?, ?)
                """,
                (organization_name, now),
            )
            organization = connection.execute(
                "SELECT id FROM organizations WHERE slug = 'main-workspace'"
            ).fetchone()
            existing = connection.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if existing:
                raise ValueError("Tên đăng nhập đã được sử dụng.")
            connection.execute(
                """
                INSERT INTO users(organization_id, username, display_name, role, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (organization["id"], username, display_name, role, password_hash, now),
            )
        user = self.get_user(username)
        if not user:  # pragma: no cover - database integrity guard
            raise RuntimeError("Không thể tạo tài khoản.")
        return user

    def get_password_user(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.organization_id, users.username, users.display_name,
                       users.role, users.password_hash, organizations.name AS organization_name
                FROM users
                JOIN organizations ON organizations.id = users.organization_id
                WHERE users.username = ? AND users.password_hash IS NOT NULL
                """,
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def create_auth_session(self, token_hash: str, user_id: int, expires_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO auth_sessions(token_hash, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, user_id, expires_at, utc_now()),
            )

    def get_user_by_session(self, token_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.organization_id, users.username, users.display_name,
                       users.role, organizations.name AS organization_name
                FROM auth_sessions
                JOIN users ON users.id = auth_sessions.user_id
                JOIN organizations ON organizations.id = users.organization_id
                WHERE auth_sessions.token_hash = ? AND auth_sessions.expires_at > ?
                """,
                (token_hash, utc_now()),
            ).fetchone()
        return dict(row) if row else None

    def delete_auth_session(self, token_hash: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))

    def save_audit_event(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str | int | None = None,
        organization_id: int | None = None,
        user_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_events(
                    organization_id, user_id, action, entity_type, entity_id,
                    details_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organization_id,
                    user_id,
                    action,
                    entity_type,
                    str(entity_id) if entity_id is not None else None,
                    json.dumps(details or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return int(cursor.lastrowid)

    def list_audit_events(self, organization_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT audit_events.id, audit_events.action, audit_events.entity_type,
                       audit_events.entity_id, audit_events.details_json,
                       audit_events.created_at, users.display_name, users.username
                FROM audit_events
                LEFT JOIN users ON users.id = audit_events.user_id
                WHERE audit_events.organization_id = ?
                ORDER BY audit_events.id DESC
                LIMIT ?
                """,
                (organization_id, limit),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            events.append(item)
        return events

    def list_sources(self, limit: int = 100, organization_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT sources.id, COALESCE(sources.canonical_url, sources.url) AS url,
                       sources.organization_id, sources.title, sources.source_type,
                       sources.word_count, sources.fetched_at,
                       COUNT(source_versions.id) AS version_count
                FROM sources
                LEFT JOIN source_versions ON source_versions.source_id = sources.id
                WHERE sources.organization_id IS NULL OR sources.organization_id = ?
                GROUP BY sources.id, sources.canonical_url, sources.url, sources.organization_id,
                         sources.title, sources.source_type, sources.word_count, sources.fetched_at,
                         sources.updated_at
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (organization_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_source_versions(
        self,
        source_id: int,
        limit: int = 50,
        organization_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_versions.id, source_versions.source_id,
                       source_versions.version_number, source_versions.title,
                       source_versions.content_hash, source_versions.word_count,
                       source_versions.metadata_json, source_versions.fetched_at,
                       source_versions.created_at
                FROM source_versions
                JOIN sources ON sources.id = source_versions.source_id
                WHERE source_versions.source_id = ?
                  AND (sources.organization_id IS NULL OR sources.organization_id = ?)
                ORDER BY version_number DESC
                LIMIT ?
                """,
                (source_id, organization_id, limit),
            ).fetchall()
        versions = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            versions.append(item)
        return versions

    def save_report(
        self,
        title: str,
        text_content: str,
        result: dict[str, Any],
        *,
        organization_id: int,
        user_id: int,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reports(
                    organization_id, user_id, title, text_content,
                    similarity_percent, result_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organization_id,
                    user_id,
                    title,
                    text_content,
                    int(result["percent"]),
                    json.dumps(result, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return int(cursor.lastrowid)

    def list_reports(
        self,
        limit: int = 20,
        organization_id: int | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, similarity_percent, result_json, created_at
                FROM reports
                WHERE organization_id = ?
                  AND (CAST(? AS BIGINT) IS NULL OR user_id = ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (organization_id, user_id, user_id, limit),
            ).fetchall()
        reports = []
        for row in rows:
            item = dict(row)
            result = json.loads(item.pop("result_json"))
            item["total_words"] = int(result.get("totalWords", 0))
            reports.append(item)
        return reports

    def get_report(
        self,
        report_id: int,
        organization_id: int,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, text_content, similarity_percent, result_json, created_at
                FROM reports
                WHERE id = ? AND organization_id = ?
                  AND (CAST(? AS BIGINT) IS NULL OR user_id = ?)
                """,
                (report_id, organization_id, user_id, user_id),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def create_submission(
        self,
        *,
        title: str,
        text_content: str,
        index_for_comparison: bool = False,
        metadata: dict[str, Any] | None = None,
        organization_id: int,
        user_id: int,
    ) -> int:
        now = utc_now()
        digest = hashlib.sha256(text_content.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            if index_for_comparison:
                existing = connection.execute(
                    """
                    SELECT id
                    FROM submissions
                    WHERE content_hash = ? AND index_for_comparison = 1
                      AND organization_id = ?
                    ORDER BY id
                    LIMIT 1
                    """,
                    (digest, organization_id),
                ).fetchone()
                if existing:
                    return int(existing["id"])
            cursor = connection.execute(
                """
                INSERT INTO submissions(
                    organization_id, user_id, title, text_content, content_hash, word_count, index_for_comparison,
                    metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organization_id,
                    user_id,
                    title,
                    text_content,
                    digest,
                    count_words(text_content),
                    int(index_for_comparison),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                ),
            )
            submission_id = int(cursor.lastrowid)

        if index_for_comparison:
            source_id = self.upsert_source(
                url=f"submission://internal/{submission_id}",
                title=f"Bài nộp nội bộ: {title}",
                text_content=text_content,
                source_type="bài nộp nội bộ",
                metadata={"submissionId": submission_id, **(metadata or {})},
                organization_id=organization_id,
            )
            with self.connect() as connection:
                connection.execute(
                    "UPDATE submissions SET source_id = ? WHERE id = ?",
                    (source_id, submission_id),
                )
        return submission_id

    def list_submissions(
        self,
        limit: int = 100,
        organization_id: int | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, title, word_count, index_for_comparison, source_id, created_at
                FROM submissions
                WHERE organization_id = ?
                  AND (CAST(? AS BIGINT) IS NULL OR user_id = ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (organization_id, user_id, user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_submission(self, submission_id: int, organization_id: int | None) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, organization_id, user_id, source_id, title
                FROM submissions
                WHERE id = ? AND organization_id = ?
                """,
                (submission_id, organization_id),
            ).fetchone()
        return dict(row) if row else None

    def delete_submission(self, submission_id: int, organization_id: int | None) -> bool:
        with self.connect() as connection:
            submission = connection.execute(
                "SELECT source_id FROM submissions WHERE id = ? AND organization_id = ?",
                (submission_id, organization_id),
            ).fetchone()
            if not submission:
                return False
            connection.execute(
                "DELETE FROM submissions WHERE id = ? AND organization_id = ?",
                (submission_id, organization_id),
            )
        if submission["source_id"]:
            self.delete_source(int(submission["source_id"]))
        return True

    def delete_source(self, source_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        if cursor.rowcount and self.search_mirror:
            self.search_mirror.delete_source(source_id)
        return bool(cursor.rowcount)

    def enqueue_url(self, url: str, depth: int = 0, discovered_from: str | None = None) -> bool:
        domain = urlparse(url).netloc.lower()
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO crawl_queue(
                    url, domain, depth, status, attempts, discovered_from,
                    next_attempt_at, created_at, updated_at
                )
                VALUES (?, ?, ?, 'queued', 0, ?, NULL, ?, ?)
                """,
                (url, domain, depth, discovered_from, now, now),
            )
        return bool(cursor.rowcount)

    def claim_next_url(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, url, domain, depth, attempts
                FROM crawl_queue
                WHERE status = 'queued'
                   OR (status = 'retry_wait' AND next_attempt_at <= ?)
                ORDER BY id
                LIMIT 1
                """,
                (utc_now(),),
            ).fetchone()
            if not row:
                return None
            connection.execute(
                """
                UPDATE crawl_queue
                SET status = 'fetching', attempts = attempts + 1,
                    last_attempt_at = ?, next_attempt_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), utc_now(), row["id"]),
            )
        return dict(row)

    def finish_crawl(self, queue_id: int, status: str, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE crawl_queue
                SET status = ?, last_error = ?, next_attempt_at = NULL,
                    completed_at = CASE WHEN ? IN ('indexed', 'skipped', 'failed') THEN ? ELSE completed_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, error, status, utc_now(), utc_now(), queue_id),
            )

    def schedule_crawl_retry(
        self,
        queue_id: int,
        *,
        error: str,
        max_attempts: int,
        retry_base_seconds: float,
    ) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT attempts FROM crawl_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            if not row:
                raise ValueError("Không tìm thấy URL trong hàng đợi.")
            attempts = int(row["attempts"])
            if attempts >= max_attempts:
                status = "failed"
                next_attempt_at = None
                completed_at = utc_now()
            else:
                status = "retry_wait"
                delay = retry_base_seconds * (2 ** max(0, attempts - 1))
                next_attempt_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
                completed_at = None
            connection.execute(
                """
                UPDATE crawl_queue
                SET status = ?, last_error = ?, next_attempt_at = ?,
                    completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error[:500], next_attempt_at, completed_at, utc_now(), queue_id),
            )
        return status

    def requeue_failed_urls(self, *, limit: int = 100) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM crawl_queue
                WHERE status = 'failed'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"""
                    UPDATE crawl_queue
                    SET status = 'queued', attempts = 0, last_error = NULL,
                        next_attempt_at = NULL, completed_at = NULL, updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    (utc_now(), *ids),
                )
        return len(ids)

    def crawl_operations(self, limit: int = 50) -> dict[str, Any]:
        with self.connect() as connection:
            queue_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM crawl_queue GROUP BY status"
            ).fetchall()
            recent_rows = connection.execute(
                """
                SELECT id, url, domain, depth, status, attempts, last_error,
                       next_attempt_at, last_attempt_at, completed_at, updated_at
                FROM crawl_queue
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            domain_rows = connection.execute(
                """
                SELECT domain,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status = 'indexed' THEN 1 ELSE 0 END) AS indexed,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN status = 'retry_wait' THEN 1 ELSE 0 END) AS retry_wait
                FROM crawl_queue
                GROUP BY domain
                ORDER BY total DESC, domain
                LIMIT 20
                """
            ).fetchall()
        return {
            "queue": {row["status"]: int(row["count"]) for row in queue_rows},
            "recent": [dict(row) for row in recent_rows],
            "domains": [dict(row) for row in domain_rows],
        }

    def stats(self, organization_id: int | None = None) -> dict[str, Any]:
        with self.connect() as connection:
            source_stats = connection.execute(
                """
                SELECT COUNT(*) AS sources, COALESCE(SUM(word_count), 0) AS words
                FROM sources
                WHERE organization_id IS NULL OR organization_id = ?
                """,
                (organization_id,),
            ).fetchone()
            chunk_count = connection.execute(
                """
                SELECT COUNT(*) AS chunks
                FROM chunks
                JOIN sources ON sources.id = chunks.source_id
                WHERE sources.organization_id IS NULL OR sources.organization_id = ?
                """,
                (organization_id,),
            ).fetchone()
            version_count = connection.execute(
                """
                SELECT COUNT(*) AS versions
                FROM source_versions
                JOIN sources ON sources.id = source_versions.source_id
                WHERE sources.organization_id IS NULL OR sources.organization_id = ?
                """,
                (organization_id,),
            ).fetchone()
            report_count = connection.execute(
                "SELECT COUNT(*) AS reports FROM reports WHERE organization_id = ?",
                (organization_id,),
            ).fetchone()
            submission_stats = connection.execute(
                """
                SELECT COUNT(*) AS submissions,
                       COALESCE(SUM(CASE WHEN index_for_comparison = 1 THEN 1 ELSE 0 END), 0)
                       AS indexed_submissions
                FROM submissions
                WHERE organization_id = ?
                """
                ,
                (organization_id,),
            ).fetchone()
            queue_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM crawl_queue GROUP BY status"
            ).fetchall()
        return {
            "sources": int(source_stats["sources"]),
            "words": int(source_stats["words"]),
            "chunks": int(chunk_count["chunks"]),
            "source_versions": int(version_count["versions"]),
            "reports": int(report_count["reports"]),
            "submissions": int(submission_stats["submissions"]),
            "indexed_submissions": int(submission_stats["indexed_submissions"]),
            "crawl_queue": {row["status"]: int(row["count"]) for row in queue_rows},
        }


class PostgresCursor:
    def __init__(self, cursor: Any, *, lastrowid: int | None = None):
        self.cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return int(self.cursor.rowcount)

    def fetchone(self) -> Any:
        return self.cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return self.cursor.fetchall()


class PostgresConnection:
    _id_tables = {
        "audit_events",
        "chunks",
        "crawl_queue",
        "organizations",
        "reports",
        "source_versions",
        "sources",
        "submissions",
        "users",
    }

    def __init__(self, connection: Any):
        self.connection = connection

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> PostgresCursor:
        statement = sql.strip().rstrip(";")
        if statement.upper() == "BEGIN IMMEDIATE":
            return PostgresCursor(self.connection.execute("SELECT 1"))
        ignore_conflicts = bool(re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", statement, re.IGNORECASE))
        statement = re.sub(
            r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
            "INSERT INTO",
            statement,
            flags=re.IGNORECASE,
        )
        replace_session = bool(re.search(r"\bINSERT\s+OR\s+REPLACE\s+INTO\s+auth_sessions\b", statement, re.IGNORECASE))
        statement = re.sub(
            r"\bINSERT\s+OR\s+REPLACE\s+INTO\b",
            "INSERT INTO",
            statement,
            flags=re.IGNORECASE,
        )
        statement = statement.replace("?", "%s")
        if replace_session:
            statement += " ON CONFLICT (token_hash) DO UPDATE SET user_id = EXCLUDED.user_id, expires_at = EXCLUDED.expires_at"
        elif ignore_conflicts:
            statement += " ON CONFLICT DO NOTHING"
        table_match = re.match(r"\s*INSERT\s+INTO\s+([a-z_]+)", statement, re.IGNORECASE)
        should_return_id = (
            table_match
            and table_match.group(1).lower() in self._id_tables
            and bool(re.search(r"\bVALUES\b", statement, re.IGNORECASE))
            and " RETURNING " not in f" {statement.upper()} "
        )
        if should_return_id:
            statement += " RETURNING id"
        cursor = self.connection.execute(statement, params)
        lastrowid = None
        if should_return_id:
            row = cursor.fetchone()
            lastrowid = int(row["id"]) if row else None
        return PostgresCursor(cursor, lastrowid=lastrowid)


class PostgresStorage(Storage):
    backend_name = "postgresql"
    search_backend_name = "postgres-like"

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.search_mirror: Any | None = None
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[PostgresConnection]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:  # pragma: no cover - dependency is installed on Render
            raise RuntimeError("Thiếu thư viện psycopg để kết nối PostgreSQL.") from error
        connection = psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)
        try:
            yield PostgresConnection(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS sources (
                id BIGSERIAL PRIMARY KEY,
                organization_id BIGINT,
                url TEXT NOT NULL UNIQUE,
                canonical_url TEXT,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'website',
                text_content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                word_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                fetched_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id BIGSERIAL PRIMARY KEY,
                source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                text_content TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                folded_text TEXT NOT NULL,
                token_count INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS crawl_queue (
                id BIGSERIAL PRIMARY KEY,
                url TEXT NOT NULL UNIQUE,
                domain TEXT NOT NULL,
                depth INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                discovered_from TEXT,
                next_attempt_at TEXT,
                last_attempt_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS crawl_queue_status_idx ON crawl_queue(status, id)",
            """
            CREATE TABLE IF NOT EXISTS reports (
                id BIGSERIAL PRIMARY KEY,
                organization_id BIGINT,
                user_id BIGINT,
                title TEXT NOT NULL,
                text_content TEXT NOT NULL,
                similarity_percent INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id BIGSERIAL PRIMARY KEY,
                organization_id BIGINT,
                user_id BIGINT,
                title TEXT NOT NULL,
                text_content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                index_for_comparison INTEGER NOT NULL DEFAULT 0,
                source_id BIGINT REFERENCES sources(id) ON DELETE SET NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS source_versions (
                id BIGSERIAL PRIMARY KEY,
                source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                text_content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                fetched_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(source_id, version_number),
                UNIQUE(source_id, content_hash)
            )
            """,
            "CREATE INDEX IF NOT EXISTS source_versions_source_idx ON source_versions(source_id, version_number DESC)",
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id BIGSERIAL PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'instructor', 'student')),
                password_hash TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS auth_sessions_user_idx ON auth_sessions(user_id)",
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id BIGSERIAL PRIMARY KEY,
                organization_id BIGINT,
                user_id BIGINT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """,
        ]
        with self.connect() as connection:
            for statement in statements:
                connection.execute(statement)
            connection.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT")
            self._backfill_source_versions(connection)
            self._seed_demo_identities(connection)

    @staticmethod
    def _backfill_source_versions(connection: PostgresConnection) -> None:
        connection.execute(
            """
            INSERT INTO source_versions(
                source_id, version_number, title, text_content, content_hash,
                word_count, metadata_json, fetched_at, created_at
            )
            SELECT sources.id, 1, sources.title, sources.text_content, sources.content_hash,
                   sources.word_count, sources.metadata_json, sources.fetched_at, sources.created_at
            FROM sources
            WHERE NOT EXISTS (
                SELECT 1 FROM source_versions WHERE source_versions.source_id = sources.id
            )
            """
        )

    def search_chunks(self, text: str, limit: int = 100, organization_id: int | None = None) -> list[dict[str, Any]]:
        terms = search_terms(text)[:10]
        if not terms:
            return []
        conditions = " OR ".join("(chunks.normalized_text ILIKE ? OR chunks.folded_text ILIKE ?)" for _ in terms)
        params: list[Any] = []
        for term in terms:
            wildcard = f"%{term}%"
            params.extend([wildcard, wildcard])
        params.extend([organization_id, limit])
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunks.id, chunks.text_content, chunks.token_count,
                       sources.id AS source_id, COALESCE(sources.canonical_url, sources.url) AS url,
                       sources.title, sources.source_type, sources.organization_id
                FROM chunks
                JOIN sources ON sources.id = chunks.source_id
                WHERE ({conditions})
                  AND (sources.organization_id IS NULL OR sources.organization_id = ?)
                ORDER BY chunks.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]


def create_storage(settings: Any) -> Storage:
    if settings.database_url:
        return PostgresStorage(settings.database_url)
    return Storage(settings.database_path)
