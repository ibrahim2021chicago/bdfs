import pyodbc
import json
from utils.config import CONN_STRING
from utils.config import FILE_SERVERS
from utils.config import CENTRAL_SERVER
#from model.Opportunity import SensitivityLevel
from utils.loggerGen import setup_logger
from utils.createFolder import create_folder_on_local
from utils.sync_folder import rsync_folder
from utils.bdfsJsonHandler import get_customer_code
from utils.ldapConn import connect_ldap
from utils.ldapConn import create_ad_group

with open('dfs-customers-dev.json', 'r') as file:
    config = json.load(file)
customer_config = config['dfscustomers']['customer']
logger = setup_logger()
conn = pyodbc.connect(CONN_STRING)
cursor = conn.cursor()
country = None
region = None

try:
    logger.info("Connecting to the database to fetch opportunity IDs.")
    logger.info("Connection established successfully.")

    query = "SELECT OP.Opportunity_ID AS opp_id, OP.Sales_Stage AS sales_stage, OP.Customer_ID AS cust_id, AC.Customer_Name AS cust_name, SFO.Contract_Classification AS classification FROM cognizant.dbo.Opportunity as OP LEFT JOIN Accounts AS AC ON OP.Customer_ID = AC.Customer_ID LEFT JOIN SF.dbo.Opportunity AS SFO ON OP.Opportunity_ID = SFO.Cognizant_Synergy_WinZone_Opportunity_ID__c WHERE OP.Sales_Stage = '3. Solutioning' AND AC.Customer_Name IS NOT NULL AND SFO.Contract_Classification IS NOT NULL;"
    cursor.execute(query)
    logger.info(f"Query executed successfully.{query}")
    opportunity_data = cursor.fetchall()
    
    for opp_id,sales_stage, cust_id, cust_name, classification in opportunity_data:
            if classification == 'Sensitive - US Citizens' or classification == 'Sensitive - US Persons':
                country = 'us'
                region = 'mu'
            elif classification == 'Sensitive - UK Citizens' or classification == 'Sensitive - UK Persons':
                country = 'uk'
                region = 'db'
            elif classification == 'Unrestricted':
                continue
            else:
                region = None
                country = None
                logger.warning(f"Unknown contract classification: {classification}")
            create_folder_on_local(opp_id, region, classification)
            cust_initials = get_customer_code(cust_name)
            cust_code = f"{region or ''}{cust_initials}{country or ''}"
            codes = [item['code'] for item in customer_config]
            matched_customer = next((item for item in customer_config if item['code'] == cust_code), None)
            create_ad_group(opp_id)
            rsync_folder(opp_id, country, matched_customer)
except pyodbc.Error as e:
    logger.error(f"Database error: {e}")
except Exception as e:
    logger.error(f"An error occurred: {e}")
finally:
    if cursor:
        cursor.close()
    if conn:
        conn.close()


