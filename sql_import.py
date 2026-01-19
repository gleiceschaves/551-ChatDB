import os
import psycopg2
from dotenv import load_dotenv

# Load env
load_dotenv()

# DB config
PG_USER = os.getenv("POSTGRES_USER")
PG_PASS = os.getenv("POSTGRES_PASS")
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = os.getenv("POSTGRES_PORT", "5432")
PG_DB = "healthcare"

conn = psycopg2.connect(
    dbname=PG_DB,
    user=PG_USER,
    password=PG_PASS,
    host=PG_HOST,
    port=PG_PORT
)
conn.autocommit = True
cur = conn.cursor()

# Step 1: Run schema
print("Running CREATE_TABLES.sql...")
with open("./data/CREATE_TABLES.sql", "r") as f:
    cur.execute(f.read())
conn.commit()

with open('./data/patients.csv', 'r') as f:
    cur.copy_expert("COPY patients FROM STDIN DELIMITER ',' CSV HEADER;", f)

with open('./data/hospitals.csv', 'r') as f:
    cur.copy_expert("COPY hospitals FROM STDIN DELIMITER ',' CSV HEADER;", f)

with open('./data/doctors.csv', 'r') as f:
    cur.copy_expert("COPY doctors FROM STDIN DELIMITER ',' CSV HEADER;", f)

with open('./data/admissions.csv', 'r') as f:
    cur.copy_expert("""
        COPY admissions(patient_id, doctor_id, hospital_id, date_of_admission,
                       discharge_date, admission_type, room_number, billing_amount,
                       medication, test_results)
        FROM STDIN DELIMITER ',' CSV HEADER;
    """, f)
    
# 🛠️ Fix sequences
cur.execute("SELECT setval('patients_patient_id_seq', COALESCE(MAX(patient_id), 1)) FROM patients;")
cur.execute("SELECT setval('hospitals_hospital_id_seq', COALESCE(MAX(hospital_id), 1)) FROM hospitals;")
cur.execute("SELECT setval('doctors_doctor_id_seq', COALESCE(MAX(doctor_id), 1)) FROM doctors;")
cur.execute("SELECT setval('admissions_admission_id_seq', COALESCE(MAX(admission_id), 1)) FROM admissions;")

conn.commit()
cur.close()
conn.close()
print("✅ PostgreSQL import completed.")
