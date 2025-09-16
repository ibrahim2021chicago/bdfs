from dotenv import load_dotenv
import os

load_dotenv()

API_CONFIG = {
    'employee_url': os.getenv('EMPLOYEE_URL'),
    'folder_url': os.getenv('FOLDER_URL'),
    'client_id': os.getenv('CLIENT_ID'),
    'client_secret': os.getenv('CLIENT_SECRET'),
    'Content-Type': os.getenv('CONTENT_TYPE', 'application/json; charset=utf-8')
}

DB_CONFIG = {
    'driver': os.getenv('DB_DRIVER'),
    'server': os.getenv('DB_SERVER'),
    'database': os.getenv('DB_DATABASE_CG'),
    'username': os.getenv('DB_USERNAME'),
    'password': os.getenv('DB_PASSWORD'),
    'port': os.getenv('DB_PORT')
}
CONN_STRING = (
    f"DRIVER={DB_CONFIG['driver']};"
    f"SERVER={DB_CONFIG['server']};"
    f"DATABASE={DB_CONFIG['database']};"
    f"UID={DB_CONFIG['username']};"
    f"PWD={DB_CONFIG['password']};"
    f"PORT={DB_CONFIG['port']}"
)
FILE_SERVERS = {
    'us': os.getenv('US_SERVER'),
    'uk': os.getenv('UK_SERVER'),
    'india': os.getenv('INDIA_SERVER'),
    'port': int(os.getenv('PORT', 22)),
    'username': os.getenv('FILE_SERVER_USERNAME'),
    'key' : os.path.expanduser(os.getenv('KEY_PATH')),
    'base_path': os.getenv('FILE_SERVER_BASE_PATH')
}
CENTRAL_SERVER = {
    'base_path': os.getenv('CENTRAL_SERVER_BASE_PATH'),
}
LDAP_CONFIG = {
    'server': os.getenv('LDAP_SERVER'),
    'bind_dn': os.getenv('LDAP_BIND_DN'),
    'ldap_pass': os.getenv('LDAP_PASSWORD'),
    'group_dn': os.getenv('GROUP_DN')
}
SMTP_CONFIG = {
    'server': os.getenv('SMTP_SERVER'),
    'port': int(os.getenv('SMTP_PORT', 25)),
    'username': os.getenv('SMTP_USERNAME'),
    'password': os.getenv('SMTP_PASSWORD')
}

