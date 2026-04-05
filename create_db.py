import sqlite3

conn = sqlite3.connect("pothole.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    email TEXT,
    phone TEXT,
    password TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pothole (
    pothole_id INTEGER PRIMARY KEY AUTOINCREMENT,
    latitude REAL,
    longitude REAL,
    severity TEXT,
    image_path TEXT,
    detected_time TEXT,
    detected_date TEXT,
    address TEXT,
    pincode TEXT
)
""")

# Migrate existing tables if columns are missing
for col, typ in [("email","TEXT"),("phone","TEXT")]:
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(users)").fetchall()]
    if col not in cols:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")

for col, typ in [("address","TEXT"),("pincode","TEXT")]:
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(pothole)").fetchall()]
    if col not in cols:
        cursor.execute(f"ALTER TABLE pothole ADD COLUMN {col} {typ}")

conn.commit()
conn.close()
print("Database ready!")
