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
        labels = []
        for i, block in enumerate(filtered_blocks):
            if i in excluded_indices:
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
else:
    st.info("Please upload a JSON file to begin.")