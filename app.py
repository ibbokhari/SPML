import streamlit as st
import json
import pandas as pd
from io import StringIO

st.set_page_config(page_title="Special Meal Loader", layout="centered")
st.title("✈️ Special Meal Loader")

# Initialize session state
if "blocks" not in st.session_state:
    st.session_state["blocks"] = []

# === Upload JSON (New Session) ===
st.subheader("📂 Upload Extracted JSON")
uploaded_file = st.file_uploader("📌 Upload special_meals.json", type="json")
if uploaded_file:
    try:
        data = json.load(uploaded_file)
        st.session_state["blocks"] = data
        st.success(f"✅ Loaded {len(data)} meal blocks.")
    except Exception as e:
        st.error(f"❌ Failed to load JSON: {e}")

# === Upload JSON (Resume Previous Session) ===
st.subheader("📂 Resume Previous Session")
resume_file = st.file_uploader("📌 Load saved special_meals_edited.json", type="json", key="resume")
if resume_file:
    try:
        resumed_data = json.load(resume_file)
        st.session_state["blocks"] = resumed_data
        st.success(f"✅ Resumed session with {len(resumed_data)} blocks.")
    except Exception as e:
        st.error(f"❌ Failed to load saved session: {e}")

# === Show and Edit Blocks ===
if st.session_state["blocks"]:
    st.subheader("📅 Meal Blocks")
    excluded_indices = set()
    for i, block in enumerate(st.session_state["blocks"]):
        with st.expander(f"{block.get('seat', 'Unknown Seat')} — {block.get('meal', '')}"):
            st.text(f"Name: {block.get('name', '')} ({block.get('title', '')})")
            st.text(f"Meal: {block.get('meal', '')}")
            comment = st.text_input("📝 Crew Comment", value=block.get("crew_comments", ""), key=f"comment_{i}")
            st.session_state["blocks"][i]["crew_comments"] = comment

            delivered = st.checkbox("✅ Mark as Delivered", value=block.get("delivered", False), key=f"delivered_{i}")
            st.session_state["blocks"][i]["delivered"] = delivered

            exclude = st.checkbox("🚫 Exclude from Print", key=f"exclude_{i}")
            if exclude:
                excluded_indices.add(i)

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
        for i, block in enumerate(st.session_state["blocks"]):
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
