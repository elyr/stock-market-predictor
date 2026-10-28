"""
Market signal detection (unusual moves, volume, gaps, market-wide moves).
"""

from .detector import Signal, SignalDetector, detect_from_analysis, merge_signal_config

__all__ = ["Signal", "SignalDetector", "detect_from_analysis", "merge_signal_config"]
