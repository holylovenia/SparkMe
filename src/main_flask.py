"""
Flask Web Application for Interview Session
Supports both text and voice input/output with authentication
"""

from flask import Flask, request, jsonify, render_template, Response, redirect, url_for, flash
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import traceback
import asyncio
import threading
import os
import uuid
import argparse
import time
import logging
import secrets
import hashlib
import json
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

# Your backend imports
from src.interview_session.interview_session import InterviewSession
from src.utils.data_process import save_rating_to_csv

load_dotenv(override=True)

# =============================================================================
# CONFIGURATION
# =============================================================================

SESSION_TIMEOUT_SECONDS = 3600  # 1 hour
START_TIME = time.time()

class AppConfig:
    """Application configuration"""
    def __init__(self):
        self.default_user_id = "web_user"
        self.host = "0.0.0.0"
        self.port = 5000
        self.debug = False
        self.restart = False
        self.max_turns = None
        self.additional_context_path = None

config = AppConfig()

# =============================================================================
# FLASK APP SETUP
# =============================================================================

app = Flask(__name__,
            static_folder='web/static',
            template_folder='web/templates')

app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
CORS(app)

# =============================================================================
# AUTHENTICATION SETUP
# =============================================================================

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access the interview.'

USERS_FILE = os.path.join(os.getenv('DATA_DIR', 'data'), 'users.json')

class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

def load_users():
    """Load users from JSON file"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    """Save users to JSON file"""
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def get_user_sessions_path(user_id: str) -> str:
    """Get path to user's session list JSON"""
    data_dir = os.getenv('DATA_DIR', 'data')
    return os.path.join(data_dir, user_id, 'user_sessions.json')

def load_user_sessions(user_id: str) -> list:
    """Load session list for a user"""
    path = get_user_sessions_path(user_id)
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_user_sessions(user_id: str, sessions: list):
    """Save session list for a user"""
    path = get_user_sessions_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, indent=2)

@login_manager.user_loader
def load_user(user_id):
    users = load_users()
    if user_id in users:
        return User(user_id, users[user_id]['username'])
    return None

# =============================================================================
# LOGGING SETUP
# =============================================================================

if not app.debug:
    os.makedirs('logs', exist_ok=True)
    file_handler = RotatingFileHandler(
        'logs/flask_app.log',
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Interview application startup')

# =============================================================================
# ASYNC EVENT LOOP MANAGEMENT
# =============================================================================

loop = asyncio.new_event_loop()

def start_background_loop(loop):
    """Run async event loop in background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=start_background_loop, args=(loop,), daemon=True).start()

def run_async_task(coro):
    """Submit coroutine to background loop."""
    return asyncio.run_coroutine_threadsafe(coro, loop)

# =============================================================================
# DEMOGRAPHIC SURVEY
# =============================================================================

# ── Survey helpers ────────────────────────────────────────────────────────────

def get_survey_path(user_id: str) -> str:
    return os.path.join(os.getenv('DATA_DIR', 'data'), user_id, 'survey.json')

def load_survey(user_id: str) -> dict:
    path = get_survey_path(user_id)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_survey(user_id: str, data: dict):
    path = get_survey_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data['completed_at'] = time.time()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def survey_completed(user_id: str) -> bool:
    data = load_survey(user_id)
    required = ['gender', 'orientation', 'age', 'ethnicity', 'education', 'country']
    return all(data.get(f) for f in required)

# ── Country list for the survey dropdown ─────────────────────────────────────

def get_all_countries() -> list:
    return [
        "Afghanistan","Albania","Algeria","Argentina","Australia","Austria",
        "Bangladesh","Belgium","Brazil","Canada","Chile","China","Colombia",
        "Croatia","Czech Republic","Denmark","Egypt","Ethiopia","Finland",
        "France","Germany","Ghana","Greece","Hungary","India","Indonesia",
        "Iran","Iraq","Ireland","Israel","Italy","Japan","Jordan","Kenya",
        "Lebanon","Malaysia","Mexico","Morocco","Netherlands","New Zealand",
        "Nigeria","Norway","Pakistan","Peru","Philippines","Poland","Portugal",
        "Romania","Russia","Saudi Arabia","Serbia","Singapore","South Africa",
        "South Korea","Spain","Sri Lanka","Sweden","Switzerland","Syria",
        "Taiwan","Thailand","Turkey","UAE","Ukraine","United Kingdom",
        "United States","Venezuela","Vietnam","Yemen"
    ]

@app.route('/survey')
@login_required
def survey():
    """Demographic survey page."""
    user_id   = current_user.id
    data      = load_survey(user_id)
    completed = survey_completed(user_id)
    countries = get_all_countries()
    return render_template('survey.html',
                           data=data,
                           already_completed=completed,
                           countries=countries)


@app.route('/api/save-survey', methods=['POST'])
@login_required
def api_save_survey():
    """Save demographic survey answers."""
    data     = request.json or {}
    required = ['gender', 'orientation', 'age', 'ethnicity', 'education', 'country']
    if not all(data.get(f) for f in required):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    save_survey(current_user.id, {f: data[f] for f in required})
    return jsonify({'success': True})

# =============================================================================
# SESSION MANAGEMENT
# =============================================================================

class SessionWrapper:
    def __init__(self, session_token: str, interview_session: InterviewSession,
                 user_id: str):
        self.session_token = session_token
        self.interview_session = interview_session
        self.user_id = user_id
        self.created_at = time.time()

active_sessions: Dict[str, SessionWrapper] = {}
last_messages_by_session: Dict[str, Dict[str, str]] = {}

def _count_completed_user_turns(user_id: str, sel_session_id, session_id,
                                 country: str, topic: str, n_turns) -> int:
    """Count user-turn rows already written to the ratings CSV."""
    import csv as _csv, re as _re

    def _safe(s):
        return _re.sub(r'[^\w\-]', '_', str(s)) if s is not None else 'unknown'

    filename = (
        f"{_safe(sel_session_id if sel_session_id is not None else session_id)}_"
        f"{_safe(country)}_{_safe(topic)}_{_safe(n_turns)}.csv"
    )
    ratings_file = os.path.join(
        os.getenv('LOGS_DIR', 'logs'), user_id, 'ratings', filename
    )

    if not os.path.exists(ratings_file):
        return 0

    count = 0
    try:
        with open(ratings_file, 'r', encoding='utf-8') as f:
            reader = _csv.DictReader(f)
            for row in reader:
                if row.get('liked_model', '') == 'user':
                    count += 1
    except Exception as e:
        app.logger.warning(f"Could not count user turns from CSV: {e}")

    return count

def create_interview_session(user_id: str,
                             sel_session_id: str = None,
                             country: str = None,
                             topic: str = None,
                             n_turns: int = None) -> tuple[InterviewSession, str]:
    session_token = str(uuid.uuid4())
    effective_max_turns = n_turns if n_turns is not None else config.max_turns

    interview_session = InterviewSession(
        interaction_mode='api',
        user_config={
            "user_id": user_id,
            "enable_voice": False,
            "restart": config.restart
        },
        interview_config={
            "enable_voice": False,
            "interview_description": os.getenv(
                'INTERVIEW_DESCRIPTION',
                "Understanding the impact of AI in the workforce"
            ),
            "interview_plan_path":        os.getenv('INTERVIEW_PLAN_PATH'),
            "interview_evaluation":       os.getenv('COMPLETION_METRIC'),
            "additional_context_path":    config.additional_context_path,
            "initial_user_portrait_path": os.getenv('USER_PORTRAIT_PATH'),
            "sel_session_id": sel_session_id,
            "country":        country,
            "topic":          topic,
        },
        max_turns=effective_max_turns
    )

    # ── Restore turn count from existing CSV so max_turns check is accurate
    #    after a server restart or session reconnect.
    completed_user_turns = _count_completed_user_turns(
        user_id=user_id,
        sel_session_id=sel_session_id,
        session_id=interview_session.session_id,
        country=country,
        topic=topic,
        n_turns=effective_max_turns,
    )
    if completed_user_turns > 0:
        interview_session._user_message_count = completed_user_turns
        app.logger.info(
            f"Restored _user_message_count={completed_user_turns} "
            f"from CSV for sel_session_id={sel_session_id}"
        )

    wrapper = SessionWrapper(
        session_token=session_token,
        interview_session=interview_session,
        user_id=user_id,
    )
    active_sessions[session_token] = wrapper

    session_loop = asyncio.new_event_loop()
    def _start_loop(l):
        asyncio.set_event_loop(l)
        l.run_forever()
    t = threading.Thread(target=_start_loop, args=(session_loop,), daemon=True)
    t.start()
    wrapper.loop        = session_loop
    wrapper.loop_thread = t
    asyncio.run_coroutine_threadsafe(interview_session.run(), session_loop)

    return interview_session, session_token

def get_session(session_token: str) -> Optional[InterviewSession]:
    wrapper = active_sessions.get(session_token)
    return wrapper.interview_session if wrapper is not None else None

def get_session_wrapper(session_token: str) -> Optional[SessionWrapper]:
    return active_sessions.get(session_token)

# =============================================================================
# AUTHENTICATION ROUTES (NO @login_required)
# =============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))  # Changed: redirect to index with instructions
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        users = load_users()
        
        # Find user
        user_id = None
        for uid, user_data in users.items():
            if user_data['username'] == username:
                user_id = uid
                break
        
        if user_id and users[user_id]['password'] == hash_password(password):
            user = User(user_id, username)
            login_user(user)
            app.logger.info(f"User logged in: {username} ({user_id})")
            
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('index'))  # Changed: go to index first
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration page"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))  # Changed: redirect to index with instructions
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return render_template('register.html')
        
        users = load_users()
        
        # Check if username exists
        for user_data in users.values():
            if user_data['username'] == username:
                flash('Username already exists', 'error')
                return render_template('register.html')
        
        # Create new user
        user_id = secrets.token_urlsafe(16)
        users[user_id] = {
            'username': username,
            'password': hash_password(password),
            'created_at': time.time()
        }
        save_users(users)
        
        # Create user directories
        os.makedirs(os.path.join(os.getenv('LOGS_DIR', 'logs'), user_id), exist_ok=True)
        os.makedirs(os.path.join(os.getenv('DATA_DIR', 'data'), user_id), exist_ok=True)
        
        app.logger.info(f"New user registered: {username} ({user_id})")
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    """Logout"""
    username = current_user.username
    logout_user()
    app.logger.info(f"User logged out: {username}")
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# =============================================================================
# PAGE ROUTES - PROTECTED (REQUIRE LOGIN)
# =============================================================================

@app.route('/')
@login_required
def index():
    """Session selection page — survey must be completed first."""
    if not survey_completed(current_user.id):
        flash('Please complete the demographic survey before starting.', 'info')
        return redirect(url_for('survey'))
    return render_template('sessions.html', username=current_user.username)

@app.route('/chat')
@login_required
def unified_chat():
    """Unified chat interface - requires session selection"""
    session_id = request.args.get('session_id')
    country = request.args.get('country')
    topic = request.args.get('topic')
    n_turns = request.args.get('n_turns')

    if not all([session_id, country, topic, n_turns]):
        flash('Please select a session first.', 'error')
        return redirect(url_for('index'))

    return render_template('chat.html',
                           username=current_user.username,
                           session_id=session_id,
                           country=country,
                           topic=topic,
                           n_turns=int(n_turns))

# =============================================================================
# API ENDPOINTS - PROTECTED (REQUIRE LOGIN)
# All endpoints that handle interview data need @login_required
# =============================================================================

@app.route('/api/get-user-sessions', methods=['GET'])
@login_required
def get_user_sessions():
    """Return the list of sessions for the logged-in user"""
    user_id = current_user.id
    sessions = load_user_sessions(user_id)
    return jsonify({'success': True, 'sessions': sessions})

@app.route('/api/start-session', methods=['POST'])
@login_required
def start_session():
    """Initialize a new interview session using authenticated user's ID and session params"""
    user_id = current_user.id
    data = request.json or {}

    # Session params from the session-selection page
    sel_session_id = data.get('session_id')
    sel_country = data.get('country')
    sel_topic = data.get('topic')
    sel_n_turns = data.get('n_turns')

    if not all([sel_session_id, sel_country, sel_topic, sel_n_turns]):
        return jsonify({'success': False, 'error': 'Missing session parameters'}), 400

    sel_n_turns = int(sel_n_turns)

    app.logger.info(f"[DEBUG] start-session called by user {current_user.username} "
                    f"session_id={sel_session_id} country={sel_country} topic={sel_topic}")

    # Check if user already has an active session for THIS session_id
    for token, wrapper in active_sessions.items():
        if wrapper.user_id == user_id and getattr(wrapper, 'sel_session_id', None) == sel_session_id:
            app.logger.info(f"Returning existing session {token} for user {current_user.username}")
            return jsonify({
                'success': True,
                'session_token': token,
                'session_id': wrapper.interview_session.session_id,
                'user_id': user_id,
                'username': current_user.username,
                'message': 'Using existing session',
                'was_existing': True
            })

    # Create new session with the selected parameters
    interview_session, session_token = create_interview_session(
        user_id=user_id,
        sel_session_id=sel_session_id,
        country=sel_country,
        topic=sel_topic,
        n_turns=sel_n_turns
    )

    # Store selection metadata on the wrapper for reuse checks
    wrapper = active_sessions[session_token]
    wrapper.sel_session_id = sel_session_id
    wrapper.country = sel_country
    wrapper.topic = sel_topic
    wrapper.n_turns = sel_n_turns

    app.logger.info(f"Session created: {session_token} | User: {current_user.username} "
                    f"| sel_session_id={sel_session_id}")

    return jsonify({
        'success': True,
        'session_token': session_token,
        'session_id': interview_session.session_id,
        'user_id': user_id,
        'username': current_user.username,
        'message': 'Session started successfully',
        'was_existing': False
    })

@app.route('/api/submit-rating', methods=['POST'])
@login_required
def submit_rating():
    data                 = request.json
    session_token        = data.get('session_token')
    message_id           = data.get('message_id')
    reply_to             = data.get('reply_to', None)
    rating_cultural      = data.get('rating_cultural', None)
    rating_fluency       = data.get('rating_fluency', None)
    rejected_options     = data.get('rejected_options', [])
    rejected_message_ids = data.get('rejected_message_ids', [])

    session = get_session(session_token)
    if not session:
        return jsonify({'success': False, 'error': 'Invalid or expired session'}), 400

    # Always use the session's own stored topic/country — set at session
    # creation from user_sessions.json, not from the frontend payload.
    topic   = getattr(session, 'topic',   None)
    country = getattr(session, 'country', None)

    model_map       = getattr(session, '_response_model_map', {})
    liked_model     = model_map.get(message_id, '')
    rejected_models = [model_map.get(mid, '') for mid in rejected_message_ids]

    system_message = session.get_system_guidance(message_id=message_id)

    save_rating_to_csv(
        session_token=session_token,
        message_id=message_id,
        reply_to=reply_to,
        rating_cultural=rating_cultural,
        rating_fluency=rating_fluency,
        rejected_options=rejected_options,
        user_id=session.user_id,
        session_id=session.session_id,
        follow_up="",              # ← follow_up only lives on user rows now
        topic=topic,
        country=country,
        liked_model=liked_model,
        rejected_models=rejected_models,
        sel_session_id=session.sel_session_id,
        n_turns=session.max_turns,
    )

    if getattr(session, '_farewell_done', False):
        session._farewell_rated = True
        system_message = None

    return jsonify({'success': True, 'system_message': system_message})

@app.route('/api/send-message', methods=['POST'])
@login_required
def send_message():
    data             = request.json
    session_token    = data.get('session_token')
    user_message     = data.get('message')
    reply_to         = data.get('reply_to', None)
    rating_cultural  = data.get('rating_cultural', None)
    rating_fluency   = data.get('rating_fluency', None)
    rejected_options = data.get('rejected_options', [])
    topic            = data.get('topic', None)
    country          = data.get('country', None)

    session = get_session(session_token)
    if not session:
        return jsonify({'success': False, 'error': 'Invalid or expired session'}), 400

    if not session.session_in_progress:
        return jsonify({'success': False, 'error': 'Session has ended', 'session_completed': True}), 400

    wrapper = get_session_wrapper(session_token)
    if wrapper and hasattr(wrapper, 'loop'):
        wrapper.loop.call_soon_threadsafe(
            wrapper.interview_session.user.add_user_message,
            user_message, reply_to, rating_cultural, rating_fluency, rejected_options,
            topic, country
        )
    else:
        session.user.add_user_message(
            user_message, reply_to, rating_cultural, rating_fluency, rejected_options,
            topic, country
        )

    # The interviewer responds asynchronously — its messages land in the
    # user's _message_buffer and are picked up by the frontend's polling
    # via /api/get-messages. Calling wait_for_agent_response here would
    # drain the buffer via get_and_clear_messages before polling sees it.
    return jsonify({'success': True, 'message': 'Message sent successfully'})

# Stub
@app.route('/api/send-voice', methods=['POST'])
@login_required
def send_voice():
    return jsonify({'success': False, 'error': 'Voice input is not supported.'}), 503

@app.route('/api/get-messages', methods=['GET'])
@login_required
def get_messages():
    """Get new messages from the session (polling endpoint)"""
    session_token = request.args.get('session_token')

    session = get_session(session_token)
    if not session:
        return jsonify({
            'success': False,
            'error': 'Invalid or expired session',
            'active_sessions_count': len(active_sessions)
        }), 400

    messages = []
    if session.user:
        if hasattr(session.user, 'get_new_messages'):
            messages = session.user.get_new_messages() or []
        elif hasattr(session.user, '_message_buffer'):
            lock = getattr(session.user, '_lock', None)
            if lock:
                with lock:
                    messages = list(getattr(session.user, '_message_buffer', []))
            else:
                messages = list(getattr(session.user, '_message_buffer', []))
        elif hasattr(session.user, 'get_and_clear_messages'):
            messages = session.user.get_and_clear_messages() or []

    is_session_done = (
        getattr(session, '_farewell_rated', False)
        or session.session_completed
    )

    if is_session_done:
        end_msg_id = f"system_end_{session_token}"
        if not any(m.get('id') == end_msg_id for m in messages):
            messages.append({
                'id': end_msg_id,
                'role': 'System',
                'content': "Session has been completed! Thank you for your participation in our interview! Your responses have been recorded!",
                'timestamp': time.time()
            })

    return jsonify({
        'success': True,
        'messages': messages,
        'session_active': session.session_in_progress,
        'session_completed': is_session_done
    })

@app.route('/api/acknowledge-messages', methods=['POST'])
@login_required  # PROTECTED
def acknowledge_messages():
    """Mark messages as acknowledged by the client"""
    data = request.json
    session_token = data.get('session_token')
    message_ids = data.get('message_ids', [])

    session = get_session(session_token)
    if not session:
        return jsonify({
            'success': False,
            'error': 'Invalid or expired session'
        }), 400

    if session.user and hasattr(session.user, '_message_buffer'):
        lock = getattr(session.user, '_lock', None)
        if lock:
            with lock:
                buffer = getattr(session.user, '_message_buffer', [])
                session.user._message_buffer = [
                    m for m in buffer 
                    if m.get('id') not in message_ids
                ]
        
    return jsonify({'success': True})

# Stub
@app.route('/api/get-voice-response', methods=['GET'])
@login_required
def get_voice_response():
    return jsonify({'success': False, 'error': 'Voice output is not supported.'}), 503

@app.route('/api/mark-session-completed', methods=['POST'])
@login_required
def mark_session_completed():
    """Mark a user_sessions.json entry as completed"""
    data = request.json
    sel_session_id = data.get('session_id')
    user_id = current_user.id

    if not sel_session_id:
        return jsonify({'success': False, 'error': 'Missing session_id'}), 400

    sessions = load_user_sessions(user_id)
    found = False
    for s in sessions:
        if s['session_id'] == sel_session_id:
            s['completed'] = True
            found = True
            break

    if not found:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    save_user_sessions(user_id, sessions)
    return jsonify({'success': True, 'message': f'Session {sel_session_id} marked completed'})

@app.route('/api/session-history', methods=['GET'])
@login_required
def session_history():
    """Reconstruct chat history from the ratings CSV for a given assigned session."""
    session_token = request.args.get('session_token')

    wrapper = get_session_wrapper(session_token)
    if not wrapper:
        return jsonify({'success': False, 'error': 'Invalid session'}), 400

    session = wrapper.interview_session

    import re, csv
    def _safe(s):
        return re.sub(r'[^\w\-]', '_', str(s)) if s is not None else 'unknown'

    sel_session_id = getattr(session, 'sel_session_id', None)
    country        = getattr(session, 'country',        None)
    topic          = getattr(session, 'topic',          None)
    n_turns        = session.max_turns

    filename = (
        f"{_safe(sel_session_id if sel_session_id is not None else session.session_id)}_"
        f"{_safe(country)}_{_safe(topic)}_{_safe(n_turns)}.csv"
    )
    ratings_dir  = os.path.join(os.getenv('LOGS_DIR', 'logs'), session.user_id, 'ratings')
    ratings_file = os.path.join(ratings_dir, filename)

    if not os.path.exists(ratings_file):
        return jsonify({'success': True, 'messages': []})

    messages = []
    try:
        with open(ratings_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                liked_model    = row.get('liked_model', '')
                liked_response = row.get('liked_response', '')
                follow_up      = row.get('follow_up', '')

                if not liked_response:
                    continue

                if liked_model == 'user':
                    # User turn
                    messages.append({
                        'id':      f"history_user_{i}",
                        'role':    'User',
                        'content': liked_response,
                    })
                    # If a follow-up guidance was shown after this user turn
                    if follow_up:
                        messages.append({
                            'id':      f"history_system_{i}",
                            'role':    'System',
                            'content': follow_up,
                        })
                else:
                    # Bot turn — show as already-rated (no like button needed)
                    rating_c = row.get('rating_cultural', '')
                    rating_f = row.get('rating_fluency',  '')
                    messages.append({
                        'id':             f"history_bot_{i}",
                        'role':           'Interviewer',
                        'content':        liked_response,
                        'already_rated':  True,
                        'rating_cultural': rating_c,
                        'rating_fluency':  rating_f,
                    })
    except Exception as e:
        app.logger.error(f"Error reading history CSV: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True, 'messages': messages})

@app.route('/api/end-session', methods=['POST'])
@login_required
def end_session():
    """Trigger one final interviewer response then close the session."""
    data = request.json
    session_token = data.get('session_token')

    wrapper = get_session_wrapper(session_token)
    if not wrapper:
        return jsonify({'success': False, 'error': 'Invalid or expired session'}), 400

    session = wrapper.interview_session

    if getattr(session, '_session_ending', False) or getattr(session, '_farewell_done', False):
        return jsonify({'success': True, 'message': 'Session is already ending'})

    asyncio.run_coroutine_threadsafe(session.trigger_farewell(), wrapper.loop)
    wrapper.ended_at = time.time()
    app.logger.info(f"Session {session_token} farewell triggered by user")

    return jsonify({
        'success': True,
        'message': 'Session ending — one final response will be delivered.',
        'session_id': session.session_id,
        'user_id': session.user_id
    })

@app.route('/api/session-status', methods=['GET'])
@login_required  # PROTECTED
def session_status():
    """Get current session status including background task progress"""
    session_token = request.args.get('session_token')

    wrapper = get_session_wrapper(session_token)
    if not wrapper:
        return jsonify({
            'success': False,
            'error': 'Invalid or expired session'
        }), 400

    session = wrapper.interview_session

    # Get background task count if available
    background_tasks_count = 0
    if hasattr(session, '_background_tasks'):
        try:
            import asyncio
            # Try to get count safely
            if hasattr(session, '_background_tasks_lock'):
                # Can't acquire lock in sync context, just get len
                background_tasks_count = len(session._background_tasks)
        except:
            background_tasks_count = 0

    return jsonify({
        'success': True,
        'session_active': session.session_in_progress,
        'session_completed': session.session_completed,
        'background_tasks_remaining': background_tasks_count,
        'message_count': len(session.chat_history),
        'session_id': session.session_id,
        'user_id': session.user_id
    })

@app.route('/api/debug-session', methods=['GET'])
@login_required  # PROTECTED
def debug_session():
    """Development-only: return session internals"""
    session_token = request.args.get('session_token')
    if not session_token:
        return jsonify({'success': False, 'error': 'session_token required'}), 400

    wrapper = get_session_wrapper(session_token)
    if not wrapper:
        return jsonify({'success': False, 'error': 'Invalid or expired session', 'active_sessions_count': len(active_sessions)}), 400

    session = wrapper.interview_session

    last_msgs = []
    for m in session.chat_history[-20:]:
        last_msgs.append({
            'id': getattr(m, 'id', None),
            'role': getattr(m, 'role', None),
            'content': getattr(m, 'content', None),
            'timestamp': getattr(m, 'timestamp', None).isoformat() if getattr(m, 'timestamp', None) else None,
        })

    user_buffer = []
    user = session.user
    if hasattr(user, '_message_buffer'):
        try:
            lock = getattr(user, '_lock', None)
            if lock:
                lock.acquire()
            user_buffer = list(getattr(user, '_message_buffer', []))
        finally:
            if lock:
                lock.release()

    return jsonify({
        'success': True,
        'session_id': session.session_id,
        'session_active': session.session_in_progress,
        'session_completed': session.session_completed,
        'message_count': len(session.chat_history),
        'chat_history': last_msgs,
        'user_buffer': user_buffer,
        'active_sessions_count': len(active_sessions)
    })

@app.route('/process_audio', methods=['POST'])
@login_required  # PROTECTED
def process_audio():
    """Compatibility route for older speech_chat.html template"""
    session_token = request.form.get('session_token')
    audio_file = request.files.get('audio')

    if not audio_file:
        return jsonify({'success': False, 'error': 'No audio file provided'}), 400

    user_id = current_user.id
    
    if not session_token:
        interview_session, session_token = create_interview_session(user_id=user_id)
    else:
        interview_session = get_session(session_token)
        if not interview_session:
            interview_session, session_token = create_interview_session(user_id=user_id)

    temp_audio_path = Path(f"temp_audio_{uuid.uuid4().hex}.wav")
    audio_file.save(temp_audio_path)

    try:
        transcribed_text = transcribe_audio_to_text(temp_audio_path)
        wrapper = get_session_wrapper(session_token)
        if wrapper and hasattr(wrapper, 'loop'):
            wrapper.loop.call_soon_threadsafe(
                wrapper.interview_session.user.add_user_message, 
                transcribed_text
            )
        else:
            interview_session.user.add_user_message(transcribed_text)

        bot_reply = wait_for_agent_response(interview_session, timeout=15.0)
        
        last_messages_by_session[session_token] = {
            'user_message': transcribed_text,
            'bot_reply': bot_reply or ''
        }

        if bot_reply:
            out_path = Path(f"temp_speech_{uuid.uuid4().hex}.mp3")
            generate_speech_from_text(bot_reply, out_path)
            audio_bytes = out_path.read_bytes()
            out_path.unlink(missing_ok=True)
            return Response(audio_bytes, mimetype='audio/mpeg')

        return jsonify({
            'success': True, 
            'user_message': transcribed_text, 
            'bot_reply': bot_reply
        }), 200

    finally:
        if temp_audio_path.exists():
            temp_audio_path.unlink()

@app.route('/get_last_messages', methods=['GET'])
@login_required  # PROTECTED
def get_last_messages():
    """Get last messages for session"""
    session_token = request.args.get('session_token')
    if not session_token:
        return jsonify({'success': False, 'error': 'session_token required'}), 400

    msgs = last_messages_by_session.get(session_token, {})
    return jsonify({
        'success': True,
        'user_message': msgs.get('user_message', ''),
        'bot_reply': msgs.get('bot_reply', '')
    })

# =============================================================================
# HEALTH CHECK - NOT PROTECTED (for monitoring)
# =============================================================================

@app.route('/health', methods=['GET'])
def health():
    current_time = time.time()
    session_ages = [
        (current_time - w.created_at) / 60
        for w in active_sessions.values()
    ]
    avg_age = sum(session_ages) / len(session_ages) if session_ages else 0
    return jsonify({
        'status':                   'healthy',
        'active_sessions':          len(active_sessions),
        'avg_session_age_minutes':  round(avg_age, 2),
        'uptime_seconds':           round(current_time - START_TIME, 2)
    })

def wait_for_agent_response(session, timeout: float = 60.0, poll_interval: float = 0.5):
    """Wait for the Interviewer/Agent to produce an output"""
    start_time = None
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            start_time = None
        else:
            start_time = loop.time()
    except Exception:
        start_time = None

    elapsed = 0.0
    import time as _time

    while elapsed < timeout:
        try:
            msgs = []
            if hasattr(session.user, 'get_and_clear_messages'):
                msgs = session.user.get_and_clear_messages() or []
            interviewer_msgs = [m for m in msgs if m.get('role') == 'Interviewer']
            if interviewer_msgs:
                return interviewer_msgs[-1].get('content')
        except Exception:
            pass
        _time.sleep(poll_interval)
        elapsed += poll_interval
    return None

# =============================================================================
# SESSION CLEANUP
# =============================================================================

def cleanup_old_sessions():
    current_time = time.time()
    to_remove = []

    for token, wrapper in list(active_sessions.items()):
        age = current_time - wrapper.created_at
        session = wrapper.interview_session

        # Remove sessions older than timeout
        if age > SESSION_TIMEOUT_SECONDS:
            to_remove.append(token)
            continue

        # Remove sessions that ended (farewell done) more than 10 minutes ago
        if getattr(session, '_farewell_done', False) or \
                getattr(session, '_farewell_rated', False):
            ended_age = current_time - getattr(wrapper, 'ended_at', current_time)
            if ended_age > 600:
                to_remove.append(token)

    for token in to_remove:
        wrapper = active_sessions.pop(token, None)
        last_messages_by_session.pop(token, None)
        if wrapper:
            print(f"[Cleanup] Removed session {token} (user: {wrapper.user_id})")

    if to_remove:
        print(f"[Cleanup] Removed {len(to_remove)} sessions. Active: {len(active_sessions)}")

def start_cleanup_thread():
    """Start background thread for session cleanup"""
    def cleanup_loop():
        while True:
            time.sleep(300)  # Every 5 minutes
            try:
                cleanup_old_sessions()
            except Exception as e:
                print(f"[Cleanup] Error: {e}")
    
    t = threading.Thread(target=cleanup_loop, daemon=True, name="SessionCleanup")
    t.start()
    print("[Cleanup] Started session cleanup thread")

# =============================================================================
# MAIN
# =============================================================================

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Flask Interview Session Web Application'
    )
    parser.add_argument('--user-id', type=str, help='Default user ID')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--host', type=str, default='0.0.0.0')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--additional_context_path', default=None)
    parser.add_argument('--restart', action='store_true', default=False)
    parser.add_argument('--max_turns', type=int, default=None)
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_arguments()

    if args.restart and args.user_id:
        os.system(f"rm -rf {os.getenv('LOGS_DIR')}/{args.user_id}")
        os.system(f"rm -rf {os.getenv('DATA_DIR')}/{args.user_id}")
        print(f"Cleared data for user {args.user_id}")
    
    config.default_user_id = args.user_id if args.user_id else "web_guest"
    config.host = args.host
    config.port = args.port
    config.debug = args.debug
    config.restart = args.restart
    config.max_turns = args.max_turns
    config.additional_context_path = args.additional_context_path
    
    start_cleanup_thread()
    
    print("\n" + "="*70)
    print("Flask Interview Session Server - Multi-User Mode")
    print("="*70)
    print(f"🌐 Host:              {config.host}")
    print(f"🔌 Port:              {config.port}")
    print(f"🐛 Debug:             {config.debug}")
    print(f"🔐 Authentication:    Enabled")
    print(f"🧹 Session Cleanup:   Every 5 minutes (timeout: {SESSION_TIMEOUT_SECONDS/60:.0f} min)")
    print("="*70)
    print(f"\n📍 Login at: http://{config.host}:{config.port}/login")
    print(f"📊 Health check: http://{config.host}:{config.port}/health")
    print("="*70 + "\n")
    
    if not config.debug:
        print("⚠️  For production, use: gunicorn -w 2 --threads 4 -b 0.0.0.0:8080 flask_app:app\n")
    
    app.run(
        host=config.host,
        port=config.port,
        debug=config.debug,
        use_reloader=False,
        threaded=True
    )