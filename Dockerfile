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

# node:24, not node:20 (F-007): ketcher-core/react/standalone@3.17.2 all
# declare `engines: {node: ">=24.14.1"}`, so every build -- host and image
# alike -- emitted EBADENGINE for the app's single largest dependency.
# npm does not enforce `engines` by default, so the build succeeded and the
# 2D sketcher worked, which is exactly what makes it worth fixing rather
# than living with: the project was running Ketcher outside its supported
# range on nothing but luck, with no failure to notice until one appeared
# at runtime. Verified on Node 24.19.0: `npm ci` emits no EBADENGINE at
# all, `tsc --noEmit` is clean, and `vite build` produces the same bundle.
FROM node:24-slim AS frontend-build
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
# libopenblas-dev is a BUILD dependency, not a runtime one, and it is here
# for exactly one package. pyscf itself installs from a manylinux wheel and
# needs no compiler or BLAS at install time; pyscf-forge (MC-PDFT, L-PDFT,
# CMS-PDFT, and the csf_solver every multireference state average now uses)
# publishes an sdist only, so pip compiles it here and its CMakeLists does
# `find_package(BLAS)`. Without this the build dies on "Could NOT find BLAS
# (missing: BLAS_LIBRARIES)" after several minutes of downloading, which is
# a slow way to discover a missing apt line. Leaving it out is not an option
# while pyscf-forge has no wheel for this platform: the capability rows for
# the pair-density methods claim them unconditionally.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libopenblas-dev \
        libgomp1 \
        openmpi-bin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional extras, off by default. INSTALL_DMRG=1 adds block2, the DMRG
# backend for the AutoCAS entropy pilot -- 379 MB and its own bundled MKL,
# for a screening pool of 30 orbitals instead of exact FCI's 12. Left out,
# the app detects its absence and stops offering the option rather than
# failing on it, so a default image is fully functional without it.
# scripts/install.sh asks, and passes the answer through docker-compose.yml
# as QC_AGENT_INSTALL_DMRG.
ARG INSTALL_DMRG=0
COPY requirements-optional.txt .
RUN if [ "$INSTALL_DMRG" = "1" ]; then \
        pip install --no-cache-dir -r requirements-optional.txt; \
    else \
        echo "skipping optional extras (INSTALL_DMRG=0)"; \
    fi

COPY app/ app/
COPY server/ server/
COPY scripts/ scripts/
COPY --from=frontend-build /frontend/dist/ frontend/dist/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

# F-004: run as a non-root user whose uid/gid match the host operator's.
#
# Everything this container wrote into the bind-mounted data/ directory
# used to land root-owned, because the image ran as root and a bind mount
# preserves the writing process's uid verbatim onto the host filesystem.
# The host operator -- who owns the repository and the data directory --
# then could not delete, back up, or reclaim their own job artifacts and
# KB uploads without going back through a container or asking for sudo.
# 262 such files had accumulated on this deployment.
#
# Root was NOT required here, despite an earlier comment implying it: the
# two OMPI_ALLOW_RUN_AS_ROOT variables this replaces existed only to work
# around OpenMPI's refusal to launch as root, so dropping root removes the
# reason they existed rather than trading one problem for another. Both
# engine binaries (ORCA/BAGEL, bind-mounted read-only via
# docker-compose.override.yml) and the oneAPI tree are world-readable and
# world-executable in a normal install, so a non-root uid can still run
# them. Verified directly against a real deployment.
#
# APP_UID/APP_GID are build args so a deployment on another host can match
# its own operator instead of inheriting this one's. docker-compose.yml
# passes them; the 1000 default is the conventional first-user id.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g "${APP_GID}" -o app \
    && useradd -u "${APP_UID}" -g "${APP_GID}" -o -m -s /bin/bash app \
    && mkdir -p /app/data \
    && chown -R "${APP_UID}:${APP_GID}" /app
USER app

# The commit this image was built from, recorded as an OCI label so it can be
# read back with `docker inspect` without starting anything.
#
# scripts/update.sh needs it because "what is deployed" and "what the checkout
# is at" are different questions, and on this project they routinely disagree:
# a deployment created by scripts/install.sh is a single directory that is both
# the git working copy and the running stack, so committing moves HEAD while
# the containers keep running the previous commit. An update that asks HEAD
# reports "already up to date" and skips the backup, the destructive-change
# report and the drain -- every gate it exists to enforce. See
# docs/trackers/2026-08-update-knows-what-it-runs.md.
#
# The default is deliberately `unknown` rather than anything derived: a build
# has no access to git, and guessing here would recreate exactly the false
# confidence this is meant to remove. update.sh passes the real value on every
# build it runs, and treats `unknown` as "cannot tell, so assume stale" --
# which is what a hand-run `docker compose up --build` should look like. To
# stamp a hand-run build too:
#
#     QC_AGENT_BUILD_COMMIT=$(git rev-parse HEAD) docker compose up -d --build
ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.revision="${GIT_COMMIT}"
# The same value again, as an environment variable, because a LABEL is only
# readable with `docker inspect` from the host -- the process inside the
# container cannot see it. Two things need it from in there: /api/version, so
# the browser can tell whether its tab is running against a newer build than
# the one it loaded, and scripts/extract_frontend.sh, which stamps
# frontend/dist/.build-commit with what the image itself says rather than with
# what the caller believed. A stamp taken from the image cannot disagree with
# the image.
ENV QC_AGENT_BUILD_COMMIT="${GIT_COMMIT}"

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
# The default command when the container is run with no override (plain
# `docker compose up`) -- entrypoint.sh's `exec "$@"` forwards this, or
# forwards a real override instead when one is given, e.g.
# `docker compose run --rm api python -m server.admin_cli bootstrap-admin ...`.
CMD ["python", "-m", "server.main"]
