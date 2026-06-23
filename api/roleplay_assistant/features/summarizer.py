import os
import stat
import hashlib
import configparser
from pathlib import Path
from typing import Dict, Any, List
import asyncio
from logger import logger
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.memory import ConversationBufferMemory
from langchain_core.documents import Document
from langchain_core.callbacks import BaseCallbackHandler
from utils.token_consumption import TokenUsageCallback

config = configparser.ConfigParser()
config.read('config.ini')


model_name = config['openAI_config']['model']
openai_api_key = config['openAI_config']['key']
embedding_model_name = config['openAI_config']['embedding_model']

class SummarizerBot:
    def __init__(self, storage_dir: str = "./summary_data"):
        self.llm = ChatOpenAI(model_name=model_name, openai_api_key=openai_api_key, temperature=0)
        self.embedding_model = OpenAIEmbeddings(model=embedding_model_name, openai_api_key=openai_api_key)

        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.vectorstores: Dict[str, Any] = {}
        self.sessions: Dict[str, ConversationBufferMemory] = {}

    def _get_or_create_session(self, session_id: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationBufferMemory(
                return_messages=True, memory_key="chat_history"
            )
        return self.sessions[session_id]

    def _build_b2b_medtech_prompt(
        self, 
        file_list: str,
        role_and_purpose: str,
        desired_sections: str,
        additional_context: str,
        front_end_context: str
    ) -> str:
        """Build the B2B/MedTech sales summarization prompt template."""
        
        # Core B2B/MedTech prompt structure
        prompt = f"""You are an internal summarization agent for complex B2B/MedTech sales. Your job is to turn attached files into field-ready briefs that support a rep's next action.

        **INPUTS (by authority)**
        1. Summarize Form (this request):
        - File Upload(s): {file_list}
        - Role and purpose: {role_and_purpose}
        - Desired sections (comma-separated): {desired_sections}
        - Additional context: {additional_context}

        2. Front-End Context (org-level voice & constraints): {front_end_context}

        Instructions
        Source of truth: Use {{document}} as the primary source. Do not invent facts. If information is missing or ambiguous, say so briefly.
        Audience fit: Adapt tone, depth, and emphasis to {{user_role_and_use}}.
        Headings: Use the exact sections from {{desired_headings}} and present them in that order. If empty, default to: Key Findings, Evidence & Data Points, Implications, Recommendations, Open Questions/Assumptions, Conclusion.
        Context weaving: Incorporate {{additional_context}} only to frame or prioritize content; do not let it override the document.

        Style:
        Use Hierarchical Formatting
        Helps readers quickly scan and find what they need.
        Headings/Subheadings: Use distinct font sizes and weights (e.g., H1 > H2 > H3).
        Bold & Italics: Emphasize key points or contrast ideas.
        Bullets & Numbered Lists: Ideal for step-by-step info or grouped ideas.
        
        Chunk Information (Chunking Theory)
        Break text into manageable “chunks” to improve comprehension and retention.
        Group related concepts together.
        Limit paragraphs to 3–4 sentences.
        Use white space to give breathing room between elements.


        Actionability: Turn insights into next steps tailored to the user’s use case.
        Quality guardrails: No external knowledge unless explicitly marked as inference; label such lines as Inference and keep them minimal. Flag contradictions or data quality issues.
        Self-containment: Make the summary understandable without opening the document.

        **STYLE & VOICE**
        - Match brand voice and no-go phrases from Front-End Context
        - Be practical, specific, and concise. Prefer "do this / say this" over theory
        - Use metaphors sparingly for clarity, never to exaggerate claims

        **CITATIONS & EVIDENCE**
        - Quotes ≤20 words, then interpret the quote

        **GUARDRAILS**
        - No invention of trials, data, regulatory status, or competitive claims
        - Do not imply use beyond labeled indications
        - Flag contradictions or missing data in Risk & Open Questions with a proposed follow-up source

        Generate the summary now."""
        
        return prompt

    def summarize(
        self,
        parsed_input: dict,
        summarizer_prompt: str,
        user_id: str,
        organization_id: str
    ) -> str:
        """Generate professional HTML or B2B/MedTech sales summary based on mode."""
        try:
            session_base = f"summary_{user_id}_{organization_id or 'general'}"
            session_hash = hashlib.md5(session_base.encode()).hexdigest()[:8]
            session = self._get_or_create_session(session_hash)

            uploaded_text = parsed_input.get("uploaded_text", "")
            
            # Check if this is B2B/MedTech mode (presence of role_and_purpose indicates new mode)
            is_b2b_medtech_mode = "role_and_purpose" in parsed_input and parsed_input.get("role_and_purpose")
            
            if is_b2b_medtech_mode:
                # B2B/MedTech Sales Mode
                file_list = parsed_input.get("file_list", "Not specified")
                role_and_purpose = parsed_input.get("role_and_purpose", "Not specified")
                desired_sections = parsed_input.get("desired_sections", "")
                additional_context = parsed_input.get("additional_context", "Not specified")
                front_end_context = summarizer_prompt if summarizer_prompt else "No specific org context provided"
                
                prompt_template = self._build_b2b_medtech_prompt(
                    file_list=file_list,
                    role_and_purpose=role_and_purpose,
                    desired_sections=desired_sections,
                    additional_context=additional_context,
                    front_end_context=front_end_context
                )
                
            else:
                # Legacy HTML Summary Mode (existing functionality preserved)
                summary_request_safe = parsed_input.get("summary_request", "N/A").replace("{", "{{").replace("}", "}}")
                additional_context_safe = parsed_input.get("additional_context", "N/A").replace("{", "{{").replace("}", "}}")
                
                prompt_template = f"""
        {f"ORGANIZATION GUIDELINES (HIGHEST PRIORITY): {summarizer_prompt}" if summarizer_prompt else ""}

        You are an expert at summarization. Your task is to:
        1. Understand the full summary request: {summary_request_safe}
        2. Include additional context: {additional_context_safe}
        3. Use the uploaded content below for reference:
        {{context}}

        RULES:
        - Keep the summary concise (100–500 words)
        - Use headings (<h2>), paragraphs (<p>), and bullet points (<ul>/<li>)
        - Output a single <div>...</div> with clean HTML
        """

            # Create LangChain prompt with {context} placeholder
            prompt = PromptTemplate(
                input_variables=["context"],
                template=prompt_template
            )

            chain = create_stuff_documents_chain(self.llm, prompt)

            context_docs: List[Document] = [Document(page_content=uploaded_text)] if uploaded_text else []
            token_callback = TokenUsageCallback()
            response = chain.invoke({"context": context_docs}, config={"callbacks": [token_callback]})

            output_text = response.get("output_text", response) if isinstance(response, dict) else response
            session.chat_memory.add_user_message(prompt_template)
            session.chat_memory.add_ai_message(output_text)

            return output_text.strip(), token_callback

        except Exception as e:
            logger.error(f"Error generating summary: {e}", exc_info=True)
            return "<div><p>Error generating summary.</p></div>"


summarizer_bot = SummarizerBot()

async def generate_summary_logic(parsed_input: dict, summarizer_prompt: str, user_id: str, organization_id: str) -> str:
    """Generate summary using dedicated SummarizerBot."""
    raw_response, usage_metadata = await asyncio.to_thread(
        summarizer_bot.summarize,
        parsed_input,
        summarizer_prompt,
        user_id,
        organization_id
    )
    usage_metadata = {
        "input_tokens": usage_metadata.prompt_tokens,
        "output_tokens": usage_metadata.completion_tokens,
        "total_tokens": usage_metadata.total_tokens
    }
    return raw_response.strip(), usage_metadata
