import re

with open("esp32_firmware.txt", "r") as f:
    code = f.read()

# Lines 519: whitelist
whitelist_rem = """  HTTPClient http;
  http.begin(serverBaseURL + "/api/esp32/whitelist");
  http.setTimeout(5000);
  int httpCode = http.GET();
  if (httpCode == 200) {
    String payload = http.getString();"""
whitelist_new = """  int httpCode = 0;
  String payload = doHttpGet("/api/esp32/whitelist", 5000, &httpCode);
  if (httpCode == 200) {"""
if whitelist_rem in code:
    code = code.replace(whitelist_rem, whitelist_new)
    # Remove http.end() which is somewhere down
    code = code.replace("    }\n    http.end();", "    }")

# Line 572: today_attendance
today_rem = """  HTTPClient http;
  http.begin(serverBaseURL + "/api/esp32/today_attendance");
  http.setTimeout(3000);
  int httpCode = http.GET();
  if (httpCode == 200) {
      String payload = http.getString();"""
today_new = """  int httpCode = 0;
  String payload = doHttpGet("/api/esp32/today_attendance", 3000, &httpCode);
  if (httpCode == 200) {"""
if today_rem in code:
    code = code.replace(today_rem, today_new)
    code = re.sub(r"      \}\n      http\.end\(\);\n  \} else \{", "      }\n  } else {", code)

# Line 931: processAttendanceData master
att_master_rem = """      HTTPClient http;
      http.begin(serverBaseURL + "/api/esp32/attendance");
      http.addHeader("Content-Type", "application/json");
      http.POST(jsonString);
      http.end();"""
att_master_new = """      doHttpPost("/api/esp32/attendance", jsonString);"""
if att_master_rem in code:
    code = code.replace(att_master_rem, att_master_new)

# Line 1369: handleFingerprintEnrollment
f_enroll_rem = """  if (isOnline && serverBaseURL != "") {
    HTTPClient http;
    http.begin(serverBaseURL + "/api/esp32/enroll_success");
    http.addHeader("Content-Type", "application/json");
    int httpCode = http.POST(jsonString);
    if (httpCode == 200) {
      JsonDocument res;
      deserializeJson(res, http.getString());
      if (res["success"]) triggerIndicatorSafe(true, "Finger Linked!");
      else triggerIndicatorSafe(false, res["message"].as<String>());
    }
    http.end();
  }"""
f_enroll_new = """  if (isOnline && serverBaseURL != "") {
    int httpCode = 0;
    String responsePayload = doHttpPost("/api/esp32/enroll_success", jsonString, 4000, &httpCode);
    if (httpCode == 200) {
      JsonDocument res;
      deserializeJson(res, responsePayload);
      if (res["success"]) triggerIndicatorSafe(true, "Finger Linked!");
      else triggerIndicatorSafe(false, res["message"].as<String>());
    }
  }"""
if f_enroll_rem in code:
    code = code.replace(f_enroll_rem, f_enroll_new)

with open("esp32_firmware.txt", "w") as f:
    f.write(code)
