import ast
import csv
import json
import os
import re

from datetime import datetime
from src.interview_session.session_models import Message


def save_rating_to_csv(session_token: str, message_id: str, reply_to: str,
                       rating_cultural: int, rating_fluency: int,
                       rejected_options: list, user_id: str, session_id: str,
                       follow_up: str = None, topic: str = None, country: str = None,
                       liked_model: str = None, rejected_models: list = None,
                       sel_session_id: str = None, n_turns: int = None):
    """Persist like ratings and rejected variants to a dedicated CSV."""

    ratings_dir = os.path.join(os.getenv("LOGS_DIR", "logs"), user_id, 'ratings')
    os.makedirs(ratings_dir, exist_ok=True)

    # New naming: {user_id}_{session_id}_{country}_{topic}_{n_turns}
    if all([sel_session_id, country, topic, n_turns]):
        filename = f'{user_id}_{sel_session_id}_{country}_{topic}_{n_turns}.csv'
    else:
        filename = f'session_{session_id}.csv'

    ratings_file = os.path.join(ratings_dir, filename)

    if not os.path.exists(ratings_file):
        with open(ratings_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL, escapechar='\\')
            writer.writerow([
                'timestamp', 'message_id', 'liked_response',
                'rating_cultural', 'rating_fluency', 'rejected_options',
                'follow_up', 'topic', 'country',
                'liked_model', 'rejected_options_models',
            ])

    with open(ratings_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL, escapechar='\\')
        writer.writerow([
            datetime.now().isoformat(),
            message_id,
            reply_to or '',
            rating_cultural if rating_cultural is not None else '',
            rating_fluency  if rating_fluency  is not None else '',
            rejected_options or '',
            follow_up or '',
            topic   or '',
            country or '',
            liked_model or '',
            rejected_models or '',
        ])


def save_feedback_to_csv(interviewer_message, feedback_message, user_id: str, session_id: str,
                         sel_session_id: str = None, country: str = None,
                         topic: str = None, n_turns: int = None):
    """Save feedback message to a CSV file with the last conversation message"""

    feedback_dir = os.path.join(os.getenv("LOGS_DIR", "logs"), user_id, 'feedback')
    os.makedirs(feedback_dir, exist_ok=True)

    # New naming format: {user_id}_{session_id}_{country}_{topic}_{n_turns}
    if all([sel_session_id, country, topic, n_turns]):
        filename = f'{user_id}_{sel_session_id}_{country}_{topic}_{n_turns}.csv'
    else:
        filename = f'session_{session_id}.csv'

    feedback_file = os.path.join(feedback_dir, filename)

    if not os.path.exists(feedback_file):
        with open(feedback_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL, escapechar='\\')
            writer.writerow([
                'timestamp', 'interviewer_message', 'user_feedback',
                'rating_cultural', 'rating_fluency', 'rejected_options'
            ])

    if interviewer_message:
        interviewer_content = (
            interviewer_message if type(interviewer_message) == str
            else interviewer_message.content
        )
    else:
        interviewer_content = ''

    feedback_content = feedback_message.content if feedback_message else ''

    metadata         = feedback_message.metadata if feedback_message and feedback_message.metadata else {}
    rating_cultural  = metadata.get('rating_cultural', '')
    rating_fluency   = metadata.get('rating_fluency', '')
    rejected_options = metadata.get('rejected_options', [])

    with open(feedback_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL, escapechar='\\')
        writer.writerow([
            feedback_message.timestamp.isoformat(),
            interviewer_content,
            feedback_content,
            rating_cultural,
            rating_fluency,
            rejected_options,
        ])
        
def read_from_pdf(file_path: str):
    from PyPDF2 import PdfReader

    reader = PdfReader(file_path)
    text = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text.append(page_text)
    return "\n".join(text)

def safe_parse_json(text: str):
    text = text.strip()
    if not text:
        return None

    # Try to find ```json ... ``` fenced block first
    codeblock_match = re.search(r"```json(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if codeblock_match:
        candidate = codeblock_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass  # fallback later

    # Try parsing entire text as JSON directly
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try Python literal eval (last resort)
    try:
        parsed_dict = ast.literal_eval(text)
        if isinstance(parsed_dict, dict):
            return parsed_dict
    except Exception:
        pass
    
    return None
    