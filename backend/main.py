# === backend/main.py ===

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import requests, time, re, json

# ✅ Config (later move to Azure App Settings)
AZURE_ENDPOINT = "YOUR_AZURE_ENDPOINT"
AZURE_KEY = "YOUR_AZURE_KEY"
AZURE_MODEL_ID = "special-meal-v1"

app = FastAPI(title="SPML Backend", version="1.0")

# ✅ Allow frontend (React) to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 1. Azure OCR Call ===
def analyze_meal_list_azure(file_bytes):
    url = f"{AZURE_ENDPOINT}formrecognizer/documentModels/{AZURE_MODEL_ID}:analyze?api-version=2023-07-31"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Content-Type": "application/octet-stream"
    }
    
    # Step 1: Send image/PDF to Azure
    response = requests.post(url, headers=headers, data=file_bytes)
    if response.status_code != 202:
        raise Exception(f"Azure failed: {response.text}")
    
    # Step 2: Poll for result
    result_url = response.headers["operation-location"]
    for _ in range(15):  # max 15 sec
        result = requests.get(result_url, headers={"Ocp-Apim-Subscription-Key": AZURE_KEY})
        data = result.json()
        if data.get("status") == "succeeded":
            return data
        elif data.get("status") == "failed":
            raise Exception("Azure OCR failed")
        time.sleep(1)
    raise TimeoutError("Azure OCR timed out")

# === 2. Extract + Clean Meal Blocks ===
def clean_azure_meal_blocks(azure_json):
    clean_blocks = []
    special_meal_list = []

    def recursive_extract(d):
        if isinstance(d, dict):
            if "Seat" in d and "Meal_Code" in d:
                special_meal_list.append(d)
            if "fields" in d and isinstance(d["fields"], dict):
                f = d["fields"]
                if "Seat" in f and "Meal_Code" in f:
                    special_meal_list.append(f)
            for v in d.values():
                recursive_extract(v)
        elif isinstance(d, list):
            for v in d:
                recursive_extract(v)

    recursive_extract(azure_json)

    def extract_text(field):
        if isinstance(field, str):
            return field.strip()
        elif isinstance(field, dict):
            return field.get("content", field.get("valueString", "")).strip()
        return ""

    for entry in special_meal_list:
        raw_name  = extract_text(entry.get("content", entry.get("PassengerName", "")))
        raw_title = extract_text(entry.get("Ttile", entry.get("Title", "")))
        raw_seat  = extract_text(entry.get("Seat", ""))
        raw_meal  = extract_text(entry.get("Meal_Code", ""))

        # Name cleanup
        raw_name = re.sub(r"^\d+\.", "", raw_name)
        if "/" in raw_name:
            parts = raw_name.split("/")
            cleaned_name = " ".join(part.title() for part in parts if part)
        else:
            cleaned_name = raw_name.title()

        cleaned_meal = re.sub(r"-GU.*$", "", raw_meal)

        # Validate seat (2-3 digits + letter)
        seat_match = re.match(r"^\d{2,3}[A-Z]$", raw_seat)
        cleaned_seat = raw_seat if seat_match else ""

        clean_blocks.append({
            "name": cleaned_name,
            "title": raw_title,
            "seat": cleaned_seat or "[MISSING]",
            "meal": cleaned_meal or "[MISSING]"
        })

    return clean_blocks

# === 3. API Endpoint ===
@app.post("/upload-meal-list")
async def upload_meal_list(file: UploadFile = File(...)):
    """
    Upload meal list image/PDF → returns parsed meal blocks JSON
    """
    try:
        file_bytes = await file.read()
        azure_result = analyze_meal_list_azure(file_bytes)
        meal_blocks = clean_azure_meal_blocks(azure_result)
        return {"status": "success", "count": len(meal_blocks), "blocks": meal_blocks}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# === 4. Simple health check ===
@app.get("/")
def root():
    return {"message": "✅ SPML Backend running"}
