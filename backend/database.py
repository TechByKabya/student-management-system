import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "attendance.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # Create Students table with expanded fields
    conn.execute('''
        CREATE TABLE IF NOT EXISTS Students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            school_id TEXT UNIQUE NOT NULL,
            phone TEXT DEFAULT '',
            photo_path TEXT,
            q1 REAL DEFAULT 0.0,
            q2 REAL DEFAULT 0.0,
            q3 REAL DEFAULT 0.0,
            presentation REAL DEFAULT 0.0,
            mid REAL DEFAULT 0.0,
            final REAL DEFAULT 0.0,
            fingerprint_id INTEGER DEFAULT 0,
            rfid_uid TEXT DEFAULT '',
            is_blacklisted INTEGER DEFAULT 0
        )
    ''')
    
    # Create AttendanceLogs table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS AttendanceLogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sensor_type TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES Students(id)
        )
    ''')
    
    # Create Admin table for teacher settings
    conn.execute('''
        CREATE TABLE IF NOT EXISTS Admin (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            username TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    # Add SMS credential columns if they don't already exist (safe migration)
    try:
        conn.execute("ALTER TABLE Admin ADD COLUMN teacher_rfid TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE Admin ADD COLUMN sms_api_key TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE Admin ADD COLUMN sms_sender_id TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE Students ADD COLUMN is_blacklisted INTEGER DEFAULT 0")
    except Exception:
        pass

    # Track which students have received an absence SMS per day (prevent duplicates)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS SmsSentLog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            UNIQUE(date, student_id)
        )
    ''')

    # Voice recordings per student per day (for cross-match proxy detection)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS VoiceRecordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            file_path TEXT NOT NULL,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_proxy_source INTEGER DEFAULT 0,
            FOREIGN KEY(student_id) REFERENCES Students(id)
        )
    ''')
    # Safe migration: add is_proxy_source if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE VoiceRecordings ADD COLUMN is_proxy_source INTEGER DEFAULT 0")
    except Exception:
        pass

    # Voice match results — cross-comparison between same-day recordings
    conn.execute('''
        CREATE TABLE IF NOT EXISTS VoiceMatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            student_a_id INTEGER NOT NULL,
            student_b_id INTEGER NOT NULL,
            score REAL NOT NULL,
            is_proxy INTEGER DEFAULT 0,
            resolved_by TEXT DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_a_id) REFERENCES Students(id),
            FOREIGN KEY(student_b_id) REFERENCES Students(id)
        )
    ''')

    # Insert default admin if none exists
    admin_exists = conn.execute("SELECT COUNT(*) as count FROM Admin").fetchone()
    if admin_exists['count'] == 0:
        conn.execute("INSERT INTO Admin (id, username, password) VALUES (1, 'admin', 'admin')")
    
    conn.commit()
    conn.close()

# Basic Data Access Objects
def create_student(name: str, school_id: str, phone: str = "", photo_path: str = ""):
    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO Students (name, school_id, phone, photo_path) VALUES (?, ?, ?, ?)",
        (name, school_id, phone, photo_path)
    )
    conn.commit()
    inserted_id = cursor.lastrowid
    conn.close()
    return inserted_id

def update_student_marks(student_id: int, q1, q2, q3, presentation, mid, final):
    conn = get_db_connection()
    conn.execute(
        "UPDATE Students SET q1=?, q2=?, q3=?, presentation=?, mid=?, final=? WHERE id=?",
        (q1, q2, q3, presentation, mid, final, student_id)
    )
    conn.commit()
    conn.close()

def get_admin_credentials():
    conn = get_db_connection()
    admin = conn.execute("SELECT * FROM Admin WHERE id = 1").fetchone()
    conn.close()
    return dict(admin) if admin else {'username': 'admin', 'password': 'admin', 'teacher_rfid': ''}

def update_admin_credentials(username, password, teacher_rfid, sms_api_key='', sms_sender_id=''):
    conn = get_db_connection()
    conn.execute(
        "UPDATE Admin SET username = ?, password = ?, teacher_rfid = ?, sms_api_key = ?, sms_sender_id = ? WHERE id = 1",
        (username, password, teacher_rfid, sms_api_key, sms_sender_id)
    )
    conn.commit()
    conn.close()

def get_sms_credentials():
    conn = get_db_connection()
    admin = conn.execute("SELECT sms_api_key, sms_sender_id FROM Admin WHERE id = 1").fetchone()
    conn.close()
    if admin:
        return {'api_key': admin['sms_api_key'] or '', 'sender_id': admin['sms_sender_id'] or ''}
    return {'api_key': '', 'sender_id': ''}

def has_sms_been_sent(date_str: str, student_id: int) -> bool:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT 1 FROM SmsSentLog WHERE date = ? AND student_id = ?",
        (date_str, student_id)
    ).fetchone()
    conn.close()
    return row is not None

def mark_sms_sent(date_str: str, student_id: int):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO SmsSentLog (date, student_id) VALUES (?, ?)",
            (date_str, student_id)
        )
        conn.commit()
    finally:
        conn.close()

def reset_sms_logs_for_today(date_str: str):
    """Clears the SMS sent logs for a specific date (used for demo purposes)."""
    conn = get_db_connection()
    conn.execute("DELETE FROM SmsSentLog WHERE date = ?", (date_str,))
    conn.commit()
    conn.close()

def get_students_with_attendance_on(date_str: str):
    """Returns a set of student_ids who attended on the given date."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT DISTINCT student_id FROM AttendanceLogs WHERE date(timestamp, 'localtime') = ?",
        (date_str,)
    ).fetchall()
    conn.close()
    return {row['student_id'] for row in rows}

def get_daily_status(date_str: str):
    conn = get_db_connection()
    status = conn.execute("SELECT is_open FROM DailyStatus WHERE date = ?", (date_str,)).fetchone()
    conn.close()
    return status['is_open'] if status else 0

def toggle_daily_status(date_str: str):
    conn = get_db_connection()
    status = conn.execute("SELECT is_open FROM DailyStatus WHERE date = ?", (date_str,)).fetchone()
    if status is None:
        new_status = 1
        conn.execute("INSERT INTO DailyStatus (date, is_open) VALUES (?, ?)", (date_str, new_status))
    else:
        new_status = 0 if status['is_open'] == 1 else 1
        conn.execute("UPDATE DailyStatus SET is_open = ? WHERE date = ?", (new_status, date_str))
    conn.commit()
    conn.close()
    return new_status

def set_daily_status(date_str: str, is_open: int):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO DailyStatus (date, is_open) VALUES (?, ?)", (date_str, is_open))
    conn.commit()
    conn.close()

def get_all_students():
    conn = get_db_connection()
    students = conn.execute("SELECT * FROM Students").fetchall()
    conn.close()
    return [dict(s) for s in students]

def get_student_by_id(student_id: int):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM Students WHERE id = ?", (student_id,)).fetchone()
    conn.close()
    return dict(student) if student else None

def get_student_by_school_id(school_id: str):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM Students WHERE school_id = ?", (school_id,)).fetchone()
    conn.close()
    return dict(student) if student else None

def get_student_by_fingerprint(fingerprint_id: int):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM Students WHERE fingerprint_id = ?", (fingerprint_id,)).fetchone()
    conn.close()
    return dict(student) if student else None

def get_student_by_rfid(rfid_uid: str):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM Students WHERE rfid_uid = ?", (rfid_uid,)).fetchone()
    conn.close()
    return dict(student) if student else None

def update_student_sensors(student_id: int, fingerprint_id: int, rfid_uid: str):
    conn = get_db_connection()
    conn.execute(
        "UPDATE Students SET fingerprint_id = ?, rfid_uid = ? WHERE id = ?", 
        (fingerprint_id, rfid_uid, student_id)
    )
    conn.commit()
    conn.close()

def set_student_blacklist(student_id: int, is_blacklisted: int):
    conn = get_db_connection()
    conn.execute(
        "UPDATE Students SET is_blacklisted = ? WHERE id = ?",
        (is_blacklisted, student_id)
    )
    conn.commit()
    conn.close()

def log_attendance(student_id: int, sensor_type: str, timestamp: str = None):  # type: ignore[assignment]
    conn = get_db_connection()
    if timestamp:
        conn.execute(
            "INSERT INTO AttendanceLogs (student_id, sensor_type, timestamp) VALUES (?, ?, ?)", 
            (student_id, sensor_type, timestamp)
        )
    else:
        conn.execute(
            "INSERT INTO AttendanceLogs (student_id, sensor_type) VALUES (?, ?)", 
            (student_id, sensor_type)
        )
    conn.commit()
    conn.close()

def get_today_attendance_count():
    conn = get_db_connection()
    # Convert stored UTC timestamp to localtime before comparing with today's localtime
    count = conn.execute("SELECT COUNT(DISTINCT student_id) as count FROM AttendanceLogs WHERE date(timestamp, 'localtime') = date('now', 'localtime')").fetchone()
    conn.close()
    return count['count'] if count else 0

def get_student_attendance_count(student_id: int):
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) as count FROM AttendanceLogs WHERE student_id = ?", (student_id,)).fetchone()
    conn.close()
    return count['count'] if count else 0

def get_all_attendance_logs():
    conn = get_db_connection()
    # Join with Students table to get the name, and convert UTC to localtime for display
    logs = conn.execute('''
        SELECT a.id, a.student_id, s.name, s.school_id, a.sensor_type, datetime(a.timestamp, 'localtime') as local_time, date(a.timestamp, 'localtime') as local_date
        FROM AttendanceLogs a
        JOIN Students s ON a.student_id = s.id
        ORDER BY a.timestamp DESC
    ''').fetchall()
    conn.close()
    return [dict(row) for row in logs]

def delete_attendance_log(log_id: int):
    conn = get_db_connection()
    conn.execute("DELETE FROM AttendanceLogs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()

def delete_student(student_id: int):
    conn = get_db_connection()
    # First delete their attendance logs to maintain referential integrity
    conn.execute("DELETE FROM AttendanceLogs WHERE student_id = ?", (student_id,))
    # Then delete the student
    conn.execute("DELETE FROM Students WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()

def wipe_all_fingerprints():
    """Master Reset: clear fingerprint_id and rfid_uid for every student."""
    conn = get_db_connection()
    conn.execute("UPDATE Students SET fingerprint_id = 0, rfid_uid = ''")
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────
# Voice Recording & Match Functions
# ─────────────────────────────────────────────────────────

def log_voice_recording(student_id: int, date: str, file_path: str) -> int:
    """Save a voice recording entry. Returns the new row ID."""
    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO VoiceRecordings (student_id, date, file_path) VALUES (?, ?, ?)",
        (student_id, date, file_path)
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_voice_recordings_for_date(date: str, exclude_proxy: bool = False):
    """Return all voice recordings for a given date with student info.
    
    Args:
        date: The date string (YYYY-MM-DD) to fetch recordings for.
        exclude_proxy: If True, excludes recordings flagged as proxy sources
                       so they are not used as matching targets for future students.
                       The recordings still exist in DB and on disk for review.
    """
    conn = get_db_connection()
    proxy_filter = "AND vr.is_proxy_source = 0" if exclude_proxy else ""
    rows = conn.execute(f'''
        SELECT vr.id, vr.student_id, s.name, s.school_id, vr.file_path,
               datetime(vr.recorded_at, 'localtime') as recorded_at,
               vr.is_proxy_source
        FROM VoiceRecordings vr
        JOIN Students s ON vr.student_id = s.id
        WHERE vr.date = ? {proxy_filter}
        ORDER BY vr.recorded_at ASC
    ''', (date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_voice_recording_for_student_date(student_id: int, date: str):
    """Get the voice recording for a specific student on a given date."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM VoiceRecordings WHERE student_id = ? AND date = ? ORDER BY recorded_at DESC LIMIT 1",
        (student_id, date)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def log_voice_match(date: str, student_a_id: int, student_b_id: int,
                    score: float, is_proxy: int) -> int:
    """Save a voice match comparison result. Returns new row ID."""
    conn = get_db_connection()
    cursor = conn.execute(
        """INSERT INTO VoiceMatches (date, student_a_id, student_b_id, score, is_proxy)
           VALUES (?, ?, ?, ?, ?)""",
        (date, student_a_id, student_b_id, round(score, 4), is_proxy)
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def mark_recording_as_proxy_source(student_id: int, date: str):
    """Flag a student's voice recording for a given day as a proxy source.
    
    Proxy-flagged recordings are kept on disk and in the DB for review/comparison
    purposes, but will be excluded from future cross-match comparisons so they
    don't incorrectly flag legitimate students who scan after the proxy attempt.
    """
    conn = get_db_connection()
    conn.execute(
        "UPDATE VoiceRecordings SET is_proxy_source = 1 WHERE student_id = ? AND date = ?",
        (student_id, date)
    )
    conn.commit()
    conn.close()


def get_voice_matches_for_date(date: str):
    """Return all cross-match results for a given date with student names."""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT vm.id, vm.date, vm.score, vm.is_proxy, vm.resolved_by,
               datetime(vm.created_at, 'localtime') as created_at,
               sa.name as student_a_name, sa.school_id as student_a_school_id,
               sb.name as student_b_name, sb.school_id as student_b_school_id,
               vm.student_a_id, vm.student_b_id
        FROM VoiceMatches vm
        JOIN Students sa ON vm.student_a_id = sa.id
        JOIN Students sb ON vm.student_b_id = sb.id
        WHERE vm.date = ?
        ORDER BY vm.score DESC
    ''', (date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_voice_matches(limit: int = 200):
    """Return all voice match records across all dates (newest first)."""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT vm.id, vm.date, vm.score, vm.is_proxy, vm.resolved_by,
               datetime(vm.created_at, 'localtime') as created_at,
               sa.name as student_a_name, sa.school_id as student_a_school_id,
               sb.name as student_b_name, sb.school_id as student_b_school_id,
               vm.student_a_id, vm.student_b_id
        FROM VoiceMatches vm
        JOIN Students sa ON vm.student_a_id = sa.id
        JOIN Students sb ON vm.student_b_id = sb.id
        ORDER BY vm.created_at DESC
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_voice_dates():
    """Return distinct dates that have voice recordings, newest first."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT DISTINCT date FROM VoiceRecordings ORDER BY date DESC"
    ).fetchall()
    conn.close()
    return [r['date'] for r in rows]


def resolve_voice_match(match_id: int, resolved_by: str):
    """Mark a voice match as resolved (e.g. 'FINGERPRINT_OK' or 'BLACKLISTED')."""
    conn = get_db_connection()
    conn.execute(
        "UPDATE VoiceMatches SET resolved_by = ? WHERE id = ?",
        (resolved_by, match_id)
    )
    conn.commit()
    conn.close()
