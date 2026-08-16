# Runtime image for the `api` service: FastAPI backend + the singleton
# JobManager/job_watcher. Deliberately does NOT bundle ORCA or BAGEL --
# ORCA's license forbids redistribution, so both are bind-mounted from the
# host at run time (see docker-compose.yml). PySCF is open source and pip-
# installable, so it lives in this image like any other Python dependency.
#
# The frontend's built static assets (frontend/dist/) are produced by a
# separate build stage below and copied in only so `docker build` is
# reproducible from a clean checkout without requiring a host-side
# `npm run build` first; nginx (not this container) is what actually serves
# them in the deployed stack -- see nginx/nginx.conf.

FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
WORKDIR /app

# Build tooling needed only to compile a couple of native extensions
# (e.g. some pyscf/rdkit wheels don't ship manylinux for every platform);
# removed from the final layer via apt cleanup, not a separate stage, since
# pip's build isolation makes a true multi-stage split more trouble than
# it's worth here.
#
# openmpi-bin: a real, previously-undiscovered gap confirmed by actually
# submitting real ORCA and BAGEL CASSCF jobs in this container (never
# exercised before -- this repo's own compose bring-up and its test suite
# had only run PySCF jobs against this image up to this point). ORCA's
# %pal block (built from QC_AGENT_N_CORES, see orca_runner.py) shells out
# to `mpirun` whenever nprocs > 1, and this image had no MPI runtime
# installed at all, so every ORCA job using more than one core failed at
# startup with "mpirun: not found".
#
# The base image is pinned to `-bookworm` specifically, not left as plain
# `python:3.11-slim` (which was found to have silently drifted to Debian
# 13/trixie at some point): trixie's repos only carry OpenMPI 5.x, which
# dropped the C++ bindings library entirely upstream -- installing
# openmpi-bin there satisfies ORCA (mpirun works, confirmed by a real
# CASSCF(4,4)/STO-3G water run whose energy matched PySCF's own CASSCF to
# 1.7e-8 Ha) but leaves `bagel-1.2.2/bin/BAGEL` unable to even start
# ("error while loading shared libraries: libmpi_cxx.so.40: cannot open
# shared object file"), since BAGEL is linked against that OpenMPI-4-era
# library and trixie has no package that still provides it. Bookworm's
# OpenMPI (4.1.x) has that library and closely matches the version already
# in real use on the bare-metal host this app was otherwise verified
# against (confirmed via `mpirun --version` on that host) -- one MPI stack
# that satisfies both engines, rather than trying to straddle two.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        openmpi-bin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY server/ server/
COPY scripts/ scripts/
COPY --from=frontend-build /frontend/dist/ frontend/dist/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# This image has no USER directive (runs as root), and stock OpenMPI
# refuses to launch under mpirun as root without an explicit opt-in --
# these two env vars are OpenMPI's own documented alternative to passing
# `--allow-run-as-root`/`--allow-run-as-root-confirm` on every invocation,
# which orca_runner.py's _write_and_run has no reason to special-case
# (it just execs the orca binary directly; ORCA's own %pal machinery is
# what shells out to mpirun internally, inheriting this process's env).
ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1

COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
# The default command when the container is run with no override (plain
# `docker compose up`) -- entrypoint.sh's `exec "$@"` forwards this, or
# forwards a real override instead when one is given, e.g.
# `docker compose run --rm api python -m server.admin_cli bootstrap-admin ...`.
CMD ["python", "-m", "server.main"]
