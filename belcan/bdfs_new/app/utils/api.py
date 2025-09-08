import time
import pyodbc
import requests
from requests.exceptions import RequestException, ProxyError, ConnectionError
from config import API_CONFIG  # Import the API_CONFIG dictionary
from loggerGen import setup_logger

logger = setup_logger()

RETRIES = 5
BACKOFF = 2
REQ_DELAY = 0.5

def api_post(url, payload, retries=RETRIES, backoff=BACKOFF):
    headers = API_CONFIG.get('headers', {'Content-Type': 'application/json; charset=utf-8'})  # Use headers from config or default
    try:
        for attempt in range(1, retries + 1):
            try:
                with requests.Session() as session:
                    logger.info(f"POST to {url} with payload {payload}")
                    resp = session.post(url, headers=headers, json=payload, timeout=15)
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
    return None

def process_associates():
    try:
        conn_string = API_CONFIG.get('conn_string', None)
        if not conn_string:
            logger.error("Connection string is missing from API_CONFIG")
            return

        with pyodbc.connect(conn_string) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT Associate_ID FROM Cognizant.dbo.Resources")
            associate_ids = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"DB error: {e}")
        return

    employee_url = API_CONFIG.get('employee_url')
    folder_url = API_CONFIG.get('folder_url')
    if not employee_url or not folder_url:
        logger.error("Employee or Folder URL missing in API_CONFIG")
        return

    for ids, associate_id in enumerate(associate_ids, 1):
        payload = {"empid": associate_id}
        emp_resp = api_post(employee_url, payload)
        emp_status = emp_resp.get("Associate_Status") if emp_resp else "Unavailable"

        folder_resp = api_post(folder_url, payload)
        eligibility = folder_resp.get("ProjectTechnicalDataAccessEligibility") if folder_resp else "Unavailable"

        logger.info(
            f"{associate_id} - Employee Status: {emp_status} | Folder Eligibility: {eligibility}"
        )
        print(
            f"{associate_id} - Employee Status: {emp_status} | Folder Eligibility: {eligibility}"
        )

        time.sleep(REQ_DELAY)

if __name__ == "__main__":
    process_associates()
