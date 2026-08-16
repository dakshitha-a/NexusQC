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
#
# Forwards whatever command this container was actually invoked with
# (`exec "$@"`) rather than hardcoding `python -m server.main` -- the oneAPI
# setup above needs to happen unconditionally regardless of what runs
# afterward, since one-off admin commands (`docker compose run --rm api
# python -m server.admin_cli ...`) still import app.chemistry.jobs.base and
# could in principle touch BAGEL-adjacent code paths. With no CMD/command
# override at all (normal `docker compose up`), Dockerfile's own CMD
# supplies the default `python -m server.main`.
set -euo pipefail

SETVARS="${QC_AGENT_BAGEL_SETVARS:-/opt/intel/oneapi/setvars.sh}"
if [ -f "$SETVARS" ]; then
    echo "entrypoint: sourcing BAGEL oneAPI environment from $SETVARS" >&2
    # setvars.sh, and the per-component env scripts it in turn sources
    # (e.g. compiler/latest/env/vars.sh), probe for standard Linux tools
    # (`ps`) this image's slim Python base doesn't include, AND reference
    # a few of their own internal variables (e.g. OCL_ICD_FILENAMES)
    # without first checking they're set. Under `set -e` a plain
    # nonzero-exit command inside a sourced script can be shielded by
    # wrapping the whole `source` in an `if` (an `-e` violation is exempt
    # inside an if/while/&&/|| condition) -- but `set -u`'s "unbound
    # variable" violation is NOT subject to that same exemption; bash
    # aborts a non-interactive shell immediately the moment an unset
    # variable is referenced, regardless of surrounding if/&&/|| context.
    # So both flags are disabled for the DURATION of the source call, not
    # just wrapped in an if -- this is the only way to make this genuinely
    # non-fatal, matching this script's own "intentionally optional and
    # non-fatal" docstring above. A real, reproducible bug found while
    # bringing this container up for the auth/admin test suite:
    # docker/entrypoint.sh silently never reached `exec "$@"` at all, so
    # `python -m server.main` never ran -- first surfaced as a `set -e`
    # abort on a missing `ps`, and a second, different abort (this one) on
    # `set -u` once the first was fixed.
    set +eu
    # shellcheck disable=SC1090
    source "$SETVARS" --force
    source_status=$?
    set -eu
    if [ "$source_status" -ne 0 ]; then
        echo "entrypoint: sourcing $SETVARS reported an error -- continuing without it (BAGEL jobs may not work, everything else is unaffected)" >&2
    fi
else
    echo "entrypoint: $SETVARS not found -- skipping oneAPI setup (fine if this deployment doesn't run BAGEL jobs)" >&2
fi

exec "$@"
