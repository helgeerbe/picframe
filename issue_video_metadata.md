---
title: Implement Video Metadata Strategy and Extension Separation
labels: next gen, enhancement
---

## Context
Currently, the `MediaIndexerService` uses a single `ImageMetadataStrategy` for all files. Video files fail EXIF extraction, leading to errors or missing metadata. To prepare for Phase 3 (Video Engine Integration) and maintain our Single Table Inheritance database schema, we need to separate image and video extensions in the configuration and implement a dedicated `VideoMetadataStrategy`.

## Tasks
- [ ] Update `frontend/src/configSchema.json` to replace `allowed_extensions` with `image_extensions` and `video_extensions` under the `model` section.
- [ ] Update `src/picframe/api/models.py` (`ModelConfig`) to reflect the new `image_extensions` and `video_extensions` fields.
- [ ] Update `src/picframe/config/default_config.yaml` to include the new extension lists.
- [ ] Create `src/picframe/core/metadata/video_strategy.py` implementing `IMetadataStrategy`.
  - Extract `width`, `height`, `duration`, and `rotation` (using `ffprobe` or legacy `video_metadata.py` logic).
  - Return a `MediaItem` with `media_type=MediaType.VIDEO`.
- [ ] Update `src/picframe/core/services/media_indexer.py` to accept both `image_strategy` and `video_strategy`, routing files based on their extension.
- [ ] Update `src/picframe/main.py` to instantiate `VideoMetadataStrategy` and inject it into `MediaIndexerService`.
- [ ] Update `src/picframe/core/services/media_monitor.py` to monitor the combined set of image and video extensions.

## Success Factors
- Video files are successfully indexed without throwing EXIF-related errors.
- Video `duration`, `width`, and `height` are correctly extracted and stored in the SQLite database.
- The application can be configured to monitor only images, only videos, or both via the new configuration keys.
- The frontend Settings UI automatically reflects the new extension configuration fields.

## Definition of Done
- [ ] Code passes all `mypy` and `ruff` quality gates.
- [ ] Unit tests are written for `VideoMetadataStrategy`.
- [ ] Unit tests for `MediaIndexerService` are updated to test routing logic.
- [ ] Integration tested locally: adding a video file successfully populates the database with correct metadata.
- [ ] No regressions in existing image indexing functionality.
