FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps -e .

# State and the Instagram session live here — mount a volume so restarts
# don't re-notify and don't force a fresh login.
VOLUME ["/data"]

HEALTHCHECK --interval=5m --timeout=10s --start-period=1m \
    CMD python -c "import os,sys,time; p=os.path.join('/data','state.db'); sys.exit(0 if os.path.exists(p) else 1)"

ENTRYPOINT ["python", "-m", "insta_notify"]
CMD ["run"]
