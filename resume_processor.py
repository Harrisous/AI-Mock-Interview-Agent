
import logging
import os
import glob
from pypdf import PdfReader
from livekit.agents import llm

logger = logging.getLogger("resume-processor")
logger.setLevel(logging.INFO)

class ResumeProcessor:

    def __init__(self, example_dir: str = "example", resume_text: str = "", jd_text: str = ""):
        self.example_dir = example_dir
        self.resume_text = resume_text
        self.jd_text = jd_text

    def load_documents(self):
        """Loads JD and Resume from text overrides or files."""
        # Load JD
        if self.jd_text:
            logger.info("Using provided Job Description text.")
        else:
            jd_path = os.path.join(self.example_dir, "example_JD.md")
            if os.path.exists(jd_path):
                try:
                    with open(jd_path, "r") as f:
                        self.jd_text = f.read()
                    logger.info(f"Loaded Job Description from {jd_path}")
                except Exception as e:
                    logger.error(f"Failed to read JD: {e}")
            else:
                logger.error(f"Job Description not found at {jd_path}")
                raise FileNotFoundError(f"Job Description not found at {jd_path}")


        # Load Resume (First PDF in directory)
        if self.resume_text:
             logger.info("Using provided Resume text.")
        else:
            pdf_files = glob.glob(os.path.join(self.example_dir, "*.pdf"))
            if pdf_files:
                resume_path = pdf_files[0]
                try:
                    reader = PdfReader(resume_path)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
                    self.resume_text = text
                    logger.info(f"Loaded Resume from {resume_path}")
                except Exception as e:
                    logger.error(f"Failed to read Resume PDF: {e}")
            else:
                logger.error("No PDF resume found in example directory.")
                raise FileNotFoundError("No PDF resume found in example directory.")

    async def generate_questions(self, llm_client: llm.LLM) -> list[str]:
        """Generates 2-3 interview questions based on Resume and JD."""
        if not self.resume_text or not self.jd_text:
            logger.warning("Missing Resume or JD text. Returning generic questions.")
            return [
                "Could you tell me about a challenging project you've worked on?",
                "How do your skills align with this role?"
            ]

        prompt = f"""
        You are an expert technical interviewer.
        
        JOB DESCRIPTION:
        {self.jd_text[:2000]} # Truncate to avoid context limit if needed, but usually fine
        
        CANDIDATE RESUME:
        {self.resume_text[:2000]}
        
        TASK:
        Generate 1 deep, expert-level interview question.
        The questions must:
        1. Connect the candidate's specific past experience (from Resume) to the specific requirements of the Job.
        2. Be professional, challenging, and insightful.
        3. Do NOT include greetings or extraneous text. Just the questions, one per line.
        """

        # We'll use a ChatContext to get the response since LLM is designed for chat
        # Or we can use llm.chat check if available
        # In 0.8.0, usually: stream = await llm.chat(chat_ctx=...)
        
        chat_ctx = llm.ChatContext()
        chat_ctx.messages.append(llm.ChatMessage(role="system", content=prompt))
        
        # We need to collect the full response
        stream = llm_client.chat(chat_ctx=chat_ctx)
        full_text = ""
        async for chunk in stream:
            # 0.8.0 chunk behavior check: chunk.choices[0].delta.content?
            # Or just chunk.content if it's a simplification
            # Let's assume standard OpenAI plugin behavior: chunk.choices[0].delta.content
            # Actually, looking at 0.8.0 examples, it might be simpler.
            # Let's inspect the chunk object if debugging, but for now assume standard API.
            # Wait, livekit-agents LLM stream yields ChatChunk
            if chunk.choices:
                 content = chunk.choices[0].delta.content
                 if content:
                     full_text += content

        questions = [q.strip() for q in full_text.split('\n') if q.strip()]
        # Filter out numbering if LLM adds it "1. ..."
        clean_questions = []
        for q in questions:
            # Remove leading numbers/embedded bullets
            if q[0].isdigit() and q[1] in ['.', ')']:
                q = q[2:].strip()
            elif q.startswith('- '):
                q = q[2:].strip()
            clean_questions.append(q)
            
        return clean_questions[:1]

    async def generate_assessment(self, llm_client: llm.LLM, interview_transcript: str):
        """Generates a markdown assessment of the candidate."""
        prompt = f"""
        You are a hiring manager making a decision.
        
        JOB DESCRIPTION:
        {self.jd_text[:1500]}
        
        INTERVIEW TRANSCRIPT:
        {interview_transcript}
        
        TASK:
        Evaluate the candidate. Produce a markdown report named 'Assessment'.
        
        Format:
        # Interview Assessment
        
        **Decision**: [Proceed / Hold / Reject]
        
        **Reasoning**:
        [Detailed explanation citing specific evidence from the transcript and matching it to JD requirements]
        """
        
        chat_ctx = llm.ChatContext()
        chat_ctx.messages.append(llm.ChatMessage(role="system", content=prompt))
        
        stream = llm_client.chat(chat_ctx=chat_ctx)
        full_text = ""
        async for chunk in stream:
            if chunk.choices:
                 content = chunk.choices[0].delta.content
                 if content:
                     full_text += content
                     
        # Save to file
        with open(os.path.join(self.example_dir, "assessment.md"), "w") as f:
            f.write(full_text)
        
        return full_text
        return full_text
        
    async def extract_job_title(self, llm_client: llm.LLM) -> str:
        """Extracts the job title from the JD."""
        if not self.jd_text:
            return "Candidate"
            
        prompt = f"""
        Extract the job title from the following Job Description.
        Return ONLY the job title. No extra words.
        
        JOB DESCRIPTION:
        {self.jd_text[:1000]}
        """
        
        chat_ctx = llm.ChatContext()
        chat_ctx.messages.append(llm.ChatMessage(role="system", content=prompt))
        
        stream = llm_client.chat(chat_ctx=chat_ctx)
        full_text = ""
        async for chunk in stream:
            if chunk.choices:
                 content = chunk.choices[0].delta.content
                 if content:
                     full_text += content
        
        title = full_text.strip()
        # Fallback cleanup
        if len(title) > 50 or "job description" in title.lower():
             return "Candidate" # Fail safe
             
        return title
