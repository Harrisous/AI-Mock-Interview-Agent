
import streamlit as st
import os
import shutil

# Page Config
st.set_page_config(page_title="AI Interview Manager", page_icon="🤖")

st.title("🤖 AI Mock Interview Manager")
st.markdown("Upload your Resume and Job Description here. The Agent will automatically pick up the latest files.")

# Paths
EXAMPLE_DIR = "example"
os.makedirs(EXAMPLE_DIR, exist_ok=True)

# 1. Job Description Upload
st.header("1. Job Description")
jd_file = st.file_uploader("Upload JD (Markdown/Text)", type=["md", "txt"])
if jd_file:
    # Save to example/example_JD.md
    with open(os.path.join(EXAMPLE_DIR, "example_JD.md"), "wb") as f:
        f.write(jd_file.getbuffer())
    st.success(f"✅ Saved Job Description: {jd_file.name}")

# 2. Resume Upload
st.header("2. Resume")
resume_file = st.file_uploader("Upload Resume (PDF)", type=["pdf"])
if resume_file:
    # Clear existing PDFs first to avoid abiguity
    for f in os.listdir(EXAMPLE_DIR):
        if f.endswith(".pdf"):
            os.remove(os.path.join(EXAMPLE_DIR, f))
    
    # Save new one
    save_path = os.path.join(EXAMPLE_DIR, resume_file.name)
    with open(save_path, "wb") as f:
        f.write(resume_file.getbuffer())
    st.success(f"✅ Saved Resume: {resume_file.name}")

st.markdown("---")
st.header("3. Start Interview")
st.info("Files are updated! Please verify your agent is running.")

if st.button("How to Connect?"):
    st.markdown("""
    1. Open **[LiveKit Agents Playground](https://agents-playground.livekit.io/)**.
    2. Connect to your LiveKit URL (configured in `.env`).
    3. The agent will read your uploaded files immediately upon connection!
    """)

st.markdown("---")
st.header("4. Interview Feedback")
st.markdown("Once the interview is complete, the assessment will appear here.")

assessment_path = os.path.join(EXAMPLE_DIR, "assessment.md")

# Simple polling logic (Streamlit auto-reruns on interaction, but for real-time we might need a refresh button or st.empty)
if st.button("Check for Assessment"):
    if os.path.exists(assessment_path):
        with open(assessment_path, "r") as f:
            content = f.read()
        
        st.success("Assessment Generated!")
        st.markdown(content)
        st.download_button(
            label="Download Assessment",
            data=content,
            file_name="assessment.md",
            mime="text/markdown"
        )
    else:
        st.warning("Assessment not yet generated. Please finish the interview first.")

st.markdown("---")
st.header("5. Transcript Download")
transcript_path = os.path.join(EXAMPLE_DIR, "transcript.json")

if st.button("Check for Transcript"):
    if os.path.exists(transcript_path):
        with open(transcript_path, "r") as f:
            transcript_content = f.read()
            
        st.success("Transcript Available!")
        st.download_button(
            label="Download Transcript (JSON)",
            data=transcript_content,
            file_name="transcript.json",
            mime="application/json"
        )
    else:
        st.warning("Transcript not found. Finish the interview first.")

