from flask import Flask, render_template, request, redirect, url_for
import mysql.connector
import os
import uuid
import webbrowser
from threading import Timer
from werkzeug.utils import secure_filename
from datetime import datetime
import face_recognition
import cv2
import time

app = Flask(__name__)

# Upload folder
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# MySQL connection
def get_db_connection():
    try:
        return mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="mygallery",
            port=3306
        )
    except mysql.connector.Error as err:
        print(f"❌ Database Connection Error: {err}")
        return None

# Get face encoding from stored image
def get_user_encoding(email):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT password_image FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
    user = cursor.fetchone()
    cursor.close()
    db.close()

    if not user:
        return None

    image_path = os.path.join(UPLOAD_FOLDER, user['password_image'])
    if not os.path.exists(image_path):
        return None

    image = face_recognition.load_image_file(image_path)
    encodings = face_recognition.face_encodings(image)
    return encodings[0] if encodings else None

# Face verification with head movement check (20 sec timeout)
def detect_and_verify_face_with_head_movement(known_encoding, movement_time=20):
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        return False

    start_time = time.time()
    face_match_found = False
    x_positions = []

    while time.time() - start_time < movement_time:
        ret, frame = camera.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        if face_encodings:
            for i, face_encoding in enumerate(face_encodings):
                matches = face_recognition.compare_faces([known_encoding], face_encoding, tolerance=0.5)
                if any(matches):
                    face_match_found = True
                    top, right, bottom, left = face_locations[i]
                    face_center_x = (left + right) // 2
                    x_positions.append(face_center_x)

        cv2.imshow("Head Movement Verification - Move your head horizontally", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    camera.release()
    cv2.destroyAllWindows()

    if not face_match_found:
        return False

    if len(x_positions) < 2:
        return False

    movement = max(x_positions) - min(x_positions)
    return movement > 40  # Threshold for horizontal head movement

# Homepage
@app.route('/')
def home():
    return render_template('Homepage.html')

# Registration page
@app.route('/register_page')
def register_page():
    return render_template('register.html')

# Register user
@app.route('/register', methods=['POST'])
def register_user():
    name = request.form.get('name')
    email = request.form.get('email').strip().lower()
    password_image = request.files.get('password-image')

    if not name or not email or not password_image:
        return "❌ Error: Missing input data"

    filename = f"{uuid.uuid4()}_{secure_filename(password_image.filename)}"
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    password_image.save(image_path)

    db = get_db_connection()
    if not db:
        return "❌ Error: Could not connect to the database."
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
        existing_user = cursor.fetchone()

        if existing_user:
            return f"❌ Error: Email '{email}' is already registered! <a href='/register_page'>Try Again</a>"

        sql = "INSERT INTO users (name, email, password_image) VALUES (%s, %s, %s)"
        values = (name, email, filename)
        cursor.execute(sql, values)
        db.commit()
        user_id = cursor.lastrowid

    except mysql.connector.Error as err:
        print(f"❌ MySQL Error: {err}")
        return f"Database Error: {err}"
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('profile', user_id=user_id))

# Login page
@app.route('/login')
def login_page():
    return render_template('login.html')

# Login action (face verification + head movement)
@app.route('/login', methods=['POST'])
def login_user():
    name = request.form.get('name')
    email = request.form.get('email').strip().lower()

    if not name or not email:
        return "❌ Missing login details."

    user_encoding = get_user_encoding(email)
    if user_encoding is None:
        return "❌ User not found or image encoding failed."

    verified = detect_and_verify_face_with_head_movement(user_encoding, movement_time=20)
    if verified:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
        user = cursor.fetchone()
        cursor.close()
        db.close()
        return redirect(url_for('profile', user_id=user['id']))
    else:
        return "❌ Unauthorized Face or No Head Movement Detected. Login Failed!"

# Profile page
@app.route('/profile/<int:user_id>')
def profile(user_id):
    db = get_db_connection()
    if not db:
        return "❌ Error: Could not connect to the database."
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) AS count FROM images WHERE user_id = %s", (user_id,))
    image_count = cursor.fetchone()["count"]

    cursor.execute("SELECT filename FROM images WHERE user_id = %s", (user_id,))
    uploaded_images = cursor.fetchall()

    cursor.close()
    db.close()

    if not user:
        return "❌ User Not Found!"

    return render_template('Profile.html', user=user, image_count=image_count, uploaded_images=uploaded_images)

# Upload profile image
@app.route('/upload_profile_image/<int:user_id>', methods=['POST'])
def upload_profile_image(user_id):
    profile_image = request.files.get('profile-image')
    if not profile_image:
        return "❌ No image uploaded!"

    filename = f"{uuid.uuid4()}_{secure_filename(profile_image.filename)}"
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    profile_image.save(image_path)

    db = get_db_connection()
    if not db:
        return "❌ Error: Could not connect to the database."
    cursor = db.cursor()

    try:
        cursor.execute("UPDATE users SET profile_image = %s WHERE id = %s", (filename, user_id))
        db.commit()
    except mysql.connector.Error as err:
        print(f"❌ MySQL Error: {err}")
        return f"Database Error: {err}"
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('profile', user_id=user_id))

# Upload gallery image
@app.route('/upload_image/<int:user_id>', methods=['POST'])
def upload_image(user_id):
    image = request.files.get('gallery-image')
    if not image:
        return "❌ No image selected"

    filename = f"{uuid.uuid4()}_{secure_filename(image.filename)}"
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    image.save(image_path)

    upload_date = datetime.now()

    db = get_db_connection()
    if not db:
        return "❌ DB error"
    cursor = db.cursor()

    try:
        cursor.execute(
            "INSERT INTO images (user_id, filename, upload_date) VALUES (%s, %s, %s)",
            (user_id, filename, upload_date)
        )
        db.commit()
    except mysql.connector.Error as err:
        return f"MySQL Error: {err}"
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('profile', user_id=user_id))

# Show gallery images
@app.route('/show_images/<int:user_id>')
def show_images(user_id):
    db = get_db_connection()
    if not db:
        return "❌ Error: Could not connect to the database."
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT filename, upload_date 
        FROM images 
        WHERE user_id = %s 
        ORDER BY upload_date DESC
    """, (user_id,))
    uploaded_images = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template('ShowImages.html', uploaded_images=uploaded_images, user_id=user_id)

# Auto open browser
def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000/")

# Only open browser once
if __name__ == '__main__':
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        Timer(1, open_browser).start()
    app.run(debug=True)
