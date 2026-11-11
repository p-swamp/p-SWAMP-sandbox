"""Scaffolding for prototyping a p-SWAMP module: a grid to read, and measurements of it.

- ``open_grid`` gives a read-only LazyCIM repository over a grid: the sample grid p-SWAMP ships,
  Nordic44, a folder of CGMES files, or the running stack's Oxigraph. The grid has PMU and SCADA
  measurements (p-SWAMP adds them when its Operation profile has none).
- ``OfflineSim`` simulates that grid as the live source does, as fast as it computes, and yields
  the ``PmuFrame``s and ``ScadaScan``s the live source would have published. Trip and reclose
  branches and switches at chosen times.

For the real thing, in real time, use the live source itself:
``pswamp_core.scripts.source("rtsim-from-cim", repo=repo)`` (``scripts/live_run.py``).

This package stays in the prototype project; only ``pswamp_modules.my_module`` is promoted.
"""

import os

# Before numpy is imported. TOPS's load flow differentiates numerically, a column at a time, and
# OpenBLAS threads each of those small products: on a grid of a few hundred buses one thread takes
# ~2 s and every core minutes (see p-swamp's modules/rtsim-from-cim/examples/offline_sim.py).
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from .grid import open_grid  # noqa: E402
from .offline import OfflineSim  # noqa: E402

__all__ = ["OfflineSim", "open_grid"]
