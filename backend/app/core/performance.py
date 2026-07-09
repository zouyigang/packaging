"""Lightweight runtime metrics for solver stages."""
from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator


class PerformanceTimer:
    def __init__(self) -> None:
        self._start = perf_counter()
        self.stages_ms: dict[str, float] = {}
        self.counters: dict[str, int] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = perf_counter()
        try:
            yield
        finally:
            self.stages_ms[name] = self.stages_ms.get(name, 0.0) + (perf_counter() - start) * 1000.0

    def count(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def count_max(self, name: str, value: int) -> None:
        self.counters[name] = max(self.counters.get(name, 0), value)

    def merge(self, stages_ms: dict[str, float], counters: dict[str, int]) -> None:
        for name, elapsed_ms in stages_ms.items():
            self.stages_ms[name] = self.stages_ms.get(name, 0.0) + elapsed_ms
        for name, amount in counters.items():
            self.count(name, amount)

    @property
    def runtime_ms(self) -> float:
        return (perf_counter() - self._start) * 1000.0

    def rounded_stages(self) -> dict[str, float]:
        return {key: round(value, 3) for key, value in self.stages_ms.items()}
