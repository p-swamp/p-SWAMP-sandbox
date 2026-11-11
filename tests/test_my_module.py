"""The module, bottom up: the analysis, the module on hand-made frames, then on the simulated grid.

Test file names are unique across the p-SWAMP repo: on promotion this becomes
modules/my-module/tests/test_my_module_module.py.
"""

from datetime import datetime, timezone

import pytest

from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.my_module import MyModule, MyModuleResult, spread_and_rocof

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_spread_and_rocof():
    assert spread_and_rocof(["a", "b"], [50.0, 50.02], [0.1, -0.3]) == pytest.approx((20.0, 0.3, "b"))
    assert spread_and_rocof(["a", "b"], [None, float("nan")], [None, None]) == (None, None, None)


def frame(f: list[float | None], df: list[float | None]) -> PmuFrame:
    n = len(f)
    header = PmuHeader(
        station=[f"s{i}" for i in range(n)] * 2,
        channel=["f"] * 2 * n,
        measurement=["f"] * n + ["df"] * n,
        units=["Hz"] * n + ["Hz/s"] * n,
        data_rate=50.0,
    )
    return PmuFrame(mRID="test", timestamp=T0, header=header, values=f + df)


def test_the_module_on_hand_made_frames():
    module = MyModule(rocof_limit_hz_s=0.5)
    result = module.run_one(frame([50.0, 49.99], [0.1, 0.8]))
    assert isinstance(result, MyModuleResult)
    assert result.result.rocof_alarm and result.result.rocof_station == "s1"
    assert result.result.status == "Alert"  # what the Status panel shows
    assert result.result.generation_mw is None  # no scan yet
    assert module.run(frame([None, None], [None, None])) == []  # nothing to publish


@pytest.fixture(scope="module")
def grid():
    from pswamp_proto import open_grid

    return open_grid("sample")


def test_a_line_trip_on_the_sample_grid(grid):
    """The sample grid steady, then Alpha-Gamma tripped: a ROCOF alarm, and generation from SCADA."""
    from pswamp_proto import OfflineSim

    sim = OfflineSim(grid, scada_period=1.0)
    module = MyModule(rocof_limit_hz_s=0.5)
    module.cim_repo = grid
    results = [r.result for m in sim.run(4.0, at={2.0: sim.trip("Alpha-Gamma 400 kV line")}) for r in module.run(m)]
    assert len(results) == 200  # 4 s at 50 frames/s
    assert not any(r.rocof_alarm for r in results[:95])  # steady before the trip
    assert {r.status for r in results[:95]} == {"OK"}
    assert any(r.rocof_alarm for r in results[100:])
    assert results[-1].generation_mw == pytest.approx(490, rel=0.1)  # the sample grid's two machines
