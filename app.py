from dotenv import load_dotenv
load_dotenv()  # MUST run before importing database (which reads DATABASE_URL at module load)

from flask import Flask, request, jsonify, send_file, render_template, redirect, url_for, session
from flask_cors import CORS
import os
import re
import threading
import requests
import tempfile
from functools import wraps
from groq import Groq
from werkzeug.security import generate_password_hash, check_password_hash

import database as db

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'change-me-in-production-please')
CORS(app, supports_credentials=True)

# API keys
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
ELEVENLABS_VOICE_ID = os.getenv('ELEVENLABS_VOICE_ID', 'xctasy8XvGp2cVO9HL9k')

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

db.init_db()


def get_therapist_prompt():
    return """You are a compassionate, professional AI therapist. Your role is to:
    - Listen actively and empathetically
    - Ask thoughtful, open-ended questions
    - Provide supportive and non-judgmental responses
    - Help users explore their thoughts and feelings
    - Offer coping strategies when appropriate
    - Maintain professional boundaries
    - Always remind users that you're an AI and suggest professional help for serious concerns
    - Do not give too long replies. it should range between 10 to 30 words.

    Keep responses concise but warm, typically 2-4 sentences. Focus on understanding and supporting the user."""


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


# ---------- Pages ----------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('chat_page'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('chat_page'))
    return render_template('login.html')


@app.route('/signup', methods=['GET'])
def signup():
    if 'user_id' in session:
        return redirect(url_for('chat_page'))
    return render_template('signup.html')


@app.route('/chat')
@login_required
def chat_page():
    user = db.get_user_by_id(session['user_id'])
    return render_template('chat.html', user=user)


# ---------- Auth API ----------

@app.route('/api/signup', methods=['POST'])
def api_signup():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not username or not email or not password:
        return jsonify({'error': 'All fields are required'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Please enter a valid email'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    if db.get_user_by_email(email):
        return jsonify({'error': 'An account with this email already exists'}), 400
    if db.get_user_by_username(username):
        return jsonify({'error': 'Username is already taken'}), 400

    user_id = db.create_user(username, email, generate_password_hash(password))
    session['user_id'] = user_id
    session.permanent = True
    return jsonify({'success': True, 'user': {'id': user_id, 'username': username, 'email': email}})


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    identifier = (data.get('identifier') or data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not identifier or not password:
        return jsonify({'error': 'Please provide your credentials'}), 400

    user = db.get_user_by_email(identifier) or db.get_user_by_username(identifier)
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401

    session['user_id'] = user['id']
    session.permanent = True
    return jsonify({
        'success': True,
        'user': {'id': user['id'], 'username': user['username'], 'email': user['email']}
    })


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/api/me', methods=['GET'])
@login_required
def api_me():
    return jsonify({'user': db.get_user_by_id(session['user_id'])})


# ---------- Conversations API ----------

@app.route('/api/conversations', methods=['GET'])
@login_required
def api_list_conversations():
    return jsonify({'conversations': db.list_conversations(session['user_id'])})


@app.route('/api/conversations', methods=['POST'])
@login_required
def api_create_conversation():
    data = request.json or {}
    title = (data.get('title') or 'New Conversation').strip() or 'New Conversation'
    conv_id = db.create_conversation(session['user_id'], title)
    return jsonify({'conversation': {'id': conv_id, 'title': title}})


@app.route('/api/conversations/<int:conv_id>', methods=['GET'])
@login_required
def api_get_conversation(conv_id):
    conv = db.get_conversation(conv_id, session['user_id'])
    if not conv:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'conversation': conv,
        'messages': db.get_messages(conv_id)
    })


@app.route('/api/conversations/<int:conv_id>', methods=['DELETE'])
@login_required
def api_delete_conversation(conv_id):
    conv = db.get_conversation(conv_id, session['user_id'])
    if not conv:
        return jsonify({'error': 'Not found'}), 404
    db.delete_conversation(conv_id, session['user_id'])
    return jsonify({'success': True})


@app.route('/api/conversations/<int:conv_id>/rename', methods=['POST'])
@login_required
def api_rename_conversation(conv_id):
    conv = db.get_conversation(conv_id, session['user_id'])
    if not conv:
        return jsonify({'error': 'Not found'}), 404
    title = (request.json or {}).get('title', '').strip()
    if not title:
        return jsonify({'error': 'Title required'}), 400
    db.update_conversation_title(conv_id, session['user_id'], title)
    return jsonify({'success': True})


# ---------- Chat ----------

def derive_title(text):
    text = ' '.join(text.split())
    return (text[:40] + '…') if len(text) > 40 else text or 'New Conversation'


MEMORY_UPDATE_INTERVAL = 8  # update memory every N new messages
MEMORY_CHAR_CAP = 500


def build_system_prompt(user_id):
    base = get_therapist_prompt()
    mem = db.get_user_memory(user_id)
    memory_text = (mem or {}).get('memory_text', '').strip()
    if not memory_text:
        return base
    return (
        base
        + "\n\nBackground on this user (from prior sessions — use only as quiet context, "
          "do not bring it up unless directly relevant):\n"
        + memory_text
    )


def _format_messages_for_memory(msgs, limit=30):
    snippets = []
    for m in msgs[-limit:]:
        role = 'User' if m['role'] == 'user' else 'Therapist'
        text = (m['content'] or '').strip().replace('\n', ' ')
        if len(text) > 240:
            text = text[:240] + '…'
        snippets.append(f"{role}: {text}")
    return '\n'.join(snippets)


def _update_memory_sync(user_id):
    """Regenerate the user's persistent memory from their recent messages."""
    if not groq_client:
        return
    try:
        total = db.count_user_messages(user_id)
        if total < 4:
            return
        existing = db.get_user_memory(user_id)
        existing_text = (existing or {}).get('memory_text', '')
        recent = db.get_recent_user_messages(user_id, limit=30)
        if not recent:
            return

        prompt = (
            "You maintain a short profile of an AI-therapy user to help future sessions feel personal. "
            f"Rewrite the profile in plain prose, max {MEMORY_CHAR_CAP} characters, 3-5 short sentences. "
            "Capture: recurring feelings/themes, current struggles, coping strategies they've tried, "
            "tone/preferences (e.g. wants practical advice vs. just to vent). "
            "Use neutral, third-person language. No headings, no bullets, no quotes."
        )
        user_block = (
            f"EXISTING PROFILE:\n{existing_text or '(none yet)'}\n\n"
            f"RECENT CONVERSATION SNIPPETS:\n{_format_messages_for_memory(recent)}\n\n"
            f"UPDATED PROFILE (max {MEMORY_CHAR_CAP} chars):"
        )
        completion = groq_client.chat.completions.create(
            messages=[
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': user_block},
            ],
            model='llama-3.1-8b-instant',
            temperature=0.3,
            max_tokens=220,
        )
        new_memory = (completion.choices[0].message.content or '').strip()
        if new_memory:
            db.upsert_user_memory(user_id, new_memory[:MEMORY_CHAR_CAP], total)
    except Exception as e:
        # Memory updates are best-effort; never break the chat flow.
        app.logger.warning(f'Memory update failed for user {user_id}: {e}')


def _maybe_update_memory_async(user_id):
    """Trigger a memory refresh in a background thread if enough new content has accumulated."""
    try:
        mem = db.get_user_memory(user_id)
        last_count = (mem or {}).get('last_message_count', 0)
        total = db.count_user_messages(user_id)
        if total - last_count < MEMORY_UPDATE_INTERVAL:
            return
        t = threading.Thread(target=_update_memory_sync, args=(user_id,), daemon=True)
        t.start()
    except Exception as e:
        app.logger.warning(f'Memory trigger failed: {e}')


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    if not groq_client:
        return jsonify({'error': 'GROQ_API_KEY not configured on the server'}), 500

    data = request.json or {}
    user_message = (data.get('message') or '').strip()
    conv_id = data.get('conversation_id')

    if not user_message:
        return jsonify({'error': 'Message is required'}), 400

    user_id = session['user_id']
    is_new = False

    if conv_id:
        conv = db.get_conversation(int(conv_id), user_id)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
    else:
        conv_id = db.create_conversation(user_id, derive_title(user_message))
        is_new = True

    history = db.get_messages(conv_id)
    messages = [{'role': 'system', 'content': build_system_prompt(user_id)}]
    for m in history[-20:]:
        messages.append({'role': m['role'], 'content': m['content']})
    messages.append({'role': 'user', 'content': user_message})

    try:
        completion = groq_client.chat.completions.create(
            messages=messages,
            model='llama-3.1-8b-instant',
            temperature=0.7,
            max_tokens=300
        )
        ai_response = completion.choices[0].message.content
    except Exception as e:
        return jsonify({'error': f'AI error: {e}'}), 500

    db.add_message(conv_id, 'user', user_message)
    db.add_message(conv_id, 'assistant', ai_response)

    # If the conversation title is still the default, derive one from the first user message
    conv = db.get_conversation(conv_id, user_id)
    if is_new or conv['title'] == 'New Conversation':
        db.update_conversation_title(conv_id, user_id, derive_title(user_message))

    # Best-effort memory refresh in the background; never blocks the response.
    _maybe_update_memory_async(user_id)

    return jsonify({
        'response': ai_response,
        'conversation_id': conv_id,
        'is_new': is_new
    })


@app.route('/api/insights', methods=['POST'])
@login_required
def api_insights():
    if not groq_client:
        return jsonify({'error': 'GROQ_API_KEY not configured on the server'}), 500

    user_id = session['user_id']
    total = db.count_user_messages(user_id)
    if total < 2:
        return jsonify({
            'insights': "I haven't gathered enough from our conversations yet. "
                        "Share a few thoughts with me first — then I can offer personalised reflections."
        })

    # Refresh memory synchronously so insights use the very latest signal
    _update_memory_sync(user_id)

    mem = db.get_user_memory(user_id)
    memory_text = (mem or {}).get('memory_text', '')
    recent = db.get_recent_user_messages(user_id, limit=20)

    system = (
        "You are a warm, compassionate therapist reviewing a user's journey. "
        "Based on their profile and recent themes, give a short personalised reflection. "
        "Use markdown with three sections, each one short paragraph (max 2 sentences):\n"
        "**What I've noticed** — recurring feelings/themes.\n"
        "**Strengths I see in you** — resilience or coping you've shown.\n"
        "**Gentle suggestions** — 2-3 concrete, kind ideas tailored to them.\n"
        "Address them as \"you\". Keep total response under 180 words. Never invent facts not in the profile."
    )
    user_block = (
        f"PROFILE:\n{memory_text or '(no profile yet)'}\n\n"
        f"RECENT MESSAGES:\n{_format_messages_for_memory(recent)}"
    )
    try:
        completion = groq_client.chat.completions.create(
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_block},
            ],
            model='llama-3.1-8b-instant',
            temperature=0.6,
            max_tokens=400,
        )
        insights = (completion.choices[0].message.content or '').strip()
        return jsonify({'insights': insights, 'memory': memory_text})
    except Exception as e:
        return jsonify({'error': f'Could not generate insights: {e}'}), 500


# ---------- Text-to-Speech ----------

@app.route('/api/text-to-speech', methods=['POST'])
@login_required
def text_to_speech():
    try:
        data = request.json or {}
        text = (data.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'Text is required'}), 400

        if not ELEVENLABS_API_KEY or ELEVENLABS_API_KEY == 'your_elevenlabs_api_key_here':
            return jsonify({'error': 'ElevenLabs API key not configured'}), 400

        url = f'https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}'
        headers = {
            'Accept': 'audio/mpeg',
            'Content-Type': 'application/json',
            'xi-api-key': ELEVENLABS_API_KEY
        }
        payload = {
            'text': text,
            'model_id': 'eleven_monolingual_v1',
            'voice_settings': {'stability': 0.5, 'similarity_boost': 0.5}
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code != 200:
            return jsonify({'error': f'ElevenLabs error {response.status_code}: {response.text[:200]}'}), 500

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        tmp.write(response.content)
        tmp.close()
        return send_file(tmp.name, mimetype='audio/mpeg', as_attachment=False, download_name='speech.mp3')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--https':
        app.run(debug=True, host='0.0.0.0', port=5000, ssl_context='adhoc')
    else:
        app.run(debug=True, host='0.0.0.0', port=5000)
