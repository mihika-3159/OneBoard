# syntax=docker/dockerfile:1
# Digest-qualified base images are mandatory build arguments (see build script).
ARG NODE_IMAGE
ARG PYTHON_IMAGE
FROM ${NODE_IMAGE} AS web
WORKDIR /build/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/oneboard DATA_DIR=/var/lib/oneboard SERVE_WEB_BUILD=true
WORKDIR /opt/oneboard
COPY apps/api/requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tmp/requirements.lock && rm /tmp/requirements.lock
COPY apps/api/ apps/api/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY scripts/serve_secure_api.py scripts/serve_secure_api.py
COPY --from=web /build/apps/web/dist apps/web/dist
RUN mkdir -p /var/lib/oneboard && chown 10001:10001 /var/lib/oneboard
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["python","-m","scripts.serve_secure_api"]
