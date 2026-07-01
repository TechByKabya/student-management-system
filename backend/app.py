import os
import io
import ssl
import time
import threading
# Fix SSL certificate verification on macOS Python 3.8
ssl._create_default_https_context = ssl._create_unverified_context

import numpy as np
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename
from database import (init_db, get_all_students, get_student_by_school_id, create_student, 
                      get_today_attendance_count, log_attendance, update_student_sensors, 
                      get_student_by_fingerprint, get_student_by_rfid, get_student_by_id,
                      get_admin_credentials, update_admin_credentials, update_student_marks,
                      get_all_attendance_logs, wipe_all_fingerprints,
                      get_sms_credentials, has_sms_been_sent, mark_sms_sent,
                      get_students_with_attendance_on, reset_sms_logs_for_today,
                      log_voice_recording, get_voice_recordings_for_date,
                      get_voice_recording_for_student_date, log_voice_match,
                      get_voice_matches_for_date, get_all_voice_matches,
                      get_voice_dates, resolve_voice_match,
                      mark_recording_as_proxy_source)
from sms_service import send_absence_sms, send_grades_sms, send_notice_sms
from c_interop import CoreWrapper
import socket
from zeroconf import ServiceInfo, Zeroconf
import torch, torchaudio
import torchaudio.transforms as T

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = 'super_secret_key_change_in_production'

# Configuration for student photo uploads
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB max (voice WAV can be ~256KB)

# Voice recordings storage directory
VOICE_DIR = os.path.join(os.path.dirname(__file__), '..', 'static', 'voice_recordings')
os.makedirs(VOICE_DIR, exist_ok=True)

# In-memory store for pending voice recordings
# Maps student_id -> {'path': rel_path, 'transcription': text, 'wrong_attempts': list}
PENDING_VOICES = {}
# Maps student_id -> list of wrong transcriptions heard today
WRONG_VOICE_ATTEMPTS = {}

# ──────────────────────────────────────────────────────────
# SpeechBrain Speaker Verification Model (lazy-loaded once)
# ──────────────────────────────────────────────────────────
_speaker_model = None
_asr_model = None
_model_lock = threading.Lock()

def get_speaker_model():
    """Lazy-load the SpeechBrain ECAPA-TDNN model (thread-safe)."""
    global _speaker_model
    if _speaker_model is not None:
        return _speaker_model
    with _model_lock:
        if _speaker_model is None:
            try:
                from speechbrain.pretrained import SpeakerRecognition
                model_dir = os.path.join(os.path.dirname(__file__), '..', 'voice_recog', 'pretrained_models', 'spkrec-ecapa-voxceleb')
                os.makedirs(model_dir, exist_ok=True)
                print("[Voice] Loading SpeechBrain ECAPA-TDNN model...")
                _speaker_model = SpeakerRecognition.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    savedir=model_dir
                )
                print("[Voice] Model loaded OK.")
            except Exception as e:
                print(f"[Voice] WARNING: Could not load SpeechBrain model: {e}")
                _speaker_model = None
    return _speaker_model

def get_asr_model():
    """Lazy-load MLX Whisper module for phrase enforcement."""
    global _asr_model
    if _asr_model is not None:
        return _asr_model
    with _model_lock:
        if _asr_model is None:
            try:
                import mlx_whisper
                print("[Voice] Loading MLX Whisper 'medium' ASR model module...")
                _asr_model = mlx_whisper
                print("[Voice] MLX Whisper ASR module loaded OK.")
            except Exception as e:
                print(f"[Voice] Error loading MLX Whisper ASR module: {e}")
                _asr_model = None
        return _asr_model

def transcribe_audio(file_path: str) -> str:
    # Always use MLX Whisper Large-v3
    asr_model = get_asr_model()
    if asr_model is None:
        raise Exception("MLX Whisper module failed to load.")
    result = asr_model.transcribe(
        file_path,
        path_or_hf_repo="mlx-community/whisper-medium-mlx",
        language="en",
        initial_prompt="Present Sir"
    )
    return result["text"].strip()

def enhance_audio(file_path: str):
    """
    Applies audio processing to improve recording quality (EXACTLY following voice_recog project):
      1. Resample to 16 kHz (model target rate)
      2. Convert to mono
      3. High-pass filter at 80 Hz (removes low-freq rumble from ESP32)
      4. Normalise amplitude to –1..1
    """
    is_silent = False
    try:
        waveform, sr = torchaudio.load(file_path)

        # Resample to 16 kHz if needed
        if sr != 16000:
            waveform = T.Resample(orig_freq=sr, new_freq=16000)(waveform)
            sr = 16000

        # Convert to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        # Silence detection on raw audio before filters
        rms = torch.sqrt(torch.mean(waveform ** 2)).item()
        is_silent = rms < 0.001  # Only flags true dead-air

        # High-pass filter: remove frequencies below 80 Hz
        # Using a simple first-order IIR approximation
        import numpy as np
        RC = 1.0 / (2 * np.pi * 80)
        dt = 1.0 / sr
        alpha = RC / (RC + dt)
        sig = waveform[0].numpy()
        filtered = np.zeros_like(sig)
        filtered[0] = sig[0]
        for i in range(1, len(sig)):
            filtered[i] = alpha * (filtered[i - 1] + sig[i] - sig[i - 1])
        waveform = torch.tensor(filtered).unsqueeze(0)

        # Normalise amplitude
        peak = waveform.abs().max()
        if peak > 0:
            waveform = waveform / peak * 0.95

        torchaudio.save(file_path, waveform, sr)

    except Exception as ex:
        print(f"[enhance_audio] warning: {ex}")
        is_silent = False

    return file_path, is_silent



# Trigger lazy model load in a background thread so the server starts fast
threading.Thread(target=get_speaker_model, daemon=True).start()
threading.Thread(target=get_asr_model, daemon=True).start()

# Global Status mapped for ESP32 polling system
# `mode` determines ESP32 behavior: 'attendance', 'enroll_fingerprint', 'enroll_rfid'
esp32_status = {
    'mode': 'attendance',
    'assign_id': None,  # ID of the SQLite student currently in an enrollment process
    'last_seen': 0,     # Timestamp of last successful status poll
    'captured_rfid': None  # A one-time captured RFID tag from Settings scan mode
}

# Global list to store the most recent AI scans (up to 15)
ai_live_feed = []

def add_to_ai_feed(name, dwell_time, inter_scan, prediction):
    global ai_live_feed
    import datetime
    event = {
        'time': datetime.datetime.now().strftime("%H:%M:%S"),
        'name': name,
        'dwell_time': round(dwell_time, 2) if dwell_time else 0,
        'inter_scan': round(inter_scan, 2) if inter_scan else 0,
        'prediction': prediction
    }
    ai_live_feed.insert(0, event)
    if len(ai_live_feed) > 15:
        ai_live_feed.pop()

# --- System Initialization ---
with app.app_context():
    init_db()          # Prepare SQLite Tables
    CoreWrapper.init() # Clean and prep C memory array
    
    # Pre-load all existing students into the C shared library for fast lookup
    students = get_all_students()
    for s in students:
        CoreWrapper.add_student(
            s['id'], s['name'], s['school_id'], s['phone'],
            s['q1'], s['q2'], s['q3'], s['presentation'], s['mid'], s['final'],
            0, s['fingerprint_id'], s['rfid_uid']
        )

# --- mDNS Registration ---
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.1.1'
    finally:
        s.close()
    return IP

def setup_mdns():
    ip = get_ip()
    print(f"[mDNS] Found local IP: {ip}")
    desc = {'server': 'esp32_attendance_portal'}
    
    info = ServiceInfo(
        "_http._tcp.local.",
        "esp32-node._http._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=5005,
        properties=desc,
        server="esp32-node.local.",
    )

    zeroconf = Zeroconf()
    try:
        zeroconf.register_service(info)
        print("[mDNS] Broadcasting _http._tcp.local. on port 5005")
    except Exception as e:
        print(f"[mDNS] Failed to register service: {e}. If the ESP32 or another instance is already holding this mDNS name, this is expected.")
    return zeroconf

zeroconf_instance = setup_mdns()


# =========================================================
# Shared Notification Logic
# =========================================================

def trigger_absence_sms_if_closed(today: str):
    """Fires a background thread to send SMS if the portal was just closed."""
    import threading
    def send_absence_notifications():
        try:
            sms_creds = get_sms_credentials()
            if not sms_creds['api_key'] or not sms_creds['sender_id']:
                print("[SMS] No API key/Sender ID configured. Skipping absence notifications.")
                return
            
            all_students = get_all_students()
            attended_ids = get_students_with_attendance_on(today)
            
            # Absent = enrolled but did NOT attend today AND haven't been SMS'd yet today
            to_notify = [
                s for s in all_students
                if s['id'] not in attended_ids
                and not has_sms_been_sent(today, s['id'])
            ]
            
            if not to_notify:
                print(f"[SMS] No new absent students to notify for {today}.")
                return
            
            print(f"[SMS] Sending absence SMS to {len(to_notify)} student(s) for {today}...")
            results = send_absence_sms(sms_creds['api_key'], sms_creds['sender_id'], to_notify)
            
            # Mark as sent so they don't get duplicates if portal re-opens/closes again
            for sid in results['sent']:
                mark_sms_sent(today, sid)
            # Also mark skipped (no phone) so we don't re-attempt them pointlessly
            for sid in results['skipped']:
                mark_sms_sent(today, sid)
                
            print(f"[SMS] Done. Sent: {len(results['sent'])}, Skipped (no phone): {len(results['skipped'])}, Failed: {len(results['failed'])}")
        except Exception as e:
            print(f"[SMS] Error during absence notification: {e}")

    threading.Thread(target=send_absence_notifications, daemon=True).start()


# =========================================================
# Web Portal Routes (Phase 1 & 3)
# =========================================================

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        creds = get_admin_credentials()
        if request.form.get('username') == creds['username'] and request.form.get('password') == creds['password']:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    
    total_students = CoreWrapper.get_count()
    today_attendance = get_today_attendance_count()
    from database import get_daily_status
    today = time.strftime('%Y-%m-%d')
    current_status = get_daily_status(today)
    
    return render_template('dashboard.html', total=total_students, today=today_attendance,
                           last_seen=esp32_status['last_seen'], current_time=time.time(),
                           daily_status=current_status)

@app.route('/ai_dashboard')
def ai_dashboard():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    return render_template('ai_monitor.html')

@app.route('/api/ai_feed')
def api_ai_feed():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(ai_live_feed)

@app.route('/api/simulate_proxy', methods=['POST'])
def api_simulate_proxy():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Inject 3 rapid fake proxy scans
    import threading
    def simulate():
        students = ["Demo Student A", "Demo Student B", "Demo Student C"]
        for i, s in enumerate(students):
            time.sleep(0.8) # Rapid scanning
            dwell = 120.0 + (i * 10) # Very fast dwell
            inter = 900.0 + (i * 20) # Very fast inter-scan
            add_to_ai_feed(s, dwell, inter, "PROXY DETECTED")
    threading.Thread(target=simulate, daemon=True).start()
    return jsonify({'success': True})

@app.route('/attendance')
def attendance_log():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    from database import get_unique_attendance_dates, get_attendance_logs_by_date
    from datetime import datetime

    all_dates = get_unique_attendance_dates()
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    # Ensure today is always available in the UI (calendar max and quick pills)
    if today_str not in all_dates:
        all_dates.insert(0, today_str)
    
    # Get requested date, fallback to today
    req_date = request.args.get('date')
    if req_date:
        current_date = req_date
    else:
        current_date = today_str

    # Fetch logs for the selected date
    logs = get_attendance_logs_by_date(current_date)
        
    # Fetch all daily statuses to display Open/Closed badges
    from database import get_db_connection
    conn = get_db_connection()
    statuses = conn.execute("SELECT * FROM DailyStatus").fetchall()
    conn.close()
    status_map = {row['date']: row['is_open'] for row in statuses}
    current_status = status_map.get(current_date, 0)
    
    # Determine next/prev dates for navigation
    prev_date = None
    next_date = None
    if current_date in all_dates:
        idx = all_dates.index(current_date)
        if idx > 0:
            next_date = all_dates[idx - 1] # all_dates is sorted DESC
        if idx < len(all_dates) - 1:
            prev_date = all_dates[idx + 1]
        
    return render_template('attendance_log.html', 
                           logs=logs, 
                           current_date=current_date, 
                           all_dates=all_dates, 
                           current_status=current_status,
                           prev_date=prev_date,
                           next_date=next_date)

@app.route('/students')
def students():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    
    search_q = request.args.get('search', '')
    if search_q:
        # Use C core for searching by roll number (School ID)
        c_student = CoreWrapper.find_by_school_id(search_q)
        if c_student:
             all_studs = [get_student_by_id(c_student.id)]
        else:
             all_studs = []
    else:
        all_studs = get_all_students()
        
    return render_template('students.html', students=all_studs, search_q=search_q)

@app.route('/enroll', methods=['GET', 'POST'])
def enroll():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        school_id = request.form.get('school_id')
        phone = request.form.get('phone')
        
        # Check uniqueness
        if get_student_by_school_id(school_id):
            flash('Student with this School ID already exists!', 'error')
            return redirect(url_for('enroll'))
        
        # Handle file upload logic securely
        file = request.files.get('photo')
        photo_path = ''
        if file and file.filename != '':
            filename = secure_filename(f"{school_id}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            photo_path = f"uploads/{filename}"
            
        # Create user in SQLite
        new_id = create_student(name, school_id, phone, photo_path)
        
        # Add to the active C Core Memory (0.0 for counts/marks)
        CoreWrapper.add_student(new_id, name, school_id, phone, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, "")
        
        flash(f'Successfully created {name}. Please configure sensors now.', 'success')
        # Send user to the sensor configuration page
        return redirect(url_for('enroll_sensors', student_id=new_id))
        
    return render_template('enroll.html')

@app.route('/grading', methods=['GET', 'POST'])
def grading():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    student_id = request.args.get('student_id')
    if not student_id:
        all_studs = get_all_students()
        return render_template('grading_list.html', students=all_studs)
        
    student = get_student_by_id(int(student_id))
    if request.method == 'POST':
        q1 = float(request.form.get('q1', 0))
        q2 = float(request.form.get('q2', 0))
        q3 = float(request.form.get('q3', 0))
        presentation = float(request.form.get('presentation', 0))
        mid = float(request.form.get('mid', 0))
        final = float(request.form.get('final', 0))
        
        update_student_marks(int(student_id), q1, q2, q3, presentation, mid, final)
        
        # Sync to C Core
        c_student = CoreWrapper.find_by_school_id(student['school_id'])
        if c_student:
             # Refresh memory entirely for consistency or update specifically if needed
             # For simplicity here, re-init C memory from DB on next load or update this slot
             CoreWrapper.init()
             for s in get_all_students():
                 CoreWrapper.add_student(
                     s['id'], s['name'], s['school_id'], s['phone'],
                     s['q1'], s['q2'], s['q3'], s['presentation'], s['mid'], s['final'],
                     0, s['fingerprint_id'], s['rfid_uid']
                 )
        
        flash('Marks updated successfully.', 'success')
        return redirect(url_for('grading'))
        
    return render_template('grading.html', student=student)

@app.route('/action/send_grades_sms', methods=['POST'])
def action_send_grades_sms():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    sms_creds = get_sms_credentials()
    if not sms_creds['api_key'] or not sms_creds['sender_id']:
        return jsonify({'success': False, 'message': 'SMS API credentials not configured in settings.'})
        
    all_students = get_all_students()
    if not all_students:
        return jsonify({'success': False, 'message': 'No students found.'})
        
    import threading
    def send_bg():
        try:
            print(f"[SMS] Attempting to send grades SMS to {len(all_students)} students...")
            results = send_grades_sms(sms_creds['api_key'], sms_creds['sender_id'], all_students)
            print(f"[SMS] Grade SMS Done. Sent: {len(results['sent'])}, Skipped: {len(results['skipped'])}, Failed: {len(results['failed'])}")
        except Exception as e:
            print(f"[SMS] Error during grade SMS broadcast: {e}")
            
    threading.Thread(target=send_bg, daemon=True).start()
    return jsonify({'success': True, 'message': 'Successfully started sending grade SMS to all students!'})

@app.route('/action/send_custom_notice', methods=['POST'])
def action_send_custom_notice():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    data = request.json
    message_text = data.get('message', '').strip()
    
    if not message_text:
        return jsonify({'success': False, 'message': 'Cannot send an empty message.'})
        
    sms_creds = get_sms_credentials()
    if not sms_creds['api_key'] or not sms_creds['sender_id']:
        return jsonify({'success': False, 'message': 'SMS API credentials not configured in settings.'})
        
    all_students = get_all_students()
    if not all_students:
        return jsonify({'success': False, 'message': 'No students enrolled to receive notifications.'})
        
    import threading
    def send_notice_bg():
        try:
            print(f"[SMS Notice] Preparing to send to {len(all_students)} students...")
            results = send_notice_sms(sms_creds['api_key'], sms_creds['sender_id'], all_students, message_text)
            print(f"[SMS Notice] Done. Sent: {len(results['sent'])}, Skipped: {len(results['skipped'])}, Failed: {len(results['failed'])}")
        except Exception as e:
            print(f"[SMS Notice] Error during broadcast: {e}")
            
    threading.Thread(target=send_notice_bg, daemon=True).start()
    return jsonify({'success': True, 'message': 'Broadcast started successfully!'})

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    creds = get_admin_credentials()
    sms_creds = get_sms_credentials()
    if request.method == 'POST':
        new_user      = request.form.get('username')
        new_pass      = request.form.get('password', '').strip()
        teacher_rfid  = request.form.get('teacher_rfid', '')
        sms_api_key   = request.form.get('sms_api_key', '').strip()
        sms_sender_id = request.form.get('sms_sender_id', '').strip()
        # If no new password provided, keep the existing one
        if not new_pass:
            new_pass = creds['password']
        update_admin_credentials(new_user, new_pass, teacher_rfid, sms_api_key, sms_sender_id, creds.get('asr_engine', 'mlx'), creds.get('google_api_key', ''))
        flash('Admin settings updated.', 'success')
        return redirect(url_for('settings'))
        
    return render_template('settings.html',
                           username=creds['username'],
                           teacher_rfid=creds.get('teacher_rfid', ''),
                           sms_api_key=sms_creds['api_key'],
                           sms_sender_id=sms_creds['sender_id'])

@app.route('/api/settings/verify_password', methods=['POST'])
def api_verify_password():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    current_password = data.get('password', '')
    creds = get_admin_credentials()
    if current_password == creds['password']:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Incorrect password'})

@app.route('/asr_test', methods=['GET'])
def asr_test():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    return render_template('asr_test.html')

@app.route('/api/test_asr_upload', methods=['POST'])
def api_test_asr_upload():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
        
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400
        
    audio_file = request.files['audio']
    if audio_file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    ext = os.path.splitext(audio_file.filename)[1]
    if not ext:
        ext = '.wav'
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f'test_asr{ext}')
    audio_file.save(temp_path)
    
    # Run the transcription
    try:
        transcription = transcribe_audio(temp_path)
        return jsonify({'success': True, 'transcription': transcription})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── Voice Test Library ────────────────────────────────────────────────
VOICE_TEST_DIR = os.path.join(os.path.dirname(__file__), '..', 'static', 'voice_test_library')
os.makedirs(VOICE_TEST_DIR, exist_ok=True)

@app.route('/api/voice_test/save', methods=['POST'])
def voice_test_save():
    """Save a recorded clip to the persistent test library and transcribe it."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file'}), 400

    audio_file = request.files['audio']
    label = request.form.get('label', '').strip() or 'recording'
    # Sanitize label
    label = ''.join(c for c in label if c.isalnum() or c in (' ', '-', '_')).strip()[:40]
    ext = os.path.splitext(audio_file.filename)[1] or '.webm'

    import datetime as _dt
    ts = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_label = label.replace(' ', '_')
    filename = f"{ts}_{safe_label}{ext}"
    save_path = os.path.join(VOICE_TEST_DIR, filename)
    audio_file.save(save_path)

    # Transcribe
    try:
        transcription = transcribe_audio(save_path)
    except Exception as e:
        transcription = f'[ERROR: {e}]'

    return jsonify({
        'success': True,
        'filename': filename,
        'label': label,
        'transcription': transcription,
        'size_kb': round(os.path.getsize(save_path) / 1024, 1)
    })


@app.route('/api/voice_test/list', methods=['GET'])
def voice_test_list():
    """Return all saved voice test recordings."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    import datetime as _dt
    files = []
    for fname in sorted(os.listdir(VOICE_TEST_DIR), reverse=True):
        fpath = os.path.join(VOICE_TEST_DIR, fname)
        if os.path.isfile(fpath):
            stat = os.stat(fpath)
            files.append({
                'filename': fname,
                'size_kb': round(stat.st_size / 1024, 1),
                'created': _dt.datetime.fromtimestamp(stat.st_ctime).strftime('%d %b %Y, %H:%M')
            })
    return jsonify({'recordings': files})


@app.route('/api/voice_test/delete/<filename>', methods=['DELETE'])
def voice_test_delete(filename):
    """Delete a saved voice test recording."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    # Security: only allow filenames, no path traversal
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    fpath = os.path.join(VOICE_TEST_DIR, filename)
    if os.path.exists(fpath):
        os.remove(fpath)
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404


@app.route('/api/voice_test/audio/<filename>', methods=['GET'])
def voice_test_audio(filename):
    """Stream a saved voice test recording for playback."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    return send_from_directory(VOICE_TEST_DIR, filename)


@app.route('/api/voice_test/transcribe/<filename>', methods=['GET'])
def voice_test_transcribe(filename):
    """Re-transcribe a saved recording on demand."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    fpath = os.path.join(VOICE_TEST_DIR, filename)
    if not os.path.exists(fpath):
        return jsonify({'error': 'File not found'}), 404
    try:
        transcription = transcribe_audio(fpath)
        return jsonify({'success': True, 'transcription': transcription})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student_route(student_id):
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    
    from database import delete_student
    delete_student(student_id)
    
    # Reload C memory
    CoreWrapper.init()
    for s in get_all_students():
        CoreWrapper.add_student(
            s['id'], s['name'], s['school_id'], s['phone'],
            s['q1'], s['q2'], s['q3'], s['presentation'], s['mid'], s['final'],
            0, s['fingerprint_id'], s['rfid_uid']
        )
    
    flash('Student and their attendance deleted successfully.', 'success')
    return redirect(url_for('students'))

@app.route('/delete_attendance/<int:log_id>', methods=['POST'])
def delete_attendance_route(log_id):
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    
    from database import delete_attendance_log
    delete_attendance_log(log_id)
    
    flash('Attendance log removed.', 'success')
    return redirect(url_for('attendance_log'))

@app.route('/enroll_sensors/<int:student_id>')
def enroll_sensors(student_id):
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    student = get_student_by_id(student_id)
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('students'))
    
    return render_template('enroll_sensors.html', student=student, status=esp32_status)


# =========================================================
# Frontend AJAX Action Routes (Triggering ESP32 Modes)
# =========================================================

@app.route('/action/trigger_enrollment', methods=['POST'])
def trigger_enrollment():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    sensor_type = data.get('sensor') # Expected: 'fingerprint' or 'rfid'
    student_id = data.get('student_id')
    
    if sensor_type == 'fingerprint':
        esp32_status['mode'] = 'enroll_fingerprint'
    elif sensor_type == 'rfid':
        esp32_status['mode'] = 'enroll_rfid'
    
    esp32_status['assign_id'] = student_id
    print(f"[API] ESP32 Mode switched to: {esp32_status['mode']} for Student {student_id}")
    return jsonify({'success': True, 'mode': esp32_status['mode']})
    
@app.route('/action/cancel_enrollment', methods=['POST'])
def cancel_enrollment():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
        
    esp32_status['mode'] = 'attendance'
    esp32_status['assign_id'] = None
    print("[API] ESP32 Mode returned to nominal attendance.")
    return jsonify({'success': True, 'mode': 'attendance'})

@app.route('/action/wipe_fingerprints', methods=['POST'])
def action_wipe_fingerprints():
    """Admin action: instruct the ESP32 to wipe all fingerprint templates."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    esp32_status['mode'] = 'delete_all'
    esp32_status['assign_id'] = None
    print("[API] Master Reset triggered — ESP32 set to delete_all mode.")
    return jsonify({'success': True, 'mode': 'delete_all'})

@app.route('/action/start_teacher_rfid_scan', methods=['POST'])
def start_teacher_rfid_scan():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    esp32_status['mode'] = 'capture_rfid'
    esp32_status['captured_rfid'] = None
    print("[API] Teacher RFID scan mode activated.")
    return jsonify({'success': True})

@app.route('/action/reset_sms_log', methods=['POST'])
def action_reset_sms_log():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    
    from database import get_db_connection
    conn = get_db_connection()
    conn.execute("DELETE FROM SmsDeliveryLogs")
    conn.commit()
    conn.close()
    print("[API] SMS Delivery Log cleared.")
    return redirect(url_for('settings'))

@app.route('/action/delete_voice_log/<int:log_id>', methods=['POST'])
def action_delete_voice_log(log_id):
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    date = request.form.get('date', time.strftime('%Y-%m-%d'))
    from database import get_db_connection
    conn = get_db_connection()
    # NOTE: We intentionally do NOT delete the physical audio file.
    # Voice recordings (including proxy ones) are kept on disk for review
    # and historical comparison. Only the DB record is removed.
    conn.execute("DELETE FROM VoiceRecordings WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('voice_monitor', date=date))

@app.route('/action/clear_all_voice_logs', methods=['POST'])
def action_clear_all_voice_logs():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    date = request.form.get('date', time.strftime('%Y-%m-%d'))
    from database import get_db_connection
    conn = get_db_connection()
    # NOTE: We intentionally do NOT delete the physical audio files.
    # All voice recordings are preserved on disk for historical review,
    # proxy comparison, and audit purposes. Only DB entries are removed.
    conn.execute("DELETE FROM VoiceRecordings WHERE date = ?", (date,))
    # Also remove associated match records for the date
    conn.execute("DELETE FROM VoiceMatches WHERE date(created_at, 'localtime') = ?", (date,))
    conn.commit()
    conn.close()

    # Clear any pending voices in memory
    PENDING_VOICES.clear()

    return redirect(url_for('voice_monitor', date=date))

@app.route('/api/teacher_rfid_capture', methods=['GET'])
def teacher_rfid_capture():
    """ Polled by the Settings page JS to check if a new RFID has been captured """
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    uid = esp32_status.get('captured_rfid')
    if uid:
        esp32_status['captured_rfid'] = None  # consume it
        esp32_status['mode'] = 'attendance'
        return jsonify({'captured': True, 'uid': uid})
    return jsonify({'captured': False})

@app.route('/action/toggle_attendance', methods=['POST'])
def action_toggle_attendance():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    from database import toggle_daily_status
    today = time.strftime('%Y-%m-%d')
    new_status = toggle_daily_status(today)
    status_str = "OPENED" if new_status == 1 else "CLOSED"

    # --- Absence SMS: fire only when portal is CLOSED ---
    if new_status == 0:
        trigger_absence_sms_if_closed(today)

    # Respond with JSON if called via AJAX (e.g. the dashboard button)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'new_status': new_status, 'message': f"Portal {status_str}"})
    flash(f"Today's attendance portal is now {status_str}.", "success")
    return redirect(request.referrer or url_for('dashboard'))


# =========================================================
# System Dashboard Monitoring
# =========================================================

@app.route('/api/system/status', methods=['GET'])
def system_status():
    """ Called by the dashboard UI to get ESP32 connection state without spoofing a ping """
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    
    from database import get_daily_status
    today = time.strftime('%Y-%m-%d')
    current_portal_status = get_daily_status(today)
        
    return jsonify({
        'esp32_last_seen': esp32_status['last_seen'],
        'server_time': time.time(),
        'daily_status': current_portal_status,
        'esp32_mode': esp32_status['mode']
    })

@app.route('/api/dashboard/stats', methods=['GET'])
def dashboard_stats():
    """Return attendance & proxy analytics for the dashboard graphs (last 7 days)."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401

    from database import get_db_connection, get_all_voice_matches
    total_students = CoreWrapper.get_count()

    # Build last-7-days labels and attendance counts
    labels = []
    attendance_counts = []
    proxy_counts = []

    from datetime import datetime, timedelta
    conn = get_db_connection()
    for i in range(6, -1, -1):
        day_dt = datetime.now() - timedelta(days=i)
        day = day_dt.strftime('%Y-%m-%d')
        labels.append(day_dt.strftime('%d %b'))

        # Attendance count — use 'localtime' modifier so UTC timestamps match local dates
        row = conn.execute(
            "SELECT COUNT(DISTINCT student_id) FROM AttendanceLogs WHERE date(timestamp, 'localtime') = ?", (day,)
        ).fetchone()
        attendance_counts.append(row[0] if row else 0)

        # Fingerprint proxy alerts from ESP32 for this day
        fp_row = conn.execute(
            "SELECT COUNT(*) FROM AttendanceLogs WHERE date(timestamp, 'localtime') = ? AND sensor_type = 'proxy_alert'", (day,)
        ).fetchone()

        # Voice proxy detections for this day
        vp_row = conn.execute(
            "SELECT COUNT(*) FROM VoiceMatches WHERE date = ? AND is_proxy = 1", (day,)
        ).fetchone()

        proxy_counts.append((fp_row[0] if fp_row else 0) + (vp_row[0] if vp_row else 0))

    # Today's voice proxy stats — use local date (datetime.now) not UTC
    today = datetime.now().strftime('%Y-%m-%d')
    today_voice = conn.execute(
        "SELECT COUNT(*) FROM VoiceMatches WHERE date = ? AND is_proxy = 1", (today,)
    ).fetchone()
    today_fp_proxy = conn.execute(
        "SELECT COUNT(*) FROM AttendanceLogs WHERE date(timestamp, 'localtime') = ? AND sensor_type = 'proxy_alert'", (today,)
    ).fetchone()
    today_attendance = conn.execute(
        "SELECT COUNT(DISTINCT student_id) FROM AttendanceLogs WHERE date(timestamp, 'localtime') = ?", (today,)
    ).fetchone()
    total_voice_checks = conn.execute(
        "SELECT COUNT(*) FROM VoiceMatches WHERE date = ?", (today,)
    ).fetchone()
    blacklisted_count = conn.execute(
        "SELECT COUNT(*) FROM Students WHERE is_blacklisted = 1"
    ).fetchone()
    conn.close()

    voice_proxies_today = today_voice[0] if today_voice else 0
    fp_proxies_today = today_fp_proxy[0] if today_fp_proxy else 0
    attendance_today = today_attendance[0] if today_attendance else 0
    voice_checks_today = total_voice_checks[0] if total_voice_checks else 0
    blacklisted_today = blacklisted_count[0] if blacklisted_count else 0

    attendance_rate = round((attendance_today / total_students * 100), 1) if total_students > 0 else 0
    voice_clear_rate = round(((voice_checks_today - voice_proxies_today) / voice_checks_today * 100), 1) if voice_checks_today > 0 else 100


    return jsonify({
        'labels': labels,
        'attendance_counts': attendance_counts,
        'proxy_counts': proxy_counts,
        'total_students': total_students,
        'attendance_today': attendance_today,
        'attendance_rate': attendance_rate,
        'voice_proxies_today': voice_proxies_today,
        'fp_proxies_today': fp_proxies_today,
        'voice_clear_rate': voice_clear_rate,
        'voice_checks_today': voice_checks_today,
        'blacklisted_today': blacklisted_today,
    })

# =========================================================
# ESP32 API Endpoints (Phase 2)
# =========================================================

@app.route('/api/esp32/status', methods=['GET'])
def esp32_status_api():
    esp32_status['last_seen'] = time.time()
    from database import get_admin_credentials, get_daily_status
    admin_creds = get_admin_credentials()
    
    today = time.strftime('%Y-%m-%d')
    portal_open = get_daily_status(today)

    current_mode = esp32_status['mode']
    
    # One-shot modes: Reset to attendance after sending once to ESP32
    if current_mode in ['force_audit', 'enroll_master_finger', 'test_record']:
        esp32_status['mode'] = 'attendance'

    return jsonify({
        'mode': current_mode,
        'assign_id': esp32_status['assign_id'],
        'master_rfid': admin_creds.get('teacher_rfid', ''),
        'portal_open': portal_open,
        'timestamp': int(time.time())
    })


@app.route('/api/voice_test/trigger_esp32', methods=['POST'])
def voice_test_trigger_esp32():
    """Tell the ESP32 to do a test recording with its INMP441 mic."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    esp32_status['mode'] = 'test_record'
    esp32_status['voice_test_pending'] = True
    esp32_status['voice_test_filename'] = None
    return jsonify({'success': True, 'message': 'ESP32 will record on next poll (~2s)'})


@app.route('/api/voice_test/esp32_poll', methods=['GET'])
def voice_test_esp32_poll():
    """Poll whether the ESP32 test recording has been received and transcribed."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    pending = esp32_status.get('voice_test_pending', False)
    filename = esp32_status.get('voice_test_filename')
    transcription = esp32_status.get('voice_test_transcription')  # None = still processing
    return jsonify({'pending': pending, 'filename': filename, 'transcription': transcription})


@app.route('/api/esp32/voice_test_submit', methods=['POST'])
def esp32_voice_test_submit():
    """
    ESP32 uploads a WAV recorded from its INMP441 mic for the voice testing lab.
    No session required — device endpoint, same pattern as /api/esp32/voice_submit.
    Marks file as received IMMEDIATELY so the dashboard poll doesn't time out,
    then runs enhance_audio + Whisper transcription in a background thread.
    """
    audio_file = request.files.get('audio')
    if not audio_file:
        print("[VoiceTestLab] ERROR: No 'audio' field in multipart request")
        return jsonify({'error': 'No audio file'}), 400

    import datetime as _dt
    ts = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{ts}_esp32_mic.wav"
    save_path = os.path.join(VOICE_TEST_DIR, filename)
    audio_file.save(save_path)

    saved_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
    print(f"[VoiceTestLab] Received ESP32 recording: {filename} | Size: {saved_size} bytes")

    if saved_size == 0:
        if os.path.exists(save_path):
            os.remove(save_path)
        print("[VoiceTestLab] ERROR: 0-byte file — SD card read may have failed on ESP32")
        return jsonify({'error': 'Empty audio file — check SD card on ESP32'}), 400

    # ── Mark as received IMMEDIATELY so the dashboard poll returns now ──
    # Transcription runs in the background; poll endpoint delivers it when ready.
    esp32_status['voice_test_pending'] = False
    esp32_status['voice_test_filename'] = filename
    esp32_status['voice_test_transcription'] = None  # None = still processing

    def _transcribe_bg(path, fname):
        """Background thread: enhance audio then transcribe with Whisper."""
        try:
            enhance_audio(path)
            print(f"[VoiceTestLab] enhance_audio done for {fname}")
        except Exception as e:
            print(f"[VoiceTestLab] enhance_audio warning: {e}")
        try:
            text = transcribe_audio(path)
            print(f"[VoiceTestLab] Transcription: '{text}'")
            esp32_status['voice_test_transcription'] = text
        except Exception as e:
            print(f"[VoiceTestLab] Transcription failed: {e}")
            esp32_status['voice_test_transcription'] = f'[ERROR: {e}]'

    threading.Thread(target=_transcribe_bg, args=(save_path, filename), daemon=True).start()

    return jsonify({'success': True, 'filename': filename, 'size_bytes': saved_size})

# Alias so enroll_sensors.html url_for('esp32_status_check') still works
@app.route('/api/esp32/status_check', methods=['GET'])
def esp32_status_check():
    return esp32_status_api()

@app.route('/api/simulate_proxy_hardware', methods=['POST'])
def simulate_proxy_hardware():
    esp32_status['mode'] = 'force_audit'
    add_to_ai_feed("SIMULATED BURST", 45.2, 50.1, "PROXY DETECTED")
    return jsonify({"success": True})

@app.route('/action/whitelist_student/<int:student_id>', methods=['POST'])
def action_whitelist_student(student_id):
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    from database import set_student_blacklist
    set_student_blacklist(student_id, 0)
    return jsonify({"success": True, "message": "Student whitelisted"})

@app.route('/api/enroll_master_finger', methods=['POST'])
def enroll_master_finger():
    esp32_status['mode'] = 'enroll_master_finger'
    return jsonify({"success": True})

@app.route('/api/esp32/whitelist', methods=['GET'])
def esp32_whitelist():
    """ Returns all enrolled students with sensors for offline validation """
    students = get_all_students()
    whitelist = []
    for s in students:
        # Include students who have either a fingerprint or RFID registered
        if s['fingerprint_id'] or s['rfid_uid']:
            whitelist.append({
                "s": s['id'],
                "n": s['name'][:12], # limit to 12 chars for OLED
                "f": int(s['fingerprint_id']) if s['fingerprint_id'] else 0,
                "r": s['rfid_uid'] or "",
                "b": 1 if s.get('is_blacklisted') else 0
            })
    return jsonify(whitelist)

@app.route('/api/esp32/today_attendance', methods=['GET'])
def esp32_today_attendance():
    """ 
    Returns an array of student IDs who have successfully scanned today. 
    Helps ESP32 rebuild offline duplicate cache. 
    """
    from database import get_students_with_attendance_on
    today = time.strftime('%Y-%m-%d')
    attended_ids = list(get_students_with_attendance_on(today))
    return jsonify(attended_ids)

@app.route('/api/esp32/attendance/batch', methods=['POST'])
def esp32_attendance_batch():
    """ Batch sync from ESP32 SD card offline storage """
    data = request.json
    if not isinstance(data, list):
        return jsonify({'error': 'Expected JSON array'}), 400
        
    for item in data:
        sensor = item.get('sensor')
        timestamp = item.get('timestamp')
        
        # Verify master card offline portal toggle isn't in this payload
        if sensor == 'rfid':
            uid = item.get('uid')
            from database import get_admin_credentials
            master_rfid = get_admin_credentials().get('teacher_rfid', '')
            if master_rfid and str(uid) == master_rfid:
                # We could toggle the portal retrospectively here, but typically offline master scans 
                # are just logged without altering the online portal state. 
                # For safety, skip any offline master toggles.
                continue

        student = None
        if sensor == 'fingerprint':
            fid = item.get('id')
            c_student = CoreWrapper.find_by_fingerprint(int(fid))
            if c_student:
                 student = get_student_by_id(c_student.id)
                 
        elif sensor == 'rfid':
            uid = item.get('uid')
            c_student = CoreWrapper.find_by_rfid(str(uid))
            if c_student:
                 student = get_student_by_id(c_student.id)
                 
        if student:
            # Note: Because this is offline backfill, we don't block it with `get_daily_status()`. 
            # We assume if the offline ESP32 allowed it, it was valid at the time.
            
            # Extract date from timestamp to check for duplicates
            # timestamp format expected: 2026-03-13T00:00:00Z
            date_part = timestamp.split('T')[0] if timestamp else time.strftime('%Y-%m-%d')
            
            # Check for duplicate scan on that date
            logs = get_all_attendance_logs()
            duplicate = False
            for log in logs:
                if log['student_id'] == student['id'] and log['local_date'] == date_part:
                     duplicate = True
                     break
            
            if not duplicate:
                CoreWrapper.update_attendance(student['id'])
                log_attendance(student['id'], sensor, timestamp)
                
    return jsonify({'success': True})

@app.route('/api/esp32/attendance', methods=['POST'])
def esp32_attendance():
    """ Called when ESP32 scans an enrolled user in nominal mode """
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid JSON format'}), 400
        
    sensor = data.get('sensor')

    # If we're in RFID capture mode (for Settings page scan), save the tag and return
    if sensor == 'rfid' and esp32_status['mode'] == 'capture_rfid':
        uid = data.get('uid')
        esp32_status['captured_rfid'] = uid
        return jsonify({'success': True, 'name': 'TAG CAPTURED'})

    # Check if this is the Teacher Master RFID Toggle
    if sensor == 'rfid':
        uid = data.get('uid')
        from database import get_admin_credentials, toggle_daily_status, get_daily_status
        admin_creds = get_admin_credentials()
        master_rfid = admin_creds.get('teacher_rfid', '')
        if master_rfid and str(uid) == master_rfid:
            today = time.strftime('%Y-%m-%d')
            new_status = toggle_daily_status(today)
            action_msg = "Opened" if new_status == 1 else "Closed"
            print(f"[ESP32 Action] Master RFID Tapped! Attendance {action_msg} for {today}")
            
            # --- Absence SMS: fire only when portal is CLOSED via ESP32 ---
            if new_status == 0:
                trigger_absence_sms_if_closed(today)
                
            return jsonify({'success': True, 'name': f"PORTAL {action_msg.upper()}"})

    student = None
    
    # Fast in-memory lookup using C Array
    if sensor == 'fingerprint':
        fid = data.get('id')
        c_student = CoreWrapper.find_by_fingerprint(int(fid))
        if c_student:
             student = get_student_by_id(c_student.id)
             
    elif sensor == 'rfid':
        uid = data.get('uid')
        c_student = CoreWrapper.find_by_rfid(str(uid))
        if c_student:
             student = get_student_by_id(c_student.id)
             
    if student and student.get('is_blacklisted'):
        return jsonify({'success': False, 'message': 'Card Blocked\nProxy Flagged'}), 403
             
    if student:
        today = time.strftime('%Y-%m-%d')
        
        # Verify the attendance window is currently OPEN
        from database import get_daily_status
        if get_daily_status(today) == 0:
            print(f"[ESP32 Action] Attendance attempt rejected: Portal is CLOSED for today.")
            return jsonify({'success': False, 'message': 'Portal Closed'})

        # Check for duplicate scan today
        logs = get_all_attendance_logs()
        for log in logs:
            if log['student_id'] == student['id'] and log['local_date'] == today:
                 print(f"[ESP32 Action] Duplicate attendance attempt rejected for {student['name']}")
                 return jsonify({'success': False, 'message': 'Already Scanned Today'})
        
        # 1. Update Core Memory Attendance (satisfies academic requirement)
        CoreWrapper.update_attendance(student['id'])
        # 2. Persist log to SQLite database
        log_attendance(student['id'], sensor, data.get('timestamp'))
        print(f"[ESP32 Action] Attendance logged for {student['name']} via {sensor}")
        
        # --- Finalize Pending Voice ---
        # If there's a pending voice, it means they just passed the fingerprint or voice audit!
        if student['id'] in PENDING_VOICES:
            voice_data = PENDING_VOICES[student['id']]
            pending_rel_path = voice_data['path']
            transcription = voice_data['transcription']
            wrong_attempts = ",".join(voice_data['wrong_attempts'])
            
            pending_abs_path = os.path.join(os.path.dirname(__file__), '..', 'static', pending_rel_path)
            if os.path.exists(pending_abs_path):
                # Rename the file to remove "_pending" and append a formal timestamp
                ts = time.strftime('%H%M%S')
                final_filename = f"student_{student['id']}_{ts}.wav"
                date_dir = os.path.dirname(pending_abs_path)
                final_abs_path = os.path.join(date_dir, final_filename)
                
                os.rename(pending_abs_path, final_abs_path)
                final_rel_path = f"voice_recordings/{today}/{final_filename}"
                
                # Formally log the successful voice to the database
                from database import log_voice_recording
                log_voice_recording(student['id'], today, final_rel_path, transcription, wrong_attempts)
                print(f"[Voice] Finalized verified recording for {student['name']} -> {final_rel_path}")
            
            # Remove from pending list
            del PENDING_VOICES[student['id']]
        
        if sensor == 'rfid':
            ai_dwell = data.get('ai_dwell', 0)
            ai_inter = data.get('ai_inter', 0)
            add_to_ai_feed(student['name'], ai_dwell, ai_inter, "NORMAL")
        else:
            add_to_ai_feed(student['name'], 0, 0, "FINGERPRINT")
        # Respond to ESP32 OLED

        return jsonify({'success': True, 'name': student['name']})
    else:
        # Log to AI feed even if rejected so it shows on the dashboard
        if sensor == 'rfid':
            ai_dwell = data.get('ai_dwell', 0)
            ai_inter = data.get('ai_inter', 0)
            add_to_ai_feed("Unknown Tag", ai_dwell, ai_inter, "REJECTED")
        print(f"[ESP32 Action] Scanning unassigned {sensor} tag rejected.")
        return jsonify({'success': False, 'message': 'Unknown ID or UID'}), 404

@app.route('/api/esp32/proxy_alert', methods=['POST'])
def esp32_proxy_alert():
    """ Called by ESP32 when TinyML model detects a proxy attempt that failed fingerprint audit """
    data = request.json
    uid = data.get('uid')
    ai_dwell = data.get('ai_dwell', 0)
    ai_inter = data.get('ai_inter', 0)
    
    # Identify the student who owns this card
    c_student = CoreWrapper.find_by_rfid(str(uid))
    if c_student:
        student = get_student_by_id(c_student.id)
        print(f"\n[SECURITY ALERT] Proxy attendance attempted using {student['name']}'s RFID card!")
        add_to_ai_feed(student['name'], ai_dwell, ai_inter, "PROXY DETECTED")
        from database import set_student_blacklist
        set_student_blacklist(student['id'], 1)
    else:
        print(f"\n[SECURITY ALERT] Proxy attendance attempted using unknown RFID: {uid}")
        add_to_ai_feed("Unknown Tag", ai_dwell, ai_inter, "PROXY DETECTED")
        
    return jsonify({'success': True})

@app.route('/api/esp32/audit_cleared', methods=['POST'])
def esp32_audit_cleared():
    """ Called when an audit is manually overridden or successfully verified """
    data = request.json
    uid = data.get('uid')
    method = data.get('method', 'OVERRIDE')
    
    if uid == "SIMULATED":
        add_to_ai_feed("SIMULATED BURST", 0, 0, method)
    else:
        c_student = CoreWrapper.find_by_rfid(str(uid))
        name = get_student_by_id(c_student.id)['name'] if c_student else "Unknown"
        add_to_ai_feed(name, 0, 0, method)
        
    return jsonify({'success': True})

@app.route('/api/esp32/enroll_success', methods=['POST'])
def esp32_enroll_success():
    """
    Called by ESP32 after finishing a new sensor enrollment process.
    Provides the new assigned sensor template ID or UID.
    Also handles Master Reset confirmation: {"sensor": "delete_all_confirm", "id": 0}
    """
    data = request.json

    # --- Master Reset confirmation path ---
    if data.get('sensor') == 'delete_all_confirm' and data.get('id') == 0:
        print("[ESP32 Action] Master Reset confirmed by hardware. Wiping all fingerprint records…")
        wipe_all_fingerprints()
        # Reload C memory so lookups reflect the cleared state
        CoreWrapper.init()
        for s in get_all_students():
            CoreWrapper.add_student(
                s['id'], s['name'], s['school_id'], s['phone'],
                s['q1'], s['q2'], s['q3'], s['presentation'], s['mid'], s['final'],
                0, s['fingerprint_id'], s['rfid_uid']
            )
        esp32_status['mode'] = 'attendance'
        esp32_status['assign_id'] = None
        print("[ESP32 Action] Master Reset complete. Mode restored to attendance.")
        return jsonify({'success': True, 'message': 'All fingerprints wiped'})

    # --- Master Finger Enrollment path ---
    if esp32_status.get('mode') == 'enroll_master_finger' and data.get('sensor') == 'fingerprint':
        print(f"[ESP32 Action] Master Finger enrolled at hardware slot {data.get('id')}")
        esp32_status['mode'] = 'attendance'
        return jsonify({'success': True, 'message': 'Master finger enrolled'})

    # --- Normal enrollment path (unchanged) ---
    student_id = esp32_status.get('assign_id')

    if not student_id:
        return jsonify({'error': 'No enrollment active server-side'}), 400
        
    sensor = data.get('sensor')
    
    # Identify the target student
    student = get_student_by_id(student_id)
    if not student:
        return jsonify({'error': 'Target student not found in SQLite'}), 404
        
    fid = student['fingerprint_id']
    uid = student['rfid_uid']
    
    # Override only the newly enrolled sensor method
    # and verify it isn't already taken by someone else
    if sensor == 'fingerprint':
        fid = data.get('id')
        existing = CoreWrapper.find_by_fingerprint(int(fid))
        if existing and existing.id != student_id:
            print(f"[ESP32 Action] Rejected enrollment: Fingerprint {fid} is already assigned.")
            esp32_status['mode'] = 'attendance'
            esp32_status['assign_id'] = None
            return jsonify({'success': False, 'message': 'ID Already Taken'})

    elif sensor == 'rfid':
        uid = data.get('uid')
        existing = CoreWrapper.find_by_rfid(str(uid))
        if existing and existing.id != student_id:
            print(f"[ESP32 Action] Rejected enrollment: RFID {uid} is already assigned.")
            esp32_status['mode'] = 'attendance'
            esp32_status['assign_id'] = None
            return jsonify({'success': False, 'message': 'Tag Already Taken'})
        
    # Apply to SQLite Database
    update_student_sensors(student_id, fid, uid)
    
    # Reload the C memory mapping entirely to maintain fresh synchrony
    CoreWrapper.init()
    all_studs = get_all_students()
    for s in all_studs:
        CoreWrapper.add_student(
            s['id'], s['name'], s['school_id'], s['phone'],
            s['q1'], s['q2'], s['q3'], s['presentation'], s['mid'], s['final'],
            0, s['fingerprint_id'], s['rfid_uid']
        )
        
    print(f"[ESP32 Action] Successfully registered new {sensor} to student {student['name']}")
    
    # Restore the node back to standard state
    esp32_status['mode'] = 'attendance'
    esp32_status['assign_id'] = None
    
    return jsonify({'success': True})


# =========================================================
# Voice Recording Submission & Cross-Match (Proxy Detection)
# =========================================================

# ECAPA-TDNN's built-in prediction uses a highly calibrated mathematical threshold.
# We strictly rely on the model's boolean `prediction` output to determine matches
# because manual static thresholds (like 0.30) cause false positives.

@app.route('/api/esp32/voice_submit', methods=['POST'])
def esp32_voice_submit():
    """
    Called by ESP32 after every successful RFID scan.
    Accepts a raw WAV file (multipart) + rfid_uid.
    Cross-matches the voice against all voices saved today.
    Returns proxy decision so ESP32 can trigger fingerprint audit if needed.
    """
    rfid_uid = request.form.get('rfid_uid', '').strip()
    audio_file = request.files.get('audio')

    if not rfid_uid or not audio_file:
        return jsonify({'error': 'rfid_uid and audio are required'}), 400

    # --- Identify student from RFID ---
    c_student = CoreWrapper.find_by_rfid(rfid_uid)
    if not c_student:
        return jsonify({'error': 'Unknown RFID tag', 'proxy': False}), 404
    student = get_student_by_id(c_student.id)
    if not student:
        return jsonify({'error': 'Student not found', 'proxy': False}), 404

    today = time.strftime('%Y-%m-%d')
    student_id = student['id']

    # --- Save WAV file (As Pending) ---
    date_dir = os.path.join(VOICE_DIR, today)
    os.makedirs(date_dir, exist_ok=True)
    filename = f"student_{student_id}_pending.wav"
    file_path = os.path.join(date_dir, filename)
    audio_file.save(file_path)

    # Enhance audio quality and check for silence
    is_silent = False
    try:
        _, is_silent = enhance_audio(file_path)
    except Exception as e:
        print(f"[Voice] enhance_audio error: {e}")

    # Relative path for serving static files
    rel_path = f"voice_recordings/{today}/{filename}"

    if is_silent:
        print(f"[Voice] SILENCE DETECTED for {student['name']}. Flagging as proxy to force fingerprint.")
        # Store as pending so we can finalize it if they pass fingerprint
        PENDING_VOICES[student_id] = {
            'path': rel_path,
            'transcription': '[SILENCE]',
            'wrong_attempts': WRONG_VOICE_ATTEMPTS.pop(student_id, [])
        }
        return jsonify({
            'proxy': True,
            'student_id': student_id,
            'student_name': student['name'],
            'note': 'silence_detected'
        })

    # --- Step 1: ASR Enforced Phrase Check ---
    try:
        transcription = transcribe_audio(file_path).lower()
        print(f"[Voice] Transcribed phrase for {student['name']}: '{transcription}'")
    except Exception as ex:
        print(f"[Voice] ASR Transcription failed: {ex}")
        transcription = ""

    if transcription:

            # Fuzzy keyword check: accept "present", "presence", "presents",
            # or any word starting with "pres", "prez", "priz" to handle Bangladeshi accent variations.
            # We also accept "sir" directly, since sometimes Whisper misses the first word entirely.
            words = transcription.replace(',', '').replace('.', '').replace('?', '').replace('!', '').split()
            allowed_prefixes = ("pres", "prez", "priz", "pras", "pray")
            
            has_valid_word = any(
                w in ("present", "presence", "presents", "sir", "yes", "shir") or
                any(w.startswith(prefix) and len(w) >= 4 for prefix in allowed_prefixes)
                for w in words
            )
            
            # Reject if they say things like "hello sir" or "test sir"
            banned_words = {"hello", "hi", "hey", "test", "testing", "what", "good", "morning", "afternoon", "yo"}
            has_banned_word = any(w in banned_words for w in words)
            
            phrase_ok = has_valid_word and not has_banned_word

            if not phrase_ok:
                print(f"[Voice] WRONG PHRASE for {student['name']}. Expected 'present', heard '{transcription}'.")
                add_to_ai_feed(student['name'], 0, 0, f"WRONG PHRASE: {transcription}")
                
                # Track the wrong attempt
                if student_id not in WRONG_VOICE_ATTEMPTS:
                    WRONG_VOICE_ATTEMPTS[student_id] = []
                if transcription:
                    WRONG_VOICE_ATTEMPTS[student_id].append(transcription)

                return jsonify({
                    'proxy': False,
                    'wrong_phrase': True,
                    'student_id': student_id,
                    'student_name': student['name'],
                    'note': f"wrong_phrase_heard_{transcription}"
                })

            # If phrase is OK, store in pending queue
            PENDING_VOICES[student_id] = {
                'path': rel_path,
                'transcription': transcription,
                'wrong_attempts': WRONG_VOICE_ATTEMPTS.pop(student_id, [])
            }
            print(f"[Voice] Saved PENDING recording for {student['name']} -> {rel_path}")
    # --- Cross-match against all OTHER voice recordings from today ---
    # exclude_proxy=True: proxy-flagged voices are kept in DB/disk for review,
    # but must NOT be used as comparison targets — they would falsely flag
    # legitimate students scanning after a proxy attempt.
    model = get_speaker_model()
    if model is None:
        # Model not available — skip voice check, allow normal attendance
        print("[Voice] Model unavailable, skipping cross-match.")
        return jsonify({
            'proxy': False,
            'student_id': student_id,
            'student_name': student['name'],
            'note': 'voice_model_unavailable'
        })

    today_recordings = get_voice_recordings_for_date(today, exclude_proxy=True)
    # Exclude the student who just scanned (their pending file is not DB-logged yet)
    others = [r for r in today_recordings if r['student_id'] != student_id]

    if not others:
        # First person to scan today — nothing to compare against
        return jsonify({
            'proxy': False,
            'student_id': student_id,
            'student_name': student['name'],
            'note': 'first_recording_today'
        })

    best_score      = 0.0
    best_match      = None
    best_model_pred = False
    all_comparisons = []

    for other in others:
        other_abs = os.path.join(os.path.dirname(__file__), '..', 'static', other['file_path'])
        if not os.path.exists(other_abs):
            continue
        try:
            # verify_files returns (cosine_similarity_tensor, prediction_tensor)
            # prediction uses SpeechBrain's own calibrated threshold (~0.25 cosine)
            score_tensor, pred_tensor = model.verify_files(file_path, other_abs)
            score      = float(score_tensor.item())
            model_pred = bool(pred_tensor.item())   # True = same speaker (SpeechBrain's judgement)
        except Exception as ex:
            print(f"[Voice] Compare error vs student {other['student_id']}: {ex}")
            score      = 0.0
            model_pred = False

        # ── Two-tier proxy classification ────────────────────────────────────
        # CONFIRMED proxy: model says same speaker AND score >= 70%
        # SUSPECT proxy:   model says same speaker OR score >= 45%
        #   → Both tiers trigger fingerprint audit — better safe than sorry.
        #   → 82% was too high: real proxy at 50.4% was slipping through.
        CONFIRM_THRESH = 0.70   # model_pred=True + score >= 70%  → CONFIRMED
        SUSPECT_THRESH = 0.45   # score >= 45% OR model_pred=True → SUSPECT

        if model_pred and score >= CONFIRM_THRESH:
            tier = "CONFIRMED"
        elif model_pred or score >= SUSPECT_THRESH:
            tier = "SUSPECT"
        else:
            tier = "OK"

        is_match_flag = 1 if tier in ("CONFIRMED", "SUSPECT") else 0

        all_comparisons.append({
            'student_id':   other['student_id'],
            'student_name': other['name'],
            'score':        round(score * 100, 1),
            'model_pred':   model_pred,
            'tier':         tier
        })

        log_voice_match(today, student_id, other['student_id'], score, is_match_flag)
        print(f"[Voice] {student['name']} vs {other['name']}: "
              f"score={score:.4f} ({score*100:.1f}%)  "
              f"model_pred={model_pred}  tier={tier}")

        # Prefer model_pred=True hits over pure score maximums
        # so a 50% model-confirmed match beats an 80% model-denied mismatch
        curr_priority = (model_pred, score)
        best_priority = (best_model_pred, best_score)
        if curr_priority > best_priority:
            best_score      = score
            best_match      = other
            best_model_pred = model_pred

    # ── Final proxy decision ─────────────────────────────────────────────────
    if best_model_pred and best_score >= CONFIRM_THRESH:
        final_tier = "CONFIRMED"
    elif best_model_pred or best_score >= SUSPECT_THRESH:
        final_tier = "SUSPECT"
    else:
        final_tier = "OK"

    is_proxy = final_tier in ("CONFIRMED", "SUSPECT")

    if is_proxy and best_match:
        label = f"VOICE {'PROXY' if final_tier == 'CONFIRMED' else 'SUSPECT'} {best_score*100:.0f}%"
        print(f"[Voice] {final_tier}! {student['name']} matches {best_match['name']} "
              f"at {best_score*100:.1f}% — fingerprint audit triggered")
        add_to_ai_feed(student['name'], 0, 0, label)
        mark_recording_as_proxy_source(student_id, today)
        return jsonify({
            'proxy': True,
            'tier': final_tier,
            'student_id': student_id,
            'student_name': student['name'],
            'matched_student_id': best_match['student_id'],
            'matched_student_name': best_match['name'],
            'score': round(best_score * 100, 1),
            'comparisons': all_comparisons
        })

    add_to_ai_feed(student['name'], 0, 0, f"VOICE OK {best_score*100:.0f}%")
    return jsonify({
        'proxy': False,
        'tier': 'OK',
        'student_id': student_id,
        'student_name': student['name'],
        'best_score': round(best_score * 100, 1),
        'comparisons': all_comparisons
    })


@app.route('/api/esp32/voice_match_resolve', methods=['POST'])
def voice_match_resolve():
    """Called by ESP32 after fingerprint audit to mark a match as resolved."""
    data = request.json
    rfid_uid = data.get('rfid_uid', '')
    result = data.get('result', 'UNKNOWN')  # 'FINGERPRINT_OK' or 'BLACKLISTED'

    today = time.strftime('%Y-%m-%d')
    c_student = CoreWrapper.find_by_rfid(rfid_uid)
    if c_student:
        student = get_student_by_id(c_student.id)
        if student:
            # Find the most recent proxy match for this student today and resolve it
            matches = get_voice_matches_for_date(today)
            for m in matches:
                if m['student_a_id'] == student['id'] and m['is_proxy'] == 1 and m['resolved_by'] is None:
                    resolve_voice_match(m['id'], result)
                    break
    return jsonify({'success': True})


# =========================================================
# Voice Monitor Page
# =========================================================

@app.route('/voice_monitor')
def voice_monitor():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    dates = get_voice_dates()
    selected_date = request.args.get('date', dates[0] if dates else time.strftime('%Y-%m-%d'))
    recordings = get_voice_recordings_for_date(selected_date)
    matches = get_voice_matches_for_date(selected_date)
    return render_template('voice_monitor.html',
                           dates=dates,
                           selected_date=selected_date,
                           recordings=recordings,
                           matches=matches,
                           threshold="AI Calibrated")


@app.route('/api/voice/recordings')
def api_voice_recordings():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    date = request.args.get('date', time.strftime('%Y-%m-%d'))
    return jsonify(get_voice_recordings_for_date(date))


@app.route('/api/voice/matches')
def api_voice_matches():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    date = request.args.get('date', time.strftime('%Y-%m-%d'))
    return jsonify(get_voice_matches_for_date(date))


if __name__ == '__main__':
    try:
        # Start the Flask development server on all interfaces
        app.run(host='0.0.0.0', port=5005, debug=True, use_reloader=False)
    finally:
        if zeroconf_instance:
            zeroconf_instance.close()
