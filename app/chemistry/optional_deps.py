"""Presence checks for dependencies the app can run without.

One entry so far: block2, the DMRG backend for the AutoCAS entropy pilot.
It is a 379 MB wheel that links its own MKL, and the exact-FCI pilot -- the
default -- covers every pool up to 12 orbitals without it, so most installs
will never need it. Making it compulsory taxed everyone for a screening
backend few would run, and dragged block2's MKL loading quirk (see
JobManager's LD_LIBRARY_PATH handling in jobs/base.py) into installs that
had no use for it.

What must not happen is the other failure: offering `entropy_method="dmrg"`
in a deployment that cannot run it, so a user picks it and the job dies with
ModuleNotFoundError. That is the shape of defect this module exists to
prevent -- the registry may only advertise what is actually here. So the
check is consulted where the option is offered and where a draft is
validated, and a draft naming an absent backend is refused before it can
reach READY.
"""
from __future__ import annotations

import functools
import importlib.util


@functools.lru_cache(maxsize=1)
def has_dmrg_backend() -> bool:
    """Is block2/pyblock2 installed?

    `find_spec` rather than a real import: importing pyblock2 pulls in a
    large MKL-linked extension, and doing that inside the API process to
    answer a yes/no question is a poor trade when the answer is needed on
    every draft validation.

    The consequence worth knowing: this detects that the package is
    PRESENT, not that its MKL links resolve in this process. Those are
    genuinely different questions here -- block2 dlopens a libmkl_def.so.1
    that lives in the conda environment's own lib directory rather than in
    its bundled set, which is why JobManager scopes an LD_LIBRARY_PATH fix
    onto pyscf workers specifically. An install that is present but
    mis-linked will still fail in the worker, with that error rather than
    a missing-module one.
    """
    return importlib.util.find_spec("pyblock2") is not None
