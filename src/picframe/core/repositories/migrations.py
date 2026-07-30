"""
SQLite database migration mechanism.

This module provides a standardized way to manage database schema versions
and apply migrations sequentially. It ensures that the database schema is
always up-to-date with the application code.
"""

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    """
    Represents a single database migration step.

    Attributes:
        version: The target schema version after this migration is applied.
        up_script: The SQL script or callable to apply the migration.
    """

    version: int
    up_script: str | Callable[[sqlite3.Connection], None]


class MigrationManager:
    """
    Manages the execution of database migrations.

    This class ensures that migrations are applied in the correct order
    and that the database schema version is tracked accurately.
    """

    def __init__(self, connection: sqlite3.Connection, migrations: list[Migration]) -> None:
        """
        Initialize the MigrationManager.

        Args:
            connection: The SQLite database connection.
            migrations: A list of Migration objects, ordered by version.
        """
        self._conn = connection
        self._migrations = sorted(migrations, key=lambda m: m.version)
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        """Create the schema_version table if it doesn't exist."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
                """
            )
            # Initialize version to 0 if the table is empty
            cursor = self._conn.execute("SELECT COUNT(*) FROM schema_version")
            if cursor.fetchone()[0] == 0:
                self._conn.execute("INSERT INTO schema_version (version) VALUES (0)")

    def get_current_version(self) -> int:
        """
        Retrieve the current schema version from the database.

        Returns:
            The current schema version.
        """
        cursor = self._conn.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        return row[0] if row else 0

    def _set_current_version(self, version: int) -> None:
        """
        Update the schema version in the database.

        Args:
            version: The new schema version.
        """
        with self._conn:
            self._conn.execute("UPDATE schema_version SET version = ?", (version,))

    def migrate(self) -> None:
        """
        Apply all pending migrations to the database.

        This method determines the current schema version and applies any
        migrations with a higher version number sequentially.
        """
        current_version = self.get_current_version()
        logger.info(f"Current database schema version: {current_version}")

        for migration in self._migrations:
            if migration.version > current_version:
                logger.info(f"Applying migration to version {migration.version}...")
                try:
                    with self._conn:
                        if isinstance(migration.up_script, str):
                            self._conn.executescript(migration.up_script)
                        else:
                            migration.up_script(self._conn)
                    self._set_current_version(migration.version)
                    logger.info(f"Successfully migrated to version {migration.version}.")
                except Exception as e:
                    logger.error(f"Failed to apply migration to version {migration.version}: {e}")
                    raise
