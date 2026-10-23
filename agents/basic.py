from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
import time


basic_prompt = """
You are a helpful general-purpose AI assistant.

Answer the user's questions clearly, accurately, and in a friendly manner.
Use simple language and provide examples whenever helpful.
Keep answers concise for simple questions and provide detailed explanations when requested.
For programming questions, explain the logic and provide code examples when appropriate.
If you do not know the answer, acknowledge the uncertainty instead of making up information.
Do not use external tools or web searches.
"""



ollama1 = ChatOllama(
    model="llama3:latest",
    temperature=0
)

ollama2 = ChatOllama(
    model="llama3:latest",
    temperature=0
)


class Basic:
    def __init__(self, query: str):
        self.query = query

    def chat(self):
        for attempt in range(3):
            try:
                response = ollama1.invoke(basic_prompt + "\n\nUser query: " +self.query)
                return response.content

            except Exception as e:
                
                if attempt < 2:
                    time.sleep(1)

        
        try:
            print("Switching to fallback model...")
            response = ollama2.invoke(basic_prompt + "\n\nUser query: " +self.query)
            return response.content

        except Exception as e:
           
            return "Both models failed. Please try again."




