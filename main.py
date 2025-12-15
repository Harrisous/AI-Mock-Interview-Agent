import asyncio
import logging
import time
from enum import Enum, auto
from typing import Annotated

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
Now, transition the topic to the candidate's past experience.
Ask them about a specific project or role.
If they pause for a long time, ask if they are done.
"""

RESUME_PROMPT_TEMPLATE = """
You are an AI interviewer.
You are now asking specific expert-level questions based on the candidate's resume and the job description.
Here are the target questions you should ask in order (one by one):
{questions}

Ask the first question now. Wait for the answer. Then ask the next.
After asking all questions, transition to the end.
"""

class InterviewManager:
    def __init__(self, resume_processor: ResumeProcessor):
        self.stage = InterviewStage.SELF_INTRODUCTION
        self.agent: VoiceAssistant | None = None
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
            self.agent.chat_ctx.messages.append(
                llm.ChatMessage(
                    role="system",
                    content=f"Transition triggered. Reason: {reason}. Update instructions: {PAST_EXP_PROMPT}",
                )
            )
            await self.agent.say("Thank you. Let's discuss your past experience. Could you describe a significant technical challenge you overcame?", allow_interruptions=True)

        return "Transition successful."

    async def transition_to_resume_qa(self):
        logger.info("Transitioning to Resume QA.")
        if self.stage == InterviewStage.RESUME_QUESTIONS:
            return "Already in Resume QA stage."
            
        self.stage = InterviewStage.RESUME_QUESTIONS
        
        # Format questions
        questions_str = "\\n".join([f"- {q}" for q in self.resume_questions])
        instructions = RESUME_PROMPT_TEMPLATE.replace("{questions}", questions_str)
        
        if self.agent:
            self.agent.chat_ctx.messages.append(
                llm.ChatMessage(
                    role="system",
                    content=f"Transition triggered. Moving to specific Resume Questions. Instructions: {instructions}",
                )
            )
            # Ask the first question immediately? Or let LLM do it?
            # LLM usually needs a nudge or it waits for user. 
            # We'll nudge it by saying asking it to proceed.
            await self.agent.say("I have reviewed your resume and found some interesting points. Let's dive deeper.", allow_interruptions=True)
            
    async def end_interview(self):
        logger.info("Ending interview and generating assessment.")
        self.stage = InterviewStage.FEEDBACK
        
        transcript = self.get_transcript()
        
        if self.agent:
            await self.agent.say("Thank you for your time. I am now generating your assessment. Please wait a moment.", allow_interruptions=True)
            
            # Generate assessment
            # We run this in background so we don't block audio?
            # Using agent.llm directly might block? No, it's async.
            asyncio.create_task(self._generate_and_announce_assessment(transcript))
            
    async def _generate_and_announce_assessment(self, transcript):
        try:
            assessment = await self.resume_processor.generate_assessment(self.agent.llm, transcript)
            logger.info("Assessment generated.")
            # Notify user
            await self.agent.say("I have generated the assessment and saved it to assessment.md. The interview is now complete. Goodbye!", allow_interruptions=True)
        except Exception as e:
            logger.error(f"Failed to generate assessment: {e}")
            await self.agent.say("I encountered an error generating the assessment, but our interview is complete. Goodbye!", allow_interruptions=True)

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

    # Initialize Resume Processor
    resume_processor = ResumeProcessor(example_dir="/home/harryitx/AI-Mock-Interview-Agent/example")
    resume_processor.load_documents()

    manager = InterviewManager(resume_processor)
    
    # Pre-generate questions if resume is present
    # We need an LLM instance. We can create a temporary one or wait?
    # Let's create one.
    temp_llm = openai.LLM()
    if resume_processor.resume_text:
        logger.info("Generating interview questions...")
        manager.resume_questions = await resume_processor.generate_questions(temp_llm)
        logger.info(f"Generated questions: {manager.resume_questions}")
    else:
        logger.warning("No resume text found, skipping question generation.")

    # Tool Context
    fnc_ctx = llm.FunctionContext()

    @fnc_ctx.ai_callable(description="Call when candidate ends self-instruction or introduction.")
    async def transition_to_experience(
        reason: Annotated[str, llm.TypeInfo(description="Reason for transition")]
    ):
        return await manager.transition_to_experience(reason)
        
    @fnc_ctx.ai_callable(description="Call when candidate has answered general experience questions and we are ready for resume-specific deep dive.")
    async def transition_to_resume_qa():
        return await manager.transition_to_resume_qa()

    @fnc_ctx.ai_callable(description="Call when all questions are answered and interview is over.")
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
            max_buffered_speech=60.0,
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
    
    await agent.say("Hello! Welcome to the interview.", allow_interruptions=False)
    await agent.say("I see you've applied for the AI Engineer role.", allow_interruptions=False)
    await agent.say("Please briefly introduce yourself.", allow_interruptions=True)

    # Loop
    while ctx.room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
        await asyncio.sleep(1)


import subprocess

def pre_start_cleanup():
    """Kill any process holding port 8081 to prevent 'address already in use' errors."""
    try:
        subprocess.run(["fuser", "-k", "8081/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

if __name__ == "__main__":
    pre_start_cleanup()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,

        ),
    )

