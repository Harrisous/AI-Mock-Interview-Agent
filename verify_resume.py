
import asyncio
import logging
from resume_processor import ResumeProcessor
from livekit.plugins import openai
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

async def main():
    rp = ResumeProcessor(example_dir="example")
    rp.load_documents()
    
    print(f"JD Length: {len(rp.jd_text)}")
    print(f"Resume Length: {len(rp.resume_text)}")
    
    if rp.jd_text and rp.resume_text:
        print("Documents loaded successfully.")
        llm = openai.LLM()
        questions = await rp.generate_questions(llm)
        print("Generated Questions:")
        for q in questions:
            print(f"- {q}")
            
if __name__ == "__main__":
    asyncio.run(main())
