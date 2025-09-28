# 🔺 ChatDB

**ChatDB**  is an intelligent, schema-aware natural language interface (NLI) that supports both relational (PostgreSQL) and document-based (MongoDB) databases. Built using LangChain, OpenAI and Streamlit, it allows users to interact with real databases using plain English—for querying, updating, inserting, and deleting data.

USC DSCI 551 – Spring 2025

Test here: https://chatdb.gleicechaves.com
---

##  Features

- 🔎 **Explore schemas and collections**
- 🤖 **Natural language executable queries** → SQL / Mongo
- 🛠️ **Database Manipulation - Insert, update, delete** across databases
- 🔄 **Cascade-aware modifications**
- 💬 **Streamlit-based chatbot UI**
- 🧠 LLM-Powered Engine **LangChain** + **OpenAI** 

---

## 🚀 Setup Instructions

### 1. Clone the repo and install dependencies

```bash
git clone https://github.com/yourusername/chatdb.git
cd chatdb
```

Install the required packages using pip:

```bash
pip install -r requirements.txt
```
or 
```bash
pip install \
    streamlit \
    streamlit-chat \
    python-dotenv \
    psycopg2-binary \
    sqlalchemy \
    pymongo \
    langchain \
    langchain-openai \
    langchain-community \
    pydantic \
    pandas
```

### 2. Set up environment variables

Create a `.env` file in the root directory based on the `.env.template` file. Fill in the required variables. 
You might need to get API keys from OpenAI and Langsmith if you want to use them.

### 3. Prepare the DBs. 

### Data 
- Healthcare Database (Public healthcare datasets adapted from Kagle)
- Tables: Hospitals, doctors, patients, admissions
- Refugees Database (Synthetic data generated using CHATGPT)
- Collections: refugee_cases, refugee_exams, nested_psychosocial_assessment_data


#### **PostgreSQL**
- Create a database named `healthcare`
- Run the following to import schema and data
    ```bash
    python sql_import.py
    ```

This will:
- Run data/CREATE_TABLES.sql to create tables
- Import data from:
  - data/hospitals.csv
  - data/doctors.csv
  - data/patients.csv
  - data/admissions.csv
- Reset Serial counters for the ID columns

#### **MongoDB**
- Run the following to import schema and data
    ```bash
    python mongo_import.py
    ```
This will:
- Import JSONs into the refugees database:
  - data/refugee_cases.json
  - data/refugee_exams.json
  - data/nested_psychosocial_assessment_data.json

### 4. Run the Streamlit app
To start the Streamlit app, run the following command in your terminal:
    ```bash
    streamlit run app.py
    ```

To run the app in test mode. Use the file Test_Cases_for_ChatDB.csv and add prompts in the prompt column. Set the `TEST_MODE` environment variable to `true` in your `.env` file. Then run the app as follows:

    ```bash
    python app.py
    ```

### 5. Open your browser and navigate to `http://localhost:8501`
You should see the ChatDB interface.    
Type your queries in the input box and hit enter to see the results.

## Example Queries
- List all available databases.
- What tables are in the healthcare database?
- Show me the schema for the patients table.
- Show a few rows from the admissions table.
- What collections are in the refugees database?
- What fields are in the refugee_cases collection?
- Show me the structure of the refugee_exams documents.
- Give me a sample document from refugee_exams.
- Show one refugee case record.
- Show 5 patients from the patients table.
- List all patients over age 60.
- Find all hospitals named “Cook PLC”.
- Show hospitals with average billing above $20,000 in 2024.
- Show admissions for patient ID 1.
- Show the average billing amount by hospital in 2024.
- What are the top 5 most expensive admissions?
- Get 10 doctors but skip the first 5.
- List patient names and hospital names for all admissions.
- Show the doctor name and their hospital for each admission. 
- Give me a query that joins doctor name and patient name using the admissions table.
- Add a patient named Carlos, age 45, with blood type O+.
- Add a new hospital called New Life Medical.
- Add a refugee case with applicant 'Ali' and status 'pending'.
- Add the required exams : blood test and rm for case id 101
- Update hospital 1’s name to “Hope Hospital”.
- Change Carlos’s age to 46.
- Update Ali’s age to 30 in the applicant data.
- Change the status of refugee case 999 to “approved”. 
- Add more exams to refugee case 999.
- show me case id I78303
- Delete the hospital with ID 3.
- Remove the patient named John Doe.
- Delete refugee case with ID 999.
- Delete refugee case 999 and all its related exams.
- Show refugee cases along with their required exams.
- Count how many refugee cases are in each status.
- Show the 5 refugee cases with the most support services.
- Show refugee cases that have no support services listed.

## Architecture Overview
- LangChain: Prompt + tool orchestration
- OpenAI : LLM for reasoning and generation. 
- SQLAlchemy / PyMongo: DB execution layer - Connect to the the databases
- Streamlit: Frontend chat interface
- LangSmith: Tracing and debugging. 

## Folder Structure
```
chatdb/
│
├── app.py                      # main Streamlit app
├── sql_import.py               # schema + csv importer
├── mongo_import.py             # mongo json importer
├── global_db_state.json        # loaded DB schema. generated by the app
├── data/                       # CSVs, SQL, and JSON files
├── .env.template               # environment variable config
├── requirements.txt
└── README.md
```

### 👩‍💻 Author
- Gleice Chaves

### 6. References 

https://python.langchain.com/docs/concepts/lcel/ - LCEL

https://platform.openai.com/docs/guides/rate-limits - OpenAi Rate Limits

https://www.marktechpost.com/2025/04/15/from-logic-to-confusion-mit-researchers-show-how-simple-prompt-tweaks-derail-llm-reasoning/ - Study Prompt Sensitivity 

https://www.udemy.com/course/langchain/?couponCode=LEARNNOWPLANS - Practical Video course to understand LangChain basics, agents, tools and RAG

https://www.promptingguide.ai/ - Best Pratices for designing effective prompts 

https://python.langchain.com/docs/introduction/ - Langchain Documentation

https://docs.smith.langchain.com/ - LangSmith Documentation

https://medium.com/@eugenesh4work/what-are-embeddings-and-how-do-it-work-b35af573b59e - Explanation of vector embbeddings 

https://python.langchain.com/v0.1/docs/modules/model_io/output_parsers/ - Output Parser

https://www.youtube.com/watch?v=qFGdygmYgto - Langchain Tutorial 
