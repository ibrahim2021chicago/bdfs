import time
import pyodbc
import requests
from requests.exceptions import ProxyError, ConnectionError, RequestException
from config import API_CONFIG, CONN_STRING
from loggerGen import setup_logger

logger = setup_logger()

RETRIES = 5
BACKOFF = 2
REQ_DELAY = 0.5

EMPLOYEE_URL = API_CONFIG['employee_url']
FOLDER_URL = API_CONFIG['folder_url']

HEADERS = {
    'client_id': API_CONFIG['client_id'],
    'client_secret': API_CONFIG['client_secret'],
    'Content-Type': API_CONFIG['Content-Type']
}

def api_post(url, payload, retries=RETRIES, backoff=BACKOFF):
    try:
        with requests.Session() as session:
            for attempt in range(1, retries + 1):
                try:
                    #logger.info(f"POST to {url} with payload {payload}")
                    resp = session.post(url, headers=HEADERS, json=payload, timeout=15)
                    logger.info(f"[{resp.status_code}]: {resp.text}")
                    resp.raise_for_status()
                    return resp.json()
                except (ProxyError, ConnectionError) as e:
                    logger.warning(f"Attempt {attempt} failed: {e}")
                    if attempt == retries:
                        logger.error(f"Max attempts for payload {payload}")
                        return None
                    time.sleep(backoff * attempt)
                except RequestException as e:
                    logger.error(f"Request failed: {e}")
                    return None
    except Exception as e:
        logger.error(f"Unhandled error in api_post: {e}")
    return None

def process_associates():
    try:
        with pyodbc.connect(CONN_STRING) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT Associate_ID FROM Cognizant.dbo.Resources")
            associate_ids = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Database error: {e}")
        return

    for associate_id in associate_ids:
        payload = {"emplid": associate_id}

        emp_resp = api_post(EMPLOYEE_URL, payload)
        emp_status = emp_resp.get("Associate_Status") if emp_resp else "Unavailable"

        folder_resp = api_post(FOLDER_URL, payload)
        eligibility = folder_resp.get("ProjectTechnicalDataAccessEligibility") if folder_resp else "Unavailable"

        logger.info(f"{associate_id} - Employee Status: {emp_status} | Folder Eligibility: {eligibility}")
        print(f"{associate_id} - Employee Status: {emp_status} | Folder Eligibility: {eligibility}")

        time.sleep(REQ_DELAY)

if __name__ == "__main__":
    process_associates()
