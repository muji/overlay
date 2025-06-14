import os
import sqlite3
from datetime import datetime
from typing import Optional

DATABASE = "recordings.db"

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        camera_no INTEGER,
        start_time DATETIME,
        end_time DATETIME
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT,
        chunk_path TEXT UNIQUE,
        start_time DATETIME,
        end_time DATETIME,
        status TEXT,
        slow_chunk_path TEXT
    )''')

    conn.commit()
    conn.close()

def add_session(token, camera_no, start_time):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                     (token, camera_no, start_time, None))

def update_session_end_time(token, end_time):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("UPDATE sessions SET end_time = ? WHERE token = ?",
                     (end_time, token))

def add_chunk(token, chunk_path, start_time, estimated_end):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute('''INSERT INTO chunks (
            token, chunk_path, start_time, end_time, status, slow_chunk_path
        ) VALUES (?, ?, ?, ?, 'recording', NULL)''',
        (token, chunk_path, start_time, estimated_end))

def add_generated_chunk(token, chunk_path, start_time, end_time):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute('''INSERT OR IGNORE INTO chunks (
            token, chunk_path, start_time, end_time, status
        ) VALUES (?, ?, ?, ?, 'generated')''',
        (token, chunk_path, start_time, end_time))


def update_chunk_end_time(chunk_path: str, end_time: datetime):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute('''UPDATE chunks
                        SET end_time = ?
                        WHERE chunk_path = ?''',
                     (end_time.isoformat(), chunk_path))


def update_chunk_completion(chunk_path, end_time):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute('''UPDATE chunks
            SET end_time = ?, status = 'complete'
            WHERE chunk_path = ?''',
            (end_time, chunk_path))

def update_chunk_slow_path(chunk_path: str, slow_chunk_path: str):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute('''UPDATE chunks
            SET slow_chunk_path = ?
            WHERE chunk_path = ?''',
            (slow_chunk_path, chunk_path))
        
        


def mark_chunk_corrupt(chunk_path):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("UPDATE chunks SET status = 'corrupt' WHERE chunk_path = ?",
                     (chunk_path,))

def delete_chunk_by_path(chunk_path: str):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chunks WHERE chunk_path LIKE ?", (f"%{os.path.basename(chunk_path)}%",))
        conn.commit()


def get_active_sessions():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT token, camera_no, start_time FROM sessions WHERE end_time IS NULL")
        return cursor.fetchall()

def get_session_chunks(token):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.token, c.chunk_path, c.start_time, 
                   c.end_time, c.status, s.camera_no, c.slow_chunk_path
            FROM chunks c
            JOIN sessions s ON c.token = s.token
            WHERE c.token = ?
        ''', (token,))
        return cursor.fetchall()

def get_all_recordings():
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.token, c.chunk_path, c.start_time, 
                   c.end_time, c.status, s.camera_no, c.slow_chunk_path
            FROM chunks c
            JOIN sessions s ON c.token = s.token
        ''')
        return cursor.fetchall()

def get_chunk_info_by_id(chunk_id: int) -> Optional[tuple]:
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.chunk_path, s.camera_no 
            FROM chunks c
            JOIN sessions s ON c.token = s.token
            WHERE c.id = ?
        ''', (chunk_id,))
        return cursor.fetchone()

def get_chunk_path_by_id(chunk_id: int) -> Optional[str]:
    result = get_chunk_info_by_id(chunk_id)
    return result[0] if result else None

# Always initialize DB on import
init_db()
