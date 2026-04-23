# System Patterns *Optional*

This file documents recurring patterns and standards used in the project.
It is optional, but recommended to be updated as the project evolves.
2026-04-22 13:17:52 - Log of updates made.

*

## Coding Patterns

* [2026-04-23 10:17:00] - **Immutable DTOs (Data Transfer Objects):** All events and commands passed across the Event Bus are strictly typed, immutable Python objects using `@dataclass(frozen=True)`. This guarantees thread safety by preventing background threads from modifying events while the main thread reads them.

## Architectural Patterns

* [2026-04-23 08:41:27] - **Clean Architecture (Hexagonal Architecture):** The system is structured into concentric layers (Core Domain, Application Layer, Infrastructure/Adapters). Dependencies point inwards, decoupling the UI (Vue/REST) and Database (SQLite) from the core media playback logic.
* [2026-04-23 08:41:27] - **Strict Event-Driven Architecture (EDA):** A central, asynchronous Event Bus mediates all communication. The Control Plane (FastAPI/MQTT) publishes typed `CommandEvents`. The Media Orchestrator subscribes to these and publishes `RenderCommands` to the Presentation Layer.
* [2026-04-23 08:41:27] - **State Machine Pattern:** A dedicated `PlaybackEngine` encapsulates all business logic, timing, and playback state progression. It enforces the rules for transitioning between states (e.g., `SHOWING_IMAGE`, `TRANSITIONING`, `PLAYING_VIDEO`).
* [2026-04-23 08:41:27] - **Exclusive Renderer Ownership:** Only one rendering engine (`pi3d` or GStreamer) actively owns the EGL/OpenGL context and display hardware at any given time, preventing resource contention and compositing overhead.
* [2026-04-23 08:41:27] - **Adapter / Strategy Pattern:** The Orchestrator interacts with a generic `RendererInterface`. `Pi3dRenderer` and `GstVideoRenderer` are concrete strategies, allowing the Orchestrator to command actions without knowing OpenGL or GStreamer specifics.
* [2026-04-23 08:46:48] - **Strategy Pattern (Metadata Extraction):** A unified `MetadataExtractor` service uses specific strategies (`ImageMetadataStrategy`, `VideoMetadataStrategy`) to parse different file types, returning a consistent `MediaItem` domain model.
* [2026-04-23 08:50:59] - **Modern Packaging (PEP 621):** The project utilizes a unified `pyproject.toml` for all build, dependency, and developer tooling configurations, eliminating legacy `setup.py` scripts and enforcing strict quality gates (pytest, mypy, ruff).
* [2026-04-23 08:56:55] - **Repository Pattern (Dual-Database Strategy):** The system uses two distinct databases (`config.db3` for persistent user settings, `media_cache.db3` for ephemeral media metadata). The core logic interacts with these via strict `IConfigRepository` and `IMediaRepository` interfaces, ensuring complete decoupling of the data access layer from the business logic.
* [2026-04-23 10:12:00] - **Manual Dependency Injection (Composition Root):** All components are instantiated and wired together in a single location (`main.py`) at startup. Dependencies are passed explicitly via constructors, eliminating global state and enabling robust unit testing.
* [2026-04-23 10:17:00] - **Interface Segregation Principle (ISP):** The Event Bus exposes distinct `IEventPublisher` and `IEventSubscriber` protocols. Components only receive the interface they need, preventing accidental cross-talk or invalid operations.
* [2026-04-23 10:17:00] - **Separation of Concerns (SoC) - Playlist vs. Playback:** The orchestration logic is split into a `PlaylistManager` (handling media querying, filtering, and shuffle logic) and a `PlaybackEngine` (handling state transitions and timing). This allows independent unit testing of complex playlist algorithms.
* [2026-04-23 10:17:00] - **Factory Pattern:** Used within the Composition Root to encapsulate the complex instantiation logic of dependencies (e.g., `RendererFactory`), keeping `main.py` clean and adhering to the Open/Closed Principle.

## Loop Architecture & Concurrency

* [2026-04-23 08:41:27] - **Asynchronous Control Loop:** FastAPI and MQTT clients run asynchronously, listening for external inputs and translating them into events without blocking the main application.
* [2026-04-23 08:41:27] - **Synchronous Render Loop:** The `pi3d` render loop runs continuously at 60fps. It *only* executes drawing commands received via the Event Bus; it no longer decides *when* to change images or manage the playlist.
* [2026-04-23 10:03:00] - **PriorityQueue Event Bus:** Communication between the asynchronous background threads and the synchronous main thread is handled exclusively via a thread-safe `queue.PriorityQueue`. This ensures safe cross-thread communication and allows critical commands to preempt standard events.

## Testing Patterns

*

## Definition of Done (Mandatory for every task)

All work must satisfy ALL of the following before a task is considered done:

### Development Process
- Follow Test-Driven Development (TDD):
  - Write or adapt tests first.
  - Implement only until tests pass.
  - Refactor while keeping tests green.

### Correctness
- Preserve existing behavior unless an explicit change is requested.
- No regressions may be introduced.
- The complete test suite must run successfully with zero failures.
- All new or changed logic must be covered by appropriate tests:
  - Unit tests
  - Integration tests where affected
  - Edge cases and error paths

### Code Quality
- Every touched file must include:
  - A short module-level description
  - Short and precise inline documentation for all functions
- All functions in touched modules must be fully type safe:
  - Complete type annotations
  - Pass project type checker with no errors
- Follow existing architecture and coding conventions.
- Reduce or maintain complexity; do not introduce unnecessary abstractions.
- No dead code, unused imports, commented-out code, duplication, or technical debt.

### Quality Gates (must all pass)
- Full test suite passes
- Linting passes with no errors
- Formatting checks pass
- Type checks pass
- Existing CI quality checks pass
- No warnings introduced unless explicitly justified

### Refactoring Requirements
- Prefer small, safe, incremental changes.
- Refactoring should improve readability, maintainability, or structure.
- Delete obsolete code when possible instead of preserving unused code.
- Public interfaces/APIs remain compatible unless explicitly requested otherwise.
- Document any intentional interface or behavior change.

### Non-Functional Requirements
- Do not introduce performance regressions in touched paths.
- Do not introduce security regressions.
- Respect error handling, logging, and resource management conventions.

### Completion Criteria
A task is only done when:
- Implementation is complete
- Tests are green
- Quality gates pass
- Documentation is updated
- Type safety is complete
- Refactoring goals are achieved
- The result is production-ready and review-ready

Never mark a task complete if any item above is unmet.