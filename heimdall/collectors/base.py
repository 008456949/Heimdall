"""
collectors/base.py — abstract base every collector must implement.

Rules:
  - __init__ receives a live DB connection
  - collect() does its work, writes to DB, returns a summary dict
  - safe_collect() wraps collect() — a crashing collector never kills the daemon
"""

from abc import ABC, abstractmethod
import sqlite3
import logging

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    name: str = "base"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @abstractmethod
    def collect(self) -> dict:
        """
        Run one collection cycle. Write results to self.conn.
        Return a summary dict (used for logging).
        Never raise — catch internally and return {"error": str(e)}.
        """
        ...

    def safe_collect(self) -> dict:
        """Wraps collect() — a crash here never kills the daemon thread."""
        try:
            return self.collect()
        except Exception as e:
            logger.error("[%s] collect() raised: %s", self.name, e, exc_info=True)
            return {"error": str(e)}
