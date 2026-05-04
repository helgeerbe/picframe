# Configuration Management

Picframe uses a centralized configuration management system backed by SQLite and validated by Pydantic.

## Initialization (`picframe init`)

When you run `picframe init`, the application bootstraps your environment (defaulting to `~/.picframe`).

### Interactive Prompts
If the configuration database (`config.db3`) or media cache database (`media_cache.db3`) already exists, the CLI will interactively prompt you to either keep or delete them.

### Force Flag
For automated environments (like Docker or CI/CD), you can bypass these prompts using the `--force` (or `-f`) flag:
```bash
picframe init --force
```
This will automatically overwrite any existing databases.

### Database Seeding
If the configuration database is newly created or cleared, it is automatically seeded with default values. These defaults are read from `src/picframe/config/default_config.yaml`, validated against the Pydantic models, and stored in the SQLite database.


## CLI Parameters

The `picframe run` command accepts several parameters to override default paths and ports. These parameters take precedence over any configuration database settings.

*   `--dir`: Base directory for picframe data (default: `~/.picframe` or `PICFRAME_DIR` env var).
*   `--port`: Port for the web server (default: `9000` or `PICFRAME_PORT` env var).
*   `--config-db`: Path to config database (default: `<dir>/data/config.db3` or `PICFRAME_CONFIG_DB` env var).
*   `--media-db`: Path to media database (default: `<dir>/data/media_cache.db3` or `PICFRAME_MEDIA_DB` env var).
*   `--html-dir`: Path to frontend HTML assets (default: `<dir>/html` or `PICFRAME_HTML_DIR` env var).

*Note: The webserver port and HTML directory path are strictly managed via CLI arguments and environment variables. They are not editable via the frontend UI to prevent connection loss and synchronization issues.*


## CLI Parameters

The `picframe run` command accepts several parameters to override default paths and ports. These parameters take precedence over any configuration database settings.

*   `--dir`: Base directory for picframe data (default: `~/.picframe` or `PICFRAME_DIR` env var).
*   `--port`: Port for the web server (default: `9000` or `PICFRAME_PORT` env var).
*   `--config-db`: Path to config database (default: `<dir>/data/config.db3` or `PICFRAME_CONFIG_DB` env var).
*   `--media-db`: Path to media database (default: `<dir>/data/media_cache.db3` or `PICFRAME_MEDIA_DB` env var).
*   `--html-dir`: Path to frontend HTML assets (default: `<dir>/html` or `PICFRAME_HTML_DIR` env var).

*Note: The webserver port and HTML directory path are strictly managed via CLI arguments and environment variables. They are not editable via the frontend UI to prevent connection loss and synchronization issues.*

## Developer Guide: Adding Configuration Keys

To add a new configuration key, you must update three locations to ensure the frontend, backend validation, and database seeding remain synchronized:

1.  **Frontend Schema (`frontend/src/configSchema.json`)**:
    Add the new key and its type to the appropriate section. This dictates how the Vue.js frontend renders the input field.

2.  **Backend Baseline (`src/picframe/config/default_config.yaml`)**:
    Add the new key with its default value. This file acts as the single source of truth for factory resets and initial database seeding.

3.  **Backend Validation (`src/picframe/api/models.py`)**:
    Add the new key to the corresponding Pydantic model (e.g., `ViewerConfig`, `ModelConfig`). Ensure you provide a default value (e.g., `my_new_key: int = 10`) so that validation passes even if the key is missing from an older database.

## Database Migrations

Picframe uses a code-based migration system to handle schema changes for both `config.db3` and `media_cache.db3`.

To modify a database schema:
1.  Open the relevant repository file (`src/picframe/core/repositories/sqlite_config.py` or `sqlite_media.py`).
2.  Locate the `MIGRATIONS` list (e.g., `CONFIG_MIGRATIONS`).
3.  Append a new `Migration` object to the list.
4.  Increment the `version` integer sequentially.
5.  Provide the SQL `up_script` to execute the schema change.

Example:
```python
CONFIG_MIGRATIONS = [
    # ... existing migrations ...
    Migration(
        version=2,
        up_script="ALTER TABLE app_config ADD COLUMN description TEXT;"
    )
]
```
The `MigrationManager` will automatically detect and apply this script during the next application startup.