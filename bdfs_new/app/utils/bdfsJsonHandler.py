import json
from pathlib import Path

CurrentDir = Path(__file__).parent
OneLevelUp = CurrentDir.parent
bdfs_json_path = OneLevelUp / 'bdfs.json'
with open(bdfs_json_path, 'r') as file:
    bdfs = json.load(file)
customer_codes = bdfs['customercodes']

def get_customer_code(customer_full_name):
    for(key, value) in customer_codes.items():
        if customer_full_name.lower() in value.lower():
            return key
    return None

def get_groups_perms(region, classification):
    default_groups = bdfs.get('defaults', {}).get('defaultgroups', [])
    return [{'group': g, 'perm': p} for g, p in default_groups]
