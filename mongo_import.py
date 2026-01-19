import os
import json
from pymongo import MongoClient
from dotenv import load_dotenv

# Load .env vars
load_dotenv()

# MongoDB connection config
mongo_uri = f"mongodb://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASS')}@{os.getenv('MONGO_HOST')}:{os.getenv('MONGO_PORT')}/?authSource={os.getenv('MONGO_DB')}" \
    if os.getenv("IS_MONGO_AUTH", "false").lower() == "true" else \
    f"mongodb://{os.getenv('MONGO_HOST')}:{os.getenv('MONGO_PORT')}"

client = MongoClient(mongo_uri)
db = client["refugees"]

# Files to collections mapping
files = {
    "refugee_cases.json": "refugee_cases",
    "refugee_exams.json": "refugee_exams",
    "nested_psychosocial_assessment_data.json": "nested_psychosocial_assessment_data"
}

for filename, collection_name in files.items():
    path = os.path.join("data", filename)
    print(f"Inserting into {collection_name} from {path}")
    with open(path, "r") as f:
        data = json.load(f)
        if isinstance(data, dict):
            data = [data]
        elif isinstance(data, list):
            pass
        else:
            raise Exception(f"Unsupported JSON structure in {filename}")

    db[collection_name].delete_many({})
    db[collection_name].insert_many(data)

print("✅ MongoDB import completed.")
