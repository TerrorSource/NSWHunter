FROM python:3.15-slim

LABEL org.opencontainers.image.title="NSWHunter" \
      org.opencontainers.image.description="Finds the Switch updates that switch-library-manager-web misses through Prowlarr and sends them to your usenet client" \
      org.opencontainers.image.source="https://github.com/<account>/NSWHunter"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    HOME=/tmp \
    PORT=3033 \
    TZ=Etc/UTC \
    PUID=1000 \
    PGID=1000

# tzdata: without it the log and the panel show UTC.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY app/ /app/
COPY CHANGELOG.md /app/CHANGELOG.md
# Always readable for the app user, also when a file had stricter rights on the build machine.
RUN chmod -R a+rX /app && mkdir -p /data /backup
COPY --chmod=755 entrypoint.sh /entrypoint.sh
WORKDIR /app

# /backup is a volume of its own, so the backups do not sit next to what they are a backup of.
VOLUME /data /backup
EXPOSE 3033
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s \
  CMD python3 -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '3033'), timeout=5)" || exit 1

# The entrypoint starts as root, gives /data to PUID:PGID and then runs NSWHunter as that user.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "-u", "/app/main.py"]
