"""Small shims that keep pinned third-party OCR packages importable."""

from __future__ import annotations

import os
import ssl
import sys
from importlib import import_module, metadata
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _distribution(name: str) -> SimpleNamespace:
    """The one pkg_resources call gdown 4.4 makes: get_distribution(...).version."""
    try:
        version = metadata.version(name)
    except metadata.PackageNotFoundError:
        version = "0"
    return SimpleNamespace(project_name=name, version=version)


def ensure_pkg_resources() -> None:
    """Provide a minimal ``pkg_resources`` when setuptools no longer ships it.

    VietOCR pins gdown 4.4.0, which imports ``pkg_resources`` at import time;
    setuptools 81+ removed that module, so on a fresh install VietOCR, the
    default engine, failed to load at all.
    """
    try:
        import_module("pkg_resources")
        return
    except ImportError:
        pass
    shim = ModuleType("pkg_resources")
    shim.get_distribution = _distribution  # type: ignore[attr-defined]
    shim.DistributionNotFound = metadata.PackageNotFoundError  # type: ignore[attr-defined]
    sys.modules["pkg_resources"] = shim


def ensure_ca_certificates() -> str | None:
    """Give a python.org macOS build a CA bundle so model downloads verify.

    That Python ships without trusted roots until "Install Certificates" is
    run, so EasyOCR and the weights downloader failed with
    CERTIFICATE_VERIFY_FAILED. Only macOS is touched, and only when nothing
    is configured: Windows keeps the system store, which may hold corporate
    roots. Returns the bundle that was applied, if any.
    """
    if sys.platform != "darwin" or os.environ.get("SSL_CERT_FILE"):
        return None
    paths = ssl.get_default_verify_paths()
    if paths.cafile or (paths.capath and any(Path(paths.capath).iterdir())):
        return None
    try:
        bundle = str(import_module("certifi").where())
    except (ImportError, AttributeError):
        return None
    os.environ["SSL_CERT_FILE"] = bundle
    return bundle
