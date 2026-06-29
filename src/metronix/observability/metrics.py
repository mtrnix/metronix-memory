"""Metrics and observability — timing decorators, counters, thread-safe."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


@dataclass
class OperationMetrics:
    """Metrics for a single operation type."""

    count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_duration: float = 0.0
    min_duration: float = float("inf")
    max_duration: float = 0.0
    last_error: str = ""

    @property
    def avg_duration(self) -> float:
        return self.total_duration / self.count if self.count > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "total_duration_sec": round(self.total_duration, 3),
            "avg_duration_sec": round(self.avg_duration, 3),
            "min_duration_sec": round(self.min_duration, 3)
            if self.min_duration != float("inf")
            else 0,
            "max_duration_sec": round(self.max_duration, 3),
            "success_rate": round(self.success_count / self.count * 100, 1)
            if self.count > 0
            else 0,
            "last_error": self.last_error,
        }


class MetricsCollector:
    """Thread-safe metrics collector."""

    def __init__(self) -> None:
        self._metrics: dict[str, OperationMetrics] = defaultdict(OperationMetrics)
        self._lock = threading.Lock()
        self._start_time = time.time()

    def record_success(self, operation: str, duration: float) -> None:
        with self._lock:
            m = self._metrics[operation]
            m.count += 1
            m.success_count += 1
            m.total_duration += duration
            m.min_duration = min(m.min_duration, duration)
            m.max_duration = max(m.max_duration, duration)

    def record_error(self, operation: str, duration: float, error: str) -> None:
        with self._lock:
            m = self._metrics[operation]
            m.count += 1
            m.error_count += 1
            m.total_duration += duration
            m.min_duration = min(m.min_duration, duration)
            m.max_duration = max(m.max_duration, duration)
            m.last_error = error[:200]

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            uptime = time.time() - self._start_time
            return {
                "uptime_sec": round(uptime, 1),
                "operations": {name: metrics.to_dict() for name, metrics in self._metrics.items()},
            }

    def reset(self) -> None:
        with self._lock:
            self._metrics.clear()
            self._start_time = time.time()


_collector = MetricsCollector()


def get_metrics() -> dict[str, Any]:
    return _collector.get_metrics()


def reset_metrics() -> None:
    _collector.reset()


def timed(operation_name: str | Callable | None = None, log_args: bool = False):
    """Decorator to measure and log function execution time.

    Supports ``@timed``, ``@timed()``, and ``@timed("name")``.
    """
    # TODO: async migration

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        name = operation_name if isinstance(operation_name, str) else func.__name__

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.perf_counter()

            if log_args and args:
                display_args = args[1:] if args and hasattr(args[0], "__class__") else args
                arg_str = str(display_args)[:100]
                log_prefix = f"{name}({arg_str})"
            else:
                log_prefix = name

            try:
                result = func(*args, **kwargs)
                duration = time.perf_counter() - start
                _collector.record_success(name, duration)

                if duration > 5.0:
                    logger.warning("slow_operation", op=log_prefix, duration=f"{duration:.3f}s")
                elif duration > 1.0:
                    logger.info("operation_complete", op=log_prefix, duration=f"{duration:.3f}s")
                else:
                    logger.debug("operation_complete", op=log_prefix, duration=f"{duration:.3f}s")

                return result

            except Exception as e:
                duration = time.perf_counter() - start
                error_msg = str(e)
                _collector.record_error(name, duration, error_msg)
                logger.error(
                    "operation_failed", op=log_prefix, duration=f"{duration:.3f}s", error=error_msg
                )
                raise

        return wrapper

    if callable(operation_name):
        func = operation_name
        operation_name = None
        return decorator(func)

    return decorator


class Timer:
    """Context manager for manual timing.

    Usage::

        with Timer("my_operation") as t:
            do_something()
        print(f"Took {t.duration:.3f}s")
    """

    def __init__(self, operation_name: str, log: bool = True) -> None:
        self.operation_name = operation_name
        self.log = log
        self.start = 0.0
        self.duration = 0.0

    def __enter__(self) -> Timer:
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # type: ignore[type-arg]
        self.duration = time.perf_counter() - self.start

        if exc_type is not None:
            error_msg = str(exc_val)
            _collector.record_error(self.operation_name, self.duration, error_msg)
            if self.log:
                logger.error(
                    "timer_failed",
                    op=self.operation_name,
                    duration=f"{self.duration:.3f}s",
                    error=error_msg,
                )
        else:
            _collector.record_success(self.operation_name, self.duration)
            if self.log:
                logger.debug(
                    "timer_complete", op=self.operation_name, duration=f"{self.duration:.3f}s"
                )

        return False
