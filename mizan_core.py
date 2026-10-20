"""Backwards-compatible entry point: `python mizan_core.py` runs the demo."""

from mizan.core import *  # noqa: F401,F403
from mizan.telemetry import *  # noqa: F401,F403
from mizan.demo import demo

if __name__ == "__main__":
    demo()
