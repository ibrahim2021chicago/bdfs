from utils.loggerGen import setup_logger
from utils.config import CENTRAL_SERVER
from utils.config import FILE_SERVERS
import subprocess

logger = setup_logger()

def rsync_folder(opp_id, country, matched_customer_list):
    for sync_type in ["opportunity", "contract"]:
        try:
            for entry in matched_customer_list[sync_type]:
                if isinstance(entry, dict) and 'path' in entry and entry['path']:
                    logger.info(f"Syncing {sync_type} folders for customer: {matched_customer_list['code']}, {matched_customer_list[sync_type]}")
                    cmd = [
                        "rsync", "-avz", "--no-group", "-O", "--no-perms",
                        "-e", f"ssh -p {FILE_SERVERS['port']} -i {FILE_SERVERS['key']}",
                        f"{CENTRAL_SERVER['base_path']}{sync_type}/{opp_id}",
                        f"{FILE_SERVERS['username']}@{FILE_SERVERS[country]}:{entry['path']}/"
                    ]
                    logger.info(f"Running command: {' '.join(cmd)}")
                    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                    if result.returncode == 0:
                        logger.info(f"Rsync completed successfully: {result.stdout}")
                    else:
                        logger.error(f"Rsync failed: {result.stderr}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Rsync command failed with error: {e.stderr}")