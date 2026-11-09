#!/bin/sh
# Seed the config volume, then start the BBS as the unprivileged mesh user.
#
# Arguments that start with "-" (or none) are passed to server.py, so
#   docker run tc2-bbs-mesh --interface-type tcp --host 192.168.1.50
# keeps working. Any other command (e.g. "sh") runs as given.
set -eu

APP_DIR=/home/mesh/bbs
CONFIG_DIR="$APP_DIR/config"
DEFAULTS_DIR="$APP_DIR/defaults"

# Copy each default into the config volume unless the file already exists.
seed() {
    [ -f "$CONFIG_DIR/config.ini" ] || cp "$DEFAULTS_DIR/example_config.ini" "$CONFIG_DIR/config.ini"
    [ -f "$CONFIG_DIR/fortunes.txt" ] || cp "$DEFAULTS_DIR/fortunes.txt" "$CONFIG_DIR/fortunes.txt"
}

if [ "$#" -eq 0 ] || [ "${1#-}" != "$1" ]; then
    set -- python "$APP_DIR/server.py" "$@"
fi

if [ "$(id -u)" = 0 ]; then
    # Match the host owner of the bind mount so files stay editable there.
    PUID="${PUID:-1000}"
    PGID="${PGID:-1000}"
    if [ "$(id -g mesh)" != "$PGID" ]; then
        groupmod --non-unique --gid "$PGID" mesh
    fi
    if [ "$(id -u mesh)" != "$PUID" ]; then
        usermod --non-unique --uid "$PUID" mesh
    fi

    mkdir -p "$CONFIG_DIR"
    seed
    # Only touch entries not already owned by mesh; leaves correct files alone.
    find "$CONFIG_DIR" \( ! -user mesh -o ! -group mesh \) -exec chown mesh:mesh {} +

    exec setpriv --reuid=mesh --regid=mesh --init-groups "$@"
fi

# Started with an explicit non-root --user: ownership is the caller's job.
# Seed if the volume is writable; otherwise warn and let the app report it.
seed || echo "entrypoint: cannot seed $CONFIG_DIR (not writable by uid $(id -u))" >&2
exec "$@"
