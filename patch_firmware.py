import re

with open('esp32_firmware.txt', 'r') as f:
    code = f.read()

# 1. Fix text glitch by explicitly setting background color for all text prints
code = code.replace('display.setTextColor(SSD1306_WHITE);', 'display.setTextColor(SSD1306_WHITE, SSD1306_BLACK);')
code = code.replace('display.setTextColor(SSD1306_BLACK);', 'display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);')

# 2. Add NTP sync for RTC module
ntp_logic = """    if (wifiConnected) {
      static bool ntpConfigured = false;
      if (!ntpConfigured) {
        configTime(0, 0, "pool.ntp.org", "time.nist.gov"); // Fetch UTC time
        ntpConfigured = true;
      }
      
      if (ntpConfigured && rtcReady) {
        static bool rtcUpdatedFromNTP = false;
        if (!rtcUpdatedFromNTP) {
          struct tm timeinfo;
          // non-blocking check
          if (getLocalTime(&timeinfo, 10)) {
            if (timeinfo.tm_year > (2024 - 1900)) {
              rtc.adjust(DateTime(timeinfo.tm_year + 1900, timeinfo.tm_mon + 1, timeinfo.tm_mday, timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec));
              rtcUpdatedFromNTP = true;
              Serial.println("[NTP] RTC successfully synced with internet time (UTC).");
            }
          }
        }
      }

      // mDNS auto-discovery"""

code = code.replace('    if (wifiConnected) {\n      // mDNS auto-discovery', ntp_logic)

with open('esp32_firmware.txt', 'w') as f:
    f.write(code)

print("Patch applied successfully.")
