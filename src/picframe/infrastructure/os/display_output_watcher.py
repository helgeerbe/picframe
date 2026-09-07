"""Display output presence watcher (#755).

Polls the configured Wayland output's presence/enabled state and publishes
``DisplayPowerEvent`` on real off->on / on->off transitions that
:class:`~picframe.core.services.display_power.DisplayPowerManager` cannot
observe. The manager's ``WaylandDisplayPower.is_on()`` reflects only
picframe-initiated commands (it caches ``self._is_on``), so an external
power-cycle — the monitor's physical power button or a compositor-initiated
DPMS sleep — leaves the overlay orphaned with no event published: the
compositor destroys the output the layer-shell surface was bound to, recreates
a new one on power-up, and the orphaned surface never re-attaches.

The watcher reuses the *same* ``DisplayPowerEvent`` respawn path that
picframe's own power commands already drive
(``WebKitOverlayRenderer._on_display_power_event``), so external and internal
power-cycles heal identically. It is best-effort and fully safe when the
tooling is missing: when ``wlr-randr`` is absent or the compositor does not
support ``wlr-output-management``, the probe returns ``None`` and nothing is
published, so VM/headless/dev environments are unaffected.

The probe polls rather than subscribing to ``Gdk.Display::monitor-added`` on
purpose: that would pull a live GLib/GTK main loop into the main process
(violating the keep-WebKit-out-of-process non-negotiable) and would not detect
DPMS-only blanks where the output object is never destroyed.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from collections.abc import Callable

from picframe.core.events.dto import DisplayPowerEvent
from picframe.core.events.interfaces import IEventPublisher

logger = logging.getLogger(__name__)

_DEFAULT_PROBE_INTERVAL_SECONDS = 0.5
_PROBE_TIMEOUT_SECONDS = 3.0
_WLR_RANDR = "wlr-randr"
_ENABLED_RE = re.compile(r"^\s*enabled:\s*(yes|no)\s*$", re.IGNORECASE)

#: ``True`` = output present and enabled, ``False`` = absent or disabled,
#: ``None`` = probe unavailable/errored (no state change).
ProbeResult = bool | None
ProbeFn = Callable[[], ProbeResult]


class DisplayOutputWatcher:
    """Poll the configured Wayland output and publish ``DisplayPowerEvent`` on
    transitions observed from the compositor (external power-cycles).

    Only real transitions after the baseline is established are published, so
    startup never emits a spurious "power-on". Transient probe failures
    (``None``) are ignored — they neither publish nor update the baseline, so a
    flaky ``wlr-randr`` cannot fabricate a transition. Bursts are de-duplicated
    downstream by ``WebKitOverlayRenderer``'s restart guard, so a watcher event
    arriving alongside a picframe command's own ``DisplayPowerEvent`` collapses
    to a single respawn.
    """

    def __init__(
        self,
        display_output: str,
        publisher: IEventPublisher,
        *,
        probe_interval: float = _DEFAULT_PROBE_INTERVAL_SECONDS,
        probe: ProbeFn | None = None,
    ) -> None:
        self._display_output = display_output
        self._publisher = publisher
        self._probe_interval = probe_interval
        self._probe: ProbeFn = probe if probe is not None else self._default_probe
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_state: ProbeResult = None
        self._unavailable_logged = False

    def start(self) -> None:
        """Start the poller daemon thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._last_state = None
        self._unavailable_logged = False
        self._thread = threading.Thread(target=self._run, name="DisplayOutputWatcher", daemon=True)
        self._thread.start()
        logger.info(
            "DisplayOutputWatcher started (output=%s, interval=%.1fs).",
            self._display_output,
            self._probe_interval,
        )

    def stop(self) -> None:
        """Signal the poller to stop and wait for it. Idempotent."""
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._probe_interval + _PROBE_TIMEOUT_SECONDS)
        logger.info("DisplayOutputWatcher stopped.")

    # --- Probe ----------------------------------------------------------------

    def _default_probe(self) -> ProbeResult:
        """Probe via ``wlr-randr``: returns the configured output's state.

        ``True`` when the output is listed and enabled; ``False`` when it is
        absent (e.g. monitor physically off and the connector dropped from DRM)
        or present but disabled; ``None`` when the probe cannot run
        (``wlr-randr`` missing, compositor lacks ``wlr-output-management``,
        timeout, etc.).
        """
        try:
            completed = subprocess.run(
                [_WLR_RANDR],
                check=False,
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            self._log_unavailable_once(
                "`wlr-randr` not found; external power-cycle healing disabled."
            )
            return None
        except subprocess.TimeoutExpired:
            logger.debug("DisplayOutputWatcher: wlr-randr timed out; skipping probe.")
            return None

        stdout = completed.stdout or ""
        if completed.returncode != 0:
            self._log_unavailable_once(
                f"wlr-randr exited {completed.returncode}; compositor may not "
                "support wlr-output-management."
            )
            return None

        result = self._parse_output_state(stdout)
        logger.debug(
            "DisplayOutputWatcher: probe parsed %s state=%s",
            self._display_output,
            result,
        )
        return result

    def _parse_output_state(self, stdout: str) -> ProbeResult:
        """Parse a ``wlr-randr`` listing for the configured output's state.

        ``wlr-randr`` lists each output as an unindented name line followed by
        indented ``key: value`` lines. We locate the configured output's block
        and read its ``enabled:`` value. An absent output (monitor off, HPD
        drop) is reported as ``False`` (a real "off", not a probe error).

        The unindented name line carries the connector name plus an optional
        quoted human description, e.g. ``HDMI-A-2 "Samsung Electric Company
        SAMSUNG (HDMI-A-2)"``. We match on the *first whitespace-delimited
        token* (the connector name) rather than the whole line, so a real
        ``wlr-randr`` dump with a description is correctly detected (#755).
        The older exact-equality comparison only ever matched fictional fixtures
        that emit a bare name, so the watcher silently mis-detected every real
        output as absent/off.
        """
        in_target_block = False
        enabled: bool | None = None
        for line in stdout.splitlines():
            is_indented = line[:1].isspace()
            stripped = line.strip()
            if not is_indented and stripped:
                name_token = stripped.split(None, 1)[0]
                in_target_block = name_token == self._display_output
                continue
            if not in_target_block:
                continue
            match = _ENABLED_RE.match(line)
            if match:
                enabled = match.group(1).lower() == "yes"
                break
        if not in_target_block and enabled is None:
            # Configured output is not listed at all -> output destroyed/off.
            return False
        if enabled is None:
            # Listed but no `enabled:` key seen; assume present and on (older
            # wlr-randr only lists enabled outputs by default).
            return True
        return enabled

    # --- Loop -----------------------------------------------------------------

    def _run(self) -> None:
        # Establish a baseline without publishing so startup never emits a
        # spurious power-on.
        self._last_state = self._probe()
        while not self._stop_event.is_set():
            self._stop_event.wait(self._probe_interval)
            if self._stop_event.is_set():
                break
            state = self._probe()
            if state is None:
                continue
            if state != self._last_state and self._last_state is not None:
                logger.info(
                    "DisplayOutputWatcher: %s power state %s -> %s; publishing DisplayPowerEvent.",
                    self._display_output,
                    self._last_state,
                    state,
                )
                self._publisher.publish(DisplayPowerEvent(power_on=state))
            self._last_state = state

    # --- Helpers --------------------------------------------------------------

    def _log_unavailable_once(self, message: str) -> None:
        if self._unavailable_logged:
            logger.debug("DisplayOutputWatcher: %s", message)
            return
        self._unavailable_logged = True
        logger.warning("DisplayOutputWatcher: %s", message)
