# AI Mock Interview Agent 🤖

An advanced, real-time voice AI agent designed to conduct mock job interviews. It analyzes your resume and job description to ask tailored questions, evaluates your responses, and provides a detailed assessment.

Built with [LiveKit Agents](https://docs.livekit.io/agents/), OpenAI, and Silero VAD.

## 🌟 Features

*   **Real-time Voice Interaction**: Low-latency conversation (optimized to ~2s response time).
*   **Resume & JD Integration**: Parses PDF resumes and Markdown Job Descriptions to generate context-aware interview questions.
*   **Smart Silence Detection**: Uses patched Silero VAD to detect when you've finished speaking (or via verbal cues).
*   **Automated Assessment**: Generates a comprehensive `assessment.md` report after the interview, grading your performance.
*   **Robust Architecture**: Auto-heals port conflicts and handles audio stream edge cases.

## 🛠️ Prerequisites

*   Python 3.10+
*   LiveKit Server (Cloud or Local)
*   OpenAI API Key

## 📦 Installation

1.  **Clone the repository** (if applicable).
2.  **Create a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    *Note: The `livekit-plugins-silero` library will be automatically patched on first run to fix known upstream bugs.*

4.  **Configure Environment**:
    Create a `.env` file in the root directory:
    ```env
    LIVEKIT_URL=...
    LIVEKIT_API_KEY=...
    LIVEKIT_API_SECRET=...
    OPENAI_API_KEY=...
    ```

## 🚀 Usage

1.  **Prepare your Resume/JD**:
    *   Place your Resume PDF in `example/`.
    *   Place the Job Description in `example/example_JD.md`.
    *   *(The agent defaults to `example/CV AIE Haochen Li 202511.pdf`, modify `verify_resume.py` or `main.py` to change this).*

2.  **Run the Agent**:
    ```bash
    ./venv/bin/python3 main.py dev
    ```
    *You should see "starting worker" logs.*

3.  **Connect**:
    *   Open the [LiveKit Agents Playground](https://agents-playground.livekit.io/).
    *   Connect to your room.
    *   Start speaking!

4.  **Run via Docker (Recommended for Production/Demo)**:
    ```bash
    sudo docker compose up --build
    ```
    *Starts the Agent + a local File Upload UI at http://localhost:8501*

## ⚙️ Configuration

**Number of Questions**:
To change the number of generated interview questions:
1.  Open `resume_processor.py`.
2.  Edit line **74** in the prompt (e.g., "Generate 3 deep...").
3.  Edit line **114** to slice the list accordingly (e.g., `return clean_questions[:3]`).

**Timeouts**:
Timeouts (1 min Intro, 5 min Resume Question) are defined in `main.py` using `monitor_intro_duration` and `monitor_experience_duration` functions.

## 📝 Interview Flow

1.  **Greeting**: The agent welcomes you.
2.  **Self-Introduction**: You introduce yourself (Agent waits for ~2s silence).
3.  **Experience**: Agent asks about your background.
4.  **Technical Deep Dive**: Agent asks 3 specific questions based on your Resume/JD.
5.  **Closing & Assessment**: The interview ends, and an `assessment.md` file is generated in the project root.

## 🔧 Troubleshooting

*   **"Address already in use"**: The agent includes an auto-cleanup script. Just re-run the `main.py` command, and it will free port 8081 automatically.
*   **VAD Crash / Stream Closed**: A patch script (`patch_vad_class.py`) is applied automatically to fix `livekit-plugins-silero` issues.
