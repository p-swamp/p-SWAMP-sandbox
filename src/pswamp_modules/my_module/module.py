"""``MyModule`` (``my-module``): a placeholder analysis to replace with your own.

It shows the shapes a real module needs, so replacing the analysis is all that is left:

- **two inputs, one handler each** (``@on``): the PMU frames (50/s) and the SCADA scans (every
  couple of seconds). The slow input only updates state; the fast one publishes. That is one of the
  three input styles of ``pswamp_core.modules``; its docstring has the other two (one input, and
  named inputs combined by a join).
- **columns found by the frame's header**, once per layout (``header_id``), never by position.
- **the CIM graph** (``cim = True``): ``self.cim_repo`` says what each SCADA measurement is.
  Anything derived from the graph is dropped in ``cim_changed``, which the core calls when the graph
  changed (an operator opened a breaker), and rebuilt on next use.
- **state cleared in ``reset``**, which a host calls when the stream starts over.
- **settings in ``parameters``**, published with every result.

The analysis is in plain functions (``spread_and_rocof``); ``on_frame`` only adapts a frame to them.
Keep that split: the functions are what you test hardest, with no frames at all.

The same class runs from a script or a test (``run``/``run_one``, synchronous) and, once promoted,
hosted in the server or a worker. When it runs from a script, hand it the script's repository
(``module.cim_repo = repo``) or it opens the grid of the environment (``PSWAMP_CIM_URL`` or
``PSWAMP_CIM_PATH``; Nordic44 when neither is set).
"""

from __future__ import annotations

import math

from pswamp_core.cim import measurement_table
from pswamp_core.modules import Module, on
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.scada import ScadaScan

from .messages import MyModuleBody, MyModuleResult  # on promotion: from pswamp_models.my_module import ...

__all__ = ["MyModule", "spread_and_rocof"]


def spread_and_rocof(
    stations: list[str], f_hz: list[float | None], rocof_hz_s: list[float | None]
) -> tuple[float | None, float | None, str | None]:
    """The frequency spread (mHz), and the largest |ROCOF| (Hz/s) with its station. A station with
    no value (``None``, or NaN) is left out; with none left, ``None``."""
    fs = [f for f in f_hz if f is not None and math.isfinite(f)]
    spread = (max(fs) - min(fs)) * 1000.0 if fs else None
    rocofs = [(abs(r), s) for s, r in zip(stations, rocof_hz_s, strict=True) if r is not None and math.isfinite(r)]
    if not rocofs:
        return spread, None, None
    peak, station = max(rocofs)
    return spread, peak, station


class MyModule(Module):
    name = "my-module"  # the entry point's name in pyproject.toml, and what a pipeline file lists
    inputs = (PmuFrame, ScadaScan)
    outputs = (MyModuleResult,)
    cim = True  # self.cim_repo: this instance's repository over the CIM graph

    def __init__(self, rocof_limit_hz_s: float = 0.5) -> None:
        super().__init__()
        self.rocof_limit_hz_s = rocof_limit_hz_s
        self.parameters = {"rocof_limit_hz_s": rocof_limit_hz_s}
        self._header_id: str | None = None
        self._f: list[int] = []
        self._df: list[int] = []
        self._stations: list[str] = []
        self._machine_p: dict[str, float] | None = None  # SCADA P Analog of each machine -> sign to generation
        self._generation_mw: float | None = None

    # -- life cycle ------------------------------------------------------------------------

    def reset(self) -> None:
        """The stream starts over: forget what came before."""
        self._generation_mw = None

    def cim_changed(self) -> None:
        """The graph changed: what was derived from it is read again on next use."""
        self._machine_p = None

    # -- inputs ----------------------------------------------------------------------------

    def _use(self, header: PmuHeader) -> None:
        self._header_id = header.header_id
        self._f = header.columns(measurement="f")
        self._df = header.columns(measurement="df")  # ROCOF; the stations' order in each is the same
        self._stations = [header.station[i] for i in self._f]

    @on(PmuFrame)
    def on_frame(self, frame: PmuFrame) -> MyModuleBody | None:
        if frame.header.header_id != self._header_id:
            self._use(frame.header)  # a new layout: the simulation rebuilt its model
        values = frame.values
        spread, rocof, station = spread_and_rocof(
            self._stations, [values[i] for i in self._f], [values[i] for i in self._df]
        )
        if spread is None:
            return None  # publish nothing for this frame
        alarm = rocof is not None and rocof > self.rocof_limit_hz_s
        return MyModuleBody(
            frequency_spread_mhz=spread,
            max_rocof_hz_s=rocof,
            rocof_station=station,
            rocof_alarm=alarm,
            generation_mw=self._generation_mw,
            status="Alert" if alarm else "OK",
        )

    @on(ScadaScan)
    def on_scan(self, scan: ScadaScan) -> None:
        if self._machine_p is None:
            self._machine_p = self._read_machines()
        values = [a.value * self._machine_p[a.mRID] for a in scan.analogs if a.mRID in self._machine_p]
        self._generation_mw = sum(values) if values else None
        return None  # state only: the next frame publishes it

    def _read_machines(self) -> dict[str, float]:
        """Each machine's SCADA active-power Analog. Measurements are signed into the equipment (as
        CGMES does), so a machine's generation is minus its value."""
        table = measurement_table(self.cim_repo)
        machines = table[(table.source == "SCADA") & (table.quantity == "P") & (table.equipment_class == "SynchronousMachine")]
        return {mrid: -1.0 for mrid in machines.mRID}
