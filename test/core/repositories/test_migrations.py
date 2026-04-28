"""
Unit tests for the SQLite migration mechanism.

This module verifies that the MigrationManager correctly tracks schema versions
and applies migrations sequentially.
"""

import sqlite3
from collections.abc import Generator

import pytest

from picframe.core.repositories.migrations import Migration, MigrationManager


@pytest.fixture
def db_connection() -> Generator[sqlite3.Connection, None, None]:
    """Provide an in-memory SQLite database connection for testing."""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


def test_migration_manager_initialization(
    db_connection: sqlite3.Connection,
) -> None:
    """Test that the MigrationManager initializes the schema_version table."""
    manager = MigrationManager(db_connection, [])
    assert manager.get_current_version() == 0


def test_apply_string_migration(db_connection: sqlite3.Connection) -> None:
    """Test applying a migration defined as a SQL string."""
    migrations = [
        Migration(
            version=1,
            up_script=(
                "CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT);"
            ),
        )
    ]
    manager = MigrationManager(db_connection, migrations)
    manager.migrate()

    assert manager.get_current_version() == 1

    # Verify the table was created
    cursor = db_connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='test_table'"
    )
    assert cursor.fetchone() is not None


def test_apply_callable_migration(db_connection: sqlite3.Connection) -> None:
    """Test applying a migration defined as a Python callable."""

    def migration_func(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT);"
        )

    migrations = [Migration(version=1, up_script=migration_func)]
    manager = MigrationManager(db_connection, migrations)
    manager.migrate()

    assert manager.get_current_version() == 1

    # Verify the table was created
    cursor = db_connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='test_table'"
    )
    assert cursor.fetchone() is not None


def test_sequential_migrations(db_connection: sqlite3.Connection) -> None:
    """Test applying multiple migrations sequentially."""
    migrations = [
        Migration(
            version=1,
            up_script="CREATE TABLE test_table (id INTEGER PRIMARY KEY);",
        ),
        Migration(
            version=2,
            up_script="ALTER TABLE test_table ADD COLUMN name TEXT;",
        ),
    ]
    manager = MigrationManager(db_connection, migrations)
    manager.migrate()

    assert manager.get_current_version() == 2

    # Verify the column was added
    cursor = db_connection.execute("PRAGMA table_info(test_table)")
    columns = [row[1] for row in cursor.fetchall()]
    assert "name" in columns


def test_migration_failure_rolls_back(
    db_connection: sqlite3.Connection,
) -> None:
    """Test that a failed migration does not update the schema version."""
    migrations = [
        Migration(
            version=1,
            up_script="CREATE TABLE test_table (id INTEGER PRIMARY KEY);",
        ),
        Migration(
            version=2,
            up_script="INVALID SQL SYNTAX;",
        ),
    ]
    manager = MigrationManager(db_connection, migrations)

    with pytest.raises(sqlite3.OperationalError):
        manager.migrate()

    # Version should remain at 1 because version 2 failed
    assert manager.get_current_version() == 1
