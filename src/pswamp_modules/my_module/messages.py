"""What the module publishes.

In the p-SWAMP repo a module's messages never live in the module: on promotion this file moves to
``models/src/pswamp_models/my_module/`` (``pswamp_models.my_module``), and the module imports it
from there. Keep it free of anything but pydantic and ``pswamp_models``, so that move is a move.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pswamp_models.common import AppStatus, ResultEnvelope

__all__ = ["MyModuleBody", "MyModuleResult"]


class MyModuleBody(BaseModel):
    """One frame's assessment. Replace the fields with your own."""

    frequency_spread_mhz: float | None = Field(description="Highest minus lowest station frequency, mHz.")
    max_rocof_hz_s: float | None = Field(description="The largest |ROCOF| of any station, Hz/s.")
    rocof_station: str | None = Field(description="The station it is at.")
    rocof_alarm: bool = Field(description="Whether that ROCOF is over the module's limit.")
    generation_mw: float | None = Field(
        description="Total machine generation in the latest SCADA scan, MW; null until the first scan."
    )
    # What the grid monitor's Status panel shows for this module: a result body with a `status`
    # field (OK, Alert or Emergency) is how a module appears there. Leave it out and it does not.
    status: AppStatus = Field(description="'Alert' while the ROCOF alarm holds, 'OK' otherwise.")


class MyModuleResult(ResultEnvelope[MyModuleBody]):
    # The pinned version of the message: bump it on a breaking change of the body.
    version: Literal["v1"] = "v1"
