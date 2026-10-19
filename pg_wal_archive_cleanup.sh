#!/bin/bash

# PostgreSQL WAL archive cleanup (hardened version, v4)
# Designed for Patroni PostgreSQL HA:
#   cgnmssql01 = Primary/Leader
#   munmssql01 = Standby/Replica
#
# SAFETY FEATURES
#   - DRY_RUN=1 by default (set DRY_RUN=0 for a live run)
#   - Whitespace-safe parsing of pg_controldata output
#   - Primary: boundary = MINIMUM replay position across ALL replicas
#   - Primary: aborts unless EVERY replica is streaming/running
#   - Primary: aborts if any replica lag exceeds MAX_LAG_BYTES
#   - Primary: safety margin of KEEP_SEGMENTS WAL segments
#   - Both: never deletes files younger than MIN_AGE_HOURS
#   - WAL segment size is detected, not assumed
#
# NOT SAFE TO USE IF the archive also feeds pgBackRest/Barman/PITR.
# In that case use the backup tool's own retention instead.

set -u

# Start from / so "sudo -u postgres" never hits a permission error
# on the caller's home directory.
cd / || exit 1

ARCHIVE_DIR="/var/lib/pgsql/archive"
PGDATA_DIR="/var/lib/pgsql/data"
PATRONI_API="${PATRONI_API:-}"   # empty = auto-detect (127.0.0.1, then this node's IPv4 addresses); or set PATRONI_API=http://<ip>:8008/cluster
CURL_OPTS="${CURL_OPTS:-}"                                         # e.g. CURL_OPTS=-k for self-signed HTTPS
LOG_FILE="/var/log/pg_wal_archive_cleanup.log"
LOCK_FILE="/var/run/pg_wal_archive_cleanup.lock"

DRY_RUN="${DRY_RUN:-1}"

# Tunables (override via environment if needed)
KEEP_SEGMENTS="${KEEP_SEGMENTS:-32}"            # extra segments kept behind slowest replica (primary)
MAX_LAG_BYTES="${MAX_LAG_BYTES:-1073741824}"    # abort if any replica lags more than 1 GiB
MIN_AGE_HOURS="${MIN_AGE_HOURS:-24}"            # never delete WAL files younger than this

log()
{
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "$LOG_FILE"
}

fail()
{
    log "ERROR: $*"
    exit 1
}

# A valid WAL segment name is exactly 24 hex characters.
is_valid_wal_name()
{
    [[ "$1" =~ ^[0-9A-Fa-f]{24}$ ]]
}

# Never delete files younger than MIN_AGE_HOURS.
# Prints the newest WAL file in the archive that is older than the
# age threshold (empty output if there is none).
newest_old_enough_wal()
{
    find "$ARCHIVE_DIR" -maxdepth 1 -type f \
        -regextype posix-extended -regex '.*/[0-9A-Fa-f]{24}' \
        -mmin +"$((MIN_AGE_HOURS * 60))" -printf '%f\n' 2>/dev/null |
        tr 'a-f' 'A-F' | sort | tail -n 1
}

# Run pg_archivecleanup (dry or live) for a given boundary WAL.
run_cleanup()
{
    local boundary="$1"
    local rc

    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY RUN - files that would be removed (older than $boundary):"
        sudo -u postgres pg_archivecleanup -n \
            "$ARCHIVE_DIR" "$boundary" 2>&1 | tee -a "$LOG_FILE"
        rc=${PIPESTATUS[0]}
        [ "$rc" -eq 0 ] || fail "pg_archivecleanup dry-run failed."
        log "Dry-run completed successfully."
    else
        log "LIVE CLEANUP - removing WAL files older than $boundary"
        sudo -u postgres pg_archivecleanup \
            "$ARCHIVE_DIR" "$boundary" 2>&1 | tee -a "$LOG_FILE"
        rc=${PIPESTATUS[0]}
        [ "$rc" -eq 0 ] || fail "pg_archivecleanup failed."
        log "Cleanup completed successfully."
    fi
}

# Apply the minimum-age guard to a proposed boundary.
# Sets FINAL_BOUNDARY (empty = nothing safe to delete).
apply_age_guard()
{
    local proposed="${1^^}"
    local age_boundary

    age_boundary=$(newest_old_enough_wal)

    if [ -z "$age_boundary" ]; then
        FINAL_BOUNDARY=""
        log "No WAL files older than ${MIN_AGE_HOURS}h in archive. Nothing to clean."
        return
    fi

    if [[ "$age_boundary" < "$proposed" ]]; then
        FINAL_BOUNDARY="$age_boundary"
        log "Age guard (${MIN_AGE_HOURS}h) lowered boundary: $proposed -> $FINAL_BOUNDARY"
    else
        FINAL_BOUNDARY="$proposed"
        log "Age guard (${MIN_AGE_HOURS}h) not limiting; boundary stays $FINAL_BOUNDARY"
    fi
}

# Find the Patroni REST API on this node and load the cluster JSON into
# CLUSTER_JSON. If PATRONI_API is set, only that URL is tried. Otherwise
# tries 127.0.0.1 and then each local IPv4 address (Patroni often listens
# on the node IP only, and the leader can move between nodes).
fetch_cluster_json()
{
    local candidates url ip

    if [ -n "$PATRONI_API" ]; then
        candidates="$PATRONI_API"
    else
        candidates="http://127.0.0.1:8008/cluster"
        for ip in $(hostname -I 2>/dev/null); do
            [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] &&
                candidates="$candidates http://$ip:8008/cluster"
        done
    fi

    for url in $candidates; do
        CLUSTER_JSON=$(curl -fsS $CURL_OPTS --max-time 10 "$url" 2>/dev/null)
        if [ -n "$CLUSTER_JSON" ]; then
            log "Patroni API: $url"
            return 0
        fi
    done

    log "Patroni API not reachable. Tried: $candidates"
    return 1
}

# ------------------------------------------------------------
# Basic checks
# ------------------------------------------------------------

[ "$(id -u)" -eq 0 ] || fail "Script must be run as root."

[ -d "$ARCHIVE_DIR" ] || fail "Archive directory does not exist: $ARCHIVE_DIR"

for cmd in psql pg_archivecleanup pg_controldata flock find sort; do
    command -v "$cmd" >/dev/null 2>&1 || fail "$cmd command not found."
done

case "$DRY_RUN" in
    0|1) ;;
    *) fail "DRY_RUN must be 0 or 1 (got: '$DRY_RUN')." ;;
esac

for v in KEEP_SEGMENTS MAX_LAG_BYTES MIN_AGE_HOURS; do
    [[ "${!v}" =~ ^[0-9]+$ ]] || fail "$v must be a non-negative integer (got: '${!v}')."
done

# ------------------------------------------------------------
# Prevent concurrent execution
# ------------------------------------------------------------

exec 9>"$LOCK_FILE"

if ! flock -n 9; then
    log "Another cleanup process is already running. Exiting."
    exit 0
fi

log "Starting WAL archive cleanup (DRY_RUN=$DRY_RUN, KEEP_SEGMENTS=$KEEP_SEGMENTS, MAX_LAG_BYTES=$MAX_LAG_BYTES, MIN_AGE_HOURS=$MIN_AGE_HOURS)"

# ------------------------------------------------------------
# Determine local PostgreSQL role
# ------------------------------------------------------------

IS_RECOVERY=$(sudo -u postgres psql -Atc \
    "SELECT pg_is_in_recovery();" 2>/dev/null | tr -d '[:space:]')

[ "$IS_RECOVERY" = "t" ] || [ "$IS_RECOVERY" = "f" ] ||
    fail "Unable to determine PostgreSQL recovery state."

# ============================================================
# STANDBY / REPLICA
# ============================================================

if [ "$IS_RECOVERY" = "t" ]; then

    log "Local PostgreSQL node is REPLICA/STANDBY."

    # pg_controldata pads values with spaces after the colon, so split on
    # the colon and strip ALL whitespace from the value.
    REDO_WAL_FILE=$(
        sudo -u postgres pg_controldata "$PGDATA_DIR" 2>/dev/null |
        awk -F':' '/Latest checkpoint.s REDO WAL file/ {
            gsub(/[[:space:]]/, "", $2)
            print $2
        }'
    )

    [ -n "$REDO_WAL_FILE" ] ||
        fail "Unable to determine standby REDO WAL file."

    is_valid_wal_name "$REDO_WAL_FILE" ||
        fail "Standby REDO WAL name is not a valid 24-hex-character WAL name: '$REDO_WAL_FILE'"

    log "Standby REDO WAL: $REDO_WAL_FILE"

    apply_age_guard "$REDO_WAL_FILE"

    if [ -n "$FINAL_BOUNDARY" ]; then
        run_cleanup "$FINAL_BOUNDARY"
    fi

# ============================================================
# PRIMARY / LEADER
# ============================================================

else

    log "Local PostgreSQL node is PRIMARY/LEADER."

    command -v curl >/dev/null 2>&1 ||
        fail "curl command not found."

    command -v python3 >/dev/null 2>&1 ||
        fail "python3 command not found."

    # --------------------------------------------------------
    # Detect WAL segment size (bytes)
    # --------------------------------------------------------

    WAL_SEGMENT_SIZE=$(sudo -u postgres psql -Atc \
        "SELECT pg_size_bytes(current_setting('wal_segment_size'));" 2>/dev/null |
        tr -d '[:space:]')

    [[ "$WAL_SEGMENT_SIZE" =~ ^[0-9]+$ ]] && [ "$WAL_SEGMENT_SIZE" -gt 0 ] ||
        fail "Unable to determine wal_segment_size."

    log "WAL segment size: $WAL_SEGMENT_SIZE bytes"

    # --------------------------------------------------------
    # Get Patroni cluster information.
    # --------------------------------------------------------

    fetch_cluster_json ||
        fail "Unable to obtain Patroni cluster information. Set PATRONI_API (and CURL_OPTS for HTTPS) explicitly."

    # Evaluate ALL replicas (role replica / sync_standby):
    #   - every one must be streaming/running with replay_lsn,
    #     timeline and a numeric lag within MAX_LAG_BYTES
    #   - boundary = slowest replica position minus KEEP_SEGMENTS
    #
    # Output:
    #   OK|<WAL_FILE>|<details>
    #   ERROR|<message>

    RESULT=$(
        printf '%s\n' "$CLUSTER_JSON" |
        python3 -c '
import json
import sys

max_lag = int(sys.argv[1])
keep = int(sys.argv[2])
segsize = int(sys.argv[3])

def err(msg):
    print("ERROR|" + msg)
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception as e:
    err("Cannot parse Patroni JSON: %s" % e)

replicas = [
    m for m in data.get("members", [])
    if str(m.get("role", "")).lower() in ("replica", "sync_standby")
]

if not replicas:
    err("No replica members found in Patroni cluster. Primary cleanup skipped.")

best = None
details = []

for m in replicas:
    name = m.get("name", "?")
    state = str(m.get("state", "")).lower()
    lsn = m.get("replay_lsn")
    tl = m.get("timeline")
    lag = m.get("lag")

    if state not in ("streaming", "running"):
        err("Replica %s is not streaming/running (state=%s)" % (name, state))

    if not lsn or not tl:
        err("Replica %s has no replay_lsn/timeline" % name)

    try:
        lag_i = int(lag)
    except Exception:
        err("Replica %s reported non-numeric lag: %r" % (name, lag))

    if lag_i > max_lag:
        err("Replica %s lag %d bytes exceeds MAX_LAG_BYTES=%d" % (name, lag_i, max_lag))

    try:
        hi, lo = str(lsn).split("/")
        pos = int(hi, 16) * (2 ** 32) + int(lo, 16)
        tl_i = int(tl)
    except Exception:
        err("Replica %s has invalid LSN/timeline: %s / %s" % (name, lsn, tl))

    details.append("%s(tl=%d lsn=%s lag=%d)" % (name, tl_i, lsn, lag_i))

    key = (tl_i, pos)
    if best is None or key < best:
        best = key

tl_i, pos = best

segs_per_log = (2 ** 32) // segsize
abs_seg = pos // segsize - keep
if abs_seg < 0:
    abs_seg = 0

wal = "%08X%08X%08X" % (tl_i, abs_seg // segs_per_log, abs_seg % segs_per_log)

print("OK|%s|%s" % (wal, ", ".join(details)))
' "$MAX_LAG_BYTES" "$KEEP_SEGMENTS" "$WAL_SEGMENT_SIZE"
    )

    [ -n "$RESULT" ] || fail "Replica evaluation produced no output."

    STATUS="${RESULT%%|*}"
    REST="${RESULT#*|}"

    if [ "$STATUS" != "OK" ]; then
        fail "$REST"
    fi

    WAL_FILE="${REST%%|*}"
    DETAILS="${REST#*|}"

    is_valid_wal_name "$WAL_FILE" ||
        fail "Constructed WAL name is invalid: '$WAL_FILE'"

    log "Replicas evaluated: $DETAILS"
    log "Boundary WAL (slowest replica minus $KEEP_SEGMENTS segments): $WAL_FILE"

    apply_age_guard "$WAL_FILE"

    if [ -n "$FINAL_BOUNDARY" ]; then
        run_cleanup "$FINAL_BOUNDARY"
    fi

fi

# ------------------------------------------------------------
# Final filesystem information
# ------------------------------------------------------------

log "Archive size:"
du -sh "$ARCHIVE_DIR" 2>&1 | tee -a "$LOG_FILE"

log "Filesystem status:"
df -h "$ARCHIVE_DIR" 2>&1 | tee -a "$LOG_FILE"

exit 0