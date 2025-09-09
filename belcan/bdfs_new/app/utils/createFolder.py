import os
from utils.loggerGen import setup_logger
from utils.config import CENTRAL_SERVER
from utils.sync_folder import rsync_folder
from utils.ldapConn import create_ad_group
from utils.setPerms import set_opp_acl
from utils.setPerms import set_local_acls
from utils.bdfsJsonHandler import get_groups_perms

logger = setup_logger()

def create_folder_on_local(opp_id, region, classification):
    # Opportunity folder creation
    parentPath = os.path.join(CENTRAL_SERVER['base_path'], "opportunity")
    try:
        os.makedirs(parentPath, exist_ok=True)
        folder_path = os.path.join(parentPath, opp_id)
        os.makedirs(folder_path, exist_ok=True)
        logger.info(f"Opportunity Folder created: {folder_path}")
        set_opp_acl(opp_id, folder_path)
    except Exception as e:
        logger.error(f"An error occurred while creating folders: {e}")

    # Contract subfolder creation
    contract_parent_path = os.path.join(CENTRAL_SERVER['base_path'], "contract")
    contract_folder = os.path.join(contract_parent_path, opp_id)
    review_folder = os.path.join(contract_folder, "2contract_review")
    try:
        os.makedirs(review_folder, exist_ok=True)
        logger.info(f"Contract folder created {contract_folder}")
        logger.info(f"Review subfolder created: {review_folder}")
        group_perms = get_groups_perms(region, classification)
        set_local_acls(contract_folder, group_perms)
    except Exception as e:
        logger.error(f"Failed to create contract folder for {opp_id}: {e}")
