import os
import time
import logging
import json
import pyodbc
import requests
from requests.exceptions import ProxyError, ConnectionError, HTTPError
import concurrent.futures
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

# Load sensitive configs from environment or config
from config import API_CONFIG, CONN_STRING

# -- Configurable settings
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 5))
RETRIES = int(os.getenv("API_MAX_RETRIES", 5))
INITIAL_BACKOFF = int(os.getenv("API_BACKOFF_SEC", 2))
PROGRESS_EVERY = int(os.getenv("PROGRESS_EVERY", 100))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 1000))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))
CONNECTION_POOL_SIZE = int(os.getenv("CONNECTION_POOL_SIZE", 10))

# Proxy configuration
proxies = {
    "http": os.getenv("HTTP_PROXY", "http://proxysrv.belcan.com:3128"),
    "https": os.getenv("HTTPS_PROXY", "https://proxysrv.belcan.com:3128")
}

# API configuration
url = API_CONFIG['url']
headers = {
    "client-id": API_CONFIG['client_id'],
    "client-secret": API_CONFIG['client_secret'],
    "content-type": API_CONFIG['content_type']
}

# -- Logging config
logging.basicConfig(
    format='%(asctime)s %(levelname)s [%(module)s:%(lineno)d] %(message)s',
    level=os.getenv("LOG_LEVEL", "INFO"),
    handlers=[
        logging.FileHandler(f"employee_processor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class EmployeeResult:
    associate_id: str
    status: Optional[str]
    classification: Optional[str]
    error: Optional[str] = None

def api_post_with_retries(session: requests.Session, payload: Dict, retries: int = RETRIES, initial_backoff: int = INITIAL_BACKOFF) -> Optional[Dict]:
    """Make API POST request with exponential backoff retry mechanism."""
    backoff = initial_backoff
    for attempt in range(1, retries + 1):
        try:
            response = session.post(
                url,
                headers=headers,
                data=json.dumps(payload),
                proxies=proxies,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", backoff))
                logger.warning(f"Rate limit hit (429). Waiting {retry_after}s (attempt {attempt}) for payload: {payload}")
                time.sleep(retry_after)
                backoff *= 2  # Exponential backoff
                continue
            response.raise_for_status()
            logger.debug(f"API success for payload {payload}: {response.status_code}")
            return response.json()
        except (ProxyError, ConnectionError) as e:
            logger.warning(f"Attempt {attempt} failed (proxy/connection error): {e}")
            if attempt == retries:
                logger.error(f"All retries failed for payload: {payload}")
                return None
            time.sleep(backoff)
            backoff *= 2
        except HTTPError as e:
            logger.error(f"HTTP error for payload {payload}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error for payload {payload}: {e}")
            return None
    return None

def process_employee(associate_id: str, session: requests.Session) -> EmployeeResult:
    """Process a single employee and return their status and classification."""
    try:
        # Validate associate_id
        if not isinstance(associate_id, str) or not associate_id.strip():
            return EmployeeResult(associate_id=associate_id, status=None, classification=None, error="Invalid associate ID")

        # Employee status request
        emp_payload = {"empid": associate_id, "type": "employee"}
        emp_response = api_post_with_retries(session, emp_payload)
        emp_status = emp_response.get("Associate_Status") if emp_response else None

        # Folder classification request
        folder_payload = {"empid": associate_id, "type": "folder"}
        folder_response = api_post_with_retries(session, folder_payload)
        classification = folder_response.get("ProjectTechnicalDataAccessEligibility") if folder_response else None

        logger.info(f"Processed {associate_id} - Status: {emp_status}, Classification: {classification}")
        return EmployeeResult(associate_id=associate_id, status=emp_status, classification=classification)
    except Exception as e:
        logger.error(f"Error processing associate {associate_id}: {e}")
        return EmployeeResult(associate_id=associate_id, status=None, classification=None, error=str(e))

def save_results(results: List[EmployeeResult], batch_number: int) -> None:
    """Save batch results to a JSON file."""
    output_file = f"employee_results_batch_{batch_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(output_file, 'w') as f:
            json.dump([vars(result) for result in results], f, indent=2)
        logger.info(f"Saved batch {batch_number} results to {output_file}")
    except Exception as e:
        logger.error(f"Failed to save results to {output_file}: {e}")

def get_associate_ids() -> List[str]:
    """Fetch associate IDs from database with connection pooling."""
    try:
        # Configure connection pooling
        conn = pyodbc.connect(CONN_STRING, autocommit=True, pool_timeout=30, pool_pre_ping=True)
        with conn.cursor() as cursor:
            cursor.execute("SELECT Associate_ID FROM Cognizant.dbo.Resources")
            associate_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        logger.info(f"Retrieved {len(associate_ids)} associate IDs from database")
        return associate_ids
    except pyodbc.Error as e:
        logger.error(f"Database error: {e}")
        return []

def main():
    """Main function to process employees in batches."""
    try:
        associate_ids = get_associate_ids()
        if not associate_ids:
            logger.error("No associate IDs retrieved. Exiting.")
            return

        total_processed = 0
        batch_number = 1
        results = []

        # Process in batches
        for i in range(0, len(associate_ids), BATCH_SIZE):
            batch_ids = associate_ids[i:i + BATCH_SIZE]
            logger.info(f"Processing batch {batch_number} with {len(batch_ids)} associates")

            with requests.Session() as session:
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = {executor.submit(process_employee, associate_id, session): associate_id for associate_id in batch_ids}
                    for future in concurrent.futures.as_completed(futures):
                        result = future.result()
                        results.append(result)
                        total_processed += 1
                        if total_processed % PROGRESS_EVERY == 0 or total_processed == len(associate_ids):
                            logger.info(f"Processed {total_processed}/{len(associate_ids)} associates")

            # Save batch results
            save_results(results, batch_number)
            results = []  # Clear results for next batch
            batch_number += 1

        logger.info(f"Completed processing {total_processed} associates")
    except KeyboardInterrupt:
        logger.warning("Execution interrupted by user. Saving current results and shutting down.")
        if results:
            save_results(results, batch_number)
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        if results:
            save_results(results, batch_number)

if __name__ == "__main__":
    main()