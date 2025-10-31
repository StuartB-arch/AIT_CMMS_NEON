#!/usr/bin/env python3
"""
Startup Performance Profiler for AIT CMMS
Measures time taken by each initialization step
"""
import time
import sys

class StartupProfiler:
    """Profile startup performance"""

    def __init__(self):
        self.start_time = time.time()
        self.checkpoints = []

    def checkpoint(self, name):
        """Record a timing checkpoint"""
        elapsed = time.time() - self.start_time
        self.checkpoints.append((name, elapsed))
        print(f"[{elapsed:.3f}s] {name}")

    def report(self):
        """Print timing report"""
        print("\n" + "="*60)
        print("STARTUP PERFORMANCE REPORT")
        print("="*60)

        if not self.checkpoints:
            print("No checkpoints recorded")
            return

        prev_time = 0
        for name, total_time in self.checkpoints:
            delta = total_time - prev_time
            print(f"{name:.<50} {delta:.3f}s (total: {total_time:.3f}s)")
            prev_time = total_time

        total = self.checkpoints[-1][1]
        print("="*60)
        print(f"TOTAL STARTUP TIME: {total:.3f}s")
        print("="*60)

# Global profiler instance
profiler = StartupProfiler()
