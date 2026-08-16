#!/usr/bin/env bash
# Container entrypoint for the `api` service.
#
# BAGEL's Intel oneAPI dependency (MKL etc.) needs its environment sourced
# into THIS process before any BAGEL subprocess worker is spawned, because
# app/chemistry/jobs/base.py's `_run_inner` inherits `os.environ` for every
# non-PySCF engine rather than building a fresh env per job -- so whatever
# env this shell has when it execs `python -m server.main` is what every
# BAGEL job will see for the lifetime of the container.
#
# This is intentionally optional and non-fatal: a lab that only uses PySCF
# (or only ORCA) has no oneAPI install to source, and QC_AGENT_BAGEL_SETVARS
# defaults to a host path (/opt/intel/oneapi/setvars.sh) that won't exist
# unless that directory is bind-mounted in -- see docker-compose.yml.
set -euo pipefail

SETVARS="${QC_AGENT_BAGEL_SETVARS:-/opt/intel/oneapi/setvars.sh}"
if [ -f "$SETVARS" ]; then
    echo "entrypoint: sourcing BAGEL oneAPI environment from $SETVARS" >&2
    # shellcheck disable=SC1090
    source "$SETVARS" --force
else
    echo "entrypoint: $SETVARS not found -- skipping oneAPI setup (fine if this deployment doesn't run BAGEL jobs)" >&2
fi

exec python -m server.main
