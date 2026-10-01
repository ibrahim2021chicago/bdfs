#!/bin/bash

# PostgreSQL WAL archive cleanup
# Role-aware: cleanup is performed ONLY on standby
# Primary nodes are skipped automatically.

ARCHIVE_DIR="/var/lib/pgsql/archive"
LOG_FILE="/var/log/pg_wal_archive_cleanup.log"
LOCK_FILE="/var/run/pg_wal_archive_cleanup.lock"

PGUSER="postgres"

# 1. Prevent multiple cleanup jobs from running simultaneously
exec 9>"$LOCK_FILE"

if ! flock -n 9; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Cleanup already running. Exiting." >> "$LOG_FILE"
    exit 0
fi

# 2. Check PostgreSQL role
IS_RECOVERY=$(sudo -u "$PGUSER" psql -Atc \
    "SELECT pg_is_in_recovery();" 2>/dev/null)

if [ "$IS_RECOVERY" != "t" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Local PostgreSQL node is PRIMARY. Cleanup skipped." >> "$LOG_FILE"
    exit 0
fi

# 3. Verify archive directory
if [ ! -d "$ARCHIVE_DIR" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR: Archive directory does not exist: $ARCHIVE_DIR" >> "$LOG_FILE"
    exit 1
fi

# 4. Get REDO WAL file
REDO_WAL=$(sudo -u "$PGUSER" psql -Atc \
    "SELECT redo_wal_file FROM pg_control_checkpoint();" 2>/dev/null)

if [ -z "$REDO_WAL" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR: Could not determine REDO WAL file. Cleanup skipped." >> "$LOG_FILE"
    exit 1
fi

# 5. Log current state
echo "$(date '+%Y-%m-%d %H:%M:%S') - STANDBY detected. REDO WAL: $REDO_WAL" >> "$LOG_FILE"

# 6. Dry-run first
echo "$(date '+%Y-%m-%d %H:%M:%S') - Files that would be removed:" >> "$LOG_FILE"

sudo -u "$PGUSER" pg_archivecleanup \
    -n \
    "$ARCHIVE_DIR" \
    "$REDO_WAL" >> "$LOG_FILE" 2>&1

RET=$?

if [ $RET -ne 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR: pg_archivecleanup dry-run failed." >> "$LOG_FILE"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - Dry-run completed successfully." >> "$LOG_FILE"