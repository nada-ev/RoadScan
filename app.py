from flask import Flask, request, jsonify, render_template, redirect, url_for, session, Response
import sqlite3
import hashlib
import os
import cv2
from ultralytics import YOLO
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)
app.secret_key = "pothole_secret_key"

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "static/outputs"
POTHOLE_IMAGES_FOLDER = "pothole_images"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(POTHOLE_IMAGES_FOLDER, exist_ok=True)

model = YOLO("best.pt")

# Gmail credentials
GMAIL_USER     = "roadpothole123@gmail.com"
GMAIL_PASSWORD = "rmmfpstzzjgmcbrl"

def send_email(to_email, subject, body):
    try:
        msg = MIMEText(body, 'plain')
        msg['Subject'] = subject
        msg['From']    = GMAIL_USER
        msg['To']      = to_email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASSWORD)
            smtp.sendmail(GMAIL_USER, to_email, msg.as_string())
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Email error: {e}")

def notify_admin(username, pothole_count, severity_summary, latitude, longitude):
    import threading
    subject = f"RoadScan — {pothole_count} Pothole(s) Reported by {username}"
    body = (
        f"A new pothole report has been submitted.\n\n"
        f"Reported by : {username}\n"
        f"Location    : {latitude}, {longitude}\n"
        f"Potholes    : {pothole_count}\n"
        f"Breakdown   : {severity_summary}\n\n"
        f"View and manage this report in the admin dashboard:\n"
        f"http://127.0.0.1:5000/admin_dashboard\n\n"
        f"— RoadScan System"
    )
    threading.Thread(target=send_email, args=(GMAIL_USER, subject, body), daemon=True).start()

# ---------- DB ----------
def get_db():
    return sqlite3.connect("pothole.db")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ---------- HOME ----------
@app.route('/')
def home():
    return render_template('index.html')

# ---------- DASHBOARD ----------
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# ---------- REGISTER ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    data = request.get_json(force=True)

    username = (data.get("username") or "").strip()
    email    = (data.get("email") or "").strip()
    phone    = (data.get("phone") or "").strip()
    password = (data.get("password") or "")

    import re
    if not username or len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters."})
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return jsonify({"error": "Username can only contain letters, numbers and underscores."})
    if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return jsonify({"error": "Enter a valid email address."})
    if not phone or not re.match(r'^\d{10}$', phone):
        return jsonify({"error": "Enter a valid 10-digit phone number."})
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."})

    password = hash_password(password)

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO users (username, email, phone, password)
        VALUES (?, ?, ?, ?)
        """, (username, email, phone, password))

        conn.commit()
        conn.close()

        return jsonify({"message": "Registered successfully"})

    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"})
    except Exception as e:
        return jsonify({"error": str(e)})

# ---------- LOGIN (unified for user + admin) ----------
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True)
    username = data.get("username", "").strip()
    raw_password = data.get("password", "").strip()

    conn = get_db()
    cursor = conn.cursor()

    # Check admin first (plain text password)
    cursor.execute("SELECT * FROM admin WHERE username=? AND password=?", (username, raw_password))
    admin = cursor.fetchone()
    if admin:
        conn.close()
        session["admin_id"] = admin[0]
        session["admin_username"] = admin[1]
        return jsonify({"success": True, "role": "admin"})

    # Check regular user (hashed password)
    hashed = hash_password(raw_password)
    cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (username, hashed))
    user = cursor.fetchone()
    conn.close()

    if user:
        session["user_id"] = user[0]
        session["username"] = user[1]
        return jsonify({"success": True, "role": "user"})

    return jsonify({"success": False})

# ---------- ADMIN: GET USER DETAILS ----------
@app.route('/admin/user/<username>')
def admin_user_details(username):
    conn = get_db()
    cursor = conn.cursor()
    user = cursor.execute(
        "SELECT id, username, email, phone FROM users WHERE username=?", (username,)
    ).fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    uid, uname, email, phone = user
    reports = cursor.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN r.status='Pending'  THEN 1 ELSE 0 END) as pending,
               SUM(CASE WHEN r.status='Fixed'    THEN 1 ELSE 0 END) as fixed,
               SUM(CASE WHEN r.status='Reviewed' THEN 1 ELSE 0 END) as reviewed
        FROM report r WHERE r.user_id=?
    """, (uid,)).fetchone()
    conn.close()
    return jsonify({
        "username": uname, "email": email, "phone": phone,
        "total": reports[0] or 0, "pending": reports[1] or 0,
        "fixed": reports[2] or 0, "reviewed": reports[3] or 0
    })


# ---------- ADMIN DASHBOARD ----------
@app.route('/admin_dashboard')
def admin_dashboard():
    if not session.get("admin_id"):
        return redirect(url_for('home'))
    return render_template('admin_dashboard.html')

# ---------- SERVE POTHOLE IMAGES ----------
@app.route('/pothole_img/<filename>')
def pothole_img(filename):
    from flask import send_from_directory
    return send_from_directory(POTHOLE_IMAGES_FOLDER, filename)

# ---------- ADMIN: GET ALL POTHOLES ----------
@app.route('/admin/potholes')
def admin_potholes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.pothole_id, p.latitude, p.longitude, p.severity,
               p.image_path, p.detected_time, p.detected_date,
               r.report_id, r.status, u.username,
               COALESCE(p.address,'') as address, COALESCE(p.pincode,'') as pincode
        FROM pothole p
        LEFT JOIN report r ON p.pothole_id = r.pothole_id
        LEFT JOIN users u ON r.user_id = u.id
        ORDER BY CASE p.severity
            WHEN 'Severe'   THEN 1
            WHEN 'Moderate' THEN 2
            WHEN 'Minor'    THEN 3
            ELSE 4 END
    """)
    rows = cursor.fetchall()
    conn.close()
    keys = ["pothole_id","latitude","longitude","severity","image_path",
            "detected_time","detected_date","report_id","status","username","address","pincode"]
    result = []
    for row in rows:
        d = dict(zip(keys, row))
        d["image_filename"] = os.path.basename(d["image_path"].replace("\\", "/")) if d["image_path"] else ""
        result.append(d)
    return jsonify(result)

# ---------- ADMIN: UPDATE STATUS ----------
@app.route('/admin/update_status', methods=['POST'])
def update_status():
    data = request.get_json(force=True)
    report_id = data.get("report_id")
    status    = data.get("status")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE report SET status=? WHERE report_id=?", (status, report_id))
    conn.commit()

    if status == "Fixed":
        # get user email and pothole details
        row = cursor.execute("""
            SELECT u.email, u.username, p.severity, p.detected_date, p.latitude, p.longitude
            FROM report r
            JOIN users u ON r.user_id = u.id
            JOIN pothole p ON r.pothole_id = p.pothole_id
            WHERE r.report_id = ?
        """, (report_id,)).fetchone()

        if row:
            email, username, severity, date, lat, lon = row
            subject = "RoadScan — Your reported pothole has been Fixed!"
            body = (
                f"Hello {username},\n\n"
                f"Great news! A pothole you reported has been marked as Fixed.\n\n"
                f"Details:\n"
                f"  Severity  : {severity}\n"
                f"  Reported  : {date}\n"
                f"  Location  : {lat}, {lon}\n\n"
                f"Thank you for helping keep our roads safe.\n\n"
                f"— RoadScan Team"
            )
            import threading
            threading.Thread(target=send_email, args=(email, subject, body), daemon=True).start()

    conn.close()
    return jsonify({"success": True})

@app.route('/camera_detect', methods=['POST'])
def camera_detect():
    import base64, numpy as np
    data = request.get_json(force=True)
    img_data  = data.get('frame', '')
    latitude  = data.get('latitude', 0.0)
    longitude = data.get('longitude', 0.0)
    user_id   = session.get('user_id', 1)

    if ',' in img_data:
        img_data = img_data.split(',')[1]
    np_arr = np.frombuffer(base64.b64decode(img_data), np.uint8)
    frame  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({'error': 'Invalid frame'}), 400

    seen_key = f"cam_seen_{user_id}"
    seen_boxes = session.get(seen_key, [])
    # total_saved tracks how many unique potholes saved this session
    total_key = f"cam_total_{user_id}"
    total_saved = session.get(total_key, 0)

    def iou(a, b):
        ax1,ay1,ax2,ay2 = a; bx1,by1,bx2,by2 = b
        ix1,iy1 = max(ax1,bx1), max(ay1,by1)
        ix2,iy2 = min(ax2,bx2), min(ay2,by2)
        inter = max(0, ix2-ix1) * max(0, iy2-iy1)
        if inter == 0: return 0.0
        ua = (ax2-ax1)*(ay2-ay1)+(bx2-bx1)*(by2-by1)-inter
        return inter/ua if ua > 0 else 0.0

    results = model(frame, verbose=False)
    new_count = 0
    conn = get_db()
    cursor = conn.cursor()

    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])

            # confidence threshold
            if conf < 0.55:
                continue

            # road surface validation — reject skin, paper, bright/colourful regions
            crop = frame[max(0,y1):y2, max(0,x1):x2]
            if not is_road_surface(crop):
                continue

            current_box = [x1, y1, x2, y2]
            size_ratio = ((x2-x1)*(y2-y1)) / (frame.shape[0]*frame.shape[1])
            distance_factor = ((y1+y2)/2) / frame.shape[0]
            adjusted_size = size_ratio * (1 + distance_factor)

            if adjusted_size < 0.015:   severity, color = 'Minor',    (0,255,0)
            elif adjusted_size < 0.04:  severity, color = 'Moderate', (0,255,255)
            else:                       severity, color = 'Severe',   (0,0,255)

            # draw always
            cv2.rectangle(frame, (x1,y1),(x2,y2), color, 2)
            cv2.putText(frame, f'{severity} {conf:.2f}', (x1, y1-8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            # save only if not duplicate
            if any(iou(current_box, sb) > 0.4 for sb in seen_boxes):
                continue

            seen_boxes.append(current_box)
            new_count += 1
            total_saved += 1

            img_filename = f"cam_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
            img_path = os.path.join(POTHOLE_IMAGES_FOLDER, img_filename)
            cv2.imwrite(img_path, frame[y1:y2, x1:x2])

            now = datetime.now()
            cursor.execute("""INSERT INTO pothole (latitude,longitude,severity,image_path,detected_time,detected_date)
                VALUES (?,?,?,?,?,?)""", (latitude, longitude, severity, img_path,
                now.strftime('%H:%M:%S'), now.strftime('%Y-%m-%d')))
            cursor.execute("""INSERT INTO report (user_id,pothole_id,date,status) VALUES (?,?,?,?)""",
                (user_id, cursor.lastrowid, now.strftime('%Y-%m-%d'), 'Pending'))
            conn.commit()

    session[seen_key]  = seen_boxes[-50:]
    session[total_key] = total_saved
    session.modified   = True
    conn.close()

    if new_count > 0:
        uconn = get_db()
        urow = uconn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        uconn.close()
        uname = urow[0] if urow else f"User#{user_id}"
        notify_admin(uname, new_count, "detected via live camera", latitude, longitude)

    # blue count on frame = total_saved (matches what frontend accumulates)
    cv2.putText(frame, f'Potholes: {total_saved}', (10,30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,0,0), 2)

    # store annotated frame for video compilation
    frames_key = f"cam_frames_{user_id}"
    if frames_key not in cam_frame_store:
        cam_frame_store[frames_key] = []
    cam_frame_store[frames_key].append(frame.copy())

    _, buf = cv2.imencode('.jpg', frame)
    encoded = base64.b64encode(buf).decode('utf-8')
    return jsonify({'frame': 'data:image/jpeg;base64,' + encoded, 'count': new_count, 'total': total_saved})


@app.route('/camera_reset', methods=['POST'])
def camera_reset():
    user_id = session.get('user_id', 1)
    session.pop(f"cam_seen_{user_id}", None)
    session.pop(f"cam_total_{user_id}", None)
    cam_frame_store.pop(f"cam_frames_{user_id}", None)
    return jsonify({"success": True})


@app.route('/camera_stop', methods=['POST'])
def camera_stop():
    """Compile stored frames into a video and return its URL."""
    user_id = session.get('user_id', 1)
    frames_key = f"cam_frames_{user_id}"
    frames = cam_frame_store.pop(frames_key, [])

    if not frames:
        return jsonify({"video_url": None, "total": session.get(f"cam_total_{user_id}", 0)})

    h, w = frames[0].shape[:2]
    out_filename = f"cam_output_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4"
    out_path = os.path.join(OUTPUT_FOLDER, out_filename)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(out_path, fourcc, 10.0, (w, h))
    for f in frames:
        writer.write(f)
    writer.release()

    total = session.get(f"cam_total_{user_id}", 0)
    return jsonify({"video_url": f"/static/outputs/{out_filename}", "total": total})


def is_road_surface(crop):
    """Returns True only if the cropped region looks like a road/ground surface.
    Road surfaces are typically dark, low-saturation, and have texture (std dev > threshold).
    White/light/colorful images (text, logos, etc.) are rejected."""
    import numpy as np
    if crop is None or crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mean_val   = float(np.mean(hsv[:,:,2]))   # brightness (V channel)
    mean_sat   = float(np.mean(hsv[:,:,1]))   # saturation (S channel)
    std_val    = float(np.std(hsv[:,:,2]))    # texture roughness

    # Road/pothole: not too bright, low saturation, some texture
    # Relaxed thresholds — water-filled potholes can be bright/reflective
    if mean_val > 200:   return False   # extremely bright — paper/white background
    if mean_sat > 100:   return False   # very colourful — not road
    if std_val < 6:      return False   # completely uniform — no texture at all
    return True


@app.route('/detect', methods=['POST'])
def detect():
    import numpy as np
    file = request.files['file']
    address = request.form.get('address', 'Not specified')
    pincode = request.form.get('pincode', '')
    location_str = f"{address} {pincode}".strip()

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    results = model(filepath)
    img = cv2.imread(filepath)

    severity_counts = {"Severe": 0, "Moderate": 0, "Minor": 0}
    CONF_THRESHOLD = 0.5

    for r in results:
        for box in r.boxes:
            conf = float(box.conf[0])
            if conf < CONF_THRESHOLD:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])

            # validate the crop looks like a road surface
            crop = img[max(0,y1):y2, max(0,x1):x2]
            if not is_road_surface(crop):
                continue

            box_area = (x2-x1)*(y2-y1)
            frame_area = img.shape[0]*img.shape[1]
            size_ratio = box_area / frame_area
            distance_factor = ((y1+y2)/2) / img.shape[0]
            adjusted_size = size_ratio * (1 + distance_factor)

            if adjusted_size < 0.015:
                severity = "Minor"
                color = (0, 200, 0)
            elif adjusted_size < 0.04:
                severity = "Moderate"
                color = (0, 200, 255)
            else:
                severity = "Severe"
                color = (0, 0, 255)
            severity_counts[severity] += 1

            # save to DB
            now = datetime.now()
            img_filename = f"img_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
            img_path = os.path.join(POTHOLE_IMAGES_FOLDER, img_filename)
            cv2.imwrite(img_path, crop)
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""INSERT INTO pothole (latitude,longitude,severity,image_path,detected_time,detected_date,address,pincode)
                VALUES (?,?,?,?,?,?,?,?)""",
                (0, 0, severity, img_path, now.strftime('%H:%M:%S'), now.strftime('%Y-%m-%d'), address, pincode))
            pothole_id = cur.lastrowid
            user_id = session.get("user_id", 1)
            cur.execute("INSERT INTO report (user_id,pothole_id,date,status) VALUES (?,?,?,?)",
                (user_id, pothole_id, now.strftime('%Y-%m-%d'), 'Pending'))
            conn.commit()
            conn.close()

            cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
            cv2.putText(img, f"{severity} {conf:.2f}", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)

    output_path = os.path.join(OUTPUT_FOLDER, file.filename)

    total = sum(severity_counts.values())
    if total == 0:
        cv2.imwrite(output_path, img)
        return jsonify({"no_pothole": True})

    # draw total count on image
    cv2.putText(img, f"Total Potholes: {total}", (10, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 0, 0), 3)
    cv2.imwrite(output_path, img)

    user_id = session.get("user_id", 1)
    conn = get_db()
    urow = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    uname = urow[0] if urow else f"User#{user_id}"
    summary = ", ".join(f"{k}: {v}" for k, v in severity_counts.items() if v > 0)
    notify_admin(uname, total, summary, location_str, "")

    return jsonify({"image_url": f"/static/outputs/{file.filename}?t={int(datetime.now().timestamp())}", "total": total, "summary": summary})


import threading
import hashlib as _hashlib
import hmac
import time

# Shared state per session (simple single-user approach)
stream_state = {}

def generate_admin_token():
    """Generate a time-limited HMAC token valid for 1 hour."""
    expires = int(time.time()) + 3600
    raw = f"{expires}:{app.secret_key}"
    sig = hmac.new(app.secret_key.encode(), raw.encode(), _hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"

def verify_admin_token(token):
    try:
        expires_str, sig = token.split('.', 1)
        expires = int(expires_str)
        if time.time() > expires:
            return False
        raw = f"{expires}:{app.secret_key}"
        expected = hmac.new(app.secret_key.encode(), raw.encode(), _hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ---------- ADMIN AUTO-LOGIN VIA EMAIL LINK ----------
@app.route('/admin_login_token')
def admin_login_token():
    token = request.args.get('token', '')
    if not verify_admin_token(token):
        return redirect(url_for('home'))
    conn = get_db()
    admin = conn.execute("SELECT * FROM admin LIMIT 1").fetchone()
    conn.close()
    if admin:
        session["admin_id"] = admin[0]
        session["admin_username"] = admin[1]
    return redirect(url_for('admin_dashboard'))

# In-memory store for camera annotated frames
cam_frame_store = {}


def process_video_stream(input_path, output_path, user_id, latitude, longitude, state_key):
    """Runs in a background thread, processes frames and stores them for streaming."""
    # latitude here is actually location_str when called from detect_video
    cap = cv2.VideoCapture(input_path)
    frame_width = int(cap.get(3))
    frame_height = int(cap.get(4))
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (frame_width, frame_height))

    conn = get_db()
    cursor = conn.cursor()

    counted_ids = set()
    pothole_count = 0
    severity_counts = {"Severe": 0, "Moderate": 0, "Minor": 0}

    stream_state[state_key] = {"frame": None, "done": False, "pothole_count": 0, "severity_counts": {}}

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        results = model.track(frame, persist=True, verbose=False)

        for result in results:
            boxes = result.boxes
            if boxes.id is None:
                continue

            for box, track_id in zip(boxes.xyxy, boxes.id):
                x1, y1, x2, y2 = map(int, box)
                track_id = int(track_id)
                conf = float(boxes.conf[list(boxes.id).index(track_id)]) if boxes.conf is not None else 1.0
                if conf < 0.5:
                    continue

                box_area = (x2 - x1) * (y2 - y1)
                frame_area = frame.shape[0] * frame.shape[1]
                size_ratio = box_area / frame_area
                distance_factor = ((y1 + y2) / 2) / frame.shape[0]
                adjusted_size = size_ratio * (1 + distance_factor)

                if adjusted_size < 0.015:
                    severity, color = "Minor", (0, 255, 0)
                elif adjusted_size < 0.04:
                    severity, color = "Moderate", (0, 255, 255)
                else:
                    severity, color = "Severe", (0, 0, 255)

                if track_id not in counted_ids:
                    counted_ids.add(track_id)

                    crop = frame[max(0,y1):y2, max(0,x1):x2]
                    if not is_road_surface(crop):
                        continue

                    pothole_count += 1
                    severity_counts[severity] = severity_counts.get(severity, 0) + 1

                    img_path = os.path.join(POTHOLE_IMAGES_FOLDER, f"pothole_{track_id}_{pothole_count}.jpg")
                    cv2.imwrite(img_path, frame[y1:y2, x1:x2])

                    now = datetime.now()
                    date = now.strftime("%Y-%m-%d")
                    time_str = now.strftime("%H:%M:%S")

                    cursor.execute("""
                        INSERT INTO pothole (latitude, longitude, severity, image_path, detected_time, detected_date)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (latitude, longitude, severity, img_path, time_str, date))
                    pothole_id = cursor.lastrowid

                    cursor.execute("""
                        INSERT INTO report (user_id, pothole_id, date, status)
                        VALUES (?, ?, ?, ?)
                    """, (user_id, pothole_id, date, "Pending"))
                    conn.commit()

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"Pothole {track_id} | {severity}", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.putText(frame, f"Total Potholes: {pothole_count}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 3)

        out.write(frame)
        stream_state[state_key]["frame"] = frame.copy()
        stream_state[state_key]["pothole_count"] = pothole_count
        stream_state[state_key]["severity_counts"] = severity_counts

    cap.release()
    out.release()
    conn.close()
    stream_state[state_key]["done"] = True

    if pothole_count > 0:
        # build severity summary
        sev = stream_state[state_key].get("severity_counts", {})
        summary = ", ".join(f"{k}: {v}" for k, v in sev.items()) or "N/A"
        # get username
        uconn = get_db()
        urow = uconn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        uconn.close()
        uname = urow[0] if urow else f"User#{user_id}"
        notify_admin(uname, pothole_count, summary, latitude, longitude)


# ---------- VIDEO UPLOAD (starts processing thread) ----------
@app.route('/detect_video', methods=['POST'])
def detect_video():
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    user_id = session.get("user_id", 1)
    state_key = f"user_{user_id}"

    address = request.form.get('address', 'Not specified')
    pincode = request.form.get('pincode', '')
    location_str = f"{address} {pincode}".strip()

    input_path = os.path.join(UPLOAD_FOLDER, file.filename)
    output_filename = "detected_" + file.filename
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)
    file.save(input_path)

    session["output_filename"] = output_filename

    t = threading.Thread(target=process_video_stream, args=(
        input_path, output_path, user_id, location_str, "", state_key
    ))
    t.daemon = True
    t.start()

    return jsonify({"stream_url": f"/video_feed/{state_key}"})


# ---------- MJPEG STREAM ----------
@app.route('/video_feed/<state_key>')
def video_feed(state_key):
    def generate():
        import time
        while True:
            state = stream_state.get(state_key)
            if state is None:
                time.sleep(0.05)
                continue

            frame = state.get("frame")
            if frame is not None:
                _, buffer = cv2.imencode('.jpg', frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' +
                       buffer.tobytes() + b'\r\n')

            if state.get("done") and frame is not None:
                break

            time.sleep(0.03)

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


# ---------- STREAM STATUS ----------
@app.route('/stream_status/<state_key>')
def stream_status(state_key):
    state = stream_state.get(state_key, {})
    return jsonify({
        "done": state.get("done", False),
        "pothole_count": state.get("pothole_count", 0),
        "video_url": f"/static/outputs/{session.get('output_filename', '')}"
    })


if __name__ == "__main__":
    app.run(debug=True)