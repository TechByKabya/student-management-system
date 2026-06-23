import re

with open("esp32_firmware.txt", "r") as f:
    code = f.read()

# Add a specific handler for enroll_master_finger in the main SensorUITask loop
# Currently there is:
#     } else if (currentMode == "enroll_rfid") {
#       handleRFIDEnrollment();
#     } else if (currentMode == "delete_all") {
#       handleDeleteAll();
#     }

enroll_master_handler = """    } else if (currentMode == "enroll_rfid") {
      handleRFIDEnrollment();
    } else if (currentMode == "enroll_master_finger") {
      handleMasterFingerEnrollment();
    } else if (currentMode == "delete_all") {"""

code = code.replace("""    } else if (currentMode == "enroll_rfid") {
      handleRFIDEnrollment();
    } else if (currentMode == "delete_all") {""", enroll_master_handler)

# Create handleMasterFingerEnrollment
master_enroll_func = """
void handleMasterFingerEnrollment() {
  triggerIndicatorSafe(true, "Enrolling\nMaster Bypass...");
  delay(1000);
  
  // Hardcode ID 127 for Master Finger
  int id = 127;
  
  // Step 1
  triggerIndicatorSafe(true, "Place Demo Finger\nOn Sensor");
  while (finger.getImage() != FINGERPRINT_OK) { delay(50); }
  if (finger.image2Tz(1) != FINGERPRINT_OK) {
    triggerIndicatorSafe(false, "Failed to capture");
    currentMode = "attendance"; return;
  }
  
  triggerIndicatorSafe(true, "Remove Finger");
  delay(1000);
  while (finger.getImage() != FINGERPRINT_NOFINGER) { delay(50); }
  
  // Step 2
  triggerIndicatorSafe(true, "Place Finger\nAgain");
  while (finger.getImage() != FINGERPRINT_OK) { delay(50); }
  if (finger.image2Tz(2) != FINGERPRINT_OK) {
    triggerIndicatorSafe(false, "Failed to capture");
    currentMode = "attendance"; return;
  }
  
  // Create & Store Model
  if (finger.createModel() != FINGERPRINT_OK) {
    triggerIndicatorSafe(false, "Prints did not\nmatch");
    currentMode = "attendance"; return;
  }
  
  if (finger.storeModel(id) == FINGERPRINT_OK) {
    playAudio("success");
    triggerIndicatorSafe(true, "Master Finger\nSaved! (ID: 127)");
    
    // Tell server success
    JsonDocument doc;
    doc["sensor"] = "fingerprint";
    doc["id"] = id;
    String jsonString;
    serializeJson(doc, jsonString);
    if (isOnline && serverBaseURL != "") {
      int httpCode = 0;
      doHttpPost("/api/esp32/enroll_success", jsonString, 4000, &httpCode);
    }
  } else {
    triggerIndicatorSafe(false, "Failed to store\nMaster Finger");
  }
  delay(2000);
  currentMode = "attendance";
}
"""

if "handleMasterFingerEnrollment" not in code:
    code = code.replace("void handleFingerprintEnrollment() {", master_enroll_func + "\nvoid handleFingerprintEnrollment() {")

# Update handleAttendance to check for RFID and Master Finger
old_audit_check = """      // Wait for fingerprint
      if (finger.getImage() == FINGERPRINT_OK && finger.image2Tz() == FINGERPRINT_OK) {
          if (finger.fingerSearch() == FINGERPRINT_OK) {
              // Got a finger. Let's process the original attendance via RFID
              // since we verified they are physically here!
              triggerIndicatorSafe(true, "AUDIT PASSED\\nIdentity OK");
              processAttendanceData("rfid", auditExpectedRFID);
              pendingAudit = false;
          } else {
              triggerIndicatorSafe(false, "Unknown Finger\\nTry Again");
          }
      }
      return; // Do not process normal RFID while auditing"""

new_audit_check = """      // 1. Check if they used the Master ID Card to bypass
      uint8_t u[7];
      uint8_t uLen;
      if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, u, &uLen, 50)) {
          String uStr = "";
          for (uint8_t i = 0; i < uLen; i++) {
              if(u[i] < 0x10) uStr += "0";
              uStr += String(u[i], HEX);
          }
          uStr.toUpperCase();
          
          if (cachedMasterRFID != "" && uStr == cachedMasterRFID) {
              triggerIndicatorSafe(true, "AUDIT PASSED\\nMaster Bypass");
              if (auditExpectedRFID != "SIMULATED") processAttendanceData("rfid", auditExpectedRFID);
              pendingAudit = false;
              return;
          } else {
              triggerIndicatorSafe(false, "INVALID RFID\\nUse Fingerprint");
              delay(1000);
          }
      }

      // 2. Wait for fingerprint (Any registered finger or Master 127)
      if (finger.getImage() == FINGERPRINT_OK && finger.image2Tz() == FINGERPRINT_OK) {
          if (finger.fingerSearch() == FINGERPRINT_OK) {
              if (finger.fingerID == 127) {
                  triggerIndicatorSafe(true, "AUDIT PASSED\\nMaster Bypass");
              } else {
                  triggerIndicatorSafe(true, "AUDIT PASSED\\nIdentity OK");
              }
              if (auditExpectedRFID != "SIMULATED") processAttendanceData("rfid", auditExpectedRFID);
              pendingAudit = false;
          } else {
              triggerIndicatorSafe(false, "Unknown Finger\\nTry Again");
          }
      }
      return; // Do not process normal RFID while auditing"""

code = code.replace(old_audit_check, new_audit_check)

with open("esp32_firmware.txt", "w") as f:
    f.write(code)
