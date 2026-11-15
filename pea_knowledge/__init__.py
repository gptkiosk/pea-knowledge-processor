# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Lets `python3 -m pea_knowledge` run from a checkout without installing: the real package is in src/pea_knowledge."""
import os as _os

__path__ = [_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src", "pea_knowledge")]
with open(_os.path.join(__path__[0], "__init__.py"), encoding="utf-8") as _f:
    exec(compile(_f.read(), _f.name, "exec"))
del _os, _f
