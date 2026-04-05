import sqlite3

conn = sqlite3.connect("pothole.db")
cursor = conn.cursor()

# USERS TABLE
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    email TEXT,
    phone TEXT,
    password TEXT
)
""")

# ADMIN TABLE
cursor.execute("""
CREATE TABLE IF NOT EXISTS admin (
    admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    password TEXT
)
""")

# Insert default admin
cursor.execute("""
INSERT OR IGNORE INTO admin (admin_id, username, password)
VALUES (1, 'admin@gmail.com', 'Admin123')
""")

# POTHOLE TABLE
cursor.execute("""
CREATE TABLE IF NOT EXISTS pothole (
    pothole_id INTEGER PRIMARY KEY AUTOINCREMENT,
    latitude REAL,
    longitude REAL,
    severity TEXT,
    image_path TEXT,
    detected_time TEXT,
    detected_date TEXT
)
""")

# REPORT TABLE
cursor.execute("""
CREATE TABLE IF NOT EXISTS report (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    pothole_id INTEGER,
    date TEXT,
    status TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(pothole_id) REFERENCES pothole(pothole_id)
)
""")

conn.commit()
conn.close()

print("Database created successfully!")