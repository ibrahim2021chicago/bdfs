from ldap3 import Server, Connection, ALL
from utils.loggerGen import setup_logger
from utils.config import LDAP_CONFIG

logger = setup_logger()

#def connect_ldap():
#    try:
#        server = Server(LDAP_CONFIG['server'], get_info=ALL)
#        conn = Connection(server, user=f"{LDAP_CONFIG['bind_dn']}", password=LDAP_CONFIG['ldap_pass'], auto_bind=True)
#        logger.info("LDAP connection established successfully.")
#        conn.unbind()
#    except Exception as e:
#        logger.error(f"LDAP connection error: {e}")

def create_ad_group(opp_id):
    try:
        server = Server(LDAP_CONFIG['server'], get_info=ALL)
        conn = Connection(server, user=f"{LDAP_CONFIG['bind_dn']}", password=LDAP_CONFIG['ldap_pass'], auto_bind=True)
        group_dn = f"CN={opp_id},{LDAP_CONFIG['group_dn']}"
        attributes = {
            'objectClass': ['top', 'group'],
            'sAMAccountName': opp_id,
            'description': f'AD group for opportunity {opp_id}'
        }
        if conn.add(group_dn, attributes=attributes):
            logger.info(f"AD group {opp_id} created successfully.")
            return True
        else:
            if conn.result['description'] == 'entryAlreadyExists':
                logger.info(f"AD group {opp_id} already exists.")
                return True
            else:
                logger.error(f"Failed to create AD group {opp_id}: {conn.result}")
                return False
    except Exception as e:
        logger.error(f"Error creating AD group {opp_id}: {e}")
        return False
    finally:
        if conn:
            conn.unbind()
