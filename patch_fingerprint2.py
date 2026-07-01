import re

with open('esp32_firmware.txt', 'r') as f:
    code = f.read()

# Swap the order of NFC and Fingerprint in handleAttendance()
attendance_func_start = "void handleAttendance() {"
attendance_nfc_start = "  // ── Normal RFID Scan ──"
attendance_finger_start = "  // ── Fingerprint fallback ──"
attendance_end = "// ========================= Enrollment Handlers ====================="

# Find indices
idx_func = code.find(attendance_func_start)
idx_nfc = code.find(attendance_nfc_start, idx_func)
idx_finger = code.find(attendance_finger_start, idx_func)
idx_end = code.find(attendance_end, idx_func)

if idx_nfc != -1 and idx_finger != -1 and idx_finger > idx_nfc:
    # Extract sections
    part_before_nfc = code[:idx_nfc]
    nfc_section = code[idx_nfc:idx_finger]
    finger_section = code[idx_finger:idx_end]
    part_after_end = code[idx_end:]

    # Modify the finger_section to replace "fallback" with "Check"
    finger_section = finger_section.replace("Fingerprint fallback", "Fingerprint Primary Check")
    nfc_section = nfc_section.replace("Normal RFID Scan", "RFID Fallback Check")

    # Combine them in reverse order
    new_code = part_before_nfc + finger_section + nfc_section + part_after_end
    
    with open('esp32_firmware.txt', 'w') as f:
        f.write(new_code)
    print("Swapped order successfully.")
else:
    print("Could not find sections to swap.")
