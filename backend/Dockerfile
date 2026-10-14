FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock .
RUN python -m pip install -r requirements.lock \
    && groupadd --gid 10001 labpass \
    && useradd --uid 10001 --gid labpass --no-create-home labpass
COPY --chown=labpass:labpass labpass ./labpass
COPY --chown=labpass:labpass certs ./certs
COPY --chown=labpass:labpass migrations ./migrations
COPY --chown=labpass:labpass alembic.ini .
USER labpass
EXPOSE 8000
CMD ["uvicorn", "labpass.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
