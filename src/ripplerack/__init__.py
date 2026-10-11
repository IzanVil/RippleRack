"""RippleRack: local-first datacenter & data pipeline simulator with semantic versioning."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ripplerack")
except PackageNotFoundError:  # pragma: no cover - running from a source checkout
    __version__ = "0.0.0"

__all__ = ["__version__"]
