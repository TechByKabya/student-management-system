import requests

data = {
    "sensor": "rfid",
    "uid": "1234567",
    "timestamp": 1234567890,
    "ai_dwell": 120.5,
    "ai_inter": 1500.2
}
r = requests.post("http://localhost:5005/api/esp32/attendance", json=data)
print(r.status_code)
print(r.text)
