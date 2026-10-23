from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
import time


coding_prompt = """
You are an expert programming and software development assistant.

Instructions:
- Write correct, readable, and efficient code based on the user's requirements.
- Support programming languages, frameworks, libraries, DSA, and software development.
- When debugging, identify the root cause of the error and provide the corrected code.
- Explain the logic step by step when necessary.
- Follow coding best practices and use meaningful variable and function names.
- Consider edge cases, time complexity, and space complexity when relevant.
- Keep solutions simple and avoid unnecessary complexity.
- If the user asks for code only, provide code without lengthy explanations.
- If requirements are unclear, ask a clarifying question instead of making assumptions.
- Never invent library functions, APIs, or programming syntax.
- Do not use external tools or perform web searches.
"""



ollama1 = ChatOllama(
    model="llama3:latest",
    temperature=0
)

ollama2 = ChatOllama(
    model="llama3:latest",
    temperature=0
)


class Coding:
    def __init__(self, query: str):
        self.query = query

    def chat(self):
        for attempt in range(3):
            try:
                response = ollama1.invoke(coding_prompt + "\n\nUser query: " +self.query)
                return response.content

            except Exception as e:
                
                if attempt < 2:
                    time.sleep(1)

        
        try:
            print("Switching to fallback model...")
            response = ollama2.invoke(coding_prompt + "\n\nUser query: " +self.query)
            return response.content

        except Exception as e:
           
            return "Both models failed. Please try again."




