from dotenv import load_dotenv
import os

load_dotenv()

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
    # 'contract_base_path': os.getenv('CONTRACT_BASE_PATH')
}
