"""The adapter registry: one adapter per manifest family key.

Adding a language means adding its module and registering it here; the shared
core never changes. Constructing the adapters touches no network.
"""
from __future__ import annotations

from lifecycle.adapters.go import GoAdapter
from lifecycle.adapters.python import PythonAdapter
from lifecycle.core import Adapter

ADAPTERS: dict[str, Adapter] = {a.key: a for a in (PythonAdapter(), GoAdapter())}
