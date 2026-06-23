import re

with open("esp32_firmware.txt", "r") as f:
    code = f.read()

# 1. Forward Declarations
fw_decls = """
// ================= Forward Declarations =================
String doHttpGet(String endpoint, int timeoutMs = 2500, int* outHttpCode = NULL);
String doHttpPost(String endpoint, String jsonPayload, int timeoutMs = 4000, int* outHttpCode = NULL);"""

if "String doHttpGet" not in code[:1000]:
    code = code.replace("// ================= Forward Declarations =================", fw_decls)

# 2. Remove stray http.end()
# Lines to target:
# 564, 601, 935, 1044, 1122, 1138, 1326
# I will use standard string replacements for these blocks

# A: processAttendanceData (1044)
code = code.replace("""      goto offline_cache;
    }
    http.end();
    return;""", """      goto offline_cache;
    }
    return;""")

# B: handleRFIDEnrollment (1326)
code = code.replace("""        if (res["success"]) triggerIndicatorSafe(true, "Tag Linked!");
        else triggerIndicatorSafe(false, res["message"].as<String>());
      }
      http.end();
    }
  }
  currentMode = "attendance"; 
}""", """        if (res["success"]) triggerIndicatorSafe(true, "Tag Linked!");
        else triggerIndicatorSafe(false, res["message"].as<String>());
      }
    }
  }
  currentMode = "attendance"; 
}""")

# C: fetchWhitelist (564)
code = code.replace("""      delay(10);
    }
  }
  http.end();
}""", """      delay(10);
    }
  }
}""")

# D: fetchTodayAttendance (601)
code = code.replace("""      }
  } else {
      Serial.println("Failed to fetch today's attendance.");
  }
  http.end();
}""", """      }
  } else {
      Serial.println("Failed to fetch today's attendance.");
  }
}""")

# E: getLocalDateStr / where is 935? 
# Let's just remove all standalone `http.end();` that have indentation of 4, 6, or 8 spaces.
# Actually, the Python script can just strip lines matching exactly `http.end();` with leading spaces.
lines = code.split("\n")
new_lines = []
for line in lines:
    if line.strip() == "http.end();":
        continue
    new_lines.append(line)

code = "\n".join(new_lines)

with open("esp32_firmware.txt", "w") as f:
    f.write(code)
