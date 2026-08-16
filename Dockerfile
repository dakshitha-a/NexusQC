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

FROM python:3.11-slim AS runtime
WORKDIR /app

# Build tooling needed only to compile a couple of native extensions
# (e.g. some pyscf/rdkit wheels don't ship manylinux for every platform);
# removed from the final layer via apt cleanup, not a separate stage, since
# pip's build isolation makes a true multi-stage split more trouble than
# it's worth here.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY server/ server/
COPY scripts/ scripts/
COPY --from=frontend-build /frontend/dist/ frontend/dist/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
