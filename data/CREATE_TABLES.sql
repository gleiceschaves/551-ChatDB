
CREATE TABLE patients (
    patient_id SERIAL PRIMARY KEY,
    name VARCHAR,
    age INT,
    gender VARCHAR,
    blood_type VARCHAR,
    medical_condition VARCHAR,
    insurance_provider VARCHAR
);

CREATE TABLE hospitals (
    hospital_id SERIAL PRIMARY KEY,
    hospital_name VARCHAR
);


CREATE TABLE doctors (
    doctor_id SERIAL,
    doctor_name VARCHAR,
    hospital_id INT,
    PRIMARY KEY (doctor_id, hospital_id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id)
);


DROP TABLE IF EXISTS admissions;

CREATE TABLE admissions (
    patient_id INT,
    doctor_id INT,
    hospital_id INT,
    date_of_admission DATE,
    discharge_date DATE,
    admission_type VARCHAR,
    room_number INT,
    billing_amount DECIMAL,
    medication VARCHAR,
    test_results VARCHAR,
    admission_id SERIAL PRIMARY KEY,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id),
    FOREIGN KEY (doctor_id, hospital_id) REFERENCES doctors(doctor_id, hospital_id)
);
