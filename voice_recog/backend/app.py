import os
import io
import numpy as np
import requests
import torch
import torchaudio
import torchaudio.transforms as T
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from speechbrain.pretrained import SpeakerRecognition

app = FastAPI()

# Setup directories
os.makedirs("backend/static", exist_ok=True)
os.makedirs("backend/recordings", exist_ok=True)
RECORDINGS_DIR = "backend/recordings"

app.mount("/static",     StaticFiles(directory="backend/static"),     name="static")
app.mount("/recordings", StaticFiles(directory=RECORDINGS_DIR),       name="recordings")
templates = Jinja2Templates(directory="backend/templates")

# ── Load SpeechBrain model ───────────────────────────────────────────────────
print("Loading SpeechBrain Model...")
try:
    verification = SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="pretrained_models/spkrec-ecapa-voxceleb"
    )
    print("Model loaded successfully!")
except Exception as e:
    print(f"Error loading model: {e}")
    verification = None

# ── In-memory profile store ──────────────────────────────────────────────────
saved_profiles = {}   # name -> file path

# ── Audio Enhancement ────────────────────────────────────────────────────────
def enhance_audio(file_path: str) -> str:
    """
    Applies audio processing to improve recording quality:
      1. Resample to 16 kHz (model target rate)
      2. Convert to mono
      3. High-pass filter at 80 Hz (removes low-freq rumble from ESP32)
      4. Normalise amplitude to –1..1
    Overwrites the file in-place and returns the path.
    """
    try:
        waveform, sr = torchaudio.load(file_path)

        # Resample to 16 kHz if needed
        if sr != 16000:
            waveform = T.Resample(orig_freq=sr, new_freq=16000)(waveform)
            sr = 16000

        # Convert to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        # High-pass filter: remove frequencies below 80 Hz
        # Using a simple first-order IIR approximation
        RC = 1.0 / (2 * np.pi * 80)
        dt = 1.0 / sr
        alpha = RC / (RC + dt)
        sig = waveform[0].numpy()
        filtered = np.zeros_like(sig)
        filtered[0] = sig[0]
        for i in range(1, len(sig)):
            filtered[i] = alpha * (filtered[i - 1] + sig[i] - sig[i - 1])
        waveform = torch.tensor(filtered).unsqueeze(0)

        # Normalise amplitude
        peak = waveform.abs().max()
        if peak > 0:
            waveform = waveform / peak * 0.95

        torchaudio.save(file_path, waveform, sr)
    except Exception as ex:
        print(f"[enhance_audio] warning: {ex}")

    return file_path


# ── Routes ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    profiles_data = [
        {"name": p, "url": f"/recordings/{os.path.basename(path)}"}
        for p, path in saved_profiles.items()
    ]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "profiles": profiles_data
    })


@app.get("/esp-status")
async def check_esp_status(ip: str):
    if not ip:
        return JSONResponse(status_code=400, content={"error": "IP is required"})
    try:
        res = requests.get(f"http://{ip}/status", timeout=3)
        res.raise_for_status()
        return {"status": "online"}
    except requests.exceptions.RequestException:
        return {"status": "offline"}


@app.get("/profiles")
async def get_profiles():
    return [
        {"name": p, "url": f"/recordings/{os.path.basename(path)}"}
        for p, path in saved_profiles.items()
    ]


@app.post("/record")
async def record_audio(
    esp32_ip: str = Form(...),
    profile_name: str = Form(...),
    is_reference: bool = Form(False)
):
    if not esp32_ip:
        return JSONResponse(status_code=400, content={"error": "ESP32 IP required"})

    try:
        response = requests.get(f"http://{esp32_ip}/record", timeout=12)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return JSONResponse(status_code=500, content={"error": f"ESP32 error: {str(e)}"})

    file_path = os.path.join(RECORDINGS_DIR, f"{profile_name}.wav")
    with open(file_path, "wb") as f:
        f.write(response.content)

    # Enhance audio quality
    enhance_audio(file_path)

    if is_reference:
        saved_profiles[profile_name] = file_path
        return {"status": "success", "message": f"Saved Reference Voice: {profile_name}"}
    else:
        return {"status": "success", "message": f"Recorded audio for {profile_name}", "file_path": file_path}


@app.get("/cross-match-all")
async def cross_match_all():
    """
    Cross-compare every saved profile against every other profile.
    Returns a dict: { profile_name: { best_match, score, all_scores: [{profile, percent, match}] } }
    """
    if verification is None:
        return JSONResponse(status_code=500, content={"error": "Model not loaded properly."})
    if len(saved_profiles) < 2:
        return JSONResponse(status_code=400, content={"error": "Need at least 2 profiles to cross-match."})

    profiles = list(saved_profiles.items())   # [(name, path), ...]
    results = {}

    for i, (name_a, path_a) in enumerate(profiles):
        comparisons = []
        best_score = -1
        best_match = None

        for j, (name_b, path_b) in enumerate(profiles):
            if i == j:
                continue   # skip self
            try:
                score, prediction = verification.verify_files(path_a, path_b)
                score_val = float(score.item())
                is_match  = bool(prediction.item())
            except Exception as ex:
                score_val = 0.0
                is_match  = False

            comparisons.append({
                "profile": name_b,
                "percent": round(score_val * 100, 1),
                "match":   is_match
            })
            if score_val > best_score:
                best_score = score_val
                best_match = name_b

        # Sort comparisons highest first
        comparisons.sort(key=lambda x: x["percent"], reverse=True)

        results[name_a] = {
            "best_match":   best_match,
            "best_score":   round(best_score * 100, 1),
            "comparisons":  comparisons
        }

    return results
