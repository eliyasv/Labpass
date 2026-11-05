FROM python:3.15-alpine3.24@sha256:20a82dbc2783112ddb91d1534603f802d222a3e63e593cd002eb2ac534e70211 AS python-base

# Install hash-verified wheels, remove package installers and run as an unprivileged user.
FROM python-base AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock .
RUN apk upgrade --no-cache \
    && python -m pip install --only-binary=:all: --require-hashes -r requirements.lock \
    && python -m pip check \
    && python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.14/ensurepip \
    && addgroup -S -g 10001 labpass \
    && adduser -S -D -H -u 10001 -G labpass labpass
COPY --chown=labpass:labpass labpass ./labpass
COPY --chown=labpass:labpass certs ./certs
COPY --chown=labpass:labpass migrations ./migrations
COPY --chown=labpass:labpass alembic.ini .
USER labpass
EXPOSE 8000
CMD ["uvicorn", "labpass.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

# Keep test dependencies separate from the deployed runtime.
FROM python-base AS test-tools
COPY requirements-dev.lock .
RUN python -m pip install --only-binary=:all: --require-hashes --target /test-tools -r requirements-dev.lock

# Exercise the runtime image with the additional test tools and transaction suite.
FROM runtime AS test
COPY --from=test-tools /test-tools /test-tools
COPY tests ./tests
COPY pyproject.toml .
ENV PYTHONPATH=/test-tools:/app
CMD ["python", "-m", "pytest"]

# Default build target contains only the application runtime.
FROM runtime AS release
