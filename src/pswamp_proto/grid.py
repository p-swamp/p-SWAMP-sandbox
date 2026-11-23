"""A grid to prototype against, as a read-only LazyCIM repository."""

from __future__ import annotations

from pathlib import Path

from pswamp_core.cim import SAMPLE_GRID, CimSettings, connect_reader

__all__ = ["open_grid"]


def open_grid(grid: str | Path = "sample"):
    """A repository over ``grid``, with its PMU and SCADA measurements:

    - ``"sample"``: the small grid p-SWAMP ships (4 stations in southern Norway, 58 measurements).
      Quick to load and simulate; what p-SWAMP's CI and tests use.
    - ``"nordic44"``: Statnett's original Nordic44, which LazyCIM downloads on first use. The
      modified copy in ``grids/nordic44`` (with OP, DY and GL) is opened as a folder. Both are
      CC BY-NC-SA 4.0: no commercial use.
    - a folder of CGMES ``*_<PROFILE>.xml`` files.
    - ``"http://127.0.0.1:7878"``: the Oxigraph of a running stack (``uv run pswamp dev server``),
      so you read exactly the grid the server loaded, edits included. Read only: the server's CIM
      graph app is that store's one writer.

    The first three load into an in-process store of this process's own. The repository refuses to
    commit, and is for one thread."""
    if isinstance(grid, str) and grid.startswith(("http://", "https://")):
        settings = CimSettings(url=grid)
    elif grid == "sample":
        settings = CimSettings(cim_path=SAMPLE_GRID)
    elif grid == "nordic44":
        settings = CimSettings()  # no folder: Nordic44
    else:
        path = Path(grid).expanduser()
        if not path.is_dir():
            raise FileNotFoundError(f"{grid!r} is not 'sample', 'nordic44', an Oxigraph url or a folder of CGMES files")
        settings = CimSettings(cim_path=path)
    return connect_reader(settings)
