"""Prototype loop: simulate the grid offline, disturb it, run the module over every message, plot.

A notebook in a plain file: each ``# %%`` is a cell for VS Code's Interactive Window (or any REPL),
and the whole file still runs top to bottom:

    uv run python scripts/offline_run.py

Loading the grid and building the model are the slow cells (seconds on the sample grid, longer on
Nordic44); run them once, then re-run the simulation and the module as often as you change them.
After editing the module, re-import it (or restart the kernel): ``importlib.reload`` of
``pswamp_modules.my_module.module`` then of the package.
"""

# %% Settings
import pswamp_proto  # first: it sets OPENBLAS_NUM_THREADS before numpy is imported

GRID = "./grids/nordic44"
SECONDS = 20.0  # simulated seconds
LINE = '300KRISTIAN-ARENDAL'
EVENTS = {  # simulated time -> what happens: names or mRIDs from sim.operable()
    2.0: ("trip", [LINE]),
    10.0: ("reclose", [LINE]),
}
SCADA_PERIOD = 2.0  # simulated seconds between SCADA scans (0: none)
SAVE: str | None = None  # write the plot to this PNG instead of showing it

# %% Load the grid (slow)
repo = pswamp_proto.open_grid(GRID)

# %% Build the simulation (slow): a fresh one starts at steady state at t = 0
sim = pswamp_proto.OfflineSim(repo, scada_period=SCADA_PERIOD)
if sim.left_out:
    print("left out of the model:", sim.left_out)
print(f"{sim.header.n_columns} PMU columns; operable:")
print(sim.operable().to_string())

# %% Simulate, and run the module over every message in order
from pswamp_core.scripts import module  # noqa: E402

my = module("my-module", rocof_limit_hz_s=0.5)  # by its entry point, as a pipeline names it
my.cim_repo = repo  # the module reads the script's grid, not the environment's

at = {t: (sim.trip if kind == "trip" else sim.reclose)(*names) for t, (kind, names) in EVENTS.items()}
frames, scans, results = [], [], []
for message in sim.run(SECONDS, at=at):
    (frames if type(message).__name__ == "PmuFrame" else scans).append(message)
    results += my.run(message)  # exactly what a host would publish for it
print(f"{len(frames)} frames, {len(scans)} scans, {len(results)} results")

# %% The frames as arrays, for exploring: samples x columns, NaN where a value is missing
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

header = frames[0].header
t0 = frames[0].timestamp
t = np.array([(f.timestamp - t0).total_seconds() for f in frames])
values = np.array([f.values for f in frames], dtype=float)
columns = pd.DataFrame({"station": header.station, "measurement": header.measurement, "unit": header.units, "analog": header.analog})
print(columns.head(10).to_string())

# Each column's Analog leads into the graph: the measurement table says what and where it measures.
from pswamp_core.cim import measurement_table  # noqa: E402

measurements = measurement_table(repo)
print(measurements[measurements.source == "SCADA"][["name", "quantity", "unit", "equipment_class", "equipment_name"]].head(10).to_string())

# %% Plot: every stations frequency, and what the module says
import matplotlib  # noqa: E402

if SAVE:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

f_cols = header.columns(measurement="f")
r_t = np.array([(r.timestamp - t0).total_seconds() for r in results])
body = pd.DataFrame([r.result.model_dump() for r in results])

figure, (freq, rocof, gen) = plt.subplots(3, 1, sharex=True, figsize=(9, 8))
freq.plot(t, values[:, f_cols], linewidth=0.8, label=[header.station[i] for i in f_cols])
freq.set(ylabel="frequency (Hz)", title="the offline simulation, and what my-module says of it")
freq.legend(fontsize="small", ncol=2)
rocof.plot(r_t, body.max_rocof_hz_s, linewidth=0.8, label="largest |ROCOF|")
rocof.axhline(my.rocof_limit_hz_s, color="red", linestyle=":", label="limit")
rocof.set(ylabel="Hz/s")
rocof.legend(fontsize="small")
gen.plot(r_t, body.generation_mw, drawstyle="steps-post")
gen.set(xlabel="simulated time (s)", ylabel="generation, SCADA (MW)")
for axes in (freq, rocof, gen):
    for when in EVENTS:
        axes.axvline(when, color="grey", linestyle="--")
figure.tight_layout()
if SAVE:
    figure.savefig(SAVE, dpi=120)
    print(f"wrote {SAVE}")
else:
    plt.show()

# %%
