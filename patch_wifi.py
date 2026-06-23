import re

with open("esp32_firmware.txt", "r") as f:
    code = f.read()

# Add wifiMutex globally
if "SemaphoreHandle_t wifiMutex;" not in code:
    code = code.replace("SemaphoreHandle_t sdMutex;", "SemaphoreHandle_t sdMutex;\nSemaphoreHandle_t wifiMutex;")

# Initialize in setup()
if "wifiMutex = xSemaphoreCreateMutex();" not in code:
    code = code.replace("sdMutex = xSemaphoreCreateMutex();", "sdMutex = xSemaphoreCreateMutex();\n  wifiMutex = xSemaphoreCreateMutex();")

# We don't want to use regex blindly for all http blocks because some have early returns or goto
# Let's do it cleanly:
# We will create helper methods in the firmware!
helpers = """
// ================= Thread-Safe HTTP Helpers =================
String doHttpGet(String endpoint, int timeoutMs = 2500, int* outHttpCode = NULL) {
    String payload = "";
    if (xSemaphoreTake(wifiMutex, portMAX_DELAY)) {
        HTTPClient http;
        http.begin(serverBaseURL + endpoint);
        http.setTimeout(timeoutMs);
        int httpCode = http.GET();
        if (outHttpCode) *outHttpCode = httpCode;
        if (httpCode == 200) payload = http.getString();
        http.end();
        xSemaphoreGive(wifiMutex);
    }
    return payload;
}

String doHttpPost(String endpoint, String jsonPayload, int timeoutMs = 4000, int* outHttpCode = NULL) {
    String payload = "";
    if (xSemaphoreTake(wifiMutex, portMAX_DELAY)) {
        HTTPClient http;
        http.begin(serverBaseURL + endpoint);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(timeoutMs);
        int httpCode = http.POST(jsonPayload);
        if (outHttpCode) *outHttpCode = httpCode;
        if (httpCode == 200) payload = http.getString();
        http.end();
        xSemaphoreGive(wifiMutex);
    }
    return payload;
}
"""
if "Thread-Safe HTTP Helpers" not in code:
    code = code.replace("// ================= Mode Handlers =================", helpers + "\n// ================= Mode Handlers =================")

with open("esp32_firmware.txt", "w") as f:
    f.write(code)
