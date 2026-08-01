from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def fixture_root() -> Path:
    """Return the installed package's fixture directory.

    Wheels installed by pip are unpacked on disk, so exposing a Path keeps the
    existing explicit fixture override contracts while removing checkout-relative
    path assumptions.
    """

    return Path(str(files("biofield").joinpath("fixtures")))
