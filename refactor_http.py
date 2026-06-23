import re

with open("esp32_firmware.txt", "r") as f:
    code = f.read()

# Refactor Status Poll
status_old = """      // 1. Poll Server Status (Every 2s)
      if (millis() - lastPollTime > 2000 && serverBaseURL != "") {
        HTTPClient http;
        http.begin(serverBaseURL + "/api/esp32/status");
        http.setTimeout(2500); // 2.5 second timeout to prevent blocking when server drops
        int httpCode = http.GET();
        if (httpCode == 200) {
          isOnline = true; // Mark as online ONLY when server responds
          lastSuccessfulPing = millis();
          JsonDocument doc;
          deserializeJson(doc, http.getString());"""

status_new = """      // 1. Poll Server Status (Every 2s)
      if (millis() - lastPollTime > 2000 && serverBaseURL != "") {
        int httpCode = 0;
        String responsePayload = doHttpGet("/api/esp32/status", 2500, &httpCode);
        if (httpCode == 200) {
          isOnline = true; // Mark as online ONLY when server responds
          lastSuccessfulPing = millis();
          JsonDocument doc;
          deserializeJson(doc, responsePayload);"""

code = code.replace(status_old, status_new)

# In status processing, remove http.end()
code = code.replace("""        }
        http.end();
        lastPollTime = millis();""", """        }
        lastPollTime = millis();""")

# Add logic for new modes inside the JSON doc processing
mode_logic_old = """          String newMode = doc["mode"].as<String>();
          if (!doc["assign_id"].isNull()) targetID = doc["assign_id"].as<int>();
          if (newMode != currentMode) currentMode = newMode;"""

mode_logic_new = """          String newMode = doc["mode"].as<String>();
          if (!doc["assign_id"].isNull()) targetID = doc["assign_id"].as<int>();
          
          if (newMode == "force_audit") {
              pendingAudit = true;
              auditExpectedRFID = "SIMULATED";
              auditStartTime = millis();
              playAudio("error");
              if (xSemaphoreTake(displayMutex, portMAX_DELAY)) {
                  display.clearDisplay();
                  display.fillRect(0, 0, 128, 16, SSD1306_WHITE);
                  display.setTextColor(SSD1306_BLACK);
                  display.setCursor(4, 4); display.print("SECURITY AUDIT");
                  display.setTextColor(SSD1306_WHITE);
                  display.setCursor(0, 24); display.print("Proxy Suspected!");
                  display.setCursor(0, 36); display.print("Verify Identity:");
                  display.setCursor(0, 50); display.print("Place Fingerprint!");
                  display.display();
                  xSemaphoreGive(displayMutex);
              }
              currentMode = "attendance";
          } else if (newMode == "enroll_master_finger") {
              currentMode = "enroll_master_finger";
          } else if (newMode != currentMode) {
              currentMode = newMode;
          }"""

code = code.replace(mode_logic_old, mode_logic_new)

# Batch Sync
batch_old = """             HTTPClient http;
             http.begin(serverBaseURL + "/api/esp32/attendance/batch");
             http.addHeader("Content-Type", "application/json");
             http.setTimeout(4000); // 4 second timeout for network call
             int httpCode = http.POST(jsonArray);
             http.end();

             if (httpCode == 200) {"""

batch_new = """             int httpCode = 0;
             doHttpPost("/api/esp32/attendance/batch", jsonArray, 4000, &httpCode);
             if (httpCode == 200) {"""
             
code = code.replace(batch_old, batch_new)

with open("esp32_firmware.txt", "w") as f:
    f.write(code)
