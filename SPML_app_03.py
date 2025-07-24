import streamlit as st
import json
import pandas as pd
from io import StringIO
import os
from collections import Counter
import requests, time, json, re, sys

# ✅ Force Streamlit to use Azure-friendly host/port
os.environ["STREAMLIT_SERVER_ADDRESS"] = "0.0.0.0"
os.environ["STREAMLIT_SERVER_PORT"] = "8000"
os.environ["STREAMLIT_SERVER_ENABLECORS"] = "false"
os.environ["STREAMLIT_SERVER_ENABLEXSRS_PROTECTION"] = "false"

# ✅ Load secrets from Azure App Settings (environment variables)
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_KEY")
AZURE_MODEL_ID = os.getenv("AZURE_MODEL_ID", "special-meal-v1")

from PIL import Image
import io
@st.cache_data
def normalize_image_for_azure(uploaded_file, target_dpi=200, max_width=3000, max_height=3000):
    """
    Resize image safely for Azure OCR:
    - Ensures manageable DPI (~200)
    - Avoids file > 50MB
    - Keeps within Azure limits (max 10k px)
    """
    img = Image.open(uploaded_file)
    img = img.convert("RGB")  # ensure no alpha

    # Current dimensions
    width, height = img.size
    dpi_info = img.info.get("dpi", (72, 72))
    current_dpi = dpi_info[0]

    # --- Decide scaling ---
    # If too small (<150 DPI), upscale moderately
    if current_dpi < 150:
        scale_factor = 150 / current_dpi
        new_width = min(int(width * scale_factor), max_width)
        new_height = min(int(height * scale_factor), max_height)
        img = img.resize((new_width, new_height), Image.LANCZOS)

    # If too large, downscale
    if width > max_width or height > max_height:
        img.thumbnail((max_width, max_height), Image.LANCZOS)

    # Save optimized image
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90, dpi=(target_dpi, target_dpi))
    buffer.seek(0)

    return buffer.read()

# === Azure OCR Call ===
def analyze_meal_list_azure(file_bytes):
    """
    Sends image/PDF to Azure OCR (Document Intelligence V1 model)
    and waits for the structured JSON result.
    """
    url = f"{AZURE_ENDPOINT}formrecognizer/documentModels/{AZURE_MODEL_ID}:analyze?api-version=2023-07-31"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Content-Type": "application/octet-stream"
    }
    
    # Step 1: Send image/PDF to Azure
    response = requests.post(url, headers=headers, data=file_bytes)
    if response.status_code != 202:
        raise Exception(f"Azure failed: {response.text}")
    
    # Step 2: Poll until Azure finishes analysis
    result_url = response.headers["operation-location"]
    for _ in range(30):  # wait up to 30 seconds
        result = requests.get(result_url, headers={"Ocp-Apim-Subscription-Key": AZURE_KEY})
        data = result.json()
        if data.get("status") == "succeeded":
            return data
        elif data.get("status") == "failed":
            raise Exception("Azure analysis failed")
        time.sleep(1)
    raise TimeoutError("Azure OCR timed out")


# === Helper: Extract Text Safely ===
def extract_text(field):
    """
    Handles Azure fields that can be either a string or a nested dict.
    Always returns a clean string.
    """
    if isinstance(field, str):
        return field.strip()
    elif isinstance(field, dict):
        return field.get("content", field.get("valueString", "")).strip()
    return ""


# === Cleanup Parser ===
def clean_azure_meal_blocks(azure_json):
    """
    Cleans Azure OCR JSON and returns ready-to-use meal blocks for SPML.
    Adds fallback regex for Seat & Meal when missing.
    """
    clean_blocks = []
    special_meal_list = []

    # --- Grab full OCR text for fallback ---
    raw_text = azure_json.get("content", "")
    seat_candidates = re.findall(r"\b\d{2,3}[A-Z]\b", raw_text)
    meal_candidates = re.findall(r"\b(?:FPML|DBML|VGML|LSML|CHML|LCML|AVML)\b", raw_text)

    # --- Recursive scan to find meal rows ---
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

    for entry in special_meal_list:
        raw_name  = extract_text(entry.get("content", entry.get("PassengerName", "")))
        raw_title = extract_text(entry.get("Ttile", entry.get("Title", "")))
        raw_seat  = extract_text(entry.get("Seat", ""))
        raw_meal  = extract_text(entry.get("Meal_Code", ""))

        # 1️⃣ Clean Passenger Name
        raw_name = re.sub(r"^\d+\.", "", raw_name)
        if "/" in raw_name:
            parts = raw_name.split("/")
            cleaned_name = " ".join(part.title() for part in parts if part)
        else:
            cleaned_name = raw_name.title()

        # 2️⃣ Clean Meal Code
        cleaned_meal = re.sub(r"-GU.*$", "", raw_meal)

        # 3️⃣ Validate seat
        seat_match = re.match(r"^\d{2,3}[A-Z]$", raw_seat)
        cleaned_seat = raw_seat if seat_match else ""

        # 4️⃣ Fallback if seat/meal missing
        if not cleaned_seat and seat_candidates:
            cleaned_seat = seat_candidates.pop(0)
        if not cleaned_meal and meal_candidates:
            cleaned_meal = meal_candidates.pop(0)

        # 5️⃣ Still log if missing after fallback
        if not cleaned_seat or not cleaned_meal:
            print(f"⚠️ Even fallback missing for: {cleaned_name} (seat={cleaned_seat}, meal={cleaned_meal})")

        clean_blocks.append({
            "name": cleaned_name,
            "title": raw_title,
            "seat": cleaned_seat or "[MISSING]",
            "meal": cleaned_meal or "[MISSING]"
        })

    return clean_blocks
# === Simple Access Control ===
if "access_granted" not in st.session_state:
    st.session_state["access_granted"] = False

if not st.session_state["access_granted"]:
    st.subheader("🔒 Crew Access Only")
    passcode_input = st.text_input("Enter crew passcode", type="password")
    
    # Set your passcode here (can later move to secrets.toml)
    correct_passcode = "flysafesnf"
    
    if passcode_input == correct_passcode:
        st.session_state["access_granted"] = True
        st.success("✅ Access granted. Welcome crew!")
        st.rerun()
    elif passcode_input:
        st.error("❌ Incorrect passcode.")
    
    st.stop()
###Start of SPML
st.set_page_config(page_title="Special Meal Loader", layout="centered")
st.title("✈️ Special Meal Loader")
st.markdown("""
> ✈️ **Why use this app?**  
> With the help of ChatGPT to extract your meal list data, this app helps you **assign zones**, **track delivery**, **print crew-ready labels**, and **many more** — faster and cleaner.
""")
#Chatgpt OCR Feature. the dream is having all the OCR done in without leaving the page using chat gpt umbeded. inshallah
st.markdown("## 📤 Use ChatGPT to Extract Meals from Image")

st.markdown("""
If you have a special meal list **image**, you can send it to ChatGPT to extract passenger data (name, seat, meal).

1. 📎 Open ChatGPT [**ChatGPT**](https://chat.openai.com)
2. 📸 Upload the image
3. 💾 Ask it to *"Please extract passenger name, title (MR/MS/MRS), seat number (ignore no seat), and meal code into a special_meals.json format and return to download "*
4. ✅ Download the file and re-upload here to continue
""", unsafe_allow_html=True)

prompt_text = "Please extract passenger name, title (MR/MS/MRS), seat number, and meal code into a special_meals.json format."

with st.expander("📋 Show ChatGPT Prompt"):
    st.text_input(
        label="📋 Tap and hold to copy this prompt (works on all devices)",
        value=prompt_text,
        key="prompt_input",
        help="Copy this prompt manually and paste it into ChatGPT.",
        disabled=True  # read-only
    )

# Initialize session state
if "blocks" not in st.session_state:
    st.session_state["blocks"] = []
if "aircraft_type" not in st.session_state:
    st.session_state["aircraft_type"] = None
if "registration_prefix" not in st.session_state:
    st.session_state["registration_prefix"] = None
if "side_filter" not in st.session_state:
    st.session_state["side_filter"] = "Both"
if "zone_filter" not in st.session_state:
    st.session_state["zone_filter"] = "All"
#Printing labels to indicate which file was printed 
if "downloaded_zones" not in st.session_state:
    st.session_state["downloaded_zones"] = set()
# Initialize session state
if "blocks" not in st.session_state:
    st.session_state["blocks"] = []
#Lock/unlock aircraft entry
if "aircraft_locked" not in st.session_state:
    st.session_state["aircraft_locked"] = False
# Path to auto-save file
auto_save_path = "special_meals_autosave.json"

def auto_save():
    with open(auto_save_path, "w") as f:
        json.dump(st.session_state["blocks"], f, indent=2)

# === Multi-file Upload (New Sessions) ===
st.subheader("📂 Upload One or More Extracted JSON Files")
uploaded_files = st.file_uploader("📌 Upload special_meals.json files", type="json", accept_multiple_files=True)
if uploaded_files:
    merged_blocks = []
    for file in uploaded_files:
        try:
            data = json.load(file)
            merged_blocks.extend(data)
        except Exception as e:
            st.error(f"❌ Failed to load {file.name}: {e}")
    if merged_blocks:
        st.session_state["blocks"] = merged_blocks
        auto_save()
        st.success(f"✅ Loaded {len(merged_blocks)} total meal blocks from {len(uploaded_files)} files.")

# ✅ === NEW Azure OCR Section ===
st.subheader("📸 Upload Meal List Image (Azure OCR V1)")

azure_image = st.file_uploader(
    "Upload JPG/PNG/PDF for OCR",
    type=["jpg", "jpeg", "png", "pdf"],
    key="azure_upload"
)

if azure_image is not None:
    try:
        # Spinner for image optimization + OCR call
        with st.spinner("⏳ Optimizing image & sending to Azure OCR..."):
            optimized_bytes = normalize_image_for_azure(azure_image)
            azure_result = analyze_meal_list_azure(optimized_bytes)

        # Spinner for cleaning the OCR result
        with st.spinner("⏳ Cleaning Azure OCR results..."):
            meal_blocks = clean_azure_meal_blocks(azure_result)

        if meal_blocks:
            st.session_state["blocks"] = meal_blocks
            auto_save()
            st.success(f"✅ Azure OCR loaded {len(meal_blocks)} meal blocks!")
            st.json(meal_blocks[:5])  # quick preview
        else:
            st.warning("⚠️ Azure returned no valid meal blocks. Try again or check model.")

    except Exception as e:
        st.error(f"❌ Azure OCR failed: {e}")

def assign_side_and_zone(block, aircraft_type, reg_prefix):
    seat = block.get("seat", "")
    if not seat or len(seat) < 4:
        return
    row = int(seat[:3])
    letter = seat[-1]
    side = None
    zone = None

    # Seat letter logic (simplified)
# Airbus 330 
    if aircraft_type == "A330":
        left = {"A", "C", "D", "E"}
        right = {"F", "H", "J", "L"}
    # A333
        if reg_prefix in {"QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH"}:  # A333
            if row <= 46:
                zone = "L3" if letter in left else "R3"
            else:
                zone = "L4" if letter in left else "R4"
    # A33R            
        elif reg_prefix in {"Q11", "Q12", "Q13", "Q14", "Q15", "Q16", "Q17", "Q18", "Q19", "Q20", "Q21", "Q22", "Q23", "Q24", "Q25", "Q26", "Q27", "Q28", "Q29"}:  # A33R
            if row <= 43:
                zone = "L2" if letter in left else "R2"
            elif row <= 56:
                zone = "L3" if letter in left else "R3"
            else:
                zone = "L4" if letter in left else "R4"
    # A33D
        elif reg_prefix in {"QI", "QJ", "QK", "QL"}:  # A33D
            if row <= 46:
                zone = "L3" if letter in left else "R3"
            else:
                zone = "L4" if letter in left else "R4"
# Boing 787
    elif aircraft_type == "B787":
        left = {"A", "B", "C", "D", "E"}
        right = {"H", "J", "K", "L"}
    # B780
        if reg_prefix in {"R24", "R25", "R26", "R27", "R28", "R29", "R32", "R33"}:  # B780
            if row <= 50:
                zone = "L3" if letter in left else "R3"
            else:
                zone = "L4" if letter in left else "R4"
            
    # B789
        elif reg_prefix in {"R11", "R12", "R13", "R22", "R23", "RA", "RB", "RC", "RD", "RE", "RF", "RG", "RH"}:  # B789
            if row <= 45:
                zone = "L3" if letter in left else "R3"
            else:
                zone = "L4" if letter in left else "R4"
 
# Boing 777
    elif aircraft_type == "B777":
        left = {"A", "B", "C", "D", "E"}
        right = {"F", "H", "J", "K", "L"}
    # B77Z
        if reg_prefix in {"K36", "K37", "K38", "K39", "K40", "K41", "K42", "K43", "K44", "K45"}:  # B77Z
            if row <= 43:
                zone = "L4" if letter in left else "R4"
            else:
                zone = "L5" if letter in left else "R5"
     # B77D NOTE: some aircraft has been added here recently but not updated in the code 
        elif reg_prefix in {"K17", "K18", "K19", "K20", "K21", "K22"}:  # 77D
            if row <= 44:
                zone = "L2" if letter in left else "R2"
            elif row <= 59:
                zone = "L4" if letter in left else "R4"
            else:
                zone = "L5" if letter in left else "R5"
    # B773 / B77A
        elif reg_prefix in {"K11", "K12", "K13", "K14", "K15", "K16", "K31", "K32", "K33", "K34", "K35"}:  # B773 / B77A
            if row <= 41:
                zone = "L3" if letter in left else "R3"
            elif row <= 54:
                zone = "L4" if letter in left else "R4"
            else:
                zone = "L5" if letter in left else "R5"
    # B77H
        elif reg_prefix in {"K23", "K24", "K25", "K26", "K27", "K28", "K29", "K30"}:  # B77H
            if row <= 44:
                zone = "L3" if letter in left else "R3"
            elif row <= 58:
                zone = "L4" if letter in left else "R4"
            else:
                zone = "L5" if letter in left else "R5"
# result of aircraft filter 
    side = "L" if letter in left else "R" if letter in right else None
    block["side"] = side
    block["zone"] = zone

# === Aircraft & Registration Selection ===
st.subheader("✈️ Aircraft & Registration")
acft_options = ["A330", "B787", "B777"]
st.session_state["aircraft_type"] = st.selectbox(
    "Select Aircraft Type",
    acft_options,
    key="aircraft_type_select",
    disabled=st.session_state["aircraft_locked"]
)

#registration list
reg_options = []
if st.session_state["aircraft_type"] == "A330":
    reg_options = ["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH", "QI", "QJ", "QK", "QL"] + [f"Q{i}" for i in range(11, 30)]
elif st.session_state["aircraft_type"] == "B787":
    reg_options = ["R11", "R12", "R13", "R22", "R23"] + [f"R{i}" for i in range(24, 30)] + ["R32", "R33"] + [f"R{c}" for c in ["A","B","C","D","E","F","G","H"]]
elif st.session_state["aircraft_type"] == "B777":
    reg_options = [f"K{i}" for i in range(11, 46)] + [f"K{c}" for c in ["A","B","C","D","E","F","G","H"]]

st.session_state["registration_prefix"] = st.selectbox(
    "Select Registration Prefix",
    sorted(reg_options),
    key="reg_prefix_select",
    disabled=st.session_state["aircraft_locked"]
)
if st.session_state["aircraft_locked"]:
    st.warning("✋ Aircraft & registration are locked after label generation. MAKE SURE ALL PRINTS ARE DONE")
    if st.button("🔓 Unlock Aircraft Selection. (Zone distribution will change)"):
        st.session_state["aircraft_locked"] = False
        st.success("✅ Confirm ? Aircraft selection will be unlocked. Be careful when reprinting!")

# Reassign side and zone after aircraft/prefix selection
for block in st.session_state["blocks"]:
    assign_side_and_zone(block, st.session_state["aircraft_type"], st.session_state["registration_prefix"])
for block in st.session_state["blocks"]:
    if not block.get("side") or not block.get("zone"):
        st.warning(f"⚠️ Block missing side/zone: {block}")

# === Print Side and Zone Filters ===
# Ensure all blocks are updated first
for block in st.session_state["blocks"]:
    assign_side_and_zone(block, st.session_state["aircraft_type"], st.session_state["registration_prefix"])

# Allow filtering (I add it a generote labble by side and zone)
st.session_state["side_filter"] = st.radio("Print Side Filter", ["Both", "Left Only", "Right Only"], key="side_filter_radio")

#Zone Filter Logic to Match Zone Prefix
if st.session_state["side_filter"] != "Both":
    side_key = st.session_state["side_filter"][0]  # L or R

    all_zones = sorted(set(
        b["zone"] for b in st.session_state["blocks"]
        if b.get("zone") and b["zone"].startswith(side_key)
    ))

    if all_zones:
        st.session_state["zone_filter"] = st.selectbox(
            "Optional Door Zone Filter", ["All"] + all_zones, key="zone_filter_select"
        )
    else:
        st.session_state["zone_filter"] = "All"
        st.warning("⚠️ No valid zones detected for selected side.")

else:
    st.session_state["zone_filter"] = "All"

#Optional: Print Zone Distribution Debug Info

from collections import Counter
zone_counts = Counter(b.get("zone", "Missing") for b in st.session_state["blocks"])
st.text(f"📊 Zone distribution: {dict(zone_counts)}")

# === Upload JSON (Resume Previous Session) ===
st.subheader("📂 Resume Previous Session")
resume_file = st.file_uploader("📌 Load saved special_meals_edited.json", type="json", key="resume")
if resume_file:
    try:
        resumed_data = json.load(resume_file)
        st.session_state["blocks"] = resumed_data
        auto_save()
        st.success(f"✅ Resumed session with {len(resumed_data)} blocks.")
    except Exception as e:
        st.error(f"❌ Failed to load saved session: {e}")

# === Filtering Panel ===
if st.session_state["blocks"]:
    st.subheader("🔍 Filter Options By Meals")
    all_meals = sorted({b.get("meal", "") for b in st.session_state["blocks"]})
    meal_filter = st.selectbox("🍱 Filter by Meal Type", options=["All"] + all_meals)
    show_undelivered_only = st.checkbox("❌ Show only Undelivered")

    filtered_blocks = []
    for block in st.session_state["blocks"]:
        if meal_filter != "All" and block.get("meal") != meal_filter:
            continue
        if show_undelivered_only and block.get("delivered"):
            continue
        filtered_blocks.append(block)

    # === Summary Statistics ===
    st.subheader("📊 Summary Stats")
    meal_counts = Counter(b.get("meal", "Unknown") for b in filtered_blocks)
    delivered_count = sum(1 for b in filtered_blocks if b.get("delivered"))
    total_count = len(filtered_blocks)

    missing_seat = sum(1 for b in filtered_blocks if not b.get("seat"))
    missing_meal = sum(1 for b in filtered_blocks if not b.get("meal"))
    missing_name = sum(1 for b in filtered_blocks if not b.get("name"))

    st.markdown(f"**Total Blocks:** {total_count}")
    st.markdown(f"**Delivered:** {delivered_count}")
    st.markdown("**By Meal Type:**")
    for meal, count in meal_counts.items():
        st.markdown(f"- {meal}: {count}")

    st.markdown("**Validation Warnings:**")
    st.markdown(f"- ⚠️ Missing Seat: {missing_seat}")
    st.markdown(f"- ⚠️ Missing Meal Code: {missing_meal}")
    st.markdown(f"- ⚠️ Missing Name: {missing_name}")

    st.subheader("📅 Meal Blocks")
    excluded_indices = set()
    for i, block in enumerate(filtered_blocks):
        with st.expander(f"{block.get('seat', 'Unknown Seat')} — {block.get('meal', '')}"):
            st.text(f"Name: {block.get('name', '')} ({block.get('title', '')})")
            st.text(f"Meal: {block.get('meal', '')}")

            # Validation warnings
            warnings = []
            if not block.get("seat"):
                warnings.append("⚠️ Missing seat")
            if not block.get("meal"):
                warnings.append("⚠️ Missing meal code")
            if not block.get("name"):
                warnings.append("⚠️ Missing name")

            if warnings:
                st.warning(" | ".join(warnings))

            comment = st.text_input("📝 Crew Comment", value=block.get("crew_comments", ""), key=f"comment_{i}")
            block["crew_comments"] = comment

            delivered = st.checkbox("✅ Mark as Delivered", value=block.get("delivered", False), key=f"delivered_{i}")
            block["delivered"] = delivered

            exclude = st.checkbox("🚫 Exclude from Print", key=f"exclude_{i}")
            if exclude:
                excluded_indices.add(i)

            auto_save()

    # === Save Button ===
    st.subheader("📃 Save Progress")
    json_str = json.dumps(st.session_state["blocks"], indent=2)
    st.download_button(
        label="📃 Download JSON",
        file_name="special_meals_edited.json",
        mime="application/json",
        data=json_str.encode('utf-8')
    )

    # === Export Printable Labels ===
    st.subheader("🖨️ Export Printable Labels")
    if st.button("🖨️ Generate Labels"):
        st.session_state["aircraft_locked"] = True   # 🔒 Lock aircraft selection
        side_target = st.session_state["side_filter"]
        zone_target = st.session_state["zone_filter"]
        labels = []
        for i, block in enumerate(filtered_blocks):
            if i in excluded_indices:
                continue
            if side_target != "Both" and block.get("side") != side_target[0]:
                continue
            if zone_target != "All" and block.get("zone") != zone_target:
                continue

            seat = f"** {block.get('seat', '')} **".center(28)
            meal = block.get("meal", "").center(28)
            title = block.get("title", "")
            name = block.get("name", "")
            title_name = f"{title} {name}".strip().center(28)
            label = [
                "+" + "-" * 28 + "+",
                "|" + seat + "|",
                "|" + meal + "|",
                "|" + title_name + "|",
                "+" + "-" * 28 + "+",
                ""
            ]
            labels.append("\n".join(label))

        printable = "\n".join(labels)
        st.download_button(
            label="📄 Download Labels (TXT)",
            file_name="print_labels.txt",
            mime="text/plain",
            data=printable
        )

    # === Export Labels by Zone ===
    st.subheader("🖨️ Export Labels by Zone")
    if st.button("📦 Generate Zone Files"):
        st.session_state["aircraft_locked"] = True  # 🔒 Lock aircraft selection
        from collections import defaultdict
        zone_groups = defaultdict(list)

        side_target = st.session_state["side_filter"]
        zone_target = st.session_state["zone_filter"]

        for i, block in enumerate(filtered_blocks):
            if i in excluded_indices:
                continue
            if side_target != "Both" and block.get("side") != side_target[0]:
                continue
            if zone_target != "All" and block.get("zone") != zone_target:
                continue
            zone = block.get("zone", "UNKNOWN")
            zone_groups[zone].append(block)

        if not zone_groups:
            st.warning("❌ No blocks matched the filters for zone export.")
        else:
            for zone, blocks in zone_groups.items():
                label_lines = []
                for block in blocks:
                    seat = f"** {block.get('seat', '')} **".center(28)
                    meal = block.get("meal", "").center(28)
                    title = block.get("title", "")
                    name = block.get("name", "")
                    title_name = f"{title} {name}".strip().center(28)
                    label = [
                        "+" + "-" * 28 + "+",
                        "|" + seat + "|",
                        "|" + meal + "|",
                        "|" + title_name + "|",
                        "+" + "-" * 28 + "+",
                        ""
                    ]
                    label_lines.append("\n".join(label))

                file_content = "\n".join(label_lines)

                # ✅ Track whether this zone was already downloaded
                zone_downloaded = zone in st.session_state["downloaded_zones"]
                # 🧱 Split into two columns for button + status
                col1, col2 = st.columns([1, 2])

                with col1:

                    st.download_button(
                        label=f"📄 Download {zone} Labels",
                        file_name=f"print_{zone}.txt",
                        mime="text/plain",
                        data=file_content,
                        key=f"download_button_{zone}",  # Unique key per zone
                        on_click=lambda z=zone: st.session_state["downloaded_zones"].add(z)
                    )
                with col2:
                    if zone_downloaded:
                        st.success("✅ Downloaded")
    
                # Apply side and zone filter before printing
                if side_target != "Both" and block.get("side") != side_target[0]:
                    continue
                if zone_target != "All" and block.get("zone") != zone_target:
                    continue
# general Label
            seat = f"** {block.get('seat', '')} **".center(28)
            meal = block.get("meal", "").center(28)
            title = block.get("title", "")
            name = block.get("name", "")
            title_name = f"{title} {name}".strip().center(28)
            label = [
                "+" + "-" * 28 + "+",
                "|" + seat + "|",
                "|" + meal + "|",
                "|" + title_name + "|",
                "+" + "-" * 28 + "+",
                ""
            ]
           # labels.append("\n".join(label))

        #printable = "\n".join(labels)
        #st.download_button(
            #label="📄 Download Labels (TXT)",
            #file_name="print_labels.txt",
            #mime="text/plain",
            #data=printable
        #)
else:
    st.info("Please upload a JSON file to begin.")

 
 
