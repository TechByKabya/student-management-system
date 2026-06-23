import re

with open("esp32_firmware.txt", "r") as f:
    code = f.read()

# fetchWhitelist
whitelist_old = """  HTTPClient http;
  http.begin(serverBaseURL + "/api/esp32/whitelist");
  http.setTimeout(5000);
  int httpCode = http.GET();
  if (httpCode == 200) {
    String payload = http.getString();"""

whitelist_new = """  int httpCode = 0;
  String payload = doHttpGet("/api/esp32/whitelist", 5000, &httpCode);
  if (httpCode == 200) {"""

code = code.replace(whitelist_old, whitelist_new)
code = code.replace("    }\n    http.end();", "    }")

# fetchTodayAttendance
today_old = """  HTTPClient http;
  http.begin(serverBaseURL + "/api/esp32/today_attendance");
  http.setTimeout(3000);
  int httpCode = http.GET();
  if (httpCode == 200) {
      String payload = http.getString();"""

today_new = """  int httpCode = 0;
  String payload = doHttpGet("/api/esp32/today_attendance", 3000, &httpCode);
  if (httpCode == 200) {"""

code = code.replace(today_old, today_new)
# Need to remove the http.end()
code = re.sub(r"      \}\n      http\.end\(\);\n  \} else \{", "      }\n  } else {", code)


# processAttendanceData POST
att_old = """    HTTPClient http;
    http.begin(serverBaseURL + "/api/esp32/attendance");
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(4000);
    int httpCode = http.POST(jsonString);
    if (httpCode == 200) {
      JsonDocument resDoc;
      deserializeJson(resDoc, http.getString());"""

att_new = """    int httpCode = 0;
    String responsePayload = doHttpPost("/api/esp32/attendance", jsonString, 4000, &httpCode);
    if (httpCode == 200) {
      JsonDocument resDoc;
      deserializeJson(resDoc, responsePayload);"""

code = code.replace(att_old, att_new)

code = code.replace("""    } else {
      // HTTP failed mid-request — fall through to offline cache below
      http.end();
      goto offline_cache;
    }
    http.end();""", """    } else {
      // HTTP failed mid-request — fall through to offline cache below
      goto offline_cache;
    }""")


# handleAttendance (proxy alert)
proxy_alert_old = """              HTTPClient http;
              http.begin(serverBaseURL + "/api/esp32/proxy_alert");
              http.addHeader("Content-Type", "application/json");
              http.POST(jsonString);
              http.end();"""

proxy_alert_new = """              doHttpPost("/api/esp32/proxy_alert", jsonString, 4000);"""

code = code.replace(proxy_alert_old, proxy_alert_new)

# handleCaptureRfid
capture_old = """      HTTPClient http;
      http.begin(serverBaseURL + "/api/esp32/attendance");
      http.addHeader("Content-Type", "application/json");
      http.POST(jsonString);
      http.end();"""
capture_new = """      doHttpPost("/api/esp32/attendance", jsonString);"""
code = code.replace(capture_old, capture_new)

# handleRFIDEnrollment
rfid_enroll_old = """      HTTPClient http;
      http.begin(serverBaseURL + "/api/esp32/enroll_success");
      http.addHeader("Content-Type", "application/json");
      int httpCode = http.POST(jsonString);
      if (httpCode == 200) {
        JsonDocument res;
        deserializeJson(res, http.getString());"""

rfid_enroll_new = """      int httpCode = 0;
      String responsePayload = doHttpPost("/api/esp32/enroll_success", jsonString, 4000, &httpCode);
      if (httpCode == 200) {
        JsonDocument res;
        deserializeJson(res, responsePayload);"""

code = code.replace(rfid_enroll_old, rfid_enroll_new)

code = code.replace("""      }
      http.end();
    }
  }
  currentMode = "attendance";""", """      }
    }
  }
  currentMode = "attendance";""")


# handleDeleteAll
delete_old = """    HTTPClient http;
    http.begin(serverBaseURL + "/api/esp32/enroll_success");
    http.addHeader("Content-Type", "application/json");
    http.POST(jsonString);
    http.end();"""
delete_new = """    doHttpPost("/api/esp32/enroll_success", jsonString);"""
code = code.replace(delete_old, delete_new)


with open("esp32_firmware.txt", "w") as f:
    f.write(code)
