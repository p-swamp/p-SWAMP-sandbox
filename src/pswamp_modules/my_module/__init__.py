"""The module being prototyped (``my-module``): see ``module.py``. What it publishes is in
``messages.py`` (``pswamp_models.my_module``, once promoted)."""

from .messages import MyModuleBody, MyModuleResult
from .module import MyModule, spread_and_rocof

__all__ = ["MyModule", "MyModuleBody", "MyModuleResult", "spread_and_rocof"]
