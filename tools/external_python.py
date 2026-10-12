# SPDX-License-Identifier: GPL-3.0-or-later
"""external_python.py - choose the Python that runs the black suit / Web of Shadows finishing step.

Used by blacksuit_runner.py and rvb_runner.py. Their last step (blacksuit_finalize.py,
rvb_finalize.py: atlas dilation, texture encoding, packaging) runs in a separate Python process
that needs numpy and Pillow.

Why a separate interpreter has to be found at all: when SM3 Studio runs from source, the Python
running it is the natural choice. Inside "SM3 Studio.exe", sys.executable is the .exe itself, and
starting it again would open a second window instead of running the script.

Order of the candidates:
  1. the SM3_PYTHON environment variable: full path of a python.exe (only this one is tried);
  2. from source: the Python running SM3 Studio (sys.executable);
     from the .exe: `python`, then the `py` launcher, as found on PATH.
The first candidate that can `import numpy` and `from PIL import Image` is used; if none can,
a RuntimeError says what to install or set.

History: until 2026-10-12 both runners used a fixed path to an interpreter that only existed on
the author's machine (Python 3.12 + numpy 2.3.5 + Pillow 12.3.0): the Black Suit target (from
the .exe) and the Web of Shadows mode (always) only worked there. To rerun the author's
conversions with that same interpreter, point SM3_PYTHON at it. Measured on one model
(2026-10-12): the black suit files came out identical with that interpreter and with
Python 3.14 + numpy 2.5.2 + Pillow 12.3.0.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ENVIRONMENT_VARIABLE = 'SM3_PYTHON'
# The finishing scripts import exactly these.
REQUIRED_IMPORTS = 'import numpy; from PIL import Image'


def candidates():
    """Interpreters to try, in order (see the module docstring)."""
    configured = os.environ.get(ENVIRONMENT_VARIABLE, '').strip().strip('"')
    if configured:
        return [Path(configured)]
    if not getattr(sys, 'frozen', False):
        return [Path(sys.executable)]
    found = []
    for name in ('python', 'py'):
        path = shutil.which(name)
        if path:
            found.append(Path(path))
    return found


def has_required_modules(python):
    """True if `python` exists and can import numpy and Pillow."""
    if not python.is_file():
        return False
    try:
        result = subprocess.run([str(python), '-c', REQUIRED_IMPORTS],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return result.returncode == 0


def find_python():
    """Path of the first suitable interpreter; RuntimeError with a clear message otherwise."""
    tried = []
    for python in candidates():
        if has_required_modules(python):
            return python
        tried.append(str(python))
    if os.environ.get(ENVIRONMENT_VARIABLE, '').strip():
        hint = ('%s is set to "%s", which is not a Python that can import numpy and Pillow.'
                % (ENVIRONMENT_VARIABLE, os.environ[ENVIRONMENT_VARIABLE]))
    else:
        hint = ('Tried: %s.' % (', '.join(tried) if tried else 'no python or py on PATH'))
    raise RuntimeError(
        'The texture step needs a Python 3 with numpy and Pillow. ' + hint + ' Install Python 3 '
        'and run "python -m pip install numpy pillow", or set the %s environment variable to '
        'the full path of a python.exe that has them, then convert again.' % ENVIRONMENT_VARIABLE)
