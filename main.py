
import asyncio
import logging
import time
import os
from enum import Enum, auto
from typing import Annotated
import json

from dotenv import load_dotenv
from livekit.agents import (
    WorkerOptions,
    JobContext,
    cli,
    llm,
)
from livekit.agents.job import AutoSubscribe
from livekit.agents.voice_assistant import VoiceAssistant, AssistantTranscriptionOptions
from livekit.plugins import openai, silero
from livekit import rtc

from resume_processor import ResumeProcessor

load_dotenv()

logger = logging.getLogger("mock-interview")
logger.setLevel(logging.INFO)

class InterviewStage(Enum):
    SELF_INTRODUCTION = auto()
    PAST_EXPERIENCE = auto()
    RESUME_QUESTIONS = auto()
    FEEDBACK = auto()

# Prompts
SELF_INTRO_PROMPT = """
You are an AI interviewer conducting a mock interview.
Your current goal is to ask the candidate to introduce themselves.
Be professional but friendly. Listen to their introduction.
If they stop talking for a long time (5s), politely ask "Is there anything else you'd like to share regarding this topic?" or "Have you finished your answer?".
If they say they are done, call the transition tool.
"""

PAST_EXP_PROMPT = """
You are an AI interviewer.
Now, transition the topic to the specific resume question provided.
Ask the question and then WAIT for the candidate to answer.
DO NOT call the end_interview tool immediately.
ONLY call the end_interview tool AFTER the candidate has given their response to this question.
"""

RESUME_PROMPT_TEMPLATE = """
"""

class InterviewManager:
    def __init__(self, resume_processor: ResumeProcessor, job_id: str = "unknown"):
        self.stage = InterviewStage.SELF_INTRODUCTION
        self.agent: VoiceAssistant | None = None
        self.job_id = job_id
        self.resume_processor = resume_processor
        self.resume_questions = []
        self.transcript = []

    def get_transcript(self):
        # In a real app we'd capture actual text, here we rely on what we have or VAD events
        # VoiceAssistant 0.8.0 doesn't automatically store a transcript list easily accessible?
        # chat_ctx.messages contains it!
        if self.agent and self.agent.chat_ctx:
            return "\\n".join([f"{m.role}: {m.content}" for m in self.agent.chat_ctx.messages])
        return ""

    async def transition_to_experience(
        self, reason: str
    ):
        logger.info(f"Transitioning to Past Experience. Reason: {reason}")
        if self.stage == InterviewStage.PAST_EXPERIENCE:
            return "Already in Past Experience stage."

        self.stage = InterviewStage.PAST_EXPERIENCE
        
        if self.agent:
            # USE SPECIFIC RESUME QUESTION HERE
            question = "Could you tell me about your background?"
            if self.resume_questions:
                question = self.resume_questions[0]

            self.agent.chat_ctx.messages.append(
                llm.ChatMessage(
                    role="system",
                    content=f"Transition triggered. Reason: {reason}. Update instructions: {PAST_EXP_PROMPT}. IMMEDIATE ACTION: Ask the candidate this specific question based on their resume: '{question}'",
                )
            )
            # Removed explicit agent.say to prevent double speaking. LLM will generate response based on new prompt.
            
        return "Transition successful. Stage is now PAST_EXPERIENCE. Proceed with the question."

    async def monitor_experience_duration(self, agent: VoiceAssistant):
        """Hard limit of 5 minutes for Past Experience (Resume Question) stage."""
        logger.info("Starting 5-minute timer for Past Experience stage.")
        await asyncio.sleep(300) # 5 minutes
        if self.stage == InterviewStage.PAST_EXPERIENCE:
            logger.info("Past Experience time limit reached (5 mins).")
            await agent.say("We are running out of time for this section. Let's move to the conclusion.", allow_interruptions=False)
            await self.end_interview()
    

            
    def get_transcript_json(self):
        """Returns the transcript as a JSON-serializable list."""
        if self.agent and self.agent.chat_ctx:
            transcript = []
            for m in self.agent.chat_ctx.messages:
                # Filter out system messages for cleaner history if desired, but user might want debug info.
                # Let's keep everything but maybe mark system?
                transcript.append({
                    "role": m.role,
                    "content": m.content,
                    # "timestamp": ... (not easily available in simple Message object unless we track it)
                })
            return transcript
        return []

    def save_transcript(self):
        """Saves or appends the current transcript to transcript.json."""
        if not self.agent or not self.agent.chat_ctx:
            return

        try:
            transcript_new_session = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "job_id": self.job_id,
                "transcript": self.get_transcript_json()
            }
            
            transcript_path = "example/transcript.json"
            all_transcripts = []
            
            # Read existing
            if os.path.exists(transcript_path):
                try:
                    with open(transcript_path, "r") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            all_transcripts = data
                        else:
                            all_transcripts = [{"legacy": True, "data": data}]
                except json.JSONDecodeError:
                    pass
            
            # Check if we already saved this job_id in this run to avoid duplicates if called multiple times?
            # Or just append. Appending multiple times might duplicate if called on update.
            # Ideally we update the existing entry if job_id matches!
            
            updated = False
            for i, session in enumerate(all_transcripts):
                if session.get("job_id") == self.job_id:
                     all_transcripts[i] = transcript_new_session
                     updated = True
                     break
            
            if not updated:
                all_transcripts.append(transcript_new_session)
            
            with open(transcript_path, "w") as f:
                json.dump(all_transcripts, f, indent=2)
            logger.info("Transcript saved to example/transcript.json")
        except Exception as e:
            logger.error(f"Failed to save transcript: {e}")

    async def end_interview(self):
        logger.info("Ending interview and generating assessment.")
        self.stage = InterviewStage.FEEDBACK
        
        transcript = self.get_transcript()
        
        self.save_transcript()

        if self.agent:
            await self.agent.say("Thank you for your time. We will review your application and get back to you. Goodbye!", allow_interruptions=False)
            
            # Generate assessment in background
            asyncio.create_task(self._generate_assessment_silent(transcript))
            
    async def _generate_assessment_silent(self, transcript):
        try:
            logger.info("Generating assessment in background...")
            await self.resume_processor.generate_assessment(self.agent.llm, transcript)
            logger.info("Assessment generated successfully.")
        except Exception as e:
            logger.error(f"Failed to generate assessment: {e}")

async def wait_for_participant(room: rtc.Room) -> rtc.RemoteParticipant:
    if room.remote_participants:
        return list(room.remote_participants.values())[0]

    event = asyncio.Event()
    participant = None

    @room.on("participant_connected")
    def on_participant_connected(p: rtc.RemoteParticipant):
        nonlocal participant
        participant = p
        event.set()

    logger.info("Waiting for participant to connect...")
    await event.wait()
    return participant

async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info(f"Room connected: {ctx.room.name}")
    
    # Metadata parsing for Production Resume/JD
    resume_text = ""
    jd_text = ""
    try:
        if ctx.room.metadata:
            logger.info(f"Parsing room metadata: {ctx.room.metadata[:50]}...")
            data = json.loads(ctx.room.metadata)
            resume_text = data.get("resume_text", "")
            jd_text = data.get("job_description", "")
            if resume_text or jd_text:
                logger.info(f"Loaded dynamic context from metadata (Resume len: {len(resume_text)}, JD len: {len(jd_text)})")
    except Exception as e:
        logger.warning(f"Failed to parse room metadata: {e}")

    # Initialize Resume Processor with potential overrides
    rp = ResumeProcessor(
        example_dir="example", 
        resume_text=resume_text, 
        jd_text=jd_text
    )
    try:
        rp.load_documents()
    except FileNotFoundError as e:
        logger.error(f"Critical Error: {e}")
        # We need a way to communicate this to the user even if connection is fresh
        # But we need an agent instance to speak...
        # Let's create a minimal agent just to say error? Or rely on logging if this is dev. 
        # User asked to "holds the process".
        # If we return here, the worker might restart. 
        # But let's at least stop the interview logic.
        return

    manager = InterviewManager(rp, job_id=ctx.job.id)
    
    # Pre-generate questions if resume is present
    # We need an LLM instance. We can create a temporary one or wait?
    # Let's create one.
    temp_llm = openai.LLM()
    if rp.resume_text:
        logger.info("Generating interview questions...")
        manager.resume_questions = await rp.generate_questions(temp_llm)
        logger.info(f"Generated questions: {manager.resume_questions}")
    else:
        logger.warning("No resume text found, skipping question generation.")

    # Tool Context
    fnc_ctx = llm.FunctionContext()

    @fnc_ctx.ai_callable(description="Call when candidate ends self-instruction or introduction.")
    async def transition_to_experience(
        reason: Annotated[str, llm.TypeInfo(description="Reason for transition")]
    ):
        asyncio.create_task(manager.monitor_experience_duration(agent))
        return await manager.transition_to_experience(reason)
        
    @fnc_ctx.ai_callable(description="Call when candidate has answered the technical question and interview is over.")
    async def end_interview():
        return await manager.end_interview()



    # Chat Context
    initial_ctx = llm.ChatContext()
    initial_ctx.messages.append(
        llm.ChatMessage(role="system", content=SELF_INTRO_PROMPT)
    )

    # Voice Assistant with VAD=2.0s (User Request) and threshold=0.6
    agent = VoiceAssistant(
        vad=silero.VAD.load(
            min_silence_duration=2.0, 
            activation_threshold=0.6,
            max_buffered_speech=300.0,
        ), 
        stt=openai.STT(),
        llm=openai.LLM(),
        tts=openai.TTS(),
        chat_ctx=initial_ctx,
        fnc_ctx=fnc_ctx,
        transcription=AssistantTranscriptionOptions(
            agent_transcription=True,
            user_transcription=True,
        ),
    )
    
    manager.agent = agent

    participant = await wait_for_participant(ctx.room)
    agent.start(ctx.room, participant)
    
    # Job Title extraction
    job_title = "exciting"
    if rp.jd_text:
        job_title = await rp.extract_job_title(temp_llm)
        logger.info(f"Extracted Job Title: {job_title}")

    await agent.say("Hello! Welcome to the interview.", allow_interruptions=False)
    await agent.say(f"I see you've applied for the {job_title} role.", allow_interruptions=False)
    await agent.say("Please briefly introduce yourself in 1 minute.", allow_interruptions=True)
    
    async def monitor_intro_duration():
        await asyncio.sleep(60)
        if manager.stage == InterviewStage.SELF_INTRODUCTION:
            logger.info("Self-Introduction time limit reached.")
            
            # Log last user input if possible (retrieving from chat context)
            if agent.chat_ctx.messages and agent.chat_ctx.messages[-1].role == "user":
                logger.info(f"User cached input before timeout: {agent.chat_ctx.messages[-1].content}")
            else:
                logger.info("User cached input not found or last message was system/agent.")
                
            await agent.say("Time's up! Thank you for the introduction. Let's move on.", allow_interruptions=False)
            await manager.transition_to_experience("Time limit reached (60s)")

    asyncio.create_task(monitor_intro_duration())

    # Loop
    try:
        while ctx.room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
            await asyncio.sleep(1)
            # Optional: Periodic save
            # if time.time() % 30 == 0: manager.save_transcript()
    finally:
        logger.info("Session disconnected. Saving final transcript...")
        manager.save_transcript()


import subprocess

def pre_start_cleanup():
    """Kill any process holding port 8081 to prevent 'address already in use' errors."""
    try:
        subprocess.run(["fuser", "-k", "8081/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    
    # Run VAD Patch (Critical for Docker/Pip install)
    try:
        logger.info("Applying robust VAD patch...")
        subprocess.run(["python3", "patch_vad_class.py"], check=True)
        logger.info("VAD patch applied successfully.")
    except Exception as e:
        logger.warning(f"Could not apply VAD patch at runtime: {e}. Assuming patched at build time.")

if __name__ == "__main__":
    pre_start_cleanup()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,

        ),
    )

