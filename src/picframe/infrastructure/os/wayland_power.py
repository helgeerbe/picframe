"""
Wayland Display Power Adapter.

This module provides the concrete implementation of the IDisplayPower port
for Wayland environments, utilizing the `wlr-randr` utility to manage
display power states.
"""

import logging
import subprocess

from picframe.core.events.dto import SystemErrorEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.ports import IDisplayPower

logger = logging.getLogger(__name__)


class WaylandDisplayPower(IDisplayPower):
    """
    Concrete implementation of IDisplayPower for Wayland using wlr-randr.
    Uses ddcutil for external monitor brightness and brightnessctl for internal displays.
    """

    def __init__(
        self,
        display_output: str = "HDMI-A-1",
        is_external: bool | None = None,
        publisher: IEventPublisher | None = None,
    ) -> None:
        """
        Initialize the Wayland display power adapter.

        Args:
            display_output: The name of the Wayland output to control (e.g., 'HDMI-A-1').
            is_external: Whether the display is external (uses ddcutil) or internal
                         (uses brightnessctl). If omitted, this is inferred from
                         the output name.
            publisher: Optional event publisher for broadcasting system errors.
        """
        self._is_on = True
        self._display_output = display_output
        self._is_external_override = is_external is not None
        self.is_external = (
            bool(is_external)
            if is_external is not None
            else self._infer_external_display(display_output)
        )
        self._publisher = publisher
        self._ddc_brightness_supported: bool | None = None
        self._ddc_brightness_unavailable_message: str | None = None
        self._last_brightness_error_signature: str | None = None
        logger.info(
            "WaylandDisplayPower initialized for output: %s, external: %s",
            self._display_output,
            self.is_external,
        )

    @staticmethod
    def _infer_external_display(display_output: str) -> bool:
        """Return whether the output normally uses external-monitor brightness."""
        output = str(display_output or "").strip().upper()
        return not output.startswith(("DSI", "EDP", "LVDS"))

    def turn_on(self) -> None:
        """Turn the display on using wlr-randr."""
        try:
            subprocess.run(
                ["wlr-randr", "--output", self._display_output, "--on"],
                check=True,
                capture_output=True,
            )
            self._is_on = True
            logger.info(f"WaylandDisplayPower: Display {self._display_output} turned ON.")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to turn display ON: {e.stderr.decode()}"
            logger.error(f"WaylandDisplayPower: {error_msg}")
            if self._publisher:
                self._publisher.publish(
                    SystemErrorEvent(
                        component="WaylandDisplayPower",
                        message=error_msg,
                    )
                )
        except FileNotFoundError:
            error_msg = "wlr-randr not found. Is it installed?"
            logger.error(f"WaylandDisplayPower: {error_msg}")
            if self._publisher:
                self._publisher.publish(
                    SystemErrorEvent(
                        component="WaylandDisplayPower",
                        message=error_msg,
                    )
                )

    def turn_off(self) -> None:
        """Turn the display off using wlr-randr."""
        try:
            subprocess.run(
                ["wlr-randr", "--output", self._display_output, "--off"],
                check=True,
                capture_output=True,
            )
            self._is_on = False
            logger.info("WaylandDisplayPower: Display turned OFF.")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to turn display OFF: {e.stderr.decode()}"
            logger.error(f"WaylandDisplayPower: {error_msg}")
            if self._publisher:
                self._publisher.publish(
                    SystemErrorEvent(
                        component="WaylandDisplayPower",
                        message=error_msg,
                    )
                )
        except FileNotFoundError:
            error_msg = "wlr-randr not found. Is it installed?"
            logger.error(f"WaylandDisplayPower: {error_msg}")
            if self._publisher:
                self._publisher.publish(
                    SystemErrorEvent(
                        component="WaylandDisplayPower",
                        message=error_msg,
                    )
                )

    def toggle(self) -> None:
        """Toggle the display power state."""
        if self.is_on():
            self.turn_off()
        else:
            self.turn_on()

    def set_brightness(self, value: float) -> None:
        """Set the display brightness (0.0 to 1.0)."""
        percent_int = max(0, min(100, round(value * 100)))

        if self.is_external:
            # Use ddcutil for HDMI/DP monitors
            if not self._ensure_ddc_brightness_supported():
                return
            if self._run_brightness_command(
                ["ddcutil", "setvcp", "10", str(percent_int)],
                "external brightness via ddcutil",
                "ddcutil-setvcp",
                timeout=5.0,
            ):
                self._last_brightness_error_signature = None
                logger.info("Set external monitor brightness to %s%%", percent_int)
            return

        # Use brightnessctl for internal/DSI displays
        if self._run_brightness_command(
            ["brightnessctl", "set", f"{percent_int}%"],
            "internal brightness via brightnessctl",
            "brightnessctl-set",
            timeout=5.0,
        ):
            self._last_brightness_error_signature = None
            logger.info("Set internal display brightness to %s%%", percent_int)

    def _ensure_ddc_brightness_supported(self) -> bool:
        """Probe VCP 0x10 once before attempting DDC brightness writes."""
        if self._ddc_brightness_supported is True:
            return True
        if self._ddc_brightness_supported is False:
            self._report_brightness_error(
                self._ddc_brightness_unavailable_message
                or "DDC brightness is not available for this display.",
                "ddcutil-getvcp",
            )
            return False

        try:
            subprocess.run(
                ["ddcutil", "getvcp", "10"],
                check=True,
                capture_output=True,
                timeout=5.0,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
            self._ddc_brightness_supported = False
            self._ddc_brightness_unavailable_message = (
                "DDC brightness is not available for this display; "
                f"cannot verify VCP 0x10 with ddcutil getvcp 10. {self._command_error_details(exc)}"
            )
            self._report_brightness_error(
                self._ddc_brightness_unavailable_message,
                "ddcutil-getvcp",
            )
            return False

        self._ddc_brightness_supported = True
        return True

    def _run_brightness_command(
        self,
        command: list[str],
        description: str,
        signature: str,
        *,
        timeout: float,
    ) -> bool:
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=timeout,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
            error_msg = f"Failed to set {description}. {self._command_error_details(exc)}"
            self._report_brightness_error(error_msg, signature)
            return False
        return True

    def _report_brightness_error(self, message: str, signature: str) -> None:
        if self._last_brightness_error_signature == signature:
            logger.debug("Suppressing repeated brightness error: %s", message)
            return
        self._last_brightness_error_signature = signature
        logger.error(message)
        if self._publisher:
            self._publisher.publish(
                SystemErrorEvent(
                    component="WaylandDisplayPower",
                    message=message,
                    code="brightness_unavailable",
                )
            )

    @classmethod
    def _command_error_details(
        cls,
        error: subprocess.CalledProcessError | FileNotFoundError | subprocess.TimeoutExpired,
    ) -> str:
        if isinstance(error, FileNotFoundError):
            return f"Command not found: {error.filename or error}."
        if isinstance(error, subprocess.TimeoutExpired):
            details = [
                f"Command timed out after {error.timeout}s: {cls._format_command(error.cmd)}."
            ]
            cls._append_output_details(details, error.output, error.stderr)
            return " ".join(details)

        details = [f"Command exited {error.returncode}: {cls._format_command(error.cmd)}."]
        cls._append_output_details(details, error.stdout, error.stderr)
        return " ".join(details)

    @classmethod
    def _append_output_details(
        cls,
        details: list[str],
        stdout: bytes | str | None,
        stderr: bytes | str | None,
    ) -> None:
        stderr_text = cls._decode_process_output(stderr)
        stdout_text = cls._decode_process_output(stdout)
        if stderr_text:
            details.append(f"stderr: {stderr_text}")
        if stdout_text:
            details.append(f"stdout: {stdout_text}")

    @staticmethod
    def _decode_process_output(output: bytes | str | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="replace").strip()
        return str(output).strip()

    @staticmethod
    def _format_command(command: object) -> str:
        if isinstance(command, (list, tuple)):
            return " ".join(str(part) for part in command)
        return str(command)

    def is_on(self) -> bool:
        """
        Check if the display is currently on.

        Returns:
            bool: True if the display is on, False otherwise.
        """
        return self._is_on

    def set_display_output(self, display_output: str) -> None:
        """Retarget future power commands to a different Wayland output."""
        if display_output == self._display_output:
            return
        logger.info(
            "WaylandDisplayPower: Retargeting display output from %s to %s.",
            self._display_output,
            display_output,
        )
        self._display_output = display_output
        if not self._is_external_override:
            self.is_external = self._infer_external_display(display_output)
        self._ddc_brightness_supported = None
        self._ddc_brightness_unavailable_message = None
        self._last_brightness_error_signature = None
