"""The module over p-SWAMP's live source itself, in real time: what the server will run.

``rtsim-from-cim`` paces at 50 frames/s, runs TOPS in a process of its own and publishes what the
live stack does: ``PmuFrame``, ``ScadaScan``, and the ``SimEvent``s and ``CimEdits`` of its
protection, which the module ignores (it does not declare them). Use this to check the module keeps
up and behaves on the real stream; use ``offline_run.py`` to iterate.

    uv run python scripts/live_run.py [--grid sample] [--seconds 20]

Nothing disturbs the grid here (the grid is read only; the live source follows edits of its graph,
which are the stack's CIM graph app's to make). For a disturbance in real time see p-swamp's
modules/frame-stats/examples/rtsim_frame_stats.py, which brings an embedded store it can edit.
"""

import pswamp_proto  # first: it sets OPENBLAS_NUM_THREADS before numpy is imported

import argparse  # noqa: E402
from datetime import timedelta  # noqa: E402

from pswamp_core.scripts import module, source  # noqa: E402
from pswamp_core.util.time import utcnow  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--grid", default="sample", help="as pswamp_proto.open_grid: sample, nordic44, a folder, an Oxigraph url")
    parser.add_argument("--seconds", type=float, default=20.0, help="how long to read once frames flow")
    args = parser.parse_args()

    repo = pswamp_proto.open_grid(args.grid)
    sim = source("rtsim-from-cim", repo=repo, scada_period=2.0)  # by its entry point, as a pipeline names it
    my = module("my-module")
    my.cim_repo = pswamp_proto.open_grid(args.grid)  # a repository of its own: one per thread, and the source owns the first

    print("starting the simulation (the model is built first: seconds) ...")
    first, printed = None, -1
    # The window is generous: the stream ends there, or when we stop reading.
    for message in sim.read(end=utcnow() + timedelta(seconds=args.seconds + 120)):
        if type(message).__name__ not in ("PmuFrame", "ScadaScan"):
            print(f"  {type(message).__name__}: {message.model_dump(exclude={'timestamp'})}")
            continue
        first = first or message.timestamp
        t = (message.timestamp - first).total_seconds()
        if t >= args.seconds:
            break
        for result in my.run(message):
            if int(t) > printed:  # one line a second
                printed = int(t)
                print(f"t={t:5.1f} s  {result.result}")


if __name__ == "__main__":
    main()
