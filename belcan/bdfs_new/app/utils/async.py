import asyncio
import aiohttp
import json
import pyodbc
from config import API_CONFIG, CONN_STRING
from loggerGen import setup_logger
from typing import Dict, Any, Optional, List, Tuple

logger = setup_logger()

# Configuration
FOLDER_URL = "https://bge-cognizant-hcm-exapi-tst.us-e2.cloudhub.io/api/v1/28/HCM/Belcan"
EMPLOYEE_URL = "https://bge-cognizant-hcm-exapi-tst.us-e2.cloudhub.io/api/v1/4537/GetAssociateDetails"

# Async configuration
SEMAPHORE_LIMIT = 20  # Concurrent request limit
MAX_RETRIES = 5
BACKOFF_FACTOR = 2

class AsyncAPIClient:
    """Async API client for handling dual endpoint requests with retry logic."""
    
    def __init__(self, semaphore_limit: int = SEMAPHORE_LIMIT, max_retries: int = MAX_RETRIES):
        self.semaphore = asyncio.Semaphore(semaphore_limit)
        self.max_retries = max_retries
        self.headers = API_CONFIG.get('headers', {}) if 'API_CONFIG' in globals() else {}
    
    async def fetch(self, session: aiohttp.ClientSession, url: str, payload: Dict[str, Any], 
                   retries: int = MAX_RETRIES, backoff: int = BACKOFF_FACTOR) -> Optional[Dict[str, Any]]:
        """
        Make async POST request with retry logic and exponential backoff.
        
        Args:
            session: aiohttp session
            url: API endpoint URL
            payload: Request payload
            retries: Number of retry attempts
            backoff: Backoff multiplier for retries
            
        Returns:
            Response JSON or None if failed
        """
        async with self.semaphore:
            for attempt in range(1, retries + 1):
                try:
                    async with session.post(
                        url, 
                        headers=self.headers, 
                        json=payload, 
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as response:
                        
                        resp_text = await response.text()
                        logger.info(f"API Response for payload {payload}: {response.status} {resp_text}")
                        
                        # Handle rate limiting
                        if response.status == 429:
                            retry_after = int(response.headers.get("Retry-After", backoff * attempt))
                            logger.warning(f"Rate limit hit. Waiting {retry_after} seconds")
                            await asyncio.sleep(retry_after)
                            continue
                        
                        response.raise_for_status()
                        return await response.json()
                        
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(f"Attempt {attempt} failed for {url}: {e}")
                    if attempt == retries:
                        logger.error(f"All {retries} retry attempts failed for payload: {payload}")
                        return None
                    await asyncio.sleep(backoff * attempt)
                    
                except Exception as e:
                    logger.error(f"Unexpected error for {url}: {e}")
                    return None
                    
            return None

    async def get_associate_ids(self) -> List[str]:
        """Fetch associate IDs from database asynchronously."""
        def fetch_from_db():
            try:
                conn = pyodbc.connect(CONN_STRING)
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT Associate_ID FROM Cognizant.dbo.Resources")
                associate_ids = [row[0] for row in cursor.fetchall()]
                cursor.close()
                conn.close()
                return associate_ids
            except Exception as e:
                logger.error(f"Database error: {e}")
                return []
        
        # Run database operation in thread pool to avoid blocking
        associate_ids = await asyncio.to_thread(fetch_from_db)
        logger.info(f"Retrieved {len(associate_ids)} associate IDs from database")
        return associate_ids

    async def process_employee(self, session: aiohttp.ClientSession, associate_id: str) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Process a single employee by making requests to both APIs concurrently.
        
        Args:
            session: aiohttp session
            associate_id: Associate ID to process
            
        Returns:
            Tuple of (associate_id, employee_status, folder_eligibility)
        """
        # Prepare payloads for both endpoints
        emp_payload = {"empid": associate_id, "type": "employee"}
        folder_payload = {"empid": associate_id, "type": "folder"}
        
        # Make both requests concurrently
        tasks = [
            self.fetch(session, EMPLOYEE_URL, emp_payload),
            self.fetch(session, FOLDER_URL, folder_payload)
        ]
        
        try:
            emp_response, folder_response = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Extract employee status
            emp_status = None
            if isinstance(emp_response, dict):
                emp_status = emp_response.get("Associate_Status", "Unknown")
            elif emp_response is not None:
                logger.error(f"Employee API error for {associate_id}: {emp_response}")
                emp_status = "Error"
            else:
                emp_status = "Unavailable"
            
            # Extract folder eligibility
            folder_eligibility = None
            if isinstance(folder_response, dict):
                folder_eligibility = folder_response.get("ProjectTechnicalDataAccessEligibility", "Unknown")
            elif folder_response is not None:
                logger.error(f"Folder API error for {associate_id}: {folder_response}")
                folder_eligibility = "Error"
            else:
                folder_eligibility = "Unavailable"
            
            logger.info(f"{associate_id} - Status: {emp_status}, Classification: {folder_eligibility}")
            
            return associate_id, emp_status, folder_eligibility
            
        except Exception as e:
            logger.error(f"Error processing associate {associate_id}: {e}")
            return associate_id, "Error", "Error"

    async def process_all_associates(self) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """Process all associates asynchronously."""
        associate_ids = await self.get_associate_ids()
        
        if not associate_ids:
            logger.warning("No associates found in database")
            return []
        
        logger.info(f"Processing {len(associate_ids)} associates asynchronously")
        
        # Configure aiohttp session with connection limits
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection limit
            limit_per_host=30,  # Per-host connection limit
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Create tasks for all associates
            tasks = [
                self.process_employee(session, associate_id) 
                for associate_id in associate_ids
            ]
            
            # Process all tasks with progress logging
            results = []
            completed = 0
            
            # Process in batches to avoid overwhelming the system
            batch_size = 50
            for i in range(0, len(tasks), batch_size):
                batch = tasks[i:i + batch_size]
                batch_results = await asyncio.gather(*batch, return_exceptions=True)
                
                for result in batch_results:
                    if isinstance(result, Exception):
                        logger.error(f"Task failed with exception: {result}")
                    else:
                        results.append(result)
                        completed += 1
                        
                        # Log progress every 10 completions
                        if completed % 10 == 0 or completed == len(associate_ids):
                            logger.info(f"Progress: {completed}/{len(associate_ids)} associates processed")
                
                # Small delay between batches to be respectful to the API
                if i + batch_size < len(tasks):
                    await asyncio.sleep(0.5)
        
        logger.info(f"Successfully processed {len(results)} associates")
        return results

async def save_results_to_db(results: List[Tuple[str, Optional[str], Optional[str]]]):
    """Save results back to database (optional)."""
    def save_to_db():
        try:
            conn = pyodbc.connect(CONN_STRING)
            cursor = conn.cursor()
            
            # Create or update results table
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ProcessingResults' AND xtype='U')
                CREATE TABLE ProcessingResults (
                    Associate_ID VARCHAR(50) PRIMARY KEY,
                    Employee_Status VARCHAR(50),
                    Folder_Eligibility VARCHAR(50),
                    Processed_Date DATETIME DEFAULT GETDATE()
                )
            """)
            
            # Insert/update results
            for associate_id, emp_status, folder_eligibility in results:
                cursor.execute("""
                    MERGE ProcessingResults AS target
                    USING (SELECT ? AS Associate_ID, ? AS Employee_Status, ? AS Folder_Eligibility) AS source
                    ON target.Associate_ID = source.Associate_ID
                    WHEN MATCHED THEN
                        UPDATE SET Employee_Status = source.Employee_Status, 
                                 Folder_Eligibility = source.Folder_Eligibility,
                                 Processed_Date = GETDATE()
                    WHEN NOT MATCHED THEN
                        INSERT (Associate_ID, Employee_Status, Folder_Eligibility)
                        VALUES (source.Associate_ID, source.Employee_Status, source.Folder_Eligibility);
                """, associate_id, emp_status, folder_eligibility)
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"Saved {len(results)} results to database")
            
        except Exception as e:
            logger.error(f"Error saving results to database: {e}")
    
    await asyncio.to_thread(save_to_db)

async def export_results_to_json(results: List[Tuple[str, Optional[str], Optional[str]]], filename: str = "processing_results.json"):
    """Export results to JSON file."""
    try:
        formatted_results = [
            {
                "associate_id": associate_id,
                "employee_status": emp_status,
                "folder_eligibility": folder_eligibility
            }
            for associate_id, emp_status, folder_eligibility in results
        ]
        
        with open(filename, 'w') as f:
            json.dump(formatted_results, f, indent=2)
        
        logger.info(f"Results exported to {filename}")
        
    except Exception as e:
        logger.error(f"Error exporting results: {e}")

async def main():
    """Main async function."""
    try:
        client = AsyncAPIClient(semaphore_limit=20, max_retries=5)
        
        logger.info("Starting async processing of associates...")
        results = await client.process_all_associates()
        
        if results:
            # Print summary
            total_processed = len(results)
            successful_emp = sum(1 for _, emp, _ in results if emp and emp not in ["Error", "Unavailable"])
            successful_folder = sum(1 for _, _, folder in results if folder and folder not in ["Error", "Unavailable"])
            
            print(f"\n=== Processing Summary ===")
            print(f"Total Associates: {total_processed}")
            print(f"Successful Employee API calls: {successful_emp}")
            print(f"Successful Folder API calls: {successful_folder}")
            
            # Optional: Save results
            await export_results_to_json(results)
            # await save_results_to_db(results)  # Uncomment to save to DB
            
        else:
            logger.warning("No results to process")
            
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")

if __name__ == "__main__":
    asyncio.run(main())