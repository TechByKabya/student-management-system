import requests

BULKSMS_API_URL = "http://bulksmsbd.net/api/smsapi"

def send_absence_sms(api_key: str, sender_id: str, absent_students: list) -> dict:
    """
    Sends an absence notification SMS to each student in the list.

    Args:
        api_key:         Your BulkSMSBD API key.
        sender_id:       Your approved BulkSMSBD Sender ID.
        absent_students: List of dicts with keys: 'id', 'name', 'phone'.

    Returns:
        A summary dict: {'sent': [...], 'failed': [...], 'skipped': [...]}
    """
    results = {'sent': [], 'failed': [], 'skipped': []}

    if not api_key or not sender_id:
        print("[SMS] Skipping: API key or Sender ID not configured.")
        return results

    for student in absent_students:
        phone = (student.get('phone') or '').strip()
        name  = student.get('name', 'Student')
        sid   = student.get('id')

        # Skip students with no phone number on file
        if not phone:
            print(f"[SMS] Skipped '{name}' — no phone number registered.")
            results['skipped'].append(sid)
            continue

        message = (
            f"Dear {name}, you were marked ABSENT today in class. "
            f"Please contact your teacher if this is an error. "
            f"- Student Attendance Portal"
        )

        try:
            response = requests.post(
                BULKSMS_API_URL,
                data={
                    'api_key':  api_key,
                    'senderid': sender_id,
                    'number':   phone,
                    'message':  message,
                },
                timeout=10
            )
            print(f"[SMS] HTTP Status: {response.status_code} | Raw Response: {response.text}")
            response_data = response.json()
            # BulkSMSBD returns response_code 202 for success
            if response_data.get('response_code') == 202:
                print(f"[SMS] ✅ Sent absence SMS to {name} ({phone}) — Success.")
                results['sent'].append(sid)
            else:
                print(f"[SMS] ❌ Failed for {name} ({phone}): Code={response_data.get('response_code')} | {response_data}")
                results['failed'].append(sid)

        except Exception as e:
            print(f"[SMS] Exception while sending to {name} ({phone}): {e}")
            results['failed'].append(sid)

    return results


def send_grades_sms(api_key: str, sender_id: str, students: list) -> dict:
    """
    Sends an academic grade notification SMS to each student in the list.

    Args:
        api_key:    Your BulkSMSBD API key.
        sender_id:  Your approved BulkSMSBD Sender ID.
        students:   List of dicts with student details and marks.

    Returns:
        A summary dict: {'sent': [...], 'failed': [...], 'skipped': [...]}
    """
    results = {'sent': [], 'failed': [], 'skipped': []}

    if not api_key or not sender_id:
        print("[SMS] Skipping: API key or Sender ID not configured.")
        return results

    for student in students:
        phone = (student.get('phone') or '').strip()
        name  = student.get('name', 'Student')
        sid   = student.get('id')

        if not phone:
            print(f"[SMS] Skipped '{name}' — no phone number registered.")
            results['skipped'].append(sid)
            continue

        # Calculate grades
        q1 = student.get('q1', 0)
        q2 = student.get('q2', 0)
        q3 = student.get('q3', 0)
        q_avg = (q1 + q2 + q3) / 3.0
        
        presentation = student.get('presentation', 0)
        mid = student.get('mid', 0)
        final = student.get('final', 0)
        total = q_avg + presentation + mid + final
        
        status = "PASSED" if total >= 40 else "FAILED"

        # Format total to 2 decimal places
        total_str = f"{total:.2f}"

        message = (
            f"Dear {name}, your results for Programming & Problem Solving Lab are published. "
            f"Total Marks: {total_str}/100. Status: {status}. "
            f"- Student Management System"
        )

        try:
            response = requests.post(
                BULKSMS_API_URL,
                data={
                    'api_key':  api_key,
                    'senderid': sender_id,
                    'number':   phone,
                    'message':  message,
                },
                timeout=10
            )
            print(f"[SMS] HTTP Status: {response.status_code} | Raw Response: {response.text}")
            response_data = response.json()
            if response_data.get('response_code') == 202:
                print(f"[SMS] ✅ Sent grade SMS to {name} ({phone}) — Success.")
                results['sent'].append(sid)
            else:
                print(f"[SMS] ❌ Failed for {name} ({phone}): Code={response_data.get('response_code')} | {response_data}")
                results['failed'].append(sid)

        except Exception as e:
            print(f"[SMS] Exception while sending to {name} ({phone}): {e}")
            results['failed'].append(sid)

    return results

def send_notice_sms(api_key: str, sender_id: str, students: list, message: str) -> dict:
    """
    Sends a custom teacher-written notice SMS to all students.

    Args:
        api_key:    Your BulkSMSBD API key.
        sender_id:  Your approved BulkSMSBD Sender ID.
        students:   List of dicts with student details (at minimum 'id', 'name', 'phone').
        message:    The custom text message body to send.

    Returns:
        A summary dict: {'sent': [...], 'failed': [...], 'skipped': [...]}
    """
    results = {'sent': [], 'failed': [], 'skipped': []}

    if not api_key or not sender_id:
        print("[SMS] Skipping Notice: API key or Sender ID not configured.")
        return results

    for student in students:
        phone = (student.get('phone') or '').strip()
        name  = student.get('name', 'Student')
        sid   = student.get('id')

        if not phone:
            print(f"[SMS] Notice Skipped '{name}' — no phone number registered.")
            results['skipped'].append(sid)
            continue

        try:
            response = requests.post(
                BULKSMS_API_URL,
                data={
                    'api_key':  api_key,
                    'senderid': sender_id,
                    'number':   phone,
                    'message':  message,
                },
                timeout=10
            )
            print(f"[SMS] Notice HTTP Status: {response.status_code} | Raw Response: {response.text}")
            response_data = response.json()
            if response_data.get('response_code') == 202:
                print(f"[SMS] ✅ Sent Notice SMS to {name} ({phone}) — Success.")
                results['sent'].append(sid)
            else:
                print(f"[SMS] ❌ Failed Notice for {name} ({phone}): Code={response_data.get('response_code')} | {response_data}")
                results['failed'].append(sid)

        except Exception as e:
            print(f"[SMS] Exception while sending Notice to {name} ({phone}): {e}")
            results['failed'].append(sid)

    return results
