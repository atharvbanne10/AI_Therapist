"""
SQLite database layer for Mindful AI.

For deployment:
- Local: a `therapist.db` file is created in the project root.
- Production (Render/Railway/Fly.io): mount a persistent disk and point
  DATABASE_PATH at it, e.g. /var/data/therapist.db. To switch to Postgres
  later, replace these helpers with SQLAlchemy or psycopg2; the route
  layer in app.py only depends on the functions exported here.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DATABASE_PATH = os.getenv('DATABASE_PATH', 'therapist.db')


@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_memory (
                user_id INTEGER PRIMARY KEY,
                memory_text TEXT NOT NULL DEFAULT '',
                last_message_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
        ''')


def now_iso():
    return datetime.utcnow().isoformat()


# ---------- Users ----------

def create_user(username, email, password_hash):
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            (username, email, password_hash, now_iso())
        )
        return cur.lastrowid


def get_user_by_email(email):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        return dict(row) if row else None


def get_user_by_username(username):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT id, username, email, created_at FROM users WHERE id = ?', (user_id,)).fetchone()
        return dict(row) if row else None


# ---------- Conversations ----------

def create_conversation(user_id, title='New Conversation'):
    ts = now_iso()
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)',
            (user_id, title, ts, ts)
        )
        return cur.lastrowid


def list_conversations(user_id):
    with get_db() as conn:
        rows = conn.execute(
            'SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC',
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_conversation(conversation_id, user_id):
    with get_db() as conn:
        row = conn.execute(
            'SELECT * FROM conversations WHERE id = ? AND user_id = ?',
            (conversation_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def update_conversation_title(conversation_id, user_id, title):
    with get_db() as conn:
        conn.execute(
            'UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?',
            (title, now_iso(), conversation_id, user_id)
        )


def touch_conversation(conversation_id):
    with get_db() as conn:
        conn.execute(
            'UPDATE conversations SET updated_at = ? WHERE id = ?',
            (now_iso(), conversation_id)
        )


def delete_conversation(conversation_id, user_id):
    with get_db() as conn:
        conn.execute(
            'DELETE FROM conversations WHERE id = ? AND user_id = ?',
            (conversation_id, user_id)
        )


# ---------- Messages ----------

def add_message(conversation_id, role, content):
    with get_db() as conn:
        conn.execute(
            'INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)',
            (conversation_id, role, content, now_iso())
        )
        conn.execute(
            'UPDATE conversations SET updated_at = ? WHERE id = ?',
            (now_iso(), conversation_id)
        )


def get_messages(conversation_id):
    with get_db() as conn:
        rows = conn.execute(
            'SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC',
            (conversation_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- User memory (Option B: persistent profile) ----------

def get_user_memory(user_id):
    with get_db() as conn:
        row = conn.execute(
            'SELECT memory_text, last_message_count, updated_at FROM user_memory WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        return dict(row) if row else None


def upsert_user_memory(user_id, memory_text, message_count):
    with get_db() as conn:
        conn.execute('''
            INSERT INTO user_memory (user_id, memory_text, last_message_count, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                memory_text = excluded.memory_text,
                last_message_count = excluded.last_message_count,
                updated_at = excluded.updated_at
        ''', (user_id, memory_text[:600], message_count, now_iso()))


def count_user_messages(user_id):
    with get_db() as conn:
        row = conn.execute('''
            SELECT COUNT(*) AS c FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE c.user_id = ?
        ''', (user_id,)).fetchone()
        return row['c'] if row else 0


def get_recent_user_messages(user_id, limit=30):
    """Return the user's most recent messages across all conversations, oldest-first."""
    with get_db() as conn:
        rows = conn.execute('''
            SELECT m.role, m.content, m.created_at
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE c.user_id = ?
            ORDER BY m.id DESC
            LIMIT ?
        ''', (user_id, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]
