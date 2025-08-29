from utils.loggerGen import setup_logger
from utils.bdfsJsonHandler import get_groups_perms
from utils.ldapConn import create_ad_group
import subprocess

logger = setup_logger()

def set_local_acls(folder_path, group_perms):
    for gp in group_perms:
        group = gp['group']
        perms = gp['perm']

        cmd = ['setfacl', '-Rm', f'g:{group}:{perms}', folder_path]

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"Set ACL {perms} for group {group} on {folder_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to set ACL {perms} for group {group} on {folder_path}: {e}")

def set_opp_acl(opp_id, opp_folder, perms="rwx"):
    ad_group_created = create_ad_group(opp_id)
    if not ad_group_created:
        logger.error(f"Failed to verify AD group for {opp_id}")
        return False
    group_perms = [{'group': opp_id, 'perm': perms}]
    set_local_acls(opp_folder, group_perms)
    print(f"Set ACL {perms} for AD group {opp_id} on {opp_folder}")
    return True