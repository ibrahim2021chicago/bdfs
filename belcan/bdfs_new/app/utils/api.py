import pyodbc
import requests
import json
import logging
import time
from requests.exceptions import ProxyError, ConnectionError, RequestException
import concurrent.futures
from utils.config import API_CONFIG, CONN_STRING

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# No proxy used
proxies = None

# Headers from config
headers = {
    "client-id": API_CONFIG['client_id'],
    "client-secret": API_CONFIG['client_secret'],
    "content-type": API_CONFIG['content_type']
}

url = API_CONFIG['url']

# Configurable settings
MAX_WORKERS = API_CONFIG.get('max_workers', 20)
RETRIES = API_CONFIG.get('retries', 5)
BACKOFF = API_CONFIG.get('backoff', 2)
REQ_DELAY = API_CONFIG.get('req_delay', 0.5)

def api_post_with_retries(payload, retries=RETRIES, backoff=BACKOFF):
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15, proxies=proxies)
            logger.info(f"API response for payload {payload}: {response.status_code} {response.text}")
            response.raise_for_status()
            return response.json()
        except (ProxyError, ConnectionError) as e:
            logger.warning(f"Attempt {attempt} failed due to connection error: {e}")
            if attempt == retries:
                logger.error(f"All {retries} retry attempts failed for payload: {payload}")
                return None
            time.sleep(backoff * attempt)
        except RequestException as e:
            logger.error(f"API request failed for payload {payload}: {e}")
            return None

def process_employee(associate_id):
    try:
        emp_payload = {"empid": associate_id, "type": "employee"}
        emp_response = api_post_with_retries(emp_payload)
        emp_status = emp_response.get("Associate_Status") if emp_response else None

        folder_payload = {"empid": associate_id, "type": "folder"}
        folder_response = api_post_with_retries(folder_payload)
        classification = folder_response.get("ProjectTechnicalDataAccessEligibility") if folder_response else None

        logger.info(f"{associate_id} - Status: {emp_status}, Classification: {classification}")
        print(f"Associate_ID: {associate_id}, Status: {emp_status}, Classification: {classification}")
    except Exception as e:
        logger.error(f"Error processing associate {associate_id}: {e}")

def main():
    conn = None
    cursor = None
    try:
        conn = pyodbc.connect(CONN_STRING)
        cursor = conn.cursor()
        cursor.execute("SELECT Associate_ID FROM your_table")  # Replace with actual table name
        associate_ids = [row[0] for row in cursor.fetchall()]

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            executor.map(process_employee, associate_ids)
    except Exception as e:
        logger.error(f"Database or unexpected error occurred: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
