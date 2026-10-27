"""QQ bot plugin internals.

The package is imported by ``backend/__init__.py``; it deliberately keeps the
protocol, middleware and host bridge in separate modules so each layer can be
tested without starting a gateway.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
