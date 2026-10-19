#!/bin/bash

# PostgreSQL WAL archive cleanup
# Designed for Patroni PostgreSQL HA:
#   cgnmssql01 = Primary/Leader
#   munmssql01 = Standby/Replica
#
# IMPORTANT:
#   DRY_RUN=1 by default.
#   Change to DRY_RUN=0 only after reviewing the dry-run output.

set -u

ARCHIVE_DIR="/var/lib/pgsql/archive"
PATRONI_API="http://127.0.0.1:8008/cluster"
LOG_FILE="/var/log/pg_wal_archive_cleanup.log"
LOCK_FILE="/var/run/pg_wal_archive_cleanup.lock"

DRY_RUN="${DRY_RUN:-1}"

log()
{
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "$LOG_FILE"
}

fail()
{
    log "ERROR: $*"
    exit 1
}

# ------------------------------------------------------------
# Basic checks
# ------------------------------------------------------------

[ "$(id -u)" -eq 0 ] || fail "Script must be run as root."

[ -d "$ARCHIVE_DIR" ] || fail "Archive directory does not exist: $ARCHIVE_DIR"

command -v psql >/dev/null 2>&1 ||
    fail "psql command not found."

command -v pg_archivecleanup >/dev/null 2>&1 ||
    fail "pg_archivecleanup command not found."

command -v flock >/dev/null 2>&1 ||
    fail "flock command not found."

# ------------------------------------------------------------
# Prevent concurrent execution
# ------------------------------------------------------------

exec 9>"$LOCK_FILE"

if ! flock -n 9; then
    log "Another cleanup process is already running. Exiting."
    exit 0
fi

# ------------------------------------------------------------
# Determine local PostgreSQL role
# ------------------------------------------------------------

IS_RECOVERY=$(sudo -u postgres psql -Atc \
    "SELECT pg_is_in_recovery();" 2>/dev/null)

[ "$IS_RECOVERY" = "t" ] || [ "$IS_RECOVERY" = "f" ] ||
    fail "Unable to determine PostgreSQL recovery state."

# ============================================================
# STANDBY / REPLICA
# ============================================================

if [ "$IS_RECOVERY" = "t" ]; then

    log "Local PostgreSQL node is REPLICA/STANDBY."

    # Get the WAL file containing the latest checkpoint REDO.
    REDO_WAL_FILE=$(
        sudo -u postgres pg_controldata /var/lib/pgsql/data 2>/dev/null |
        awk -F': ' '/Latest checkpoint.s REDO WAL file/ {
            print $2
        }'
    )

    [ -n "$REDO_WAL_FILE" ] ||
        fail "Unable to determine standby REDO WAL file."

    log "Standby REDO WAL: $REDO_WAL_FILE"

    if [ "$DRY_RUN" -eq 1 ]; then

        log "DRY RUN - files that would be removed:"

        sudo -u postgres pg_archivecleanup -n \
            "$ARCHIVE_DIR" \
            "$REDO_WAL_FILE" 2>&1 | tee -a "$LOG_FILE"

        RC=${PIPESTATUS[0]}

        [ "$RC" -eq 0 ] ||
            fail "pg_archivecleanup dry-run failed."

        log "Dry-run completed successfully."

    else

        log "LIVE CLEANUP - removing WAL files older than $REDO_WAL_FILE"

        sudo -u postgres pg_archivecleanup \
            "$ARCHIVE_DIR" \
            "$REDO_WAL_FILE" 2>&1 | tee -a "$LOG_FILE"

        RC=${PIPESTATUS[0]}

        [ "$RC" -eq 0 ] ||
            fail "pg_archivecleanup failed."

        log "Standby cleanup completed successfully."
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
    # Get Patroni cluster information.
    # --------------------------------------------------------

    CLUSTER_JSON=$(curl -fsS --max-time 10 "$PATRONI_API") ||
        fail "Unable to obtain Patroni cluster information."

    # Find a healthy replica and extract:
    #   name
    #   role
    #   state
    #   timeline
    #   replay_lsn
    #
    # We deliberately require:
    #   role = replica
    #   state = streaming
    #   replay_lsn present
    #
    # This avoids cleaning the Primary archive when the standby
    # is disconnected or not streaming.

    REPLICA_INFO=$(
        printf '%s\n' "$CLUSTER_JSON" |
        python3 -c '
import json
import sys

data = json.load(sys.stdin)

for m in data.get("members", []):
    role = str(m.get("role", "")).lower()
    state = str(m.get("state", "")).lower()
    replay_lsn = m.get("replay_lsn")
    timeline = m.get("timeline")

    if role == "replica" and state in ("streaming", "running") and replay_lsn and timeline:
        print(
            "%s|%s|%s|%s|%s" %
            (
                m.get("name", ""),
                m.get("host", ""),
                timeline,
                replay_lsn,
                state
            )
        )
        break
'
    )

    [ -n "$REPLICA_INFO" ] ||
        fail "No healthy streaming replica found. Primary cleanup skipped."

    IFS='|' read -r REPLICA_NAME REPLICA_HOST REPLICA_TIMELINE REPLAY_LSN REPLICA_STATE <<< "$REPLICA_INFO"

    log "Replica detected:"
    log "  Name       : $REPLICA_NAME"
    log "  Host       : $REPLICA_HOST"
    log "  State      : $REPLICA_STATE"
    log "  Timeline   : $REPLICA_TIMELINE"
    log "  Replay LSN : $REPLAY_LSN"

    # --------------------------------------------------------
    # Validate LSN format.
    # Example:
    #   14/5BCC8048
    # --------------------------------------------------------

    if ! [[ "$REPLAY_LSN" =~ ^[0-9A-Fa-f]+/[0-9A-Fa-f]+$ ]]; then
        fail "Invalid replica replay LSN: $REPLAY_LSN"
    fi

    # --------------------------------------------------------
    # Convert:
    #
    #   Timeline + LSN
    #
    # into a WAL filename.
    #
    # PostgreSQL WAL segment size = 16 MB.
    #
    # WAL filename:
    #   TTTTTTTTLLLLLLLLSSSSSSSS
    #
    # where:
    #   T = timeline
    #   L = logical log
    #   S = segment number
    # --------------------------------------------------------

    WAL_FILE=$(
        python3 - "$REPLICA_TIMELINE" "$REPLAY_LSN" <<'PY'
import sys

timeline = int(sys.argv[1])
lsn = sys.argv[2]

log_part, offset_part = lsn.split("/")

log_part = int(log_part, 16)
offset = int(offset_part, 16)

# PostgreSQL default WAL segment size = 16 MB
segment = offset // (16 * 1024 * 1024)

print(
    f"{timeline:08X}"
    f"{log_part:08X}"
    f"{segment:08X}"
)
PY
    )

    [ -n "$WAL_FILE" ] ||
        fail "Unable to construct WAL filename."

    log "Cleanup boundary WAL: $WAL_FILE"

    # --------------------------------------------------------
    # Safety check:
    # Don't clean if replica is badly behind.
    #
    # We use Patroni's reported byte lag.
    # --------------------------------------------------------

    REPLICA_LAG=$(
        printf '%s\n' "$CLUSTER_JSON" |
        python3 - "$REPLICA_NAME" <<'PY'
import json
import sys

data = json.load(sys.stdin)
name = sys.argv[1]

for m in data.get("members", []):
    if m.get("name") == name:
        print(m.get("lag", ""))
        break
PY
    )

    if [ -n "$REPLICA_LAG" ]; then
        log "Patroni reported replica lag: $REPLICA_LAG bytes"
    else
        log "WARNING: Patroni did not provide replica lag."
    fi

    # --------------------------------------------------------
    # Dry run / Live cleanup
    # --------------------------------------------------------

    if [ "$DRY_RUN" -eq 1 ]; then

        log "DRY RUN - files that would be removed:"

        sudo -u postgres pg_archivecleanup -n \
            "$ARCHIVE_DIR" \
            "$WAL_FILE" 2>&1 | tee -a "$LOG_FILE"

        RC=${PIPESTATUS[0]}

        [ "$RC" -eq 0 ] ||
            fail "Primary pg_archivecleanup dry-run failed."

        log "Primary dry-run completed successfully."

    else

        log "LIVE CLEANUP - removing WAL files older than $WAL_FILE"

        sudo -u postgres pg_archivecleanup \
            "$ARCHIVE_DIR" \
            "$WAL_FILE" 2>&1 | tee -a "$LOG_FILE"

        RC=${PIPESTATUS[0]}

        [ "$RC" -eq 0 ] ||
            fail "Primary pg_archivecleanup failed."

        log "Primary cleanup completed successfully."
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