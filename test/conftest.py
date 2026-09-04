"""Shared pytest configuration for Picframe tests."""

import sys
from collections.abc import Callable
from typing import Any, TypeVar
from unittest.mock import MagicMock

import pytest

# pi3d requires OpenGL/EGL which is not available on headless CI.
# Install a mock in sys.modules before any test module imports picframe modules.
if "pi3d" not in sys.modules:
    sys.modules["pi3d"] = MagicMock()

T = TypeVar("T")


async def _run_sync_inline(
    func: Callable[..., T],
    *args: Any,
    abandon_on_cancel: bool = False,
    cancellable: bool | None = None,
    limiter: Any = None,
) -> T:
    """Run AnyIO threadpool work inline under Python 3.14 test environments.

    The local Python 3.14/AnyIO stack can deadlock when Starlette offloads
    synchronous work such as FileResponse stat/open calls. Inline execution keeps
    tests deterministic without changing production code paths.
    """
    _ = abandon_on_cancel, cancellable, limiter
    return func(*args)


@pytest.fixture(autouse=True)
def anyio_python314_threadpool_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid AnyIO worker-thread deadlocks on the local Python 3.14 test stack."""
    if sys.version_info < (3, 14):
        return

    import anyio.to_thread

    monkeypatch.setattr(anyio.to_thread, "run_sync", _run_sync_inline)
