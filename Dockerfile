FROM python:3.15-slim

LABEL org.opencontainers.image.title="NSWHunter" \
      org.opencontainers.image.description="Finds the Switch updates and DLC that switch-library-manager-web misses on your indexers and sends them to your download client"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    PORT=3033 \
    TZ=Etc/UTC \
    PUID=1000 \
    PGID=1000

# tzdata: without it the log and the panel show UTC. unrar-free: a RAR inside the RAR of a
# download, which the download client unpacks only once.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata unrar-free \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY app/ /app/
COPY CHANGELOG.md /app/CHANGELOG.md
# Always readable for the app user, also when a file had stricter rights on the build machine.
# /config and /backup belong to the default user: an empty named volume takes the owner of the
# folder it is mounted on, and would else be root's.
RUN chmod -R a+rX /app && mkdir -p /config /data /backup && chown 1000:1000 /config /backup
COPY --chmod=755 entrypoint.sh /entrypoint.sh
WORKDIR /app

# /config holds the settings and the state, as with Sonarr and Radarr; /data is left for your
# media. No VOLUME lines: a volume nobody named would be gone with the container, and the
# entrypoint tells by what is mounted where the settings are.
EXPOSE 3033
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s \
  CMD python3 -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '3033'), timeout=5)" || exit 1

# With 'user:' the container never is root. Without it the entrypoint starts as root, gives the
# config folder to PUID:PGID and then runs NSWHunter as that user.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "-u", "/app/main.py"]
