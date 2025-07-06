import streamlit as st
import json
import pandas as pd
from io import StringIO
import os
from collections import Counter

st.set_page_config(page_title="Special Meal Loader", layout="centered")
st.title("✈️ Special Meal Loader")

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

# Path to auto-save file
auto_save_path = "special_meals_autosave.json"

def auto_save():
    with open(auto_save_path, "w") as f:
        json.dump(st.session_state["blocks"], f, indent=2)
def load_blocks_from_ocr_json():
    path = input("📄 Enter path to OCR layout JSON (ocr_output.json): ").strip()
    global sample_blocks

    try:
        with open(path, "r") as f:
            ocr_data = json.load(f)

        # Step 1: Flatten and sort by vertical position
        entries = []
        for bbox, text, conf in ocr_data:
            x, y = bbox[0]
            entries.append({
                "x": x,
                "y": y,
                "text": text.strip().upper(),
                "conf": conf
            })
        entries.sort(key=lambda e: (e["y"], e["x"]))

        # Step 2: Group into name/title/seat/meal
        blocks = []
        current = {"name": None, "title": None, "seat": None, "meal": None}

        for entry in entries:
            txt = entry["text"]

            if "/" in txt:
                current["name"] = txt.replace("/", " ").title()
            elif txt in {"MR", "MS", "MRS"}:
                current["title"] = txt
            elif re.match(r"[O0]?\d{2}[A-Z]", txt):
                current["seat"] = txt.replace("O", "0")
            elif re.match(r"[A-Z]{2,4}ML-[A-Z]{2}", txt):
                current["meal"] = txt

            if all(current.values()):
                blocks.append({
                    "name": current["name"],
                    "title": current["title"],
                    "seat": current["seat"],
                    "meal": current["meal"],
                    "delivered": False,
                    "delivery_time": None,
                    "crew_comments": ""
                })
                current = {"name": None, "title": None, "seat": None, "meal": None}

        sample_blocks.clear()
        sample_blocks.extend(blocks)
        print(f"✅ Loaded {len(blocks)} structured blocks from OCR layout JSON.")
    except Exception as e:
        print(f"⚠️ Failed to load structured OCR JSON: {e}")

def load_blocks_from_json():
    path = input("📄 Enter path to JSON file: ").strip()
    global sample_blocks
    try:
        with open(path, "r") as f:
            data = json.load(f)
        sample_blocks.clear()
        sample_blocks.extend(data)
        print(f"✅ Loaded {len(data)} blocks from JSON.")
    except Exception as e:
        print(f"⚠️ Failed to load JSON: {e}")

def assign_side_and_zone(block, aircraft_type, reg_prefix):
    seat = block.get("seat", "")
    if not seat or len(seat) < 4:
        return
    row = int(seat[:3])
    letter = seat[-1]
    side = None
    zone = None

    # Seat letter logic (simplified)
    if aircraft_type == "A330":
        left = {"A", "C", "D", "E"}
        right = {"F", "H", "J", "L"}
        if reg_prefix in {"QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH"}:  # A333
            zone = "L3" if row <= 46 else "L4"
        elif reg_prefix in {"Q11", "Q12", "Q13", "Q14", "Q15", "Q16", "Q17", "Q18", "Q19", "Q20", "Q21", "Q22", "Q23", "Q24", "Q25", "Q26", "Q27", "Q28", "Q29"}:  # A33R
            zone = "L2" if row <= 43 else "L4"
        elif reg_prefix in {"QI", "QJ", "QK", "QL"}:  # A33D
            zone = "L3" if row <= 46 else "L4"
    elif aircraft_type == "B787":
        left = {"A", "B", "C", "D", "E"}
        right = {"H", "J", "K", "L"}
        if reg_prefix in {"R24", "R25", "R26", "R27", "R28", "R29", "R32", "R33"}:  # B780
            zone = "L3" if row <= 50 else "L4"
        elif reg_prefix in {"R11", "R12", "R13", "R22", "R23", "RA", "RB", "RC", "RD", "RE", "RF", "RG", "RH"}:  # B789
            zone = "L3" if row <= 45 else "L4"
    elif aircraft_type == "B777":
        left = {"A", "B", "C", "D", "E"}
        right = {"F", "H", "J", "K", "L"}
        if reg_prefix in {"K36", "K37", "K38", "K39", "K40", "K41", "K42", "K43", "K44", "K45"}:  # B77Z
            zone = "L4" if row <= 43 else "L5"
        elif reg_prefix in {"K17", "K18", "K19", "K20", "K21", "K22"}:  # 77D
            if row <= 44:
                zone = "L2" if letter in left else "R2"
            elif row <= 59:
                zone = "L4" if letter in left else "R4"
            else:
                zone = "L5" if letter in left else "R5"
        elif reg_prefix in {"K11", "K12", "K13", "K14", "K15", "K16", "K31", "K32", "K33", "K34", "K35"}:  # B773 / B77A
            if row <= 41:
                zone = "L3" if letter in left else "R3"
            elif row <= 54:
                zone = "L4" if letter in left else "R4"
            else:
                zone = "L5" if letter in left else "R5"
        elif reg_prefix in {"K23", "K24", "K25", "K26", "K27", "K28", "K29", "K30"}:  # B77H
            if row <= 44:
                zone = "L3"
            elif row <= 58:
                zone = "L4" if letter in left else "R4"
            else:
                zone = "L5" if letter in left else "R5"

    side = "L" if letter in left else "R" if letter in right else None
    block["side"] = side
    block["zone"] = zone

# === Aircraft & Registration Selection ===
st.subheader("✈️ Aircraft & Registration")
acft_options = ["A330", "B787", "B777"]
st.session_state["aircraft_type"] = st.selectbox("Select Aircraft Type", acft_options)

reg_options = []
if st.session_state["aircraft_type"] == "A330":
    reg_options = ["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH", "QI", "QJ", "QK", "QL"] + [f"Q{i}" for i in range(11, 30)]
elif st.session_state["aircraft_type"] == "B787":
    reg_options = ["R11", "R12", "R13", "R22", "R23"] + [f"R{i}" for i in range(24, 30)] + ["R32", "R33"] + [f"R{c}" for c in ["A","B","C","D","E","F","G","H"]]
elif st.session_state["aircraft_type"] == "B777":
    reg_options = [f"K{i}" for i in range(11, 46)] + [f"K{c}" for c in ["A","B","C","D","E","F","G","H"]]

st.session_state["registration_prefix"] = st.selectbox("Select Registration Prefix", sorted(reg_options))

# === Print Side and Zone Filters ===
st.session_state["side_filter"] = st.radio("Print Side Filter", ["Both", "Left Only", "Right Only"])
if st.session_state["side_filter"] != "Both":
    all_zones = sorted({b.get("zone", "") for b in st.session_state["blocks"] if b.get("side") == st.session_state["side_filter"][0]})
    st.session_state["zone_filter"] = st.selectbox("Optional Door Zone Filter", ["All"] + all_zones)

# Assign side and zone for all blocks based on selected aircraft + reg
for block in st.session_state["blocks"]:
    assign_side_and_zone(block, st.session_state["aircraft_type"], st.session_state["registration_prefix"])

# === Meal Filtering & Summary ===

# Filter options
st.subheader("🔍 Filter Options")
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

# Summary Stats
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

# Meal Block Viewer
st.subheader("📅 Meal Blocks")
for i, block in enumerate(filtered_blocks):
    with st.expander(f"{block.get('seat', 'Unknown Seat')} — {block.get('meal', '')}"):
        st.text(f"Name: {block.get('name', '')} ({block.get('title', '')})")
        st.text(f"Meal: {block.get('meal', '')}")

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

        auto_save()

# === Export Printable Labels ===
st.subheader("🖨️ Export Printable Labels")
if st.button("🖨️ Generate Labels"):
    side_target = st.session_state["side_filter"]
    zone_target = st.session_state["zone_filter"]

    labels = []
    for i, block in enumerate(st.session_state["blocks"]):
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

    if st.checkbox("Show Label Preview"):
        st.subheader("📋 Label Preview")
        st.text(printable)
    st.download_button(
        label="📄 Download Labels (TXT)",
        file_name="print_labels.txt",
        mime="text/plain",
        data=printable
    )
