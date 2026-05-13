"""
PostgreSQL database layer for Mindful AI (Neon-compatible).

Connection is taken from the DATABASE_URL env var, which Neon (or any
Postgres host) provides as:
    postgresql://user:pass@host/dbname?sslmode=require

The rest of the app talks only to the functions defined here, so the
storage backend can be swapped without touching app.py.
"""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL')


@contextmanager
def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Put your Neon connection string in "
            ".env (locally) or in the Render environment variables."
        )
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fetchone(conn, sql, params=()):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def _fetchall(conn, sql, params=()):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def _execute(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    cur.close()


def _execute_returning_id(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    new_id = cur.fetchone()[0]
    cur.close()
    return new_id


def init_db():
    with get_db() as conn:
        _execute(conn, '''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        _execute(conn, '''
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        _execute(conn, '''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        _execute(conn, '''
            CREATE TABLE IF NOT EXISTS user_memory (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                memory_text TEXT NOT NULL DEFAULT '',
                last_message_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        ''')
        _execute(conn, 'CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC)')
        _execute(conn, 'CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id)')


def now_iso():
    return datetime.utcnow().isoformat()


# ---------- Users ----------

def create_user(username, email, password_hash):
    with get_db() as conn:
        return _execute_returning_id(
            conn,
            'INSERT INTO users (username, email, password_hash, created_at) '
            'VALUES (%s, %s, %s, %s) RETURNING id',
            (username, email, password_hash, now_iso())
        )


def get_user_by_email(email):
    with get_db() as conn:
        return _fetchone(conn, 'SELECT * FROM users WHERE email = %s', (email,))


def get_user_by_username(username):
    with get_db() as conn:
        return _fetchone(conn, 'SELECT * FROM users WHERE username = %s', (username,))


def get_user_by_id(user_id):
    with get_db() as conn:
        return _fetchone(
            conn,
            'SELECT id, username, email, created_at FROM users WHERE id = %s',
            (user_id,)
        )


# ---------- Conversations ----------

def create_conversation(user_id, title='New Conversation'):
    ts = now_iso()
    with get_db() as conn:
        return _execute_returning_id(
            conn,
            'INSERT INTO conversations (user_id, title, created_at, updated_at) '
            'VALUES (%s, %s, %s, %s) RETURNING id',
            (user_id, title, ts, ts)
        )


def list_conversations(user_id):
    with get_db() as conn:
        return _fetchall(
            conn,
            'SELECT id, title, created_at, updated_at FROM conversations '
            'WHERE user_id = %s ORDER BY updated_at DESC',
            (user_id,)
        )


def get_conversation(conversation_id, user_id):
    with get_db() as conn:
        return _fetchone(
            conn,
            'SELECT * FROM conversations WHERE id = %s AND user_id = %s',
            (conversation_id, user_id)
        )


def update_conversation_title(conversation_id, user_id, title):
    with get_db() as conn:
        _execute(
            conn,
            'UPDATE conversations SET title = %s, updated_at = %s WHERE id = %s AND user_id = %s',
            (title, now_iso(), conversation_id, user_id)
        )


def touch_conversation(conversation_id):
    with get_db() as conn:
        _execute(
            conn,
            'UPDATE conversations SET updated_at = %s WHERE id = %s',
            (now_iso(), conversation_id)
        )


def delete_conversation(conversation_id, user_id):
    with get_db() as conn:
        _execute(
            conn,
            'DELETE FROM conversations WHERE id = %s AND user_id = %s',
            (conversation_id, user_id)
        )


# ---------- Messages ----------

def add_message(conversation_id, role, content):
    ts = now_iso()
    with get_db() as conn:
        _execute(
            conn,
            'INSERT INTO messages (conversation_id, role, content, created_at) '
            'VALUES (%s, %s, %s, %s)',
            (conversation_id, role, content, ts)
        )
        _execute(
            conn,
            'UPDATE conversations SET updated_at = %s WHERE id = %s',
            (ts, conversation_id)
        )


def get_messages(conversation_id):
    with get_db() as conn:
        return _fetchall(
            conn,
            'SELECT role, content, created_at FROM messages '
            'WHERE conversation_id = %s ORDER BY id ASC',
            (conversation_id,)
        )


# ---------- User memory (Option B: persistent profile) ----------

def get_user_memory(user_id):
    with get_db() as conn:
        return _fetchone(
            conn,
            'SELECT memory_text, last_message_count, updated_at '
            'FROM user_memory WHERE user_id = %s',
            (user_id,)
        )


def upsert_user_memory(user_id, memory_text, message_count):
    with get_db() as conn:
        _execute(conn, '''
            INSERT INTO user_memory (user_id, memory_text, last_message_count, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                memory_text = EXCLUDED.memory_text,
                last_message_count = EXCLUDED.last_message_count,
                updated_at = EXCLUDED.updated_at
        ''', (user_id, memory_text[:600], message_count, now_iso()))


def count_user_messages(user_id):
    with get_db() as conn:
        row = _fetchone(conn, '''
            SELECT COUNT(*) AS c FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE c.user_id = %s
        ''', (user_id,))
        return row['c'] if row else 0


def get_recent_user_messages(user_id, limit=30):
    """Return the user's most recent messages across all conversations, oldest-first."""
    with get_db() as conn:
        rows = _fetchall(conn, '''
            SELECT m.role, m.content, m.created_at
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE c.user_id = %s
            ORDER BY m.id DESC
            LIMIT %s
        ''', (user_id, limit))
        return list(reversed(rows))
