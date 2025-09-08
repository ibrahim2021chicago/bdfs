import asyncio
import aiohttp
import json
import pyodbc
from config import API_CONFIG, CONN_STRING
from loggerGen import setup_logger

logger = setup_logger()

EMPLOYEE_URL = API_CONFIG['employee_url']
FOLDER_URL = API_CONFIG['folder_url']
HEADERS = API_CONFIG['headers']

semaphore = asyncio.Semaphore(20)

def get_associate_ids():
    conn = pyodbc.connect(CONN_STRING)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT Associate_ID FROM Cognizant.dbo.Resources")
    associate_ids = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return associate_ids

async def fetch(session, url, payload, retries=5, backoff=2):
    for attempt in range(1, retries + 1):
        try:
            async with session.post(url, headers=HEADERS, json=payload, timeout=15) as response:
                resp_text = await response.text()
                logger.info(f"API Response for payload {payload} @ {url}: {response.status} {resp_text}")
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"Attempt {attempt} failed for payload {payload}: {e}")
            if attempt == retries:
                logger.error(f"All {retries} retry attempts failed for payload: {payload}")
                return None
            await asyncio.sleep(backoff * attempt)

async def process_employee(session, associate_id):
    async with semaphore:
        try:
            emp_payload = {"empid": associate_id}
            emp_response = await fetch(session, EMPLOYEE_URL, emp_payload)
            emp_status = emp_response.get("Associate_Status") if emp_response else "Unavailable"

            folder_payload = {"empid": associate_id}
            folder_response = await fetch(session, FOLDER_URL, folder_payload)
            eligibility = folder_response.get("ProjectTechnicalDataAccessEligibility") if folder_response else "Unavailable"

            logger.info(f"{associate_id} - Employee Status: {emp_status} | Folder Eligibility: {eligibility}")
            print(f"{associate_id} - Employee Status: {emp_status} | Folder Eligibility: {eligibility}")
        except Exception as e:
            logger.error(f"Error processing associate {associate_id}: {e}")

async def main():
    # Note: get_associate_ids is synchronous so run in thread pool
    associate_ids = await asyncio.to_thread(get_associate_ids)
    async with aiohttp.ClientSession() as session:
        tasks = [process_employee(session, aid) for aid in associate_ids]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
