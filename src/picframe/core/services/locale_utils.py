"""Locale helpers shared by geocoding and overlay text."""

from __future__ import annotations

import locale
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

_LC_TIME_LOCK = threading.Lock()


def language_from_locale(locale_value: object) -> str:
    """Return the language code used for reverse-geocoding requests."""
    language = str(locale_value or "").split(".", 1)[0].split("_", 1)[0].strip()
    if not language or language.upper() in {"C", "POSIX"}:
        return "en"
    return language.lower()


def format_datetime_for_locale(
    value: datetime,
    date_format: str,
    locale_value: object | None,
) -> str:
    """Format a datetime with LC_TIME temporarily set to the configured locale."""
    locale_name = str(locale_value or "").strip()
    if not locale_name:
        return value.strftime(date_format)

    with _LC_TIME_LOCK:
        previous_locale = locale.setlocale(locale.LC_TIME)
        try:
            locale.setlocale(locale.LC_TIME, locale_name)
            return value.strftime(date_format)
        except (locale.Error, ValueError) as exc:
            logger.warning(
                "Unable to format datetime with locale %s; using process locale: %s",
                locale_name,
                exc,
            )
            return value.strftime(date_format)
        finally:
            try:
                locale.setlocale(locale.LC_TIME, previous_locale)
            except locale.Error as exc:
                logger.warning("Unable to restore LC_TIME locale %s: %s", previous_locale, exc)
