# ======================= Imports ============================
import base64
import uuid
import streamlit as st 
from streamlit_chat import message
import os, json, logging
import psycopg2
from sqlalchemy import create_engine, text
from pymongo import MongoClient
from langchain_openai import ChatOpenAI
from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.prompts import PromptTemplate
from langchain_community.chat_message_histories import ChatMessageHistory
import uuid
from langchain_core.output_parsers import JsonOutputParser
from typing import List, Dict, Any, Union
from langchain.tools import StructuredTool
import re
from dotenv import load_dotenv
import pandas as pd
import time
from datetime import date, datetime, timedelta, time
from decimal import Decimal

load_dotenv()

# ======================= LOGGING & LANGSMITH ============================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")#detailed logging

LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false")
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

os.environ["LANGSMITH_TRACING"] = LANGSMITH_TRACING
os.environ["LANGSMITH_API_KEY"] = LANGSMITH_API_KEY
os.environ["LANGSMITH_ENDPOINT"] = LANGSMITH_ENDPOINT
os.environ["LANGSMITH_PROJECT"] = LANGSMITH_PROJECT


# ======================= CONFIG ============================
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
GLOBAL_STATE_FILE = "global_db_state.json"

POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASS = os.getenv("POSTGRES_PASS")
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")

IS_MONGO_AUTH = os.getenv("IS_MONGO_AUTH", "false").lower() == "true"
MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASS = os.getenv("MONGO_PASS")
MONGO_HOST = os.getenv("MONGO_HOST")
MONGO_PORT = os.getenv("MONGO_PORT")
MONGO_ADMIN_DB = os.getenv("MONGO_DB")

TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"

if(IS_MONGO_AUTH):
    MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASS}@{MONGO_HOST}:{MONGO_PORT}/{MONGO_ADMIN_DB}?authSource=admin"
else:
    MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/"

DBS_TO_IGNORE = ["postgres", "admin", "config", "local", POSTGRES_USER]
    
# ======================= GLOBAL DB STATE ============================
def load_global_state():
    if not os.path.exists(GLOBAL_STATE_FILE):
        return []
    with open(GLOBAL_STATE_FILE, "r") as f:
        return json.load(f)

def safe_jsonify(obj):
    # Dates & times
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return obj.total_seconds()

    # Numerics
    if isinstance(obj, Decimal):
        return float(obj)

    # IDs / misc
    if isinstance(obj, uuid.UUID):
        return str(obj)

    # Binary-ish
    if isinstance(obj, (bytes, bytearray, memoryview)):
        b = bytes(obj)  # handles memoryview/bytearray too
        try:
            # Try utf-8 text first
            return b.decode("utf-8")
        except UnicodeDecodeError:
            # Fall back to base64 string so JSON is valid and readable if needed
            return "base64:" + base64.b64encode(b).decode("ascii")

    # Sets/tuples (occasionally show up in metadata)
    if isinstance(obj, (set, tuple)):
        return list(obj)

    # Last resort: stringify unknown types
    return str(obj)


def save_global_state(state):
    with open(GLOBAL_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=safe_jsonify)

def safe_jsonify(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.decode()
    return obj

def update_global_state():
    logging.info("Updating global DB state from live databases...")
    updated_state = []

    # PostgreSQL
    try:
        postgres_conn = psycopg2.connect(
            host=POSTGRES_HOST,
            user=POSTGRES_USER,
            password=POSTGRES_PASS,
            port=POSTGRES_PORT
        )
        cursor = postgres_conn.cursor()
        cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
        dbs = [r[0] for r in cursor.fetchall()]

        for db in dbs:
            if db in DBS_TO_IGNORE:
                continue
            logging.info(f"Scanning PostgreSQL DB: {db}")

            engine = create_engine(
                f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASS}@{POSTGRES_HOST}:{POSTGRES_PORT}/{db}"
            )

            with engine.connect() as conn:
                tables = conn.execute(text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )).fetchall()

                table_info = {}

                for table in tables:
                    tname = table[0]

                    # Get Columns
                    cols = conn.execute(text(
                        f"SELECT column_name, data_type, is_nullable, column_default "
                        f"FROM information_schema.columns WHERE table_name = '{tname}'"
                    )).fetchall()

                    col_schema = ", ".join([f"{col[0]} ({col[1]})" for col in cols])
                    not_null_fields = [col[0] for col in cols if col[2] == 'NO']
                    defaults = {col[0]: col[3] for col in cols if col[3] is not None}

                    # Get Primary Keys
                    pk_query = f"""
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = '{tname}'::regclass AND i.indisprimary;
                    """
                    pk_result = conn.execute(text(pk_query)).fetchall()
                    primary_keys = [row[0] for row in pk_result]

                    # Get Unique Constraints
                    unique_query = """
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'UNIQUE' AND tc.table_name = :table
                    """
                    unique_result = conn.execute(text(unique_query), {"table": tname}).fetchall()
                    unique_fields = [row[0] for row in unique_result]

                    # Get Foreign Keys
                    fk_query = """
                    SELECT
                        kcu.column_name,
                        ccu.table_name AS foreign_table_name,
                        ccu.column_name AS foreign_column_name
                    FROM
                        information_schema.table_constraints AS tc
                        JOIN information_schema.key_column_usage AS kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                        JOIN information_schema.constraint_column_usage AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = :table
                    """
                    fk_result = conn.execute(text(fk_query), {"table": tname}).fetchall()
                    foreign_keys = [
                        {"column": row[0], "ref_table": row[1], "ref_column": row[2]}
                        for row in fk_result
                    ]

                    # Get Row Count
                    try:
                        row_count = conn.execute(text(f"SELECT COUNT(*) FROM {tname}")).scalar()
                    except Exception as e:
                        row_count = None
                        logging.warning(f"Couldn't count rows for {tname}: {e}")

                    # Get Sample Rows
                    try:
                        sample_rows = conn.execute(text(f"SELECT * FROM {tname} LIMIT 3")).fetchall()
                        sample_rows = [
                            {k: safe_jsonify(v) for k, v in row._mapping.items()}
                            for row in sample_rows
                        ]
                    except Exception as e:
                        sample_rows = []
                        logging.warning(f"Couldn't fetch samples from {tname}: {e}")
                    # Detect Categorical Values (for low-cardinality text fields)
                    categorical_fields = {}
                    for colname, datatype in [(col[0], col[1]) for col in cols]:
                        if datatype in ("character varying", "varchar", "text"):
                            try:
                                uniq_vals = conn.execute(text(
                                    f"SELECT DISTINCT {colname} FROM {tname} WHERE {colname} IS NOT NULL LIMIT 20"
                                )).fetchall()
                                uniq_vals = [r[0] for r in uniq_vals if r[0] is not None]
                                if len(uniq_vals) <= 10 and uniq_vals:
                                    categorical_fields[colname] = uniq_vals
                            except Exception as e:
                                logging.warning(f"Couldn't fetch unique values for {tname}.{colname}: {e}")

                    # Final Table Info
                    table_info[tname] = {
                        "schema": col_schema,
                        "primary_key": primary_keys,
                        "foreign_keys": foreign_keys,
                        "unique_constraints": unique_fields,
                        "not_null_fields": not_null_fields,
                        "defaults": defaults,
                        "row_count": row_count,
                        "sample_rows": sample_rows,
                        "categorical_values": categorical_fields,
                        "description": "",  # Placeholder for future optional comments
                    }

                updated_state.append({
                    "db": db,
                    "type": "sql",
                    "tables": table_info
                })
                
    except Exception as e:
        logging.error("PostgreSQL error: %s", e)

    # MongoDB
    try:
        mongo_client = MongoClient(MONGO_URI)
        for db_name in mongo_client.list_database_names():
            if db_name in DBS_TO_IGNORE:
                logging.info(f"Skipping ignored DB: {db_name}")
                continue
            logging.info(f"Scanning MongoDB: {db_name}")
            db = mongo_client[db_name]
            collections = db.list_collection_names()
            col_info = {}

            for col in collections:
                collection_obj = db[col]
                sample_doc = collection_obj.find_one()
                if not sample_doc:
                    schema = {}
                else:
                    schema = {k: type(v).__name__ for k, v in sample_doc.items()}

                # Document count
                try:
                    doc_count = collection_obj.estimated_document_count()
                except Exception as e:
                    doc_count = None
                    logging.warning(f"Couldn't count documents in {col}: {e}")

                # Indexes
                try:
                    indexes = collection_obj.index_information()
                    indexed_fields = []
                    for idx in indexes.values():
                        indexed_fields.extend([field[0] for field in idx['key']])
                    indexed_fields = list(set(indexed_fields))
                except Exception as e:
                    indexed_fields = []
                    logging.warning(f"Couldn't fetch indexes for {col}: {e}")

                col_info[col] = {
                    "schema": schema,
                    "doc_count": doc_count,
                    "indexes": indexed_fields,
                    "description": "",  # Optional, if you have manual descriptions
                }

            updated_state.append({
                "db": db_name,
                "type": "nosql",
                "tables": col_info
            })

    except Exception as e:
        logging.error("MongoDB error: %s", e)

    save_global_state(updated_state)
    logging.info("✅ Global DB state updated")
    return updated_state

sql_engines = None
mongo_clients = None

# ========================= PROMPTS ============================

CLASSIFICATION_PROMPT = PromptTemplate.from_template(
    """
    You are a classifier. Based on the user's input, identify the type of action the user wants to take into exactly one of the following  categories:
    - list_dbs: The user wants to know what databases are available.
    - list_tables: The user wants to know what tables are available in a specific database.
    - show_schema: The user wants to know the schema of a specific table or a collection in a specific database.
    - general_question: The user is asking a general question unrelated to the databases.
    - explore_data_using_natural_language: The user wants to explore data using natural language queries for a specifc table/collection.
    - insert_data: The user wants to insert data into a specific table or collection.
    - update_data: The user wants to update data in a specific table or collection.
    - delete_data: The user wants to delete data from a specific table or collection.

    If they mention a specific DB or table/collection, extract those too. We use the key table and collection interchangeably.
    
    Look at the user’s question and choose:

    {question}
    
    ------
    Here is the list of available databases, their tables/collections, schemas, primary keys, foreign keys, indexes, and other constraints:
    {dbs}

    Return your response as a JSON object with keys:
    - query_type
    - db 
    - dbType
    - table (if any. key is table for both table or collection)
    """
)

GENERATE_SQL_QUERY = PromptTemplate.from_template(
    """
    You are an assistant that generates VALID SQL queries based on user input.

    You will be given:
    - The user's input
    - The available databases with their tables, columns, primary keys, foreign keys, not null fields, unique constraints, and default values.
    - Row counts for tables.
    
    Instructions:
    - Always prefer JOINs based on foreign keys when data needs to be combined.
    - Ensure required columns (NOT NULL fields) are included when inserting or updating.
    - Use primary keys for precise WHERE clauses if possible.
    - Respect default values if the user does not specify them.
    - Do not use database name in the query . For Example: Do not use Select * from db_name.table_name; instead use Select * from table_name;
    
    ### Available DBs:
    {db_list_str}
    ### USER INPUT:
    {user_input}

    Return your answer as JSON with keys:
    - db (the database to query)
    - query (VALID SQL query to run)
    """
)

GENERATE_MONGO_QUERY = PromptTemplate.from_template(
    """
    You are an assistant that generates VALID MongoDB aggregation pipelines based on user input.

    You will be given:
    - The user's input
    - The available MongoDB databases, collections, their fields (and types), indexed fields, and approximate document counts.
    
    Instructions:
    - Always $match on indexed fields first if possible.
    - If joining collections, use $lookup when a shared field exists (e.g., case_id).
    
    ### Available DBs:
    {db_list_str}
    ### USER INPUT:
    {user_input}

    Return your answer as JSON with keys:
    - db (the database to query)
    - collection (the collection to query)
    - pipeline (VALID MongoDB aggregation pipeline)
    """
)

REACT_PROMPT = PromptTemplate.from_template(
    """
    You are an intelligent assistant with access to structured tools.

    Use this strict format:

    Question: the input question
    Thought: what you want to do next
    Action: the tool name, must be one of [{tool_names}]
    Action Input: a valid JSON object with the correct arguments
    Observation: the result of the tool
    ... (repeat Thought/Action/Observation as needed)
    Thought: I now know the final answer
    Final Answer: your final answer to the original question

    TOOLS:
    {tools}
    
    Available DBs and Schema:
    {dbs}

    NOTES:
    - NEVER pass empty `{{}}` unless the tool requires no input.
    - Format your Action Input as valid JSON like `{{ "db_name": "a_valid_db_name" }}`.
    - Ensure the Action Input includes all required fields for the tool.

    Chat History:
    {chat_history}

    Begin!

    Question: {input}
    {agent_scratchpad}
"""
)

GENERATE_SQL_INSERT = PromptTemplate.from_template("""
You are an assistant that generates valid SQL INSERT statements based on user intent.

Context Provided:
- Available databases with tables, columns, primary keys, foreign keys, not null fields, default values.

Instructions:
- Always include NOT NULL columns unless they have a default.
- Prefer inserting fields that match the schema exactly.
- If inserting into related tables (e.g., parent and child tables), generate cascading inserts.
- Use sensible default values if missing.
- DO NOT MAKE UP VALUES. Only use values that are present in the user input.

Available Tables and Metadata:
{global_db_state}

Target Database:
{db_name}

USER Request (natural language):
{user_json}

Respond ONLY as a JSON object:
- "queries": list of valid SQL INSERT statements (e.g., ["INSERT INTO patients (...)", "INSERT INTO admissions (...)"])
""")

GENERATE_SQL_UPDATE = PromptTemplate.from_template("""
You are an assistant that generates valid SQL UPDATE statements.

Context Provided:
- Available databases with tables, columns, primary keys, foreign keys, not null fields, defaults.

Instructions:
- Use WHERE clauses based on primary keys or unique constraints whenever possible.
- Validate that updated fields exist in the table schema.
- Ensure only mutable (non-primary key) fields are updated unless explicitly allowed.

Available Tables and Metadata:
{global_db_state}

Target Database:
{db_name}
Target Table:
{table_name}

Update Criteria (WHERE conditions):
{criteria_json}

New Values to Set:
{update_json}

Respond ONLY as a JSON object:
- "queries": list of valid SQL UPDATE statements
""")

GENERATE_MONGO_INSERT = PromptTemplate.from_template("""
You are an assistant that generates valid MongoDB insert operations based on user intent.

Context Provided:
- Available databases with collections, fields (and types), indexed fields, document counts.
- Metadata includes field types, required fields, indexes.

Instructions:
- Only generate fields present in the collection schema unless the user explicitly adds new ones.
- Ensure required fields (frequently present) are included.
- If inserting into multiple collections (cascading insert), generate a separate insert for each.

Available Collections and Metadata:
{global_db_state}

Target Database:
{db_name}

USER Request (natural language):
{user_json}

Respond ONLY as a JSON object:
- "inserts": list of dict("collection": str, "document": dict)
""")

GENERATE_MONGO_UPDATE = PromptTemplate.from_template("""
You are an assistant that generates valid MongoDB update operations.

Context Provided:
- Available databases with collections, fields, indexed fields, and document counts.

Instructions:
- Always $match on indexed fields when updating for best performance.
- Only update fields that exist in the schema unless user explicitly adds new ones.
- If updating across multiple collections, generate separate update operations.

Available Collections and Metadata:
{global_db_state}

Target Database:
{db_name}
Target Collection:
{collection_name}

Update Criteria (Match):
{criteria_json}

New Values to Set:
{update_json}

Respond ONLY as a JSON object:
- "updates": list of dict("collection": str, "filter": dict, "update": dict)
""")

GENERATE_SQL_DELETE = PromptTemplate.from_template("""
You are an assistant that generates valid SQL DELETE statements.

Context Provided:
- Available databases with tables, primary keys, foreign keys, and row counts.

Instructions:
- Always delete dependent child records first if foreign key relations exist (cascading delete).
- Prefer WHERE clauses using primary keys or indexed fields.
- Never delete full tables unless explicitly instructed.

Available Tables and Metadata:
{global_db_state}

Target Database:
{db_name}
Target Table:
{table_name}

User Request:
{user_json}

Respond ONLY as a JSON object:
- "queries": list of valid SQL DELETE statements, in correct cascade order
""")

GENERATE_MONGO_DELETE = PromptTemplate.from_template("""
You are an assistant that generates valid MongoDB delete operations.

Context Provided:
- Available databases with collections, fields, indexed fields, and document counts.

Instructions:
- Always match using indexed fields where possible for faster deletion.
- If deletion should cascade (e.g., delete related documents in other collections), generate multiple deletes.
- Never delete full collections unless explicitly instructed.

Available Collections and Metadata:
{global_db_state}

Target Database:
{db_name}
Target Collection:
{collection_name}

User Request:
{user_json}

Respond ONLY as a JSON object:
- "deletes": list of dict("collection": str, "filter": dict)
""")

QUERY_VALIDATION_PROMPT = PromptTemplate.from_template("""
You are a query validator and fixer.

Given a SQL or MongoDB query generated from natural language, validate if the query will likelHAHAHy succeed.

Context Provided:
- Available database metadata: tables, columns, primary keys, foreign keys, indexes, not null fields, document counts.

Validation Instructions:
- Confirm if table/collection names are correct.
- Confirm if fields exist and match the types.
- Confirm if NOT NULL fields are respected in INSERT/UPDATE. Ignore if NOT NULL fields have defaults like auto generate.
- Confirm if JOINs use valid foreign key relations (for SQL).
- Confirm if indexed fields are used properly (for MongoDB match).
- Do not be excessively strict; allow for some flexibility in field names and types. Some fields/values may be valid even if not present in samples.

If you detect a problem:
- Suggest a corrected user input if needed (as `suggested_fix`).
- Attempt to auto-correct and provide a full corrected query as `fixed_query` (same format as input: valid SQL or MongoDB JSON).

If everything is valid:
- Leave suggested_fix and fixed_query empty.

Available Databases and Metadata:
{global_db_state}

Generated Query or Document:
{generated_query}

Respond ONLY as a JSON object:
- "is_safe": true if the query is TECHNICALLY SAFE TO RUN. false if QUERY WILL NOT RUN or violates schema.
- "reason": explain briefly why it may fail (empty if safe)
- "suggested_fix": improved natural language prompt if needed (optional)
- "fixed_query": An array of corrected queries ready to run (optional)
""")


# ======================= TOOLS ============================

def custom_parse_input(raw_input: Union[str, dict], required_fields: List[str]) -> Dict[str, Any]:
    if isinstance(raw_input, str):
        try:
            raw_input = json.loads(raw_input)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON input: {e}")

    if not isinstance(raw_input, dict):
        raise ValueError("Input must be a dictionary.")

    missing_fields = [field for field in required_fields if field not in raw_input]
    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

    return raw_input

def list_dbs() -> str:
    return json.dumps([db["db"] for db in global_db_state])

def list_tables(input: Union[str, dict]) -> str:
    parsed = custom_parse_input(input, required_fields=["db_name"])
    db_name = parsed["db_name"].strip().lower()
    db = next((d for d in global_db_state if d["db"].lower() == db_name), None)
    return json.dumps(list(db["tables"].keys())) if db else f"Database '{db_name}' not found."

def get_table_schema(input: Union[str, dict]) -> str:
    parsed = custom_parse_input(input, required_fields=["db_name", "table_name"])
    db_name = parsed["db_name"]
    table_name = parsed["table_name"]
    db = next((d for d in global_db_state if d["db"] == db_name), None)
    if not db:
        return f"Database '{db_name}' not found."
    if table_name not in db["tables"]:
        return f"Table '{table_name}' not found in database '{db_name}'."
    return db["tables"][table_name]["schema"]

def run_sql(input: Union[str, dict]) -> Any:
    parsed = custom_parse_input(input, required_fields=["db_name", "query"])
    db_name = parsed["db_name"]
    query = parsed["query"]
    engine = sql_engines.get(db_name)
    if not engine:
        return f"SQL DB '{db_name}' not found."
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query)).fetchall()
            ret_results_string = ""
            for row in result:
                ret_results_string += str(row) + "\n"
            return ret_results_string.strip()
    except Exception as e:
        return f"SQL Error: {e}"

def run_mongo(input: Union[str, dict]) -> Any:
    parsed = custom_parse_input(input, required_fields=["db_name", "collection", "pipeline"])
    db_name = parsed["db_name"]
    collection = parsed["collection"]
    pipeline = parsed["pipeline"]
    try:
        db = mongo_clients[db_name]
        a = db[collection].aggregate(pipeline)
        # convert <pymongo.synchronous.command_cursor.CommandCursor object to list. ensure to remove ObjectId from the results 
        b = []
        for doc in a:
            doc = dict(doc)
            if "_id" in doc:
                del doc["_id"]
            b.append(doc)
        return str(b)
    except Exception as e:
        return f"Mongo Error: {e}"
    
def execute_sql_multi_query(db_name: str, queries: List[str]) -> str:
    engine = sql_engines.get(db_name)
    if not engine:
        return f"SQL DB '{db_name}' not found."
    try:
        with engine.connect() as conn:
            for query in queries:
                conn.execute(text(query))
            conn.commit()
        return "✅ SQL cascade operation successful."
    except Exception as e:
        return f"❌ SQL Error: {e}"

def execute_mongo_cascade_delete(db_name: str, deletes: List[Dict[str, Any]]) -> str:
    try:
        db = mongo_clients[db_name]
        for op in deletes:
            db[op["collection"]].delete_many(op["filter"])
        return "✅ Mongo Cascade Delete successful."
    except Exception as e:
        return f"❌ Mongo Delete Error: {e}"

def execute_mongo_cascade_insert(db_name: str, inserts: List[Dict[str, Any]]) -> str:
    try:
        db = mongo_clients[db_name]
        for op in inserts:
            db[op["collection"]].insert_one(op["document"])
        return "✅ Mongo Cascade Insert successful."
    except Exception as e:
        return f"❌ Mongo Insert Error: {e}"

def execute_mongo_cascade_update(db_name: str, updates: List[Dict[str, Any]]) -> str:
    try:
        db = mongo_clients[db_name]
        for op in updates:
            db[op["collection"]].update_many(op["filter"], op["update"])
        return "✅ Mongo Cascade Update successful."
    except Exception as e:
        return f"❌ Mongo Update Error: {e}"

available_tools = [
    StructuredTool.from_function(
        func=list_dbs,
        name="list_dbs_tool",
        description="List all available databases.",
    ),
    StructuredTool.from_function(
        func=list_tables,
        name="list_tables_tool",
        description="List all tables in a specific database.",
    ),
    StructuredTool.from_function(
        func=get_table_schema,
        name="get_table_schema_tool",
        description="Get the schema of a specific table in a database.",
    ),
    StructuredTool.from_function(
        func=run_sql,
        name="run_sql_tool",
        description="Execute an SQL query on a specific database. Requires db_name and query.",
    ),
    StructuredTool.from_function(
        func=run_mongo,
        name="run_mongo_tool",
        description="Execute a MongoDB aggregation pipeline. requires db_name, collection, and pipeline.",
    ),
]


# ========================= CHAINS ============================
def get_memory(session_id: str):
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = {}
    if session_id not in st.session_state.chat_history:
        st.session_state.chat_history[session_id] = ChatMessageHistory()
    return st.session_state.chat_history[session_id]

llm = ChatOpenAI(
    model_name=OPENAI_MODEL, openai_api_key=OPENAI_API_KEY
)

classification_chain = RunnableWithMessageHistory(
    CLASSIFICATION_PROMPT | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="question",
    history_messages_key="history"
)

sql_query_generate_chain = RunnableWithMessageHistory(
    GENERATE_SQL_QUERY | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="user_input",
    history_messages_key="history"
)

mongo_query_generate_chain = RunnableWithMessageHistory(
    GENERATE_MONGO_QUERY | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="user_input",
    history_messages_key="history"
)

generate_sql_insert_chain = RunnableWithMessageHistory(
    GENERATE_SQL_INSERT | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="user_json",
    history_messages_key="history"
)

generate_mongo_insert_chain = RunnableWithMessageHistory(
    GENERATE_MONGO_INSERT | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="user_json",
    history_messages_key="history"
)

generate_sql_update_chain = RunnableWithMessageHistory(
    GENERATE_SQL_UPDATE | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="criteria_json",
    history_messages_key="history"
)

generate_mongo_update_chain = RunnableWithMessageHistory(
    GENERATE_MONGO_UPDATE | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="criteria_json",
    history_messages_key="history"
)

query_validation_chain = RunnableWithMessageHistory(
    QUERY_VALIDATION_PROMPT | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="generated_query",
    history_messages_key="history"
)

generate_sql_delete_chain = RunnableWithMessageHistory(
    GENERATE_SQL_DELETE | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="user_json",
    history_messages_key="history"
)

generate_mongo_delete_chain = RunnableWithMessageHistory(
    GENERATE_MONGO_DELETE | llm | JsonOutputParser(),
    lambda session_id: get_memory(session_id),
    input_messages_key="user_json",
    history_messages_key="history"
)

react_agent = create_react_agent(
    llm=llm,
    tools=available_tools,
    prompt=REACT_PROMPT
)

agent_executor = AgentExecutor.from_agent_and_tools(
    agent=react_agent,
    tools=available_tools,
    verbose=True,
    handle_parsing_errors=True,
)

agent_chain_with_memory = RunnableWithMessageHistory(
    agent_executor,
    lambda session_id: get_memory(session_id),
    input_messages_key="input",
    history_messages_key="chat_history" 
)

# ========================= GENERATE LOGIC ============================

def generate_response(input_text: str) -> str:
    session_id = st.session_state.session_id
    logging.info(f"User SESSION: {session_id}")
    logging.info(f"User input: {input_text}")

    try:
        # Step 1: Classify the query
        classification_result = classification_chain.invoke(
            {
                "question": input_text,
                "dbs": json.dumps(global_db_state),
            },
            config={"configurable": {"session_id": session_id}}
        )
        logging.debug(f"Classification result: {classification_result}")

        query_type = classification_result["query_type"]
        db_type = classification_result.get("dbType")
        db = classification_result.get("db")
        table = classification_result.get("table")

        def validate_and_maybe_fix(generated_query, execute_func, execute_args):
            """Helper to validate query and execute either original or fixed version."""
            validation_result = query_validation_chain.invoke(
                {
                    "generated_query": generated_query,
                    "global_db_state": json.dumps(global_db_state, indent=2)
                },
                config={"configurable": {"session_id": session_id}}
            )
            print(validation_result)
            if validation_result["is_safe"]:
                return execute_func(*execute_args)
            elif validation_result.get("fixed_query"):
                return execute_func(db, validation_result["fixed_query"])
            else:
                return f"⚠️ Validation failed: {validation_result['reason']}\n\n👉 Try: *{validation_result['suggested_fix']}*"

        # ----------- EXPLORE -----------
        if query_type == "explore_data_using_natural_language":
            if db_type == "sql":
                query_gen = sql_query_generate_chain.invoke(
                    {
                        "user_input": input_text,
                        "db_list_str": json.dumps(global_db_state),
                    },
                    config={"configurable": {"session_id": session_id}}
                )
                query = query_gen["query"]
                raw_result = run_sql({"db_name": query_gen["db"], "query": query})
                return f"**Generated SQL Query:**\n```sql\n{query}\n```\n\n**Result:**\n{raw_result}"

            elif db_type == "nosql":
                query_gen = mongo_query_generate_chain.invoke(
                    {
                        "user_input": input_text,
                        "db_list_str": json.dumps(global_db_state),
                    },
                    config={"configurable": {"session_id": session_id}}
                )
                pipeline = query_gen["pipeline"]
                raw_result = run_mongo({
                    "db_name": query_gen["db"],
                    "collection": query_gen["collection"],
                    "pipeline": pipeline
                })
                return f"**Generated MongoDB Pipeline:**\n```json\n{json.dumps(pipeline, indent=2)}\n```\n\n**Result:**\n{raw_result}"

        # ----------- INSERT -----------
        elif query_type == "insert_data":
            if db_type == "sql":
                insert_gen = generate_sql_insert_chain.invoke({
                    "db_name": db,
                    "table_name": table,
                    "user_json": input_text,
                    "global_db_state": json.dumps(global_db_state, indent=2)
                }, config={"configurable": {"session_id": session_id}})
                
                queries = insert_gen.get("queries", [])
                sql_query_str = "\n".join(queries)
                
                result = validate_and_maybe_fix(
                    sql_query_str,
                    execute_sql_multi_query,
                    (db, queries)
                )
                return f"**Generated SQL Insert:**\n```sql\n{sql_query_str}\n```\n\n**Result:**\n{result}"

            elif db_type == "nosql":
                insert_gen = generate_mongo_insert_chain.invoke({
                    "db_name": db,
                    "collection_name": table,
                    "user_json": input_text,
                    "global_db_state": json.dumps(global_db_state, indent=2)
                }, config={"configurable": {"session_id": session_id}})

                inserts = insert_gen.get("inserts", {})
                mongo_doc_str = json.dumps(inserts, indent=2)

                result = validate_and_maybe_fix(
                    mongo_doc_str,
                    execute_mongo_cascade_insert,
                    (db, inserts)
                )
                return f"**Generated Mongo Insert:**\n```json\n{mongo_doc_str}\n```\n\n**Result:**\n{result}"

        # ----------- UPDATE -----------
        elif query_type == "update_data":
            if db_type == "sql":
                update_gen = generate_sql_update_chain.invoke({
                    "db_name": db,
                    "table_name": table,
                    "criteria_json": input_text,
                    "update_json": input_text,
                    "global_db_state": json.dumps(global_db_state, indent=2)
                }, config={"configurable": {"session_id": session_id}})

                queries = update_gen.get("queries", [])
                sql_query_str = "\n".join(queries)

                result = validate_and_maybe_fix(
                    sql_query_str,
                    execute_sql_multi_query,
                    (db, queries)
                )
                return f"**Generated SQL Update:**\n```sql\n{sql_query_str}\n```\n\n**Result:**\n{result}"

            elif db_type == "nosql":
                update_gen = generate_mongo_update_chain.invoke({
                    "db_name": db,
                    "collection_name": table,
                    "criteria_json": input_text,
                    "update_json": input_text,
                    "global_db_state": json.dumps(global_db_state, indent=2)
                }, config={"configurable": {"session_id": session_id}})

                updates = update_gen.get("updates", [])
                mongo_doc_str = json.dumps(updates, indent=2)

                result = validate_and_maybe_fix(
                    mongo_doc_str,
                    execute_mongo_cascade_update,
                    (db, updates)
                )
                return f"**Generated Mongo Update:**\n```json\n{mongo_doc_str}\n```\n\n**Result:**\n{result}"

        # ----------- DELETE -----------
        elif query_type == "delete_data":
            if db_type == "sql":
                delete_gen = generate_sql_delete_chain.invoke({
                    "db_name": db,
                    "table_name": table,
                    "user_json": input_text,
                    "global_db_state": json.dumps(global_db_state, indent=2)
                }, config={"configurable": {"session_id": session_id}})
                
                queries = delete_gen.get("queries", [])
                sql_query_str = "\n".join(queries)

                result = validate_and_maybe_fix(
                    sql_query_str,
                    execute_sql_multi_query,
                    (db, queries)
                )
                return f"**Generated SQL Delete:**\n```sql\n{sql_query_str}\n```\n\n**Result:**\n{result}"

            elif db_type == "nosql":
                delete_gen = generate_mongo_delete_chain.invoke({
                    "db_name": db,
                    "collection_name": table,
                    "user_json": input_text,
                    "global_db_state": json.dumps(global_db_state, indent=2)
                }, config={"configurable": {"session_id": session_id}})

                deletes = delete_gen.get("deletes", [])
                mongo_doc_str = json.dumps(deletes, indent=2)

                result = validate_and_maybe_fix(
                    mongo_doc_str,
                    execute_mongo_cascade_delete,
                    (db, deletes)
                )
                return f"**Generated Mongo Delete:**\n```json\n{mongo_doc_str}\n```\n\n**Result:**\n{result}"

        # ----------- FALLBACK to agent if not matching any type -----------
        result = agent_chain_with_memory.invoke(
            {"input": input_text, "dbs": json.dumps(global_db_state)},
            config={"configurable": {"session_id": session_id}},
        )

        if isinstance(result, dict) and "output" in result:
            return result["output"]
        return str(result)

    except Exception as e:
        logging.exception("Error in generate_response()")
        return f"⚠️ Sorry, I couldn't process your request. Error: {e}"


# ======================= STREAMLIT ============================

if __name__ == "__main__":
    # Load DB state once
    global_db_state = update_global_state()
    sql_engines = {
        db["db"]: create_engine(f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASS}@{POSTGRES_HOST}:{POSTGRES_PORT}/{db['db']}")
        for db in global_db_state if db["type"] == "sql"
    }
    mongo_clients = MongoClient(MONGO_URI)
        
    if TEST_MODE:
        logging.info("✅ TEST MODE ACTIVE: Running test cases...")
        
        test_file = "Test_Cases_for_ChatDB.csv"
        df = pd.read_csv(test_file)

        # Ensure required columns exist
        required_cols = ["category", "prompt", "expected_result", "status", "actual_result"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = ""

        for idx, row in df.iterrows():
            try:
                logging.info(f"Processing Test Case {idx+1}: {row['prompt']}")
                st.session_state.session_id = str(uuid.uuid4())  # create a fresh session for each prompt

                result = generate_response(row["prompt"])

                df.at[idx, "actual_result"] = result
                df.at[idx, "status"] = "success"
                df.to_csv("Test_Cases_for_ChatDB.csv", index=False)
                
                time.sleep(2)  # sleep for 2 seconds to avoid API rate limits
            except Exception as e:
                logging.error(f"❌ Error in Test Case {idx+1}: {e}")
                df.at[idx, "status"] = "failed"
                df.at[idx, "actual_result"] = str(e)
                time.sleep(2)

        # Save updated results
        df.to_csv("Test_Cases_for_ChatDB_w_results.csv", index=False)
        logging.info("✅ All test cases processed. Results saved to Test_Cases_for_ChatDB.csv")
    else:
        st.set_page_config(
            page_title="ChatDB",
            page_icon="🔺",
            layout="centered",
            initial_sidebar_state="collapsed",
        )

        # Load memory and chat state
        if "messages" not in st.session_state:
            st.session_state.messages = []
        if "session_id" not in st.session_state:
            st.session_state.session_id = str(uuid.uuid4())

        st.title("🔺 CHAT DB")
        st.subheader("Chat with your Databases!")

        user_input = st.chat_input("Ask something about your databases...")
        if user_input:
            st.session_state.messages.append({"role": "user", "content": user_input})
            full_response = generate_response(user_input)

            MAX_DISPLAY_LENGTH = 1000 

            if len(full_response) > MAX_DISPLAY_LENGTH:
                # Only show first 1000 chars in chat bubble
                summary = full_response[:MAX_DISPLAY_LENGTH] + "...\n\n(Full result available for download)"
                st.session_state.messages.append({
                    "role": "bot",
                    "content": {
                        "summary": summary,
                        "full_content": full_response
                    }
                })
            else:
                st.session_state.messages.append({"role": "bot", "content": full_response})


            # # Always display full response in UI
            # st.markdown(full_response)

        for i, msg in enumerate(st.session_state.messages):
            role = msg["role"]
            content = msg["content"]

            # Special logic for bot messages that are too large
            if role == "bot" and isinstance(content, dict):
                # We stored both summary and full_content
                summary = content.get("summary", "")
                full_content = content.get("full_content", "")
                display_text = summary  # show only summary in chat bubble
            else:
                # Normal small messages
                display_text = content
                full_content = None

            message(display_text, is_user=(role == "user"), key=f"{role}_{i}")

            # If large content exists, offer a download button
            if full_content:
                st.download_button(
                    label="⬇️ Download Full Message",
                    data=full_content,
                    file_name=f"full_response_{i}.txt",
                    mime="text/plain",
                    key=f"download_btn_{i}"
                )
