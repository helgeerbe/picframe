"""
SQLite implementation of the IMediaRepository.

This module provides the concrete implementation for managing ephemeral
media metadata using a SQLite database (`media_cache.db3`).
"""

import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from picframe.core.models.playlist import (
    PlaylistCriteria,
    SHUFFLE_MODE_STANDARD,
    normalize_shuffle_mode,
)
from picframe.core.repositories.interfaces import IMediaRepository
from picframe.core.repositories.migrations import Migration, MigrationManager

logger = logging.getLogger(__name__)

# Define the initial schema migration for media_cache.db3
MEDIA_MIGRATIONS = [
    Migration(
        version=1,
        up_script="""
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            directory_id INTEGER NOT NULL,
            media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
            file_size INTEGER NOT NULL,
            last_modified REAL NOT NULL,
            width INTEGER,
            height INTEGER,
            orientation INTEGER DEFAULT 1,
            exif_datetime REAL,
            f_number REAL,
            exposure_time TEXT,
            iso INTEGER,
            focal_length TEXT,
            make TEXT,
            model TEXT,
            lens TEXT,
            rating INTEGER,
            latitude REAL,
            longitude REAL,
            title TEXT,
            caption TEXT,
            tags TEXT,
            is_portrait INTEGER,
            location TEXT,
            duration REAL,
            codec TEXT,
            pixel_format TEXT,
            framerate REAL,
            bitrate INTEGER,
            displayed_count INTEGER DEFAULT 0 NOT NULL,
            last_displayed REAL DEFAULT 0 NOT NULL,
            is_deleted INTEGER DEFAULT 0,
            created_at REAL DEFAULT (julianday('now')),
            updated_at REAL DEFAULT (julianday('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_media_directory ON media(directory_id);
        CREATE INDEX IF NOT EXISTS idx_media_type ON media(media_type);
        CREATE INDEX IF NOT EXISTS idx_media_deleted ON media(is_deleted);
        CREATE INDEX IF NOT EXISTS idx_media_last_modified ON media(last_modified);
        CREATE INDEX IF NOT EXISTS idx_media_exif_datetime ON media(exif_datetime);
        CREATE INDEX IF NOT EXISTS idx_media_location ON media(location);
        CREATE INDEX IF NOT EXISTS idx_media_tags ON media(tags);

        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            address TEXT,
            UNIQUE (latitude, longitude)
        );

        CREATE TABLE IF NOT EXISTS geocoding_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            created_at REAL DEFAULT (julianday('now')),
            UNIQUE (latitude, longitude)
        );
        """,
    ),
]

SORT_COLUMN_MAP = {
    "id": "m.id",
    "file_id": "m.id",
    "filepath": "m.filepath",
    "fname": "m.filepath",
    "filename": "m.filename",
    "last_modified": "m.last_modified",
    "orientation": "m.orientation",
    "exif_datetime": "m.exif_datetime",
    "f_number": "m.f_number",
    "exposure_time": "m.exposure_time",
    "iso": "m.iso",
    "focal_length": "m.focal_length",
    "make": "m.make",
    "model": "m.model",
    "lens": "m.lens",
    "rating": "m.rating",
    "latitude": "m.latitude",
    "longitude": "m.longitude",
    "width": "m.width",
    "height": "m.height",
    "title": "m.title",
    "caption": "m.caption",
    "tags": "m.tags",
    "is_portrait": "m.is_portrait",
    "location": "COALESCE(l.address, m.location)",
    "displayed_count": "m.displayed_count",
    "last_displayed": "m.last_displayed",
}

SORT_COLUMNS_FOR_UI = [
    {"key": "fname", "label": "File name"},
    {"key": "exif_datetime", "label": "Date taken"},
    {"key": "last_modified", "label": "Modified date"},
    {"key": "rating", "label": "Rating"},
    {"key": "location", "label": "Location"},
    {"key": "displayed_count", "label": "Shown count"},
    {"key": "last_displayed", "label": "Last shown"},
]


@dataclass(frozen=True)
class _FilterToken:
    kind: str
    value: str


class _FilterParser:
    """Translate a small boolean text-filter language into parameterized SQL."""

    _token_re = re.compile(r'"([^"]+)"|(\()|(\))|\b(AND|OR|NOT)\b|([^\s()]+)', re.I)

    def __init__(self, expression: str, column_sql: str) -> None:
        self._tokens = self._tokenize(expression)
        self._column_sql = column_sql
        self._index = 0
        self.params: list[Any] = []

    @classmethod
    def _tokenize(cls, expression: str) -> list[_FilterToken]:
        tokens: list[_FilterToken] = []
        for match in cls._token_re.finditer(expression):
            quoted, left, right, operator, term = match.groups()
            if quoted:
                tokens.append(_FilterToken("term", quoted))
            elif left:
                tokens.append(_FilterToken("left", left))
            elif right:
                tokens.append(_FilterToken("right", right))
            elif operator:
                tokens.append(_FilterToken("operator", operator.upper()))
            elif term:
                tokens.append(_FilterToken("term", term))
        return tokens

    def parse(self) -> str | None:
        if not self._tokens:
            return None
        sql = self._parse_or()
        if sql is None or self._peek() is not None:
            return None
        return sql

    def _peek(self) -> _FilterToken | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _consume(self) -> _FilterToken | None:
        token = self._peek()
        if token is not None:
            self._index += 1
        return token

    def _parse_or(self) -> str | None:
        sql = self._parse_and()
        if sql is None:
            return None
        while self._peek_is_operator("OR"):
            self._consume()
            rhs = self._parse_and()
            if rhs is None:
                return None
            sql = f"({sql} OR {rhs})"
        return sql

    def _parse_and(self) -> str | None:
        sql = self._parse_not()
        if sql is None:
            return None
        while self._peek_is_operator("AND"):
            self._consume()
            rhs = self._parse_not()
            if rhs is None:
                return None
            sql = f"({sql} AND {rhs})"
        return sql

    def _parse_not(self) -> str | None:
        token = self._peek()
        if token and token.kind == "operator" and token.value == "NOT":
            self._consume()
            sql = self._parse_not()
            return f"(NOT {sql})" if sql is not None else None
        return self._parse_primary()

    def _parse_primary(self) -> str | None:
        token = self._consume()
        if token is None:
            return None
        if token.kind == "left":
            sql = self._parse_or()
            closing = self._consume()
            if sql is None or closing is None or closing.kind != "right":
                return None
            return f"({sql})"
        if token.kind != "term":
            return None
        phrase = [token.value]
        while True:
            next_peek = self._peek()
            if next_peek is None or next_peek.kind != "term":
                break
            next_token = self._consume()
            if next_token is not None:
                phrase.append(next_token.value)
        self.params.append(f"%{self._escape_like(' '.join(phrase).lower())}%")
        return f"LOWER(COALESCE({self._column_sql}, '')) LIKE ? ESCAPE '\\'"

    def _peek_is_operator(self, value: str) -> bool:
        token = self._peek()
        return token is not None and token.kind == "operator" and token.value == value

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SQLiteMediaRepository(IMediaRepository):
    """
    SQLite-backed repository for media metadata cache.

    This class manages the `media_cache.db3` database, ensuring thread-safe
    access and automatic schema migrations upon initialization.
    """

    def __init__(self, db_path: str) -> None:
        """
        Initialize the SQLiteMediaRepository.

        Args:
            db_path: The file path to the SQLite database.
        """
        self._db_path = db_path
        self._conn = sqlite3.connect(
            self._db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        
        # Enable WAL mode for better concurrency
        self._conn.execute("PRAGMA journal_mode=WAL;")

        # Run migrations
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Execute database migrations to ensure the schema is up-to-date."""
        manager = MigrationManager(self._conn, MEDIA_MIGRATIONS)
        manager.migrate()

    def add_media_item(self, media_data: dict[str, Any]) -> int:
        """
        Add a new media item to the cache, or update if it exists.

        Args:
            media_data: A dictionary containing the media metadata.

        Returns:
            The ID of the newly inserted or updated media item.
        """
        media_data = dict(media_data)
        existing = None
        filepath = media_data.get("filepath")
        if filepath:
            existing = self.get_media_by_path(str(filepath))
        if existing:
            if not media_data.get("id"):
                media_data["id"] = existing["id"]
            media_data["displayed_count"] = existing.get("displayed_count", 0)
            media_data["last_displayed"] = existing.get("last_displayed", 0.0)

        columns = ", ".join(media_data.keys())
        placeholders = ", ".join("?" for _ in media_data)
        
        # Use INSERT OR REPLACE to handle unique constraint on filepath
        query = f"INSERT OR REPLACE INTO media ({columns}) VALUES ({placeholders})"
        
        with self._conn:
            cursor = self._conn.execute(query, tuple(media_data.values()))
            return cursor.lastrowid or 0

    def get_media_by_path(self, filepath: str) -> dict[str, Any] | None:
        """
        Retrieve a media item by its filepath.

        Args:
            filepath: The filepath of the media item to retrieve.

        Returns:
            A dictionary containing the media metadata, or None if not found.
        """
        cursor = self._conn.execute(
            """
            SELECT m.*, COALESCE(l.address, m.location) as location
            FROM media m
            LEFT JOIN locations l ON ROUND(m.latitude, 4) = ROUND(l.latitude, 4)
                AND ROUND(m.longitude, 4) = ROUND(l.longitude, 4)
            WHERE m.filepath = ?
            """,
            (filepath,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def delete_media_by_path(self, filepath: str) -> None:
        """
        Mark a media item as inactive by its filepath.

        Args:
            filepath: The filepath of the media item to mark inactive.
        """
        with self._conn:
            self._conn.execute(
                "UPDATE media SET is_deleted = 1, updated_at = julianday('now') "
                "WHERE filepath = ?",
                (filepath,),
            )

    def get_media_item(self, media_id: int) -> dict[str, Any] | None:
        """
        Retrieve a media item by its ID.

        Args:
            media_id: The ID of the media item to retrieve.

        Returns:
            A dictionary containing the media metadata, or None if not found.
        """
        cursor = self._conn.execute(
            """
            SELECT m.*, COALESCE(l.address, m.location) as location
            FROM media m
            LEFT JOIN locations l ON ROUND(m.latitude, 4) = ROUND(l.latitude, 4)
                AND ROUND(m.longitude, 4) = ROUND(l.longitude, 4)
            WHERE m.id = ?
            """,
            (media_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_media_item(self, media_id: int, updates: dict[str, Any]) -> None:
        """
        Update specific fields of an existing media item.

        Args:
            media_id: The ID of the media item to update.
            updates: A dictionary of fields to update.
        """
        if not updates:
            return

        # Automatically update the updated_at timestamp
        if "updated_at" not in updates:
            updates["updated_at"] = "julianday('now')"
            
        set_clause = ", ".join(
            f"{k} = ?" if k != "updated_at" else f"{k} = {v}" 
            for k, v in updates.items()
        )
        
        # Filter out the raw SQL values from the parameters
        params = tuple(v for k, v in updates.items() if k != "updated_at") + (media_id,)
        
        query = f"UPDATE media SET {set_clause} WHERE id = ?"
        
        with self._conn:
            self._conn.execute(query, params)

    def delete_media_item(self, media_id: int) -> None:
        """
        Mark a media item as inactive.

        Args:
            media_id: The ID of the media item to mark inactive.
        """
        with self._conn:
            self._conn.execute(
                "UPDATE media SET is_deleted = 1, updated_at = julianday('now') "
                "WHERE id = ?",
                (media_id,),
            )

    def remove_media_item(self, media_id: int) -> None:
        """
        Remove a media item from the cache.

        Args:
            media_id: The ID of the media item to remove.
        """
        with self._conn:
            self._conn.execute("DELETE FROM media WHERE id = ?", (media_id,))

    def get_all_media(self) -> list[dict[str, Any]]:
        """
        Retrieve all active (non-deleted) media items.

        Returns:
            A list of dictionaries containing media metadata.
        """
        cursor = self._conn.execute(
            """
            SELECT m.*, COALESCE(l.address, m.location) as location
            FROM media m
            LEFT JOIN locations l ON ROUND(m.latitude, 4) = ROUND(l.latitude, 4)
                AND ROUND(m.longitude, 4) = ROUND(l.longitude, 4)
            WHERE m.is_deleted = 0
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_media(self, criteria: PlaylistCriteria) -> list[dict[str, Any]]:
        """
        Retrieve active media matching playlist criteria.
        """
        where_clauses, params = self._build_media_where(criteria)
        order_clause = self._build_order_clause(criteria)

        cursor = self._conn.execute(
            f"""
            SELECT m.*, COALESCE(l.address, m.location) as location
            FROM media m
            LEFT JOIN locations l ON ROUND(m.latitude, 4) = ROUND(l.latitude, 4)
                AND ROUND(m.longitude, 4) = ROUND(l.longitude, 4)
            WHERE {" AND ".join(where_clauses)}
            ORDER BY {order_clause}
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def count_media(self, criteria: PlaylistCriteria) -> dict[str, Any]:
        """
        Count active media matching playlist criteria and the active folder scope.
        """
        selected_where, selected_params = self._build_media_where(criteria)
        total_where, total_params = self._build_media_where(
            criteria,
            include_date_filters=False,
            include_text_filters=False,
        )
        scope_label = (criteria.subdirectory or "").strip().strip("/")
        return {
            "selected_count": self._count_media_where(selected_where, selected_params),
            "total_count": self._count_media_where(total_where, total_params),
            "scope": "subdirectory" if scope_label else "pic_dir",
            "scope_label": scope_label or str(Path(criteria.pic_dir or "").expanduser()),
        }

    def record_media_displayed(self, media_id: int) -> dict[str, Any] | None:
        """Increment display statistics and return the updated media item."""
        with self._conn:
            self._conn.execute(
                """
                UPDATE media
                SET displayed_count = COALESCE(displayed_count, 0) + 1,
                    last_displayed = ?,
                    updated_at = julianday('now')
                WHERE id = ? AND is_deleted = 0
                """,
                (time.time(), media_id),
            )
        return self.get_media_item(media_id)

    def get_filter_options(self, pic_dir: str | None = None) -> dict[str, Any]:
        """Return distinct values for Remote filter controls."""
        cursor = self._conn.execute(
            """
            SELECT m.filepath, COALESCE(l.address, m.location) as location, m.tags
            FROM media m
            LEFT JOIN locations l ON ROUND(m.latitude, 4) = ROUND(l.latitude, 4)
                AND ROUND(m.longitude, 4) = ROUND(l.longitude, 4)
            WHERE m.is_deleted = 0
            """
        )
        subdirectories: set[str] = set()
        locations: set[str] = set()
        tags: set[str] = set()
        root = Path(pic_dir).expanduser() if pic_dir else None

        for row in cursor.fetchall():
            filepath = row["filepath"]
            if filepath:
                parent = Path(filepath).expanduser().parent
                subdirectory = self._relative_subdirectory(parent, root)
                if subdirectory:
                    subdirectories.add(subdirectory)
            location = row["location"]
            if location:
                locations.add(str(location))
            for tag in str(row["tags"] or "").split(","):
                tag = tag.strip()
                if tag:
                    tags.add(tag)

        return {
            "subdirectories": sorted(subdirectories, key=str.casefold),
            "locations": sorted(locations, key=str.casefold),
            "tags": sorted(tags, key=str.casefold),
            "sort_columns": SORT_COLUMNS_FOR_UI,
        }

    def _build_media_where(
        self,
        criteria: PlaylistCriteria,
        *,
        include_date_filters: bool = True,
        include_text_filters: bool = True,
    ) -> tuple[list[str], list[Any]]:
        where_clauses = ["m.is_deleted = 0"]
        params: list[Any] = []

        media_root = self._path_prefix(criteria.pic_dir, criteria.subdirectory)
        if media_root:
            where_clauses.append("m.filepath LIKE ?")
            params.append(f"{media_root}%")

        if include_date_filters:
            timestamp_expr = "COALESCE(NULLIF(m.exif_datetime, 0), m.last_modified)"
            date_from = self._parse_date_boundary(criteria.date_from, end_of_day=False)
            date_to = self._parse_date_boundary(criteria.date_to, end_of_day=True)
            if date_from is not None:
                where_clauses.append(f"{timestamp_expr} >= ?")
                params.append(date_from)
            if date_to is not None:
                where_clauses.append(f"{timestamp_expr} <= ?")
                params.append(date_to)

        if include_text_filters:
            for expression, column in (
                (criteria.location_filter, "COALESCE(l.address, m.location)"),
                (criteria.tags_filter, "m.tags"),
            ):
                sql, filter_params = self._build_text_filter(expression, column)
                if sql:
                    where_clauses.append(f"({sql})")
                    params.extend(filter_params)

        return where_clauses, params

    def _count_media_where(self, where_clauses: list[str], params: list[Any]) -> int:
        cursor = self._conn.execute(
            f"""
            SELECT COUNT(DISTINCT m.id)
            FROM media m
            LEFT JOIN locations l ON ROUND(m.latitude, 4) = ROUND(l.latitude, 4)
                AND ROUND(m.longitude, 4) = ROUND(l.longitude, 4)
            WHERE {" AND ".join(where_clauses)}
            """,
            params,
        )
        return int(cursor.fetchone()[0])

    @staticmethod
    def _path_prefix(pic_dir: str, subdirectory: str) -> str:
        root = Path(pic_dir or "").expanduser()
        if not str(root):
            return ""
        subdirectory = (subdirectory or "").strip().strip("/")
        base = root / subdirectory if subdirectory else root
        return str(base).rstrip("/") + "/"

    @staticmethod
    def _parse_date_boundary(value: str | float | int | None, *, end_of_day: bool) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        value_str = str(value).strip()
        if not value_str:
            return None
        try:
            return float(value_str)
        except ValueError:
            pass
        for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y,%m,%d"):
            try:
                dt = datetime.strptime(value_str, date_format).replace(tzinfo=UTC)
                if end_of_day:
                    dt = dt + timedelta(days=1) - timedelta(milliseconds=1)
                return dt.timestamp()
            except ValueError:
                continue
        logger.warning("Ignoring invalid playlist date filter: %s", value)
        return None

    @staticmethod
    def _build_text_filter(expression: str, column_sql: str) -> tuple[str | None, list[Any]]:
        expression = (expression or "").strip()
        if not expression:
            return None, []
        parser = _FilterParser(expression, column_sql)
        sql = parser.parse()
        if sql is None:
            logger.warning("Ignoring invalid playlist text filter: %s", expression)
            return None, []
        return sql, parser.params

    @staticmethod
    def _build_order_clause(criteria: PlaylistCriteria) -> str:
        order_parts: list[str] = []
        if criteria.recent_n and criteria.recent_n > 0:
            threshold = time.time() - (float(criteria.recent_n) * 24 * 60 * 60)
            order_parts.append(
                f"CASE WHEN m.last_modified >= {threshold:.6f} THEN 0 ELSE 1 END ASC"
            )

        if (
            criteria.shuffle
            and normalize_shuffle_mode(criteria.shuffle_mode) == SHUFFLE_MODE_STANDARD
        ):
            order_parts.append("RANDOM()")
            return ", ".join(order_parts)

        parsed_sort = SQLiteMediaRepository._parse_sort_columns(criteria.sort_cols)
        order_parts.extend(parsed_sort or ["m.filepath ASC"])
        if "m.filepath ASC" not in order_parts:
            order_parts.append("m.filepath ASC")
        return ", ".join(order_parts)

    @staticmethod
    def _parse_sort_columns(sort_cols: str) -> list[str]:
        order_parts: list[str] = []
        for item in (sort_cols or "").split(","):
            item = item.strip()
            if not item:
                continue
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\s+(ASC|DESC))?", item, re.I)
            if not match:
                logger.warning("Ignoring invalid playlist sort expression: %s", item)
                continue
            key, direction = match.groups()
            column_sql = SORT_COLUMN_MAP.get(key.lower())
            if not column_sql:
                logger.warning("Ignoring unknown playlist sort column: %s", key)
                continue
            direction = (direction or "ASC").upper()
            order_parts.append(f"{column_sql} {direction}")
        return order_parts

    @staticmethod
    def _relative_subdirectory(parent: Path, root: Path | None) -> str:
        if root is None:
            return parent.name
        try:
            relative = parent.relative_to(root)
        except ValueError:
            return parent.name
        if str(relative) == ".":
            return ""
        return relative.as_posix()

    def get_location(self, latitude: float, longitude: float) -> str | None:
        """
        Retrieve a cached location string for the given coordinates.

        Args:
            latitude: The latitude coordinate.
            longitude: The longitude coordinate.

        Returns:
            The cached address string, or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT address FROM locations WHERE latitude = ? AND longitude = ?",
            (latitude, longitude),
        )
        row = cursor.fetchone()
        return row["address"] if row else None

    def save_location(self, latitude: float, longitude: float, address: str) -> None:
        """
        Save a resolved location string for the given coordinates.

        Args:
            latitude: The latitude coordinate.
            longitude: The longitude coordinate.
            address: The resolved address string.
        """
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO locations (latitude, longitude, address) VALUES (?, ?, ?)",
                (latitude, longitude, address),
            )

    def enqueue_location_lookup(self, latitude: float, longitude: float) -> None:
        """
        Add a location lookup task to the persistent queue.

        Args:
            latitude: The latitude coordinate.
            longitude: The longitude coordinate.
        """
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO geocoding_queue (latitude, longitude) VALUES (?, ?)",
                (latitude, longitude),
            )

    def dequeue_location_lookup(self) -> tuple[float, float] | None:
        """
        Retrieve and remove the next location lookup task from the queue.

        Returns:
            A tuple of (latitude, longitude), or None if the queue is empty.
        """
        with self._conn:
            cursor = self._conn.execute(
                """
                SELECT id, latitude, longitude
                FROM geocoding_queue
                ORDER BY created_at ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row:
                self._conn.execute("DELETE FROM geocoding_queue WHERE id = ?", (row["id"],))
                return row["latitude"], row["longitude"]
            return None

    def purge_missing_files(self) -> int:
        """
        Remove database entries for files that no longer exist on disk.

        Returns:
            The number of purged records.
        """
        import os
        
        cursor = self._conn.execute("SELECT id, filepath FROM media")
        rows = cursor.fetchall()
        
        missing_ids = []
        for row in rows:
            if not os.path.exists(row["filepath"]):
                missing_ids.append(row["id"])
                
        if not missing_ids:
            return 0
            
        # Delete in batches to avoid SQLite limits
        batch_size = 999
        purged_count = 0
        
        with self._conn:
            for i in range(0, len(missing_ids), batch_size):
                batch = missing_ids[i:i + batch_size]
                placeholders = ",".join("?" * len(batch))
                cursor = self._conn.execute(
                    f"DELETE FROM media WHERE id IN ({placeholders})",
                    batch
                )
                purged_count += cursor.rowcount
                
        return purged_count

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
