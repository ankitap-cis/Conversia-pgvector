from schemas.precall_plan_schema import PrecallPlanAIResponse
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sklearn.metrics.pairwise import cosine_similarity
from api.roleplay_assistant.constants import get_vectorstore
from langchain_openai import OpenAIEmbeddings
from tiktoken import encoding_for_model
import json
from logger import *
import configparser
from typing import Dict, List
import re
from api.roleplay_assistant.general_chatbot import GeneralChatBot
from langchain.output_parsers import PydanticOutputParser
from utils.token_consumption import embedding_token_count


bot = GeneralChatBot()

config = configparser.ConfigParser()
config.read("config.ini")
OPENAI_API_KEY = config['openAI_config']['key']
embed_model = config['openAI_config']['embedding_model']
gpt_model = config['openAI_config']['model']


def summarize_uploaded_text(text: str, max_tokens: int = 1000) -> str:
    """Keep existing functionality - summarizes long text"""
    splitter = RecursiveCharacterTextSplitter(chunk_size=max_tokens, chunk_overlap=100)
    chunks = splitter.split_text(text)
    return chunks[0]


def estimate_token_count(text: str, model: str = "gpt-4") -> int:
    """Keep existing functionality - estimates token count"""
    enc = encoding_for_model(model)
    return len(enc.encode(text))


def simple_chunk_text(text: str, chunk_size: int = 500) -> List[str]:
    """Keep existing functionality - chunks text by paragraphs"""
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    for para in paragraphs:
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += para + "\n\n"
        else:
            chunks.append(current_chunk.strip())
            current_chunk = para + "\n\n"
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks


def get_top_k_similar_chunks(uploaded_text: str, query_text: str, k=5) -> List[str]:
    """Keep existing functionality - retrieves top-k similar chunks using embeddings"""
    chunks = simple_chunk_text(uploaded_text)
    embedding_model = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY, model=embed_model)
    chunk_embeddings = embedding_model.embed_documents(chunks)
    query_embedding = embedding_model.embed_query(query_text)
    similarities = cosine_similarity([query_embedding], chunk_embeddings)[0]
    top_k_indices = sorted(range(len(similarities)), key=lambda i: similarities[i], reverse=True)[:k]
    top_chunks = [chunks[i] for i in top_k_indices]
    usage_metadata = embedding_token_count(chunks, embed_model)
    return top_chunks, usage_metadata if usage_metadata else None


def generate_precall_plan_logic(
    parsed_input: Dict, 
    precall_prompt: str, 
    org_id, 
    uploaded_text: str = "",
    frontend_context_text: str = "",
    playbook_text: str = "",
    brand_voice: str = ""
) -> PrecallPlanAIResponse:
    """
    Voice/Tone Precedence:
    1. Front-End Context brand voice (highest)
    2. brand_voice parameter (fallback)
    """
    
    # Initialize PydanticOutputParser
    parser = PydanticOutputParser(pydantic_object=PrecallPlanAIResponse)
    format_instructions = parser.get_format_instructions()
    
    # Convert input dict to readable key-value lines
    input_summary = "\n".join(f"{key.upper().replace('_', ' ')}: {value}" for key, value in parsed_input.items())

    # Load vectorstore and query for related info
    try:
        vectorstore = get_vectorstore("precall_plan", org_id=org_id)
        related_docs = vectorstore.similarity_search(input_summary, k=5)
        related_texts = "\n\n".join([doc.page_content for doc in related_docs])
    except Exception as e:
        logger.error(f"Error retrieving related documents: {e}")
        related_texts = ""

    # Get similar chunks from uploaded text
    query_text = input_summary
    if uploaded_text:
        top_chunks, embedding_metadata = get_top_k_similar_chunks(uploaded_text, query_text)
    else:
        top_chunks, embedding_metadata = [], None
    similar_uploaded_text = "\n\n".join(top_chunks) if top_chunks else "[No file uploaded by rep]"

    # Build hierarchical context according to new precedence rules
    hierarchical_context = f"""
 **PRIMARY SOURCE - Rep Form & Rep File** (Situational Anchor):
{input_summary}

 **Rep Uploaded Context**:
{similar_uploaded_text}

 **AUTHORITATIVE SOURCE - Playbook** (Facts, Messaging, Claims):
{playbook_text or '[No playbook provided]'}

 **Front-End Context** (Company Facts, when not in Playbook):
{frontend_context_text or '[No front-end context provided]'}

 **Supplemental - Vector Knowledge Base**:
{related_texts or '[No related vector documents found]'}
"""

    # Token management
    trimmed_context = summarize_uploaded_text(hierarchical_context, max_tokens=4000)
    tokens = estimate_token_count(hierarchical_context)
    if tokens > 8000:
        logger.warning(f"Prompt too long ({tokens} tokens). Using trimmed version.")
        final_context = trimmed_context
    else:
        final_context = hierarchical_context

    # ENHANCED SYSTEM PROMPT with PydanticOutputParser format instructions
    system_prompt = f"""
    You are an expert sales planning assistant. Your purpose is to help <primary user/front-end prompt> from <company/front-end prompt>’ prepare effective, insightful, and actionable pre-call plans for their next customer visit.
    Your responses should help the <primary user/front-end prompt> execute an engaging and effective customer meeting with their customer audience which is <Target Customers/front-end prompt>.
 
    ### **Compliance/Taboo Handling**:
    If front-end context includes compliance flags or taboo terms, enforce them GLOBALLY.
 
    ---
    ## **Formatting Requirements**
 
    **HTML Output with Hierarchical Structure:**
    - Use `<section class='precall-card'>` wrapper for each field
    - Apply `<strong>`, `<em>`, `<ul>`, `<ol>`, `<blockquote>` as appropriate
    - Number main sections (1., 2., 3., etc.)
    - For subsections within fields, use sub-numbering (1.1, 1.2, etc.)
    - **Exception**: `insights_and_trends` and `relevant_anecdotes_metaphor` should NOT include subheadings or numbers
 
    **Style Rules:**
    - Consultative and data-driven (not fluffy)
    - Action phrasing (imperatives)
    - Short sentences (most ≤ 20 words)
    - Hierarchical headings, bold/italics, bullets, numbered lists.
    - No contradictions. No speculation. Don’t invent people, orgs, or data.
    - Keep reasoning implicit. Do not output chain-of-thought.
 
    ---
    ## **Strict Word Limits** (enforce these rigorously):
 
    - **Recap Objective Profile Pain**: 50 words max
    - **Top 3 Messages**: 200 words max
    - **Insights And Trends**: 100 words max (updated from 50)
    - **Open Ended Questions**: 100 words max
    - **Relevant Anecdotes/Metaphor**: 50 words max
    - **Potential Action Items**: 150 words max (updated from 100)
 
    ---
    ## **Context Provided**
 
    {final_context}
 
    ---
    ## **Admin Custom Instructions** (apply if present):
    {precall_prompt.strip() if precall_prompt else '[No additional admin instructions]'}
    ---
    ## **Output Requirements**
 
    SECTION FORMATTING RULES (MATCH UI EXACTLY)
        recap_objective_profile_pain

        Wrap content in <section class='precall-card'>
        Use one unordered list <ul>
        Each list item must begin with a bold label:
        Objective:
        Customer Profile:
        Key Pain Points:
        No paragraphs, no numbering, no extra labels
        
        Expected shape
        <section class='precall-card'>
        <ul>
            <li><strong>Objective:</strong> …</li>
            <li><strong>Customer Profile:</strong> …</li>
            <li><strong>Key Pain Points:</strong> …</li>
        </ul>
        </section>



        open_ended_questions
        Wrap content in <section class='precall-card'>
        Use <ul><li>
        Exactly 5 bullets
        No numbering, no headings


        top_3_messages

        Wrap content in <section class='precall-card'
        Use <ol>
        Exactly 3 items
        Each item:
        Starts with a short sentence title.
        First sentence should be in bold.
        Followed by explanation in the same <li>
        Do NOT prefix titles with 1. / 2. text

        relevant_anecdotes_metaphor

        Wrap content in <section class='precall-card'>
        Use plain text inside <p>
        Do NOT use <blockquote>
        
        
        insights_and_trends

        Wrap content in <section class='precall-card'>
        Use <ul>
        3–5 concise bullets
        No sources, no citations
        
        
        potential_action_items
        
        Wrap content in <section class='precall-card'>
        Use <ol>
        3–5 items
        Clean numbering only (no nested numbering)
        Do NOT bold anything in this section

        FINAL JSON STRUCTURE (DO NOT DEVIATE)
        {{
        "recap_objective_profile_pain": "<section class='precall-card'>...</section>",
        "open_ended_questions": "<section class='precall-card'>...</section>",
        "top_3_messages": "<section class='precall-card'>...</section>",
        "relevant_anecdotes_metaphor": "<section class='precall-card'>...</section>",
        "insights_and_trends": "<section class='precall-card'>...</section>",
        "potential_action_items": "<section class='precall-card'>...</section>"
        }}
        Processing Steps (Implicit – Do Not Output)
        Parse front-end context (voice, role, compliance)
        Extract call anchors from rep inputs
        Map pains to playbook pillars
        Apply tone and compliance globally
        Validate structure and word counts
       
    **CRITICAL**: Return ONLY the JSON object. Do NOT include:
        - HTML formatting outside JSON values
        - Source citations outside the JSON structure
        - Any text, markdown, or HTML after the closing curly brace of the JSON object
    """

    # Call the chatbot
    response = bot.chat(system_prompt, org_id=org_id)
    
    # Parse using PydanticOutputParser
    try:
        # The parser handles validation automatically
        parsed_response = parser.parse(response['answer'])
        usage_metadata = response.get('usage_metadata', None)
        usage_metadata["embed_usage_metadata"] = embedding_metadata if embedding_metadata else None
        logger.info(f"Successfully parsed precall plan response")
        return parsed_response.dict(), usage_metadata
        
    except Exception as e:
        logger.error(f"Failed to parse response with PydanticOutputParser: {e}")
        logger.error(f"Raw response text: {response['answer']}")
        
        # Optional: Try to clean common LLM output issues before re-parsing
        try:
            cleaned_response = response['answer'].strip()
            # Remove markdown code blocks if present
            if cleaned_response.startswith("```"):
                cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response)
                cleaned_response = re.sub(r'\n?```$', '', cleaned_response)

            # Retry parsing with cleaned response
            parsed_response = parser.parse(cleaned_response)
            usage_metadata = response.get('usage_metadata', None)
            usage_metadata["embed_usage_metadata"] = embedding_metadata if embedding_metadata else None
            logger.info(f"Successfully parsed after cleanup")
            return parsed_response.dict(), usage_metadata
            
        except Exception as retry_error:
            logger.error(f"Failed to parse even after cleanup: {retry_error}")
            
            # FALLBACK: Return safe empty response as worst-case scenario
            logger.warning("Returning empty fallback response due to parsing failures")
            
            fallback_response = PrecallPlanAIResponse(
                recap_objective_profile_pain="<section class='precall-card'><p>Unable to generate recap at this time. Please review your input and try again.</p></section>",
                
                open_ended_questions="<section class='precall-card'><ol><li><strong>What are your primary objectives for this meeting?</strong></li><li><strong>Who will be attending from the customer side?</strong></li><li><strong>What challenges are they currently facing?</strong></li></ol></section>",
                
                top_3_messages="<section class='precall-card'><ol><li><strong>1. Value Proposition:</strong> Unable to generate specific messages at this time.</li><li><strong>2. Differentiation:</strong> Please retry with updated context.</li><li><strong>3. Next Steps:</strong> Review your preparation materials.</li></ol></section>",
                
                insights_and_trends="<section class='precall-card'><p>Unable to generate insights at this time. Please ensure all context is provided correctly.</p></section>",
                
                relevant_anecdotes_metaphor="<section class='precall-card'><blockquote>No anecdotes available. Consider preparing a customer success story manually.</blockquote></section>",
                
                potential_action_items="<section class='precall-card'><ol><li><strong>1. Review customer background and previous interactions</strong></li><li><strong>2. Prepare key questions based on their industry</strong></li><li><strong>3. Schedule internal alignment meeting</strong></li></ol></section>"
            )
            
            return fallback_response.dict(), None
