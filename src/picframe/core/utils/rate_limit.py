"""
Rate Limiting Utilities.

This module provides thread-safe utilities for rate limiting,
such as the Token Bucket algorithm.
"""

import time
import threading

class TokenBucket:
    """
    A thread-safe implementation of the Token Bucket algorithm for rate limiting.
    """
    def __init__(self, capacity: int, refill_rate: float) -> None:
        """
        Initialize the Token Bucket.
        
        :param capacity: Maximum number of tokens the bucket can hold (burst size).
        :param refill_rate: Number of tokens added to the bucket per second.
        """
        if capacity <= 0:
            raise ValueError("Capacity must be greater than 0")
        if refill_rate <= 0:
            raise ValueError("Refill rate must be greater than 0")
            
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill_time = time.monotonic()
        self.lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens from the bucket.
        
        :param tokens: Number of tokens to consume.
        :return: True if tokens were consumed (allowed), False otherwise (rate limited).
        """
        with self.lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def _refill(self) -> None:
        """
        Refill the bucket based on the elapsed time since the last refill.
        """
        now = time.monotonic()
        elapsed = now - self.last_refill_time
        tokens_to_add = elapsed * self.refill_rate
        
        if tokens_to_add > 0:
            self.tokens = min(float(self.capacity), self.tokens + tokens_to_add)
            self.last_refill_time = now
