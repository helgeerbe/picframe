"""
Debouncing Utilities.

This module provides thread-safe utilities for debouncing actions,
ensuring they are not executed too frequently.
"""

import time
import threading
from typing import Dict

class Debouncer:
    """
    A thread-safe utility for debouncing function calls or events.
    Ensures that a function is only executed after a specified delay has passed
    since the last time it was invoked.
    """
    def __init__(self, delay_ms: int) -> None:
        """
        Initialize the Debouncer.
        
        :param delay_ms: The debounce delay in milliseconds.
        """
        if delay_ms < 0:
            raise ValueError("Delay must be non-negative")
            
        self.delay_seconds = delay_ms / 1000.0
        self.last_call_times: Dict[str, float] = {}
        self.lock = threading.Lock()

    def should_execute(self, key: str) -> bool:
        """
        Determine if an action associated with the given key should be executed.
        
        :param key: A unique identifier for the action being debounced.
        :return: True if the action should be executed, False if it should be debounced.
        """
        now = time.monotonic()
        
        with self.lock:
            last_time = self.last_call_times.get(key, 0.0)
            if now - last_time >= self.delay_seconds:
                self.last_call_times[key] = now
                return True
            return False
