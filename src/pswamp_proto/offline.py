"""The live grid simulation, offline: the same frames and scans, as fast as they compute.

``OfflineSim`` builds the TOPS model of a grid exactly as p-SWAMP's live source
(``rtsim-from-cim``) does, steps it, and yields what that source would publish: a ``PmuFrame`` per
frame (one column per PMU measurement of the graph, each carrying its Analog's mRID) and, every
``scada_period`` simulated seconds, a ``ScadaScan`` (every SCADA measurement, by mRID). No clock, no
processes, no server: a minute of the sample grid takes seconds, and a run is repeatable.

    sim = OfflineSim(open_grid("sample"))
    for message in sim.run(20.0, at={2.0: sim.trip("Alpha-Gamma 400 kV line")}):
        ...  # a PmuFrame or a ScadaScan

What it leaves out, against the live source: **protection** (the live controller clears faults and
trips overloaded lines; here nothing trips unless you trip it), edits of the graph (``CimEdits``,
``SimEvent``), and rebuilding the model mid-run. It uses ``rtsim_from_cim``'s internals (``engine``,
``pmu``, ``scada``) as that project's own ``examples/offline_sim.py`` does, so a change there may
need a change here.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pandas as pd
from lazycim.sim.tops_live import LiveTops

from pswamp_core.cim import Store, model_id
from pswamp_core.util.time import utcnow
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.scada import AnalogReading, DiscreteReading, ScadaScan
from pswamp_modules.rtsim_from_cim.engine import EXPORT, SimEngine
from pswamp_modules.rtsim_from_cim.pmu import pmu_frame, pmu_layout, read_measurements
from pswamp_modules.rtsim_from_cim.scada import scada_layout, scada_values

__all__ = ["DT", "RATE", "OfflineSim"]

#: As the live source: the integration step (simulated s) and the frames per simulated second.
DT = 0.01
RATE = 50
#: What the live source calls itself in a frame's ``mRID`` and a scan's ``source``.
STREAM_ID = "rtsim-from-cim"

#: The model's row groups an event acts on: (rows' names on the engine, ids group, TOPS category,
#: TOPS model, the action that takes it out, the one that puts it back).
_GROUPS = (
    ("line_names", "lines", "lines", "Line", "disconnect", "connect"),
    ("trafo_names", "transformers", "trafos", "Trafo", "disconnect", "connect"),
    ("switch_names", "switches", "switches", "Switch", "open", "close"),
)


class OfflineSim:
    """One simulation of the grid in ``repo`` (``open_grid``), started at steady state.

    ``dt`` and ``rate`` are the live source's; ``scada_period`` is in simulated seconds (0: no
    scans); ``start`` is the timestamp of simulated time 0 (now, when omitted)."""

    def __init__(
        self, repo, *, dt: float = DT, rate: int = RATE, scada_period: float = 2.0, start: datetime | None = None
    ) -> None:
        self.repo = repo
        self.dt, self.rate, self.scada_period = dt, rate, scada_period
        self.start = start or utcnow()
        self.live = LiveTops.from_repo(repo, dt=dt, **EXPORT)  # reads the graph: the slow part
        #: What could not be simulated: the parts the slack bus does not reach and that have a load or a machine.
        self.left_out = {kind: rows for kind, rows in self.live.left_out.items() if rows}
        built = self.live.built
        self.engine = SimEngine(built.model, dt=dt, events=built.events)
        measurements = read_measurements(repo)
        ids = self.live.sim.ids
        self._pmu = pmu_layout(measurements, self.engine, ids, rate)
        self._scada = scada_layout(measurements, self.engine, ids) if scada_period > 0 else None
        self._steps = round(1 / (rate * dt))
        try:
            self.reference = model_id(Store.of(repo))
        except Exception:  # noqa: BLE001 (a scan says which grid it is of when it can)
            self.reference = None
        self._rows = self._index(ids)
        self._next_scan = 0.0

    @property
    def header(self) -> PmuHeader:
        """The frames' layout: one column per PMU measurement (``station``, ``measurement``, ``units``,
        ``analog``: its Analog's mRID)."""
        return self._pmu.header

    @property
    def time(self) -> float:
        """Simulated seconds so far."""
        return float(self.engine.snapshot().sim_time_s)

    # -- what can be operated --------------------------------------------------------------

    def _index(self, ids: dict) -> dict[str, tuple]:
        rows = {}
        for names, group, category, model, out, back in _GROUPS:
            mrids = ids.get(group, {})
            for name in getattr(self.engine, names):
                entry = (name, category, model, out, back, mrids.get(name))
                rows[name] = entry
                if entry[-1]:
                    rows[entry[-1]] = entry  # by mRID too
        return rows

    def operable(self) -> pd.DataFrame:
        """Every line, transformer and switch an event can act on: its row name in the model, kind
        and mRID. Pass the name or the mRID to ``trip`` and ``reclose``."""
        seen = {entry for entry in self._rows.values()}
        return pd.DataFrame(
            [{"name": name, "kind": model, "mRID": mrid} for name, _, model, _, _, mrid in sorted(seen)]
        )

    def _event(self, what: str, back: bool) -> tuple:
        entry = self._rows.get(what)
        if entry is None:
            raise KeyError(f"{what!r} is no line, transformer or switch of the model; see OfflineSim.operable()")
        name, category, model, out, again, _ = entry
        return ("event", (category, model, name, again if back else out, {}))

    def trip(self, *what: str) -> list[tuple]:
        """The events that take these out: a line or a transformer disconnected, a switch opened.
        Apply them now (``apply``) or at a time (``run(..., at={t: events})``)."""
        return [self._event(w, back=False) for w in what]

    def reclose(self, *what: str) -> list[tuple]:
        """The events that put these back: a line or a transformer connected, a switch closed."""
        return [self._event(w, back=True) for w in what]

    def apply(self, events: list[tuple]) -> None:
        """Apply events now. Anything ``SimEngine.apply`` takes goes: TOPS events, and inputs set on a
        model (``("input", (category, model, input, value, index))``, e.g. a load's power)."""
        for event in events:
            self.engine.apply(event)

    # -- running ---------------------------------------------------------------------------

    def run(self, seconds: float, at: dict[float, list[tuple]] | None = None) -> Iterator[PmuFrame | ScadaScan]:
        """``seconds`` more of the simulation, frame by frame, with ``at``'s events applied once
        simulated time reaches each key. Yields each ``PmuFrame`` and, every ``scada_period`` s, a
        ``ScadaScan`` (the first at time 0), in time order. Call again to go on from where it stopped."""
        pending = sorted((at or {}).items())
        half = self._steps * self.dt / 2
        snapshot = self.engine.snapshot()
        end = snapshot.sim_time_s + seconds - half
        while True:
            while pending and snapshot.sim_time_s >= pending[0][0] - half:
                self.apply(pending.pop(0)[1])
            if self._scada is not None and snapshot.sim_time_s >= self._next_scan - 1e-9:
                yield self._scan(snapshot.sim_time_s)
                self._next_scan = max(self._next_scan + self.scada_period, snapshot.sim_time_s + 0.5 * self.scada_period)
            if snapshot.sim_time_s >= end:
                return
            snapshot = self.engine.step(self._steps)
            yield pmu_frame(self._pmu, snapshot, self._stamp(snapshot.sim_time_s), STREAM_ID)

    def _stamp(self, sim_time: float) -> datetime:
        return self.start + timedelta(seconds=sim_time)

    def _scan(self, sim_time: float) -> ScadaScan:
        analogs, discretes = scada_values(self._scada, self.engine.flows())
        return ScadaScan(
            timestamp=self._stamp(sim_time),
            source=STREAM_ID,
            sim_time=sim_time,
            cimReferenceId=self.reference,
            analogs=[AnalogReading(mRID=mrid, value=value) for mrid, value in analogs],
            discretes=[DiscreteReading(mRID=mrid, value=value) for mrid, value in discretes],
        )
