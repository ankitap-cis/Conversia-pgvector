from typing import Dict, Any, Optional
from langchain_community.chat_models import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain.memory import ConversationBufferMemory
import configparser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableWithMessageHistory


config = configparser.ConfigParser()
config.read("config.ini")

api_key = config['openAI_config']['key']
model_name = config['openAI_config']['name']
max_tokens = int(config['openAI_config']['max_tokens'])


class LLMService:
    def __init__(
        self,
        temperature: Optional[float] = 0.1,
    ):
        self.api_key = config['openAI_config']['key']
        self.model_name = config['openAI_config']['name']
        self.temperature = temperature
        self.max_tokens = int(config['openAI_config']['max_tokens'])
        # Initialize the LLM
        self.llm = ChatOpenAI(
            openai_api_key=self.api_key,
            model_name=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        # Initialize common chains
        self.chains = {}
        self._initialize_chains()
    
    def _initialize_chains(self):
        """Initialize common LangChain chains."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful assistant."),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}")
        ])
        chain = prompt | self.llm
        self.chains["default"] = RunnableWithMessageHistory(
            chain,
            lambda session_id: ConversationBufferMemory(return_messages=True),
            input_messages_key="input",
            history_messages_key="history"
        )
        
    async def generate(self, prompt: str, options: Optional[Dict[str, Any]] = None) -> str:
        """Generate text using the LLM directly."""
        options = options or {}
        # Override default settings with request options if provided
        temp_llm = self.llm
        if any(key in options for key in ["temperature", "max_tokens", "model_name"]):
            temp_llm = ChatOpenAI(
                openai_api_key=self.api_key,
                model_name=options.get("model_name", self.model_name),
                temperature=options.get("temperature", self.temperature),
                max_tokens=int(options.get("max_tokens", self.max_tokens))
            )
        # Generate response
        messages = [HumanMessage(content=prompt)]
        response = await temp_llm.ainvoke(messages)
        
        return response.content
        
    async def run_chain(self, input_text: str, chain_type: str = "default") -> str:
        """Run a specific LangChain chain."""
        if chain_type not in self.chains:
            raise ValueError(f"Chain type '{chain_type}' not found")
        
        chain = self.chains[chain_type]
        response = await chain.ainvoke({"input": input_text})
        
        return response["response"]
        
    async def check_health(self) -> bool:
        """Check if the LLM service is operational."""
        try:
            # Send a simple test query
            result = await self.generate("Hello, are you operational?", {"max_tokens": 10})
            return len(result) > 0
        except Exception:
            return False