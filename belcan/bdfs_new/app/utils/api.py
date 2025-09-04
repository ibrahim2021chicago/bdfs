import pyodbc
import requests
import json
import logging
import time
from requests.exceptions import ProxyError, ConnectionError
import concurrent.futures

from utils.config import API_CONFIG, CONN_STRING

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Proxy configuration - update or set to None if no proxy needed
proxies = {
    "http": "http://proxyuser:proxypass@proxyserver:proxyport",
    "https": "https://proxyuser:proxypass@proxyserver:proxyport"
}
#proxies = None  # Uncomment if you don't use a proxy

headers = {
    "client-id": API_CONFIG['client_id'],
    "client-secret": API_CONFIG['client_secret'],
    "content-type": API_CONFIG['content_type']
}
url = API_CONFIG['url']

def api_post_with_retries(payload, retries=5, backoff=2):
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15, proxies=proxies)
            logger.info(f"API response for payload {payload}: {response.status_code} {response.text}")
            response.raise_for_status()
            return response.json()
        except (ProxyError, ConnectionError) as e:
            logger.warning(f"Attempt {attempt} failed due to proxy/connection error: {e}")
            if attempt == retries:
                logger.error(f"All {retries} retry attempts failed for payload: {payload}")
                return None
            time.sleep(backoff * attempt)
        except requests.RequestException as e:
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
    try:
        conn = pyodbc.connect(CONN_STRING)
        cursor = conn.cursor()
        cursor.execute("SELECT Associate_ID FROM your_table")  # Replace with your table name

        associate_ids = [row[0] for row in cursor.fetchall()]

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            executor.map(process_employee, associate_ids)

        cursor.close()
        conn.close()

    except Exception as e:
        logger.error(f"Database or unexpected error occurred: {e}")

if __name__ == "__main__":
    main()