from typing import Optional, Dict, Any, List
from fastapi import HTTPException
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_community.chat_message_histories import RedisChatMessageHistory
from langchain_openai import OpenAIEmbeddings
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, MessagesState
from langchain.retrievers.document_compressors import LLMChainExtractor
from langchain.retrievers import ContextualCompressionRetriever
from api.roleplay_assistant.modelfactory import ModelFactory, PersonalityAnalyzer, ScenarioHandler, PromptManager, uuid, Chroma, Path
from langchain.schema import Document
from logger import *
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate
from langchain.prompts.chat import MessagesPlaceholder
from langchain.schema.output_parser import StrOutputParser
from langchain.schema.runnable import RunnablePassthrough
import logging
import redis
import os
logger = logging.getLogger(__name__)
import configparser
from langchain_core.callbacks import BaseCallbackHandler
from utils.token_consumption import TokenUsageCallback

config = configparser.ConfigParser()
config.read('config.ini')

gpt_model = config['openAI_config']['model']
embed_model = config['openAI_config']['embedding_model']
OPENAI_API_KEY = config['openAI_config']['key']

# Redis configuration
REDIS_HOST = config.get('redis_config', 'host', fallback='localhost')
REDIS_PORT = config.getint('redis_config', 'port', fallback=6379)
REDIS_DB = config.getint('redis_config', 'db', fallback=0)
REDIS_PASSWORD = config.get('redis_config', 'password', fallback=None)

# Build Redis URL
if REDIS_PASSWORD:
    REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
else:
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"


class RolePlaybot:
    def __init__(
            self,
            llm_provider: str = "openai",
            llm_model_name: Optional[str] = None,
            embeddings_provider: str = "openai",
            embeddings_model_name: Optional[str] = None,
            storage_dir: str = "./chatdata",
            redis_url: str = REDIS_URL,
            ttl: Optional[int] = 86400  # 24 hours default TTL
    ):
        try:
            # Set basic attributes FIRST
            self.llm_provider = llm_provider
            self.llm_model_name = llm_model_name
            self.embeddings_provider = embeddings_provider
            self.embeddings_model_name = embeddings_model_name
            
            # Initialize LLM
            self.llm = ModelFactory.init_chat_model(
                provider=llm_provider, 
                model_name=llm_model_name
            )
            
            # Set state attributes
            self.active_scenario_id = None
            self.thread_id = None
            self.active_personality = None
            self.active_scenario = None
            self.retriever = None
            
            # Redis configuration
            self.redis_url = redis_url
            self.ttl = ttl
            
            # Storage setup
            self.storage_dir = Path(storage_dir)
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            
            # Initialize helper classes
            self.personality_analyzer = PersonalityAnalyzer(
                llm_provider=llm_provider,
                llm_model_name=llm_model_name
            )
 
            self.scenario_handler = ScenarioHandler(
                llm_provider=llm_provider,
                llm_model_name=llm_model_name,
                embeddings_provider=embeddings_provider,
                embeddings_model_name=embeddings_model_name,
                storage_dir=f"{storage_dir}/scenarios"
            )
 
            self.prompt_manager = PromptManager(
                llm_provider=llm_provider,
                llm_model_name=llm_model_name,
                storage_dir=f"{storage_dir}/prompts"
            )
            
            # Set prompts
            self.custom_query = (
                "Always respond as the defined customer persona, stay in character, "
                "challenge the sales representative with objections, and realistically "
                "simulate customer behaviors and responses."
            )
            self.system_prompt = ""
            
            # Initialize chain and graph-related attributes
            self.chain = None
            self.checkpointer = MemorySaver()
            self.app = None
            
            # Validate Redis connection
            self._validate_redis_connection()
            
            # NOW create the graph (after all attributes are set)
            self._create_graph()
 
        except Exception as e:
            logger.error(f"Error initializing Roleplaybot: {str(e)}")
            raise


    def _validate_redis_connection(self) -> None:
        """Validate Redis connection on startup."""
        try:
            client = redis.from_url(self.redis_url, decode_responses=False)
            client.ping()
            logger.info("Redis connection validated successfully")
        except redis.ConnectionError as e:
            logger.error(f" Redis connection failed: {e}")
            raise ConnectionError(f"Cannot connect to Redis at {self.redis_url}")
        except Exception as e:
            logger.error(f"Redis validation error: {e}")
            raise


    def _get_redis_history(self, session_id: str) -> RedisChatMessageHistory:
        """
        Get or create a RedisChatMessageHistory instance for a session.
        Thread-safe and production-ready WITHOUT RediSearch dependency.
        """
        try:
            return RedisChatMessageHistory(
                session_id=session_id,
                url=self.redis_url,
                key_prefix="roleplay_chat:",
                ttl=self.ttl
            )
        except Exception as e:
            logger.error(f"Failed to create Redis history: {e}")
            raise


    def get_state(self) -> Dict[str, Any]:
        """Serialize bot state to JSON-compatible dictionary."""
        try:
            state = {
                "llm_provider": self.llm_provider,
                "llm_model_name": self.llm_model_name,
                "active_personality": self.active_personality,
                "active_scenario": self.active_scenario,
                "active_scenario_id": self.active_scenario_id,
                "system_prompt": self.system_prompt,
                "custom_query": getattr(self, 'custom_query', ''),
                "thread_id": getattr(self, 'thread_id', None),
                # Don't serialize messages - they're in Redis already
            }
            return state
        except Exception as e:
            logger.error(f"Error getting state: {str(e)}")
            raise

    @classmethod
    def from_state(cls, state: Dict[str, Any]) -> 'RolePlaybot':
        """Restore bot from serialized state."""
        try:
            # Create new bot instance
            bot = cls(
                llm_provider=state.get("llm_provider", "openai"),
                llm_model_name=state.get("llm_model_name"),
                storage_dir="./chatdata"
            )
            
            # Restore basic attributes
            bot.active_personality = state.get("active_personality")
            bot.active_scenario = state.get("active_scenario")
            bot.active_scenario_id = state.get("active_scenario_id")
            bot.system_prompt = state.get("system_prompt", "")
            bot.thread_id = state.get("thread_id")
            
            if "custom_query" in state:
                bot.custom_query = state["custom_query"]
            
            # Recreate the chain/app with restored state
            bot._update_system_prompt()
            
            logger.info(f"Bot restored from state")
            return bot
            
        except Exception as e:
            logger.error(f"Error restoring from state: {str(e)}")
            raise



    def create_personality(self, personality_prompt: str) -> Dict[str, Any]:
        if not isinstance(personality_prompt, str) or not personality_prompt.strip():
            raise ValueError("Invalid personality prompt: must be a non-empty string.")

        personality = self.personality_analyzer.analyze(personality_prompt)
        self.active_personality = personality

        self._update_system_prompt()
        return personality


    def create_scenario(self, scenario_prompt: str, documents: Optional[List[str]] = None) -> Dict[str, Any]:
        try:
            if not isinstance(scenario_prompt, str) or not scenario_prompt.strip():
                raise ValueError("scenario_prompt must be a non-empty string.")

            if documents is not None:
                if not isinstance(documents, list) or not all(isinstance(doc, str) for doc in documents):
                    raise ValueError("documents must be a list of strings.")

            scenario = self.scenario_handler.analyze_scenario(scenario_prompt)
            self.active_scenario = scenario

            scenario_id = f"scenario_{uuid.uuid4().hex[:8]}"
            self.active_scenario_id = scenario_id

            if documents:
                vectorstore = self.scenario_handler.process_documents(documents, scenario_id)
                compressor = LLMChainExtractor.from_llm(self.llm)

                self.retriever = ContextualCompressionRetriever(
                    base_compressor=compressor,
                    base_retriever=vectorstore.as_retriever(
                        search_type="similarity",
                        search_kwargs={"k": 3}
                    )
                )

                scenario["documents"] = documents
                
            self._update_system_prompt()
            return scenario

        except Exception as e:
            logger.error(f"Error creating scenario {str(e)}")
            raise


    def set_custom_prompt_query(self, query: str) -> None:
        self.custom_query = query
        self._update_system_prompt()


    def get_default_system_prompt(self) -> str:
        return self.prompt_manager.get_default_prompt()


    def update_default_system_prompt(self, new_prompt: str) -> str:
        updated_prompt = self.prompt_manager.update_default_prompt(new_prompt)
        self._update_system_prompt()
        return updated_prompt


    def _update_system_prompt(self):
        personality_prompt = ""
        if self.active_personality:
            personality_prompt = self.personality_analyzer.create_system_prompt(self.active_personality)
        
        scenario_prompt = ""
        if self.active_scenario:
            scenario_prompt = self.scenario_handler.create_scenario_prompt(self.active_scenario)
            
        self.system_prompt = self.prompt_manager.generate_system_prompt(
            personality_prompt=personality_prompt,
            scenario_prompt=scenario_prompt,
            custom_query=self.custom_query
        )
        self._create_chain()


    def _create_chain(self):
        try:
            if not self.system_prompt:
                self.system_prompt = "You are a helpful AI assistant. You need to respond as the customer persona."
                
            examples = [
                {"input": "Hello", "output": "Hello. As an interventional cardiologist, I'm always looking for ways to improve patient outcomes. What brings you to discuss home-based dialysis today?"},
                {"input": "Hi there", "output": "Hello. I'm interested in understanding how home-based dialysis could potentially benefit my patients. What information can you provide about this approach?"},
                {"input": "Hey", "output": "Hi. I'm always evaluating new therapies that could benefit my patients. What can you tell me about the advantages of home-based dialysis?"},
                {"input": "Good morning", "output": "Good morning. I'm keen on exploring options that could enhance patient care. What insights can you share about home-based dialysis?"},
                {"input": "Hi", "output": "Hello. I'm interested in learning more about how home-based dialysis might fit into my practice. What can you tell me about its benefits and challenges?"}
            ]
            
            example_prompt = ChatPromptTemplate.from_messages([
                ("human", "{input}"),
                ("ai", "{output}")
            ])
            
            few_shot_prompt = FewShotChatMessagePromptTemplate(
                example_prompt=example_prompt,
                examples=examples,
                input_variables=[]
            )
            
            full_prompt = ChatPromptTemplate.from_messages([
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                *few_shot_prompt.format_messages(),
                ("system", "***Remember: Stay in character as given CUSTOMER PERSONALITY AND SCENARIOS***"),
                ("system", "***DO NOT say things like 'How can I help you today?','How can I assist you today?' you're not an assistant here***"),
                ("human", "{input}")
            ])
            
            basic_chain = full_prompt | self.llm | StrOutputParser()
            
            if self.retriever:
                retrieval_prompt = ChatPromptTemplate.from_messages([
                    ("system", self.system_prompt),
                    MessagesPlaceholder(variable_name="chat_history"),
                    ("system", "Here is relevant information for answering the user's question:\n{context}"),
                    *few_shot_prompt.format_messages(),
                    ("system", "***Remember: Stay in character as given CUSTOMER PERSONALITY AND SCENARIOS***"),
                    ("system", "***DO NOT say things like 'How can I help you today?','How can I assist you today?' you're not an assistant here***"),
                    ("human", "{input}")
                ])
                
                retrieval_chain = RunnablePassthrough.assign(
                    context=lambda x: self._get_relevant_context(x["input"])
                ) | retrieval_prompt | self.llm | StrOutputParser()

                self.chain = retrieval_chain
            else:
                self.chain = basic_chain

        except Exception as e:
            logger.error(f"Error creating chain {str(e)}")
            return None
    
    def _get_relevant_context(self, query: str) -> str:
        if not self.retriever:
            return ""
        try:
            docs = self.retriever.get_relevant_documents(query)
            return "\n\n".join([doc.page_content for doc in docs])
        except Exception as e:
            logger.error(f"Error retrieving context: {e}")
            return ""


    def _ensure_retriever(self) -> None:
        """Create a Chroma-based retriever for the active scenario (if needed)."""
        if (
            self.retriever is None
            and self.active_scenario_id
            and self.active_scenario
            and "documents" in self.active_scenario
        ):
            db_path = (
                self.storage_dir
                / "scenario_uploads"
                / f"{self.active_scenario_id}_vectorstore"
            )
            if db_path.exists():
                vectorstore = Chroma(
                    persist_directory=str(db_path),
                    embedding_function=ModelFactory.init_embeddings(
                        provider=self.embeddings_provider,
                        model_name=self.embeddings_model_name,
                    ),
                )
                compressor = LLMChainExtractor.from_llm(self.llm)
                self.retriever = ContextualCompressionRetriever(
                    base_compressor=compressor,
                    base_retriever=vectorstore.as_retriever(
                        search_type="similarity", 
                        search_kwargs={"k": 3}
                    ),
                )


    def _create_graph(self):
        """Create LangGraph workflow."""
        try:
            self._ensure_retriever()

            workflow = StateGraph(state_schema=MessagesState)

            def call_model(state: MessagesState):
                msgs = state["messages"]
                context = ""
                
                # Get context if retriever exists and last message is from human
                if self.retriever and msgs and msgs[-1].type == "human":
                    context = self._get_relevant_context(msgs[-1].content)

                # Build prompt messages
                prompt_msgs = [SystemMessage(content=self.system_prompt)]
                if context:
                    prompt_msgs.append(
                        SystemMessage(
                            content="Here is relevant information for answering the "
                            "user's question:\n" + context
                        )
                    )
                prompt_msgs += msgs

                response = self.llm.invoke(prompt_msgs)
                return {"messages": [response]}

            workflow.add_node("model", call_model)
            workflow.add_edge(START, "model")
            workflow.set_finish_point("model")
            
            self.app = workflow.compile(checkpointer=self.checkpointer)
            logger.info("Graph created successfully")
            
        except Exception as e:
            logger.error(f"Error creating graph: {str(e)}")
            raise


    def retrieve_scenario_document(self, query: str, org_id: int, scenario_id: int, k: int = 5) -> list[Document]:
        """
        Retrieve relevant chunks from the single document associated with a scenario.
        """
        try:
            persist_dir = f"./vectorstores/{org_id}/scenario_uploads/{scenario_id}"

            if not os.path.exists(persist_dir):
                logger.warning(f"No vectorstore found for scenario {scenario_id} (org {org_id})")
                return []

            embeddings = OpenAIEmbeddings(model=embed_model, api_key=OPENAI_API_KEY)
            vectorstore = Chroma(
                collection_name=f"scenario_{scenario_id}",
                persist_directory=persist_dir,
                embedding_function=embeddings
            )

            docs_and_scores = vectorstore.similarity_search_with_score(query, k=k * 2)

            filtered_docs = [
                doc for doc, score in docs_and_scores
                if int(doc.metadata.get("org_id")) == int(org_id)
                and int(doc.metadata.get("scenario_id")) == int(scenario_id)
            ][:k]

            logger.info(f"Retrieved {len(filtered_docs)} chunks for scenario {scenario_id} query: '{query}'")
            return filtered_docs

        except Exception as e:
            logger.error(f"Error retrieving scenario document: {e}")
            return []


    def chat(self, message: str, thread_id: str, scenario_id: str, org_id: int | None = None, session_id: str = "default", system_prompt: str | None = None) -> str:
        """
        Production-grade chat with Redis-backed history.
        """
        if thread_id is None:
            thread_id = self.active_scenario_id or "default"

        try:
            # Get Redis chat history
            history = self._get_redis_history(thread_id)
            
            final_system_prompt = system_prompt or self.custom_query or "You are a helpful assistant."            
            system_msg = SystemMessage(content=final_system_prompt)
            
            
            # Retrieve context from scenario doc
            context_text = ""
            if scenario_id and org_id:
                try:
                    if isinstance(scenario_id, str) and scenario_id.startswith("scenario_"):
                        scenario_id = scenario_id.replace("scenario_", "", 1)

                    retrieved_docs = self.retrieve_scenario_document(
                        query=message,
                        scenario_id=scenario_id,
                        org_id=org_id,
                        k=3
                    )
                    context_text = "\n\n".join([doc.page_content for doc in retrieved_docs])
                except Exception as e:
                    logger.error(f"Retriever failed: {e}")

            # Augment user message with context
            if context_text:
                augmented_message = f"User query: {message}\n\nRelevant context:\n{context_text}"
            else:
                augmented_message = message

            # Build HumanMessage
            user_msg = HumanMessage(content=augmented_message)
            
            # Get chat history messages
            chat_history = history.messages

            token_callback = TokenUsageCallback()
            # Invoke the app with history
            events = self.app.invoke(
                {"messages": [system_msg] + chat_history + [user_msg]},
                config={
                    "configurable": {"thread_id": thread_id},
                    "callbacks": [token_callback]
                },
            )
            ai_response = events["messages"][-1].content

            # Save to Redis history (original message, not augmented)
            history.add_user_message(message)
            history.add_ai_message(ai_response)
            
            logger.info(f"Chat saved to Redis for thread: {thread_id}")

            return ai_response, token_callback
            
        except redis.ConnectionError as e:
            logger.error(f"Redis connection lost during chat: {e}")
            raise HTTPException(
                status_code=503,
                detail="Chat history service temporarily unavailable"
            )
        except Exception as e:
            logger.error(f"Chat error: {e}")
            raise


    def clear_memory(self, thread_id: str | None = None) -> None:
        """Clear Redis chat history for a session."""
        thread_id = thread_id or self.active_scenario_id or "default"
        
        try:
            history = self._get_redis_history(thread_id)
            history.clear()
            logger.info(f"Cleared chat history for thread: {thread_id}")
        except Exception as e:
            logger.error(f"Error clearing memory: {e}")
            raise

        # Reset checkpointer
        if hasattr(self.checkpointer, "delete_thread"):
            self.checkpointer.delete_thread(thread_id)
        else:
            self.checkpointer = MemorySaver()
            self._create_graph()


try:
    bot = RolePlaybot(
        llm_provider="openai",
        llm_model_name=gpt_model,
        storage_dir="./chatdata",
        redis_url=REDIS_URL,
        ttl=86400  # 24 hours
    )
    logger.info("Global RolePlaybot instance created successfully")
except Exception as e:
    logger.error(f"Failed to initialize global bot: {e}")
    bot = None
