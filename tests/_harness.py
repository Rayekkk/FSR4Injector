# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Stand-in for the `decky` module DeckyLoader injects, so main.py imports outside the loader."""

import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def install():
    if "decky" in sys.modules:
        return sys.modules["decky"]
    decky = types.ModuleType("decky")

    class _Logger:
        info = warning = error = staticmethod(lambda msg: None)

    base = tempfile.mkdtemp(prefix="fsr4i-test-")
    decky.logger = _Logger()
    decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(base, "settings")
    decky.DECKY_PLUGIN_RUNTIME_DIR = os.path.join(base, "runtime")
    decky.DECKY_USER_HOME = os.path.join(base, "home")
    sys.modules["decky"] = decky
    return decky


install()
