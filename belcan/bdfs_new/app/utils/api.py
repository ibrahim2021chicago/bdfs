import os
import time
import logging
import json
import pyodbc
import requests
from requests.exceptions import ProxyError, ConnectionError
import concurrent.futures

# Load sensitive configs from environment or config
from config import API_CONFIG, CONN_STRING

# -- Configurable settings
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 3))
RETRIES = int(os.getenv("API_MAX_RETRIES", 5))
BACKOFF = int(os.getenv("API_BACKOFF_SEC", 2))
PROGRESS_EVERY = int(os.getenv("PROGRESS_EVERY", 100))

proxies = {
    "http": os.getenv("HTTP_PROXY", "http://proxysrv.belcan.com:3128"),
    "https": os.getenv("HTTPS_PROXY", "https://proxysrv.belcan.com:3128")
}

url = API_CONFIG['url']
headers = {
    "client-id": API_CONFIG['client_id'],
    "client-secret": API_CONFIG['client_secret'],
    "content-type": API_CONFIG['content_type']
}

# -- Logging config
logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s',
    level=os.getenv("LOG_LEVEL", "INFO")
)
logger = logging.getLogger(__name__)

def api_post_with_retries(session, payload, retries=RETRIES, backoff=BACKOFF):
    for attempt in range(1, retries+1):
        try:
            response = session.post(
                url,
                headers=headers,
                data=json.dumps(payload),
                proxies=proxies,
                timeout=15
            )
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", backoff * attempt))
                logger.warning(f"Rate limit hit (429). Waiting {retry_after} seconds before retrying (attempt {attempt}) for payload: {payload}")
                time.sleep(retry_after)
                continue
            logger.debug(f"API response for payload {payload}: {response.status_code} {response.text}")
            response.raise_for_status()
            return response.json()
        except (ProxyError, ConnectionError) as e:
            logger.warning(f"Attempt {attempt} failed (proxy/connection error): {e}")
            if attempt == retries:
                logger.error(f"All retry attempts failed for payload: {payload}")
                return None
            time.sleep(backoff * attempt)
        except requests.RequestException as e:
            logger.error(f"API request failed for payload {payload}: {e}")
            return None

def process_employee(associate_id):
    try:
        with requests.Session() as session:
            emp_payload = {"empid": associate_id, "type": "employee"}
            emp_response = api_post_with_retries(session, emp_payload)
            emp_status = emp_response.get("Associate_Status") if emp_response else None

            folder_payload = {"empid": associate_id, "type": "folder"}
            folder_response = api_post_with_retries(session, folder_payload)
            classification = folder_response.get("ProjectTechnicalDataAccessEligibility") if folder_response else None

            logger.info(f"{associate_id} - Status: {emp_status}, Classification: {classification}")
            print(f"Associate_ID: {associate_id}, Status: {emp_status}, Classification: {classification}")
    except Exception as e:
        logger.error(f"Error processing associate {associate_id}: {e}")

def main():
    try:
        with pyodbc.connect(CONN_STRING) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT Associate_ID FROM Cognizant.dbo.Resources")
                associate_ids = [row[0] for row in cursor.fetchall()]

        processed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_employee, associate_id): associate_id for associate_id in associate_ids}
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                future.result()  # re-raises exceptions
                if i % PROGRESS_EVERY == 0 or i == len(futures):
                    logger.info(f"Processed {i}/{len(futures)} associates.")

    except KeyboardInterrupt:
        logger.warning("Execution interrupted by user. Shutting down gracefully.")
    except Exception as e:
        logger.error(f"Database error or unexpected error: {e}")

if __name__ == "__main__":
    main()
