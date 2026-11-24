#!/bin/sh
# Start as root only long enough to make the data folder the app's own, then run the app as the unprivileged user.
#
# A volume mounted by the host (Railway, or a bind mount) arrives owned by root, and a process that is not root cannot
# write to it. The way round that used to be to run the whole server as root (RAILWAY_RUN_UID=0). This does the one
# thing root is needed for, the chown, and then gives root up for good: the server, the parse worker and anything a
# hostile upload could reach run as uid 10001 (security review 2026-11-24).
#
# Started as any other user (docker run --user, or a platform that forces one) it changes nothing and runs the command.
#
# It fails loudly. This script was first run by a real build, not on the machine it was written on: if it cannot make
# the data folder writable, or cannot drop privileges, it says which and why on stderr and exits 70, so the deploy
# shows a plain sentence in its log instead of a server that starts and then cannot save anything.
set -u
fail() {
  echo "architect entrypoint: STOPPED. $1" >&2
  exit 70
}
DATA="${RAILWAY_VOLUME_MOUNT_PATH:-${ARCHITECT_DATA:-/data}}"
UID_NOW="$(id -u)"

if [ "$UID_NOW" = "0" ]; then
  mkdir -p "$DATA" 2>/dev/null || fail "Cannot create the data folder $DATA as root. Is the volume mounted read-only?"
  # only when it is not already the app's: a large volume is not walked on every start
  if [ "$(stat -c %u "$DATA" 2>/dev/null)" != "10001" ] || [ -n "$(find "$DATA" -maxdepth 2 ! -user 10001 -print -quit 2>/dev/null)" ]; then
    chown -R 10001:10001 "$DATA" 2>/dev/null || fail "Cannot make the data folder $DATA the app's own (chown to uid 10001 failed). The volume may be read-only, or of a kind that does not keep owners. Nothing was started."
  fi
  command -v setpriv >/dev/null 2>&1 || fail "Cannot drop privileges: setpriv is not in this image. The server will not be started as root. Nothing was started."
  # prove both things before the server starts: that privileges can be dropped, and that the user they are dropped to can write
  setpriv --reuid=10001 --regid=10001 --init-groups -- sh -c 'touch "$1/.architect-write-test" && rm -f "$1/.architect-write-test"' sh "$DATA" 2>/dev/null \
    || fail "Either privileges could not be dropped to uid 10001 (setpriv refused: the platform may forbid changing user), or uid 10001 cannot write the data folder $DATA after the chown. The server will not be started as root. Nothing was started."
  echo "architect entrypoint: data folder $DATA belongs to uid 10001; starting the server as uid 10001, not root." >&2
  export HOME=/home/architect
  exec setpriv --reuid=10001 --regid=10001 --init-groups -- "$@"
fi

# not root: nothing can be fixed from here, so say what is wrong instead of starting a server that cannot save
[ -d "$DATA" ] || mkdir -p "$DATA" 2>/dev/null || fail "Running as uid $UID_NOW, and the data folder $DATA does not exist and cannot be created. Mount a volume there."
if ! ( touch "$DATA/.architect-write-test" && rm -f "$DATA/.architect-write-test" ) 2>/dev/null; then
  fail "Running as uid $UID_NOW, which cannot write the data folder $DATA. A volume a platform mounts usually belongs to root. Let the container start as root (remove any setting that forces a user; on Railway RAILWAY_RUN_UID=0 also does it): this script then makes the folder uid 10001's and drops to uid 10001 before the server starts. Nothing was started."
fi
echo "architect entrypoint: running as uid $UID_NOW (not root); the data folder $DATA is writable." >&2
exec "$@"
