import re

with open('esp32_firmware.txt', 'r') as f:
    code = f.read()

# 1. In setup(), add finger.getParameters() to fully initialize library state
setup_target = """  if (!finger.verifyPassword()) {"""
setup_replacement = """  if (!finger.verifyPassword()) {
    Serial.println("[ERROR] Fingerprint sensor not found! Check TX/RX wiring!");
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE, SSD1306_BLACK);
    display.setTextSize(1);
    display.setCursor(0, 20);
    display.print("FINGERPRINT ERROR!");
    display.setCursor(0, 35);
    display.print("Check AS608 Wiring");
    display.setCursor(0, 48);
    display.print("(TX/RX may be swapped)");
    display.display();
    while (1) { delay(100); }
  }
  finger.getParameters(); // Required by some AS608 modules to sync packet sizes"""

if 'finger.getParameters()' not in code:
    code = code.replace(setup_target, setup_replacement)

# 2. Add debug logging for getImage() errors in attendance mode
attendance_target = """  // ── Fingerprint fallback ──
  if (finger.getImage() == FINGERPRINT_OK &&
      finger.image2Tz() == FINGERPRINT_OK) {"""

attendance_replacement = """  // ── Fingerprint fallback ──
  uint8_t p = finger.getImage();
  if (p != FINGERPRINT_OK && p != FINGERPRINT_NOFINGER) {
      Serial.printf("[Fingerprint] getImage error: 0x%02X\\n", p);
  }
  if (p == FINGERPRINT_OK) {
    uint8_t tz = finger.image2Tz();
    if (tz != FINGERPRINT_OK) {
        Serial.printf("[Fingerprint] image2Tz error: 0x%02X\\n", tz);
    }
    if (tz == FINGERPRINT_OK) {"""

if 'uint8_t p = finger.getImage();' not in code:
    code = code.replace(attendance_target, attendance_replacement)
    
    # Also fix the closing brace for the modified if statement
    code = code.replace("""    } else {
      triggerIndicatorSafe(false, "Unknown Finger\\nTry Again");
    }
  }
}

// ========================= Enrollment Handlers =====================""", """    } else {
      triggerIndicatorSafe(false, "Unknown Finger\\nTry Again");
    }
    }
  }
}

// ========================= Enrollment Handlers =====================""")

# 3. Add debug logging for getImage() in enrollment mode
enroll_target = """    p = finger.getImage();
    vTaskDelay(50 / portTICK_PERIOD_MS);
  }"""
enroll_replacement = """    p = finger.getImage();
    if (p != FINGERPRINT_OK && p != FINGERPRINT_NOFINGER) {
      Serial.printf("[Fingerprint Enroll] error: 0x%02X\\n", p);
    }
    vTaskDelay(50 / portTICK_PERIOD_MS);
  }"""

code = code.replace(enroll_target, enroll_replacement)

with open('esp32_firmware.txt', 'w') as f:
    f.write(code)

print("Fingerprint patches applied successfully.")
