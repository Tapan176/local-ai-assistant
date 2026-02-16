"""
Performance Monitor - Measure and optimize operation timing.

Phase 17: Decorator-based performance tracking:
- @measure('operation_name') decorator for any function
- Rolling statistics (mean, median, p95)
- Threshold warnings
- Performance report command
"""
import time
import functools
from collections import deque
from typing import Callable, Dict, List, Optional
import statistics as stats_module


class PerformanceMonitor:
  """Monitor and optimize system performance."""

  # Default thresholds (seconds)
  DEFAULT_THRESHOLDS = {
    'ollama_generate': 5.0,
    'rag_retrieve': 1.0,
    'knowledge_search': 0.5,
    'db_query': 0.2,
    'intent_parse': 0.05,
    'orchestrator_process': 3.0,
  }

  def __init__(self, thresholds: Dict[str, float] = None):
    self.metrics: Dict[str, deque] = {}
    self.thresholds = thresholds or self.DEFAULT_THRESHOLDS.copy()
    self._warnings: List[str] = []

  def measure(self, operation_name: str):
    """Decorator to measure function execution time.

    Usage:
      @perf_monitor.measure('ollama_generate')
      def generate(self, prompt): ...
    """
    def decorator(func: Callable):
      @functools.wraps(func)
      def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
          result = func(*args, **kwargs)
          return result
        finally:
          duration = time.perf_counter() - start
          self._record(operation_name, duration)
      return wrapper
    return decorator

  def time_block(self, operation_name: str):
    """Context manager for timing code blocks.

    Usage:
      with perf_monitor.time_block('db_query'):
        cursor.execute(...)
    """
    return _TimingContext(self, operation_name)

  def _record(self, operation: str, duration: float):
    """Record a timing measurement."""
    if operation not in self.metrics:
      self.metrics[operation] = deque(maxlen=200)
    self.metrics[operation].append(duration)

    # Check threshold
    threshold = self.thresholds.get(operation)
    if threshold and duration > threshold:
      warning = f"⚠️ {operation}: {duration:.3f}s > {threshold}s threshold"
      self._warnings.append(warning)
      # Keep only last 20 warnings
      self._warnings = self._warnings[-20:]

  def get_stats(self, operation: str) -> Optional[Dict]:
    """Get statistics for an operation."""
    if operation not in self.metrics or not self.metrics[operation]:
      return None

    values = list(self.metrics[operation])
    n = len(values)
    sorted_vals = sorted(values)

    return {
      'count': n,
      'mean': stats_module.mean(values),
      'median': stats_module.median(values),
      'min': min(values),
      'max': max(values),
      'p95': sorted_vals[int(n * 0.95)] if n >= 20 else max(values),
      'total': sum(values),
    }

  def get_report(self) -> str:
    """Generate a formatted performance report."""
    if not self.metrics:
      return "📊 No performance data collected yet."

    lines = ["📊 Performance Report\n"]
    lines.append(f"{'Operation':<25} {'Count':>6} {'Mean':>8} {'P95':>8} {'Status':>8}")
    lines.append("-" * 60)

    for op in sorted(self.metrics.keys()):
      s = self.get_stats(op)
      if not s:
        continue

      threshold = self.thresholds.get(op)
      if threshold:
        status = "✅" if s['mean'] <= threshold else "⚠️"
      else:
        status = "—"

      lines.append(
        f"{op:<25} {s['count']:>6} {s['mean']:>7.3f}s {s['p95']:>7.3f}s {status:>8}"
      )

    if self._warnings:
      lines.append(f"\n⚠️ Recent warnings ({len(self._warnings)}):")
      for w in self._warnings[-5:]:
        lines.append(f"  {w}")

    return "\n".join(lines)

  def get_warnings(self) -> List[str]:
    """Get recent performance warnings."""
    return self._warnings.copy()

  def clear(self):
    """Clear all metrics and warnings."""
    self.metrics.clear()
    self._warnings.clear()


class _TimingContext:
  """Context manager for timing code blocks."""

  def __init__(self, monitor: PerformanceMonitor, operation: str):
    self.monitor = monitor
    self.operation = operation
    self.start = 0.0

  def __enter__(self):
    self.start = time.perf_counter()
    return self

  def __exit__(self, *args):
    duration = time.perf_counter() - self.start
    self.monitor._record(self.operation, duration)


# Global singleton
_perf_monitor: Optional[PerformanceMonitor] = None


def get_perf_monitor() -> PerformanceMonitor:
  """Get or create the global performance monitor."""
  global _perf_monitor
  if _perf_monitor is None:
    _perf_monitor = PerformanceMonitor()
  return _perf_monitor
