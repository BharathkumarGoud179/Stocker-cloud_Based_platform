import boto3
import os
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8001")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "dummy")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy")

dynamodb = boto3.resource(
    "dynamodb",
    region_name=AWS_REGION,
    endpoint_url=DYNAMODB_ENDPOINT,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def create_table_if_not_exists(table_name, key_name):
    existing_tables = [table.name for table in dynamodb.tables.all()]
    if table_name not in existing_tables:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": key_name, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key_name, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST"
        )
        print(f"{table_name} created")
    else:
        print(f"{table_name} already exists")

create_table_if_not_exists("stocker_users", "user_id")
create_table_if_not_exists("stocker_portfolio", "portfolio_id")
create_table_if_not_exists("stocker_transactions", "transaction_id")

print("DynamoDB setup complete")