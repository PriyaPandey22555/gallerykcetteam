import face_recognition
import cv2
import numpy as np
from flask import Flask, render_template, request, redirect, url_for
import mysql.connector
import os
import uuid

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# MySQL connection
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="mygallery"
    )

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

def detect_and_verify_face(known_encoding):
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        return False

    result = False
    while True:
        ret, frame = camera.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        for face_encoding in face_encodings:
            matches = face_recognition.compare_faces([known_encoding], face_encoding, tolerance=0.5)
            if any(matches):  # ✅ Use any() to safely evaluate the list of booleans
                result = True
                break

        cv2.imshow("Verifying Face", frame)
        if result or cv2.waitKey(1) & 0xFF == ord('q'):
            break

    camera.release()
    cv2.destroyAllWindows()
    return result

@app.route('/')
def home():
    return render_template('login.html')  # Ensure you have this template

@app.route('/login', methods=['POST'])
def login():
    name = request.form.get('name')
    email = request.form.get('email').strip().lower()

    if not name or not email:
        return "❌ Missing login details."

    user_encoding = get_user_encoding(email)
    if user_encoding is None:  # ✅ Corrected condition
        return "❌ User not found or image encoding failed."

    verified = detect_and_verify_face(user_encoding)
    if verified:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
        user = cursor.fetchone()
        cursor.close()
        db.close()
        return redirect(url_for('profile', user_id=user['id']))
    else:
        return "❌ Unauthorized Face. Login Failed!"

@app.route('/profile/<int:user_id>')
def profile(user_id):
    return f"✅ Welcome to profile page of user {user_id}!"

if __name__ == '__main__':
    app.run(debug=True)
