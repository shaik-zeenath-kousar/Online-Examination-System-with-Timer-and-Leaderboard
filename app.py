from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from pymongo import MongoClient
from bson import ObjectId, Binary
from datetime import datetime, timedelta
import hashlib
import os
from werkzeug.utils import secure_filename
import docx
import json
import io
import markupsafe

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# Custom filter for nl2br
@app.template_filter('nl2br')
def nl2br_filter(text):
    if text is None:
        return ''
    return markupsafe.Markup(text.replace('\n', '<br>'))

# MongoDB Atlas connection
client = MongoClient('mongodb+srv://zeenath:kousar123@online.qskrwai.mongodb.net/?retryWrites=true&w=majority&appName=Online')
db = client.exam_system

# Collections
students = db.students
tests = db.tests
submissions = db.submissions
files = db.files  # New collection for storing files

# File upload configuration
ALLOWED_EXTENSIONS = {'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def is_logged_in():
    return 'user_id' in session

def is_admin():
    return session.get('user_type') == 'admin'

def is_student():
    return session.get('user_type') == 'student'

def store_file_in_mongodb(file, filename):
    """Store file in MongoDB as Binary data"""
    file_data = file.read()
    file_doc = {
        'filename': filename,
        'data': Binary(file_data),
        'content_type': file.content_type,
        'uploaded_at': datetime.now()
    }
    result = files.insert_one(file_doc)
    return str(result.inserted_id)

def get_file_from_mongodb(file_id):
    """Retrieve file from MongoDB"""
    try:
        file_doc = files.find_one({'_id': ObjectId(file_id)})
        if file_doc:
            return file_doc['data'], file_doc['filename'], file_doc['content_type']
        return None, None, None
    except:
        return None, None, None

def extract_text_from_docx_bytes(docx_bytes):
    """Extract text from docx file stored as bytes"""
    try:
        doc = docx.Document(io.BytesIO(docx_bytes))
        text_parts = []
        
        for paragraph in doc.paragraphs:
            # Get the text from the paragraph
            para_text = paragraph.text.strip()
            if para_text:  # Only add non-empty paragraphs
                text_parts.append(para_text)
        
        # Join paragraphs with double line breaks to preserve structure
        return '\n\n'.join(text_parts)
    except Exception as e:
        print(f"Error extracting text from docx: {e}")
        return "Error reading document content"

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        roll_no = request.form['roll_no']
        class_name = request.form['class']
        branch = request.form['branch']
        password = request.form['password']
        
        # Check if student already exists
        if students.find_one({'roll_no': roll_no}):
            flash('Student with this Roll Number already exists!', 'error')
            return render_template('signup.html')
        
        # Create new student
        student = {
            'name': name,
            'roll_no': roll_no,
            'class': class_name,
            'branch': branch,
            'password': hash_password(password),
            'created_at': datetime.now()
        }
        students.insert_one(student)
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        roll_no = request.form['roll_no']
        password = request.form['password']
        
        student = students.find_one({'roll_no': roll_no, 'password': hash_password(password)})
        if student:
            session['user_id'] = str(student['_id'])
            session['user_type'] = 'student'
            session['user_name'] = student['name']
            session['roll_no'] = student['roll_no']
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid Roll Number or Password!', 'error')
    
    return render_template('login.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username == 'admin' and password == '123456':
            session['user_id'] = 'admin'
            session['user_type'] = 'admin'
            session['user_name'] = 'HOD'
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials!', 'error')
    
    return render_template('admin_login.html')

@app.route('/student/dashboard')
def student_dashboard():
    if not is_logged_in() or not is_student():
        return redirect(url_for('login'))
    
    now = datetime.now()
    
    # Get all tests to process them properly
    all_tests_list = list(tests.find().sort('exam_date', 1))
    
    upcoming_tests = []
    ended_tests = []
    
    for test in all_tests_list:
        test_end_time = test['exam_date'] + timedelta(minutes=test['duration'])
        if now < test_end_time:
            # Test hasn't ended yet (upcoming or currently active)
            upcoming_tests.append(test)
        else:
            # Test has ended
            ended_tests.append(test)
    
    # Get only the 3 most recent ended tests
    recent_ended_tests = ended_tests[:3]
    
    # Combine upcoming and recent ended tests
    all_tests = upcoming_tests + recent_ended_tests
    
    # Get student's submissions
    student_submissions = list(submissions.find({
        'student_id': session['user_id']
    }).sort('submitted_at', -1))
    
    # Get student profile data
    student_profile = students.find_one({'_id': ObjectId(session['user_id'])})
    
    return render_template('student_dashboard.html', 
                         tests=all_tests,
                         submissions=student_submissions,
                         student_profile=student_profile)

@app.route('/admin/dashboard')
def admin_dashboard():
    if not is_logged_in() or not is_admin():
        return redirect(url_for('admin_login'))
    
    # Get all tests
    all_tests = list(tests.find().sort('created_at', -1))
    
    # Get all submissions
    all_submissions = list(submissions.find().sort('submitted_at', -1))
    
    # Get all students
    all_students = list(students.find())
    
    # Calculate pending evaluations
    pending_evaluations = len([s for s in all_submissions if s['status'] == 'pending_evaluation'])
    
    # Calculate active tests
    now = datetime.now()
    active_tests = len([t for t in all_tests if t['exam_date'] <= now <= t['exam_date'] + timedelta(minutes=t['duration'])])
    
    # Add submission count to each test
    for test in all_tests:
        test['submission_count'] = len([s for s in all_submissions if s['test_id'] == str(test['_id'])])
    
    return render_template('admin_dashboard.html', 
                         tests=all_tests,
                         submissions=all_submissions,
                         students=all_students,
                         pending_evaluations=pending_evaluations,
                         active_tests=active_tests,
                         now=now,
                         timedelta=timedelta)

@app.route('/admin/create_test', methods=['GET', 'POST'])
def create_test():
    if not is_logged_in() or not is_admin():
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        test_type = request.form['test_type']
        exam_name = request.form['exam_name']
        exam_date = datetime.strptime(request.form['exam_date'], '%Y-%m-%dT%H:%M')
        duration = int(request.form['duration'])
        total_marks = int(request.form['total_marks'])
        
        test = {
            'test_type': test_type,
            'exam_name': exam_name,
            'exam_date': exam_date,
            'duration': duration,
            'total_marks': total_marks,
            'created_at': datetime.now()
        }
        
        if test_type == 'objective':
            questions = []
            num_questions = int(request.form['num_questions'])
            marks_per_question = int(request.form['marks_per_question'])
            
            for i in range(num_questions):
                question = {
                    'question': request.form[f'question_{i}'],
                    'options': [
                        request.form[f'option_{i}_0'],
                        request.form[f'option_{i}_1'],
                        request.form[f'option_{i}_2'],
                        request.form[f'option_{i}_3']
                    ],
                    'correct_answer': int(request.form[f'correct_{i}']),
                    'marks': marks_per_question
                }
                questions.append(question)
            
            test['questions'] = questions
            test['marks_per_question'] = marks_per_question
        
        elif test_type == 'textual':
            if 'question_file' in request.files:
                file = request.files['question_file']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    
                    # Store file in MongoDB
                    file_id = store_file_in_mongodb(file, filename)
                    
                    # Extract text from docx
                    file_data, _, _ = get_file_from_mongodb(file_id)
                    if file_data:
                        question_text = extract_text_from_docx_bytes(file_data)
                        test['question_text'] = question_text
                        test['question_file_id'] = file_id
                        test['question_filename'] = filename
        
        tests.insert_one(test)
        flash('Test created successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('create_test.html')

@app.route('/test/<test_id>')
def take_test(test_id):
    if not is_logged_in() or not is_student():
        return redirect(url_for('login'))
    
    try:
        test = tests.find_one({'_id': ObjectId(test_id)})
    except:
        flash('Test not found!', 'error')
        return redirect(url_for('student_dashboard'))
    
    if not test:
        flash('Test not found!', 'error')
        return redirect(url_for('student_dashboard'))
    
    # Check if test is currently active
    now = datetime.now()
    if now < test['exam_date']:
        flash('Test has not started yet!', 'error')
        return redirect(url_for('student_dashboard'))
    
    if now > test['exam_date'] + timedelta(minutes=test['duration']):
        flash('Test has ended!', 'error')
        return redirect(url_for('student_dashboard'))
    
    # Check if already submitted
    existing_submission = submissions.find_one({
        'student_id': session['user_id'],
        'test_id': test_id
    })
    
    if existing_submission:
        flash('You have already submitted this test!', 'error')
        return redirect(url_for('student_dashboard'))
    
    return render_template('test.html', test=test, enumerate=enumerate)

@app.route('/submit_test/<test_id>', methods=['POST'])
def submit_test(test_id):
    if not is_logged_in() or not is_student():
        return jsonify({'error': 'Not logged in'})
    
    try:
        test = tests.find_one({'_id': ObjectId(test_id)})
    except:
        return jsonify({'error': 'Test not found'})
    
    if not test:
        return jsonify({'error': 'Test not found'})
    
    # Check if already submitted
    existing_submission = submissions.find_one({
        'student_id': session['user_id'],
        'test_id': test_id
    })
    
    if existing_submission:
        return jsonify({'error': 'Already submitted'})
    
    submission_data = {
        'student_id': session['user_id'],
        'student_name': session['user_name'],
        'student_roll_no': session['roll_no'],
        'test_id': test_id,
        'test_name': test['exam_name'],
        'test_type': test['test_type'],
        'submitted_at': datetime.now(),
        'submission_time': request.json.get('submission_time', 0)
    }
    
    if test['test_type'] == 'objective':
        answers = request.json.get('answers', [])
        score = 0
        
        for i, answer in enumerate(answers):
            if i < len(test['questions']):
                if answer == test['questions'][i]['correct_answer']:
                    score += test['questions'][i]['marks']
        
        submission_data['answers'] = answers
        submission_data['score'] = score
        submission_data['total_marks'] = test['total_marks']
        submission_data['status'] = 'completed'
    
    elif test['test_type'] == 'textual':
        answer_text = request.json.get('answer_text', '')
        submission_data['answer_text'] = answer_text
        submission_data['total_marks'] = test['total_marks']
        submission_data['status'] = 'pending_evaluation'
    
    submissions.insert_one(submission_data)
    return jsonify({'success': True})

@app.route('/admin/evaluate/<submission_id>', methods=['GET', 'POST'])
def evaluate_submission(submission_id):
    if not is_logged_in() or not is_admin():
        return redirect(url_for('admin_login'))
    
    try:
        submission = submissions.find_one({'_id': ObjectId(submission_id)})
    except:
        flash('Submission not found!', 'error')
        return redirect(url_for('admin_dashboard'))
    
    if not submission:
        flash('Submission not found!', 'error')
        return redirect(url_for('admin_dashboard'))
    
    # Get the test to ensure we have the correct total marks
    try:
        test = tests.find_one({'_id': ObjectId(submission['test_id'])})
        if test:
            # Update submission with correct total marks if not present
            if 'total_marks' not in submission or not submission['total_marks']:
                submission['total_marks'] = test['total_marks']
    except:
        pass  # If test not found, use submission's total_marks
    
    if request.method == 'POST':
        marks = int(request.form['marks'])
        feedback = request.form.get('feedback', '')
        
        submissions.update_one(
            {'_id': ObjectId(submission_id)},
            {
                '$set': {
                    'score': marks,
                    'feedback': feedback,
                    'status': 'evaluated',
                    'evaluated_at': datetime.now()
                }
            }
        )
        
        flash('Submission evaluated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('evaluate_submission.html', submission=submission)

@app.route('/leaderboard')
def leaderboard():
    # Get all completed submissions
    completed_submissions = list(submissions.find({
        'status': {'$in': ['completed', 'evaluated']}
    }))
    
    # Calculate total scores and fastest times for each student
    student_stats = {}
    
    for submission in completed_submissions:
        student_id = submission['student_id']
        if student_id not in student_stats:
            student_stats[student_id] = {
                'name': submission['student_name'],
                'roll_no': submission['student_roll_no'],
                'total_score': 0,
                'total_tests': 0,
                'fastest_time': float('inf'),
                'submissions': []
            }
        
        student_stats[student_id]['total_score'] += submission.get('score', 0)
        student_stats[student_id]['total_tests'] += 1
        student_stats[student_id]['submissions'].append(submission)
        
        if submission.get('submission_time', 0) > 0:
            student_stats[student_id]['fastest_time'] = min(
                student_stats[student_id]['fastest_time'],
                submission['submission_time']
            )
    
    # Sort by total score (desc) and fastest time (asc)
    sorted_students = sorted(
        student_stats.values(),
        key=lambda x: (-x['total_score'], x['fastest_time'] if x['fastest_time'] != float('inf') else float('inf'))
    )
    
    # Get unique tests that have been completed
    completed_test_ids = set()
    for submission in completed_submissions:
        completed_test_ids.add(submission['test_id'])
    
    # Get test details for completed tests
    completed_tests = []
    for test_id in completed_test_ids:
        try:
            test = tests.find_one({'_id': ObjectId(test_id)})
            if test:
                # Count submissions for this test
                test_submission_count = len([s for s in completed_submissions if s['test_id'] == test_id])
                test['submission_count'] = test_submission_count
                completed_tests.append(test)
        except:
            continue
    
    # Sort tests by exam date (newest first)
    completed_tests.sort(key=lambda x: x['exam_date'], reverse=True)
    
    return render_template('leaderboard.html', 
                         students=sorted_students, 
                         completed_tests=completed_tests,
                         float=float)

@app.route('/leaderboard/<test_id>')
def exam_leaderboard(test_id):
    try:
        test = tests.find_one({'_id': ObjectId(test_id)})
    except:
        flash('Test not found!', 'error')
        return redirect(url_for('leaderboard'))
    
    if not test:
        flash('Test not found!', 'error')
        return redirect(url_for('leaderboard'))
    
    # Get all completed submissions for this specific test
    test_submissions = list(submissions.find({
        'test_id': test_id,
        'status': {'$in': ['completed', 'evaluated']}
    }).sort('submitted_at', 1))
    
    # Calculate rankings for this test
    student_rankings = {}
    
    for submission in test_submissions:
        student_id = submission['student_id']
        if student_id not in student_rankings:
            student_rankings[student_id] = {
                'name': submission['student_name'],
                'roll_no': submission['student_roll_no'],
                'score': submission.get('score', 0),
                'total_marks': submission.get('total_marks', test['total_marks']),
                'submission_time': submission.get('submission_time', 0),
                'submitted_at': submission['submitted_at'],
                'status': submission['status']
            }
    
    # Sort by score (desc) and submission time (asc for fastest completion)
    sorted_rankings = sorted(
        student_rankings.values(),
        key=lambda x: (-x['score'], x['submission_time'] if x['submission_time'] > 0 else float('inf'))
    )
    
    return render_template('exam_leaderboard.html', 
                         test=test, 
                         rankings=sorted_rankings, 
                         float=float,
                         is_logged_in=is_logged_in,
                         is_admin=is_admin,
                         is_student=is_student)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/student/scores')
def student_scores():
    if not is_logged_in() or not is_student():
        return redirect(url_for('login'))
    
    # Get student's submissions
    student_submissions = list(submissions.find({
        'student_id': session['user_id']
    }).sort('submitted_at', -1))
    
    # Get student profile data
    student_profile = students.find_one({'_id': ObjectId(session['user_id'])})
    
    return render_template('student_scores.html', 
                         submissions=student_submissions,
                         student_profile=student_profile)

@app.route('/admin/submissions')
def admin_submissions():
    if not is_logged_in() or not is_admin():
        return redirect(url_for('admin_login'))
    
    # Get all submissions
    all_submissions = list(submissions.find().sort('submitted_at', -1))
    
    # Get all tests for reference
    all_tests = list(tests.find())
    
    # Create a lookup dictionary for test names
    test_lookup = {str(test['_id']): test['exam_name'] for test in all_tests}
    
    # Add test names to submissions
    for submission in all_submissions:
        submission['test_name'] = test_lookup.get(submission['test_id'], 'Unknown Test')
    
    return render_template('admin_submissions.html', 
                         submissions=all_submissions)

if __name__ == '__main__':
    app.run(debug=True) 