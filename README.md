# pswamp-prototype

A sandbox for prototyping a new p-SWAMP analysis module, outside the p-SWAMP repo,
with p-SWAMP installed as a dependency. It gives you:

- **a grid**: p-SWAMP's sample grid, Nordic44, any folder of CGMES files, or the grid
  a running stack has loaded, each with its PMU and SCADA measurements;
- **measurements of it**: the same `PmuFrame`s and `ScadaScan`s that p-SWAMP's live
  grid simulation (`rtsim-from-cim`) publishes. You can get them offline, as fast as
  they compute and with lines and switches tripped when you choose, or in real time
  from the live source itself;
- **a module skeleton** (`my-module`) written to p-SWAMP's `Module` contract. The code
  you prototype here is the code that runs in the server once promoted.

## Setup

As committed, it expects a p-SWAMP checkout beside it (`../p-swamp`); change the
paths in `[tool.uv.sources]` of `pyproject.toml` if yours is elsewhere, or switch
to a normal install (next section).

```
uv sync
uv run pytest                        # the module's tests, one of them on the simulated sample grid
uv run python scripts/offline_run.py # simulate, trip a line, run the module, plot
uv run python scripts/live_run.py    # the module on the real-time live source
```

`scripts/offline_run.py` is a notebook in a plain file (`# %%` cells for VS Code's
Interactive Window). Load the grid and build the simulation once, then re-run the
cells below them as you change the module.

## Where p-SWAMP comes from

`pyproject.toml` has two `[tool.uv.sources]` blocks; one is commented out. Swap
them, then `uv lock`.

- **Editable, from a checkout** (`path = "../p-swamp/..."`, the default): an edit
  of p-SWAMP is live here at once. Use it while you change both together.
- **A normal install, pinned to a commit** (`git = "https://github.com/p-swamp/p-swamp"`,
  `rev = "<commit>"`): p-SWAMP is installed into `.venv` like any package, and
  nothing here changes until you move the `rev`. No checkout is needed for the
  scripts and tests. The commit must be pushed.

With the pinned install you can still run against a checkout, for one run only.
The checkout's code, uncommitted edits included, shadows the pinned packages:

```
uv run --with-editable ../p-swamp/models --with-editable ../p-swamp/core \
       --with-editable ../p-swamp/modules/rtsim-from-cim  python scripts/offline_run.py
```

## Running the full stack from here

The stack (server, Kafka, Oxigraph, workers) is built from p-SWAMP's Dockerfile
and compose files, so it always needs a checkout. It does not have to be the one
this project installs from. Run p-SWAMP's CLI from this folder:

```
uv run --project ../p-swamp pswamp dev server --extra-modules .
```

`--project` runs the checkout's `pswamp`, which finds its repo by its own location;
`.` is this folder.

To configure the stack from here (which grid it loads, say), keep a compose
override in this project and add it with `-f`:

```
uv run --project ../p-swamp pswamp dev server --extra-modules . -f compose.override.yml
```

`compose.override.yml` is an example with comments. It is added after p-SWAMP's
own compose files, including p-SWAMP's `docker-compose.override.yml` if it has one.
A relative path in it (`./grids/my-grid`) is relative to this folder. Oxigraph
keeps a grid it already holds, so take the stack down before changing grids. Ctrl-C stops the stack, as does `docker compose -p p-swamp down
--remove-orphans`. In the stack the module runs on the **checkout's** p-SWAMP, not
the pinned one. Keep the two on the same commit, or what passes the tests here may
behave differently there.

## Layout

| Path | What it is | On promotion |
|---|---|---|
| `src/pswamp_modules/my_module/module.py` | the module | moves to `modules/<name>/src/pswamp_modules/<pkg>/` |
| `src/pswamp_modules/my_module/messages.py` | what it publishes | moves to `models/src/pswamp_models/<pkg>/` |
| `tests/` | its tests | move to `modules/<name>/tests/` |
| `src/pswamp_proto/grid.py` | `open_grid`: a read-only repository over a grid | stays |
| `src/pswamp_proto/offline.py` | `OfflineSim`: the live source's frames and scans, offline | stays |
| `scripts/` | the prototype loops | an example may become `modules/<name>/examples/` |

## The grid and the measurements

```python
from pswamp_proto import OfflineSim, open_grid

repo = open_grid("sample")            # or "nordic44", a folder, "http://127.0.0.1:7878"
sim = OfflineSim(repo, scada_period=2.0)
sim.operable()                        # every line, transformer and switch: name, kind, mRID
for message in sim.run(20.0, at={2.0: sim.trip("Alpha-Gamma 400 kV line"),
                                 10.0: sim.reclose("Alpha-Gamma 400 kV line")}):
    ...                               # a PmuFrame (50/s) or a ScadaScan (every 2 s)
```

- **A frame's columns** are one per PMU measurement in the graph. Find them by the
  header, not by position: `frame.header.columns(measurement="f")`, where the
  measurements are `V_Magnitude`, `V_Angle`, `f`, `df` (ROCOF), `I_Magnitude`,
  `I_Angle`. `header.analog[i]` is the column's Analog mRID, which leads into the
  graph.
- **A scan** lists the value of every SCADA Analog and Discrete by mRID.
  `pswamp_core.cim.measurement_table(repo)` says what each one is: quantity, unit,
  equipment, terminal. Power is signed into the equipment, as in CGMES, so a
  machine's generation is negative.
- **Nordic44** is downloaded by LazyCIM on first use. Its licence is CC BY-NC-SA:
  never commit it.

**What the offline simulation leaves out**, compared with the live source:
- **Protection.** Nothing trips unless you trip it.
- **Graph edits.** It reports no `CimEdits` or `SimEvent`.
- **Rebuilds.** It never rebuilds the model mid-run.

It also uses private internals of `rtsim_from_cim` (`engine`, `pmu`, `scada`), so a
change there may break `offline.py`. The live source has none of these gaps:
`scripts/live_run.py` runs the module on it in real time, which also shows whether
the module keeps up at 50 frames/s.

The sample grid's machines have no governors, so after a disturbance its frequency
drifts and is not brought back. Splitting it into islands makes the frequency swing
widely. That is the simulation, not this wrapper.

## Writing the module

`module.py` explains the shapes it shows: two inputs with a handler each, columns
found by the header, the CIM graph through `self.cim_repo`, `reset` and
`cim_changed`. The full contract is in the docstring of p-SWAMP's
`core/src/pswamp_core/modules.py`, and in `doc/module-cookbook.md`.

The rules that matter now, so that promotion is a move rather than a rewrite:

- **Import only `pswamp_core`, `pswamp_models` and third-party libraries** in the
  module. Never import `pswamp_proto`, another module or anything from p-SWAMP's
  `app/`.
- **Every message is a pydantic `DataModel` with a pinned `version`.** No dicts,
  numpy arrays or pickles in what you publish.
- **`process`/handlers are synchronous** and return a body, a message, a list or
  `None`. Call the module with `run(msg)` or `run_one(msg)` in scripts and tests.
- **`name` equals the entry point's name** in `pyproject.toml`.
- **A `status` field (`OK`, `Alert` or `Emergency`) in the result body** is what
  puts the module in the grid monitor's Status panel. Without it, the module runs
  but doesn't appear there.
- **Rename it early**: `my-module`, `my_module` and `MyModule` appear in
  `pyproject.toml`, the package folder, the class and the tests.

## Trying it in the full stack

From the p-SWAMP checkout, without moving anything into it:

```
uv run pswamp dev server --extra-modules ../pswamp-prototype
```

This is the ordinary dev stack (server, Kafka, Oxigraph, workers, the live grid
simulation), plus this project:
- **Installed into the image.** Its `pswamp-*` dependencies are the image's own.
  Third-party ones are added, but never a version that differs from one the image
  locked.
- **In the grid monitor's pipeline.** Use `--pipeline <app>` for another pipeline.
- **Hosted by an `extra-modules-worker`.** It restarts when you save a file under
  `src/`, and the image rebuilds when `pyproject.toml` changes.

The results go on Kafka as `grid-monitor.my.module.result`; the worker's log
says what it hosts. No page shows them until the module is promoted (below).
`.dockerignore` keeps `.venv/` out of the image build; keep it. The details are in
p-SWAMP's `doc/module-cookbook.md`, "Trying a module from outside the repo".

## Promoting it into p-SWAMP

In the p-SWAMP checkout:

1. `uv run pswamp new module <name> "<Label>"`. This writes `modules/<name>/`, its
   models in `models/src/pswamp_models/<pkg>/`, a pipeline file, a web API and a page.
2. Replace the generated module with `module.py` and the generated results with
   `messages.py`. Change the import to `from pswamp_models.<pkg> import ...`, and add
   the module's third-party dependencies to `modules/<name>/pyproject.toml` (plus
   `pswamp-core[cim]` if it reads the graph).
3. Move the tests into `modules/<name>/tests/`. Test file names must be unique across
   the repo, so this one becomes `test_<pkg>_module.py`. A test there cannot use
   `pswamp_proto`. Build frames by hand, or use the source by name
   (`pswamp_core.scripts.source("rtsim-from-cim", ...)`) with `rtsim-from-cim` as an
   extra.
4. To run it on the live grid, add it to `pipelines/grid-monitor.toml`, not to a
   pipeline of its own, since that would start a second simulation. Then add it to
   `PSWAMP_WORKER_MODULES` of the `module-worker` in `docker-compose.yml`. Its results
   reach a panel through `LiveGrid.handle` in
   `app/server-python/src/grid_monitor/live.py` (AGENTS.md, "Adding a p-SWAMP view").
5. `uv lock`, `uv run pswamp api generate`, `uv run pswamp check`,
   `uv run pswamp test module <name>`, then `uv run pswamp dev server` (with `--build`)
   to see it in the full system.
