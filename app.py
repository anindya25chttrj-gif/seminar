from flask import Flask, render_template, request, redirect, url_for, session
import pandas as pd
from sklearn.linear_model import LinearRegression
import json
import os
from pymongo import MongoClient

app = Flask(__name__)
app.secret_key = "super_secret_key_for_sessions"

# ==========================================
# 1. ENVIRONMENT DETECTION (Local vs Vercel)
# ==========================================
IS_VERCEL = os.environ.get('VERCEL') == '1'
MONGO_URI = os.environ.get('MONGO_URI') 
USE_MONGO = MONGO_URI is not None

# ==========================================
# 2. MOCK ML MODEL
# ==========================================
def train_model():
    data = {'attendance': [75, 80], 'study_hours': [10, 15], 'prev_cgpa': [7.0, 7.5], 'final_cgpa': [7.2, 7.8]}
    df = pd.DataFrame(data)
    model = LinearRegression()
    model.fit(df[['attendance', 'study_hours', 'prev_cgpa']], df['final_cgpa'])
    return model
ml_model = train_model()

# ==========================================
# 3. SMART DATABASE MANAGER (Updated for Security)
# ==========================================
# Notice the new 'first_login' key added to the default users
DEFAULT_DB = {
    "students": {
        "achatterjee": {
            "password": "password2026", 
            "name": "Anindya Chatterjee", 
            "course": "B.Tech",
            "section": "A",
            "first_login": True,
            "metrics": {"total_classes": 40, "attended_classes": 34, "study_hours": 20.0, "prev_cgpa": 8.2}
        }
    },
    "teachers": {
        "teacher1": {
            "password": "admin",
            "name": "Prof. Sharma",
            "department": "Computer Science",
            "routine": [
                {"class_id": "cs101_mon", "day": "Monday", "time": "10:00 AM", "subject": "Data Structures", "course": "B.Tech", "section": "A"}
            ],
            "first_login": True
        }
    }
}

DB_FILE = 'database.json'

def load_db():
    if USE_MONGO:
        client = MongoClient(MONGO_URI)
        db = client['student_portal']
        doc = db['data'].find_one({"_id": "main_db"})
        return doc['data'] if doc else DEFAULT_DB
    else:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        return DEFAULT_DB

def save_db(db_data):
    if USE_MONGO:
        client = MongoClient(MONGO_URI)
        db = client['student_portal']
        db['data'].update_one({"_id": "main_db"}, {"$set": {"data": db_data}}, upsert=True)
    elif IS_VERCEL:
        pass 
    else:
        with open(DB_FILE, 'w') as f:
            json.dump(db_data, f, indent=4)

DB = load_db()

# ==========================================
# 4. WEB ROUTES
# ==========================================
@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    msg = request.args.get('msg') # Success message from password reset
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        if role in DB and username in DB[role] and DB[role][username]['password'] == password:
            session['username'] = username
            session['role'] = role
            
            # Check if this is their first login
            if DB[role][username].get('first_login', True):
                return redirect(url_for('first_setup'))
                
            return redirect(url_for('teacher_dashboard' if role == 'teachers' else 'dashboard'))
        else:
            error = "Invalid credentials or role."
            
    return render_template('login.html', error=error, msg=msg)

@app.route('/first_setup', methods=['GET', 'POST'])
def first_setup():
    if 'username' not in session: return redirect(url_for('login'))
    
    role = session['role']
    username = session['username']
    error = None
    
    if request.method == 'POST':
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        sec_q = request.form['security_q']
        sec_a = request.form['security_a'].strip().lower() # Lowercase for easier matching later
        
        if new_password != confirm_password:
            error = "Passwords do not match!"
        elif len(new_password) < 6:
            error = "Password must be at least 6 characters."
        else:
            # Update database with new credentials and remove first_login flag
            DB[role][username]['password'] = new_password
            DB[role][username]['security_q'] = sec_q
            DB[role][username]['security_a'] = sec_a
            DB[role][username]['first_login'] = False
            save_db(DB)
            
            return redirect(url_for('teacher_dashboard' if role == 'teachers' else 'dashboard'))
            
    return render_template('first_setup.html', error=error)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    error = None
    if request.method == 'POST':
        action = request.form.get('action')
        
        # Step 1: Verify user exists and fetch their security question
        if action == 'get_question':
            role = request.form.get('role')
            username = request.form.get('username')
            
            if role in DB and username in DB[role]:
                if DB[role][username].get('first_login', True):
                    error = "You have not set up your account yet. Log in with your default password."
                else:
                    question = DB[role][username]['security_q']
                    return render_template('forgot_password.html', step=2, role=role, username=username, question=question)
            else:
                error = "User not found."
                
        # Step 2: Verify answer and reset password
        elif action == 'reset_password':
            role = request.form.get('role')
            username = request.form.get('username')
            answer = request.form.get('security_a').strip().lower()
            new_password = request.form.get('new_password')
            
            if DB[role][username]['security_a'] == answer:
                DB[role][username]['password'] = new_password
                save_db(DB)
                return redirect(url_for('login', msg="Password reset successful! You can now log in."))
            else:
                error = "Incorrect security answer."
                question = DB[role][username]['security_q']
                return render_template('forgot_password.html', step=2, role=role, username=username, question=question, error=error)

    return render_template('forgot_password.html', step=1, error=error)

# ... (Keep /teacher_dashboard, /manage_class, /dashboard, and /logout exactly the same as before) ...

@app.route('/teacher_dashboard')
def teacher_dashboard():
    if session.get('role') != 'teachers': return redirect(url_for('login'))
    teacher = DB['teachers'][session['username']]
    return render_template('teacher_dashboard.html', teacher=teacher)

@app.route('/manage_class/<class_id>', methods=['GET', 'POST'])
def manage_class(class_id):
    if session.get('role') != 'teachers': return redirect(url_for('login'))
    teacher = DB['teachers'][session['username']]
    class_info = next((c for c in teacher['routine'] if c['class_id'] == class_id), None)
    class_students = {k: v for k, v in DB['students'].items() if v['course'] == class_info['course'] and v['section'] == class_info['section']}
    if request.method == 'POST':
        for student_id in class_students.keys():
            status = request.form.get(f'status_{student_id}')
            if status in ['present', 'absent']:
                DB['students'][student_id]['metrics']['total_classes'] += 1
                if status == 'present':
                    DB['students'][student_id]['metrics']['attended_classes'] += 1
        save_db(DB)
        return redirect(url_for('teacher_dashboard'))
    return render_template('manage_class.html', class_info=class_info, students=class_students)

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if session.get('role') != 'students': return redirect(url_for('login'))
    user_info = DB['students'][session['username']]
    
    # Always calculate accurate attendance from database
    total = user_info['metrics']['total_classes']
    attended = user_info['metrics']['attended_classes']
    current_attendance_pct = round((attended / total) * 100, 2) if total > 0 else 0
    
    prediction = None
    
    # Set default display values from the database for initial load
    display_study_hours = user_info['metrics']['study_hours']
    display_prev_cgpa = user_info['metrics']['prev_cgpa']
    
    if request.method == 'POST':
        # Overwrite display values with what the user just typed so they don't reset
        att = float(request.form['attendance'])
        display_study_hours = float(request.form['study_hours'])
        display_prev_cgpa = float(request.form['prev_cgpa'])
        
        user_data = pd.DataFrame([[att, display_study_hours, display_prev_cgpa]], columns=['attendance', 'study_hours', 'prev_cgpa'])
        prediction = round(min(10.0, max(0.0, ml_model.predict(user_data)[0])), 2)
        
    return render_template('dashboard.html', 
                           user=user_info, 
                           current_attendance=current_attendance_pct, 
                           display_study_hours=display_study_hours,
                           display_prev_cgpa=display_prev_cgpa,
                           prediction=prediction)
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)