# syntax=docker/dockerfile:1
#
# Build from the repository root so the image contains this checkout's code:
#   docker build -f docker/Dockerfile -t tc2-bbs-mesh .
# or, from docker/:
#   docker compose up -d --build

FROM python:3.13-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/home/mesh/bbs \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# tzdata so TZ works for bulletin/mail timestamps (database.py uses local time).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# Unprivileged runtime user. dialout grants access to serial-attached nodes.
# UID/GID 1000 match the default first user on Raspberry Pi OS / Debian hosts;
# the entrypoint can remap them via PUID/PGID.
RUN groupadd --gid 1000 mesh \
 && useradd --uid 1000 --gid mesh --groups dialout --create-home mesh \
 && chmod 755 /home/mesh

# Dependencies first so code changes do not invalidate this layer.
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv "$VIRTUAL_ENV" \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

WORKDIR /home/mesh/bbs
COPY *.py ./
COPY flows/ ./flows/
# Defaults seeded into the config volume on first start (see entrypoint.sh).
COPY example_config.ini fortunes.txt ./defaults/
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# config.ini, fortunes.txt, bulletins.db and js8call.db all live here: the app
# resolves them relative to the working directory.
VOLUME /home/mesh/bbs/config
WORKDIR /home/mesh/bbs/config

# Runs as root only long enough to seed the volume and fix its ownership,
# then drops to the mesh user.
ENTRYPOINT ["entrypoint.sh"]
