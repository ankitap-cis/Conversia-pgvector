import hashlib
import asyncio
import configparser
from pathlib import Path
from typing import Dict, Any, List, Tuple
from bs4 import BeautifulSoup
import re
from logger import logger
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.documents import Document
from utils.GKB_retriever import _retrieve_similar_documents


config = configparser.ConfigParser()
config.read("config.ini")
gpt_model = config["openAI_config"]["model"]
openai_api_key = config["openAI_config"]["key"]

from langchain_core.callbacks import BaseCallbackHandler
from typing import Any, Dict, List
from utils.token_consumption import TokenUsageCallback

class EmailCoachBot:

    SYSTEM_ROLE = """ROLE
    You are a communications coach, an expert assistant for generating clear, professional, and well-formatted business emails, text messages and related.
    Your purpose is to help <primary user/front-end prompt> from <company/front-end prompt>’ draft high-impact messages (email, SMS, voicemail) that help reps get replies, meetings, and momentum

    PRIMARY GOAL
    Help users quickly draft polished, effective emails and text messages tailored to their audience, goals, and company context.

        **When composing the email:**  
    - Use hierarchical formatting:**
    - Headings or subheadings** to introduce main sections
    - Bold and italics to emphasize key points or contrasts
    - Bulleted and numbered lists for step-by-step or grouped ideas
    - Chunk information:  
        - Group related ideas together  
        - Limit paragraphs to 3–4 sentences  
        - Use white space and spacing for readability
    - Personalize the email based on the user’s company and audience context.  
    - Clearly incorporate all key points.**
    - Use a **professional, concise, and polite tone** that matches the sender and audience.
    - Include an appropriate greeting, logical flow, and a polite sign-off.
    - If extra context or files are provided, use them to tailor the message, but do not copy verbatim text unless asked.
    """

    """
    **Your output:**  
    Return ONLY the fully-formatted email draft, ready to send, using headings, bullets, and spacing as described. Do not add explanations or extra commentary.
    """


    COMPLIANCE_GUIDELINES = """SAFETY & COMPLIANCE (MedTech-ready):
- Never disclose PHI (Protected Health Information)
- Avoid off-label or superiority claims unless explicitly marked "approved" in uploaded materials
- Do not mention competitors unless explicitly allowed in organizational context
- Include company footer/disclaimer if specified
- Use {{placeholder}} tokens for missing information rather than fabricating details
- All promotional claims must be truthful, balanced, and evidence-based
- Ensure HIPAA and CAN-SPAM compliance in all communications"""

    MESSAGING_FRAMEWORK = """BEST-PRACTICE MESSAGING:
- Lead with relevance: Context → Value → Specific Ask (meeting, resource, intro)
- Show proof: credential, outcome, reference, or brief micro-case if available
- Reduce friction: propose two specific times or a yes/no next step
- Personalize with role/audience relevance, not biography
- Use tokens like {{FirstName}}, {{Hospital}}, {{Product}} for personalization
- Keep emails ≤180 words unless otherwise specified
- Active voice, consultative tone, grade 8-10 reading level
- Each paragraph ≤4 sentences, most sentences ≤20 words"""

    INFO_HIERARCHY = """INFORMATION HIERARCHY (highest → lowest priority):
1. User form input (role, audience, key_points, additional_context) - intent & audience are authoritative
2. Uploaded documents (domain facts and approved claims only)
3. Organization context (brand voice, compliance rules, ICP, regional guidelines)
4. General knowledge (gap fill only; never invent specific claims)

    NOTE
    - Do not repeat or return the user's instructions as the final answer.
    - Treat additional context only as guidance, not as email content.
    - The final output must be the generated email/message only.
"""

    def __init__(self, storage_dir: str = "./email_data"):
        self.llm = ChatOpenAI(
            model_name=gpt_model,
            openai_api_key=openai_api_key,
            temperature=0.3  # Slightly higher for creative variation while maintaining consistency
        )
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: Dict[str, str] = {}

    async def get_session_id(self, user_id: str, organization_id: str = None) -> str:
        """Create a consistent session ID per user/org."""
        base = f"email_gen_{user_id}_{organization_id}" if organization_id else f"email_gen_{user_id}"
        session_hash = hashlib.md5(base.encode()).hexdigest()[:8]
        session_id = f"email_{session_hash}"
        self.sessions[(user_id, organization_id)] = session_id
        return session_id

    async def clean_html(self, html_content: str) -> str:
        """Clean HTML safely and wrap in single div."""
        if not isinstance(html_content, str):
            html_content = str(html_content or "")
        html_content = html_content.strip().strip('`"\'').replace('\\n', ' ').replace('\\t', ' ')
        html_content = html_content.replace('\\"', '"').replace('\\/', '/')

        soup = BeautifulSoup(html_content, "html.parser")

        # Remove unsafe tags
        for tag in soup.find_all(['script', 'style', 'link', 'meta', 'title', 'iframe', 'object', 'embed']):
            tag.decompose()

        # Ensure single div wrapper
        if not soup.find('div'):
            wrapper = soup.new_tag('div')
            for content in list(soup.contents):
                if hasattr(content, 'name'):
                    wrapper.append(content.extract())
            soup.clear()
            soup.append(wrapper)

        # Whitelist tags and attributes
        allowed_tags = {'div', 'p', 'h1', 'h2', 'h3', 'ul', 'li', 'strong', 'em', 'br', 'a', 'span'}
        allowed_attrs = {'style', 'href'}

        for tag in soup.find_all(True):
            if tag.name not in allowed_tags:
                tag.name = 'p'
            # Remove unwanted attributes
            attrs_to_remove = [attr for attr in tag.attrs if attr not in allowed_attrs]
            for attr in attrs_to_remove:
                del tag.attrs[attr]

            # Keep only safe style properties
            if 'style' in tag.attrs:
                style_value = tag.attrs['style']
                safe_properties = ['margin', 'padding', 'font-weight', 'text-align', 'color', 'font-size', 'line-height']
                safe_styles = []
                for rule in style_value.split(';'):
                    rule = rule.strip()
                    if rule and any(rule.startswith(prop) for prop in safe_properties):
                        safe_styles.append(rule)
                if safe_styles:
                    tag.attrs['style'] = '; '.join(safe_styles)
                else:
                    del tag.attrs['style']

        result = str(soup).replace('\n', ' ')
        result = re.sub(r'\s{2,}', ' ', result).strip()
        return result

    def _build_enhanced_prompt(self) -> str:
        return f"""
    {self.SYSTEM_ROLE}

    {self.INFO_HIERARCHY}

    {self.COMPLIANCE_GUIDELINES}

    {self.MESSAGING_FRAMEWORK}

    WORKFLOW (follow in order):
    1. Parse role, audience, and key_points from user input. Define the single objective.
    2. Extract approved facts from ALL available sources:
    - USER REQUEST & FORM INPUT (highest priority - user's explicit instructions)
    - UPLOADED MATERIALS (approved claims from documents)
    - RETRIEVED DOCUMENTS (evidence-backed support from knowledge base)
    - ORGANIZATION GUIDELINES (brand voice, compliance rules)
    - SCENARIO CONTEXT (additional situational details)
    3. When RETRIEVED DOCUMENTS are provided:
    - Use them as primary evidence-backed support for claims
    - They come from your organization's verified knowledge base
    - Prioritize retrieved document content when it directly supports key points
    - DO NOT make claims without grounding them in provided context
    4. Choose medium-appropriate structure:
    - Email: Hook → Value → CTA → Availability → Signature
    - SMS: Context → Ask → Link/Availability (≤320 characters)
    - Voicemail: Name/Reason → Value → Clear Ask → Callback → "I'll email details" (25-35 seconds)
    5. Draft primary email with 3 subject line options and 1 preview line.
    6. Create SMS and voicemail variants if requested.
    7. Run compliance pass: Red-flag speculative claims, replace with neutral phrasing or {{{{placeholders}}}}.
    8. Use hierarchical formatting only when the user request explicitly requires structured sections.
    9. Do NOT add headings or subheadings unless the user provides them.

    OUTPUT REQUIREMENTS:
    - Generate professional HTML email wrapped in a single <div>
    - Use semantic HTML tags: <p>, <h2>, <h3>, <ul>/<li>, <strong>, <em>
    - Apply inline styles for consistent rendering across email clients
    - Include clear CTA with 2 specific time options or fallback scheduling link
    - Use the actual organization name from ORGANIZATION CONTEXT.
    - Do not use {{CompanyName}} or {{CompanyName}} if organization name is available.
    - Only use {{CompanyName}} if no organization name exists in context.
    - Ensure mobile-responsive formatting (single column, readable font sizes)
    - Flag any content requiring legal/compliance approval in compliance notes section

    COMPLIANCE & SAFETY GUARDRAILS:
    - NEVER make unsubstantiated medical/clinical claims
    - NEVER guarantee specific outcomes or results
    - NEVER use aggressive or manipulative language
    - NEVER include pricing without explicit user input providing it
    - ALWAYS use conditional language for forward-looking statements ("may help", "designed to", "intended for")
    - ALWAYS verify claims against provided context before including them
    - If uncertain about a claim's validity, mark it as {{{{[Needs Approval]}}}} and explain in compliance notes

    CONTEXT PROVIDED BELOW:
    {{context}}

    Based on the above guidelines and the context provided, generate a compliant, high-impact email that achieves the user's objective while maintaining professional standards and regulatory compliance.

    IMPORTANT: Remove any of these potentially unsafe HTML tags from your response:
    'script', 'style', 'link', 'meta', 'title', 'iframe', 'object', 'embed', 'form', 'input', 'button'
    """

    async def generate_email_logic(
        self,
        parsed_input: Dict[str, Any],
        uploaded_text: str = "",
        email_prompt: str = "",
        user_id: str = None,
        organization_id: str = None,
        org_name: str = "",
        scenario_context: str = "",
        general_bot=None,
    ) -> Tuple[str, TokenUsageCallback]:
        try:
            user_input = parsed_input.get("combined_input", "").strip()
            session_id = await self.get_session_id(user_id, organization_id)

            context_parts = []

            if user_input:
                context_parts.append(f"USER REQUEST & FORM INPUT:\n{user_input}")

            if uploaded_text:
                context_parts.append(
                    f"\nUPLOADED MATERIALS (Approved Claims):\n{uploaded_text[:2000]}"
                )

            retrieved_docs_text = ""

            if general_bot is not None:
                try:
                    retrieval_query = uploaded_text or user_input or scenario_context

                    if retrieval_query:
                        retrieved_docs, retrieval_metadata = await _retrieve_similar_documents(
                            query=retrieval_query[:2000],
                            general_bot=general_bot,
                            org_id=organization_id,
                            max_docs=5
                        )

                        if retrieved_docs:
                            doc_lines = []

                            for idx, doc in enumerate(retrieved_docs, start=1):
                                doc_content = doc.page_content.strip()
                                doc_lines.append(
                                    f"DOCUMENT {idx} (Source: {doc.metadata.get('source', 'Unknown')}):\n{doc_content}"
                                )

                            retrieved_docs_text = "\n\n".join(doc_lines)

                            context_parts.append(
                                "\nRETRIEVED DOCUMENTS (Evidence-Backed Support from gkb_retriever):\n"
                                "Use these documents to support claims in the email.\n\n"
                                f"{retrieved_docs_text}"
                            )

                            logger.info(
                                f"Retrieved {len(retrieved_docs)} documents for email generation",
                                extra={
                                    "session_id": session_id,
                                    "docs_count": len(retrieved_docs),
                                    "retrieval_status": retrieval_metadata.get("status", "N/A")
                                }
                            )
                        else:
                            logger.info("No documents retrieved for email generation")
                    else:
                        logger.info("No retrieval query available, skipping document retrieval")

                except Exception as retrieval_error:
                    logger.warning(
                        f"Retriever failed for session {session_id}: {retrieval_error}",
                        exc_info=True
                    )

            if email_prompt:
                context_parts.append(
                    f"\nORGANIZATION GUIDELINES:\n{email_prompt}"
                )

            if org_name:
                context_parts.append(
                    f"\nORGANIZATION NAME:\n{org_name}"
                )

            if scenario_context:
                context_parts.append(
                    f"\nSCENARIO CONTEXT:\n{scenario_context}"
                )

            context_text = "\n\n".join(context_parts)

            prompt_template = self._build_enhanced_prompt()
            prompt_template = self.escape_prompt_braces(prompt_template)

            prompt = PromptTemplate(
                input_variables=["context"],
                template=prompt_template
            )

            context_docs: List[Document] = [
                Document(page_content=context_text)
            ]

            chain = create_stuff_documents_chain(self.llm, prompt)
            token_callback = TokenUsageCallback()

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: chain.invoke(
                    {"context": context_docs},
                    config={"callbacks": [token_callback]}
                )
            )

            cleaned_email = await self.clean_html(
                response if isinstance(response, str)
                else response.get("output_text", str(response))
            )

            if org_name:
                company_placeholders = [
                    "{CompanyName}",
                    "{{CompanyName}}",
                    "{Company Name}",
                    "{{Company Name}}"
                ]

                for placeholder in company_placeholders:
                    cleaned_email = cleaned_email.replace(
                        placeholder,
                        org_name
                    )

            logger.info(f"Successfully generated email for session {session_id}")
            return cleaned_email, token_callback

        except Exception as e:
            logger.error(f"Error generating email: {e}", exc_info=True)
            return (
                "<div><p>Error generating email. Please verify your inputs and try again.</p></div>",
                None
            )
            
    async def validate_compliance(self, email_content: str, uploaded_docs: List[str] = None) -> Dict[str, Any]:
        issues = []
        
        phi_patterns = [
            r'\b\d{3}-\d{2}-\d{4}\b', 
            r'\b\d{10}\b', 
            r'\bpatient\s+\w+\s+\w+\b' 
        ]
        
        for pattern in phi_patterns:
            if re.search(pattern, email_content, re.IGNORECASE):
                issues.append(f"Potential PHI detected: {pattern}")
        
        claim_keywords = ['proven', 'clinical trial', 'study shows', 'efficacy', 'reduces by']
        has_citations = bool(re.search(r'\[.*?p\.\d+\]', email_content))
        
        if any(kw in email_content.lower() for kw in claim_keywords) and not has_citations:
            issues.append("Clinical claims detected without proper citations")
        
        return {
            "compliant": len(issues) == 0,
            "issues": issues,
            "requires_review": len(issues) > 0
        }

    def escape_prompt_braces(self, text: str) -> str:
        """
        Escapes curly braces so LangChain does not treat placeholders
        like {CompanyName}, {FirstName}, etc. as PromptTemplate variables.

        Keeps {context} available as the only real LangChain variable.
        """
        if not text:
            return ""

        escaped = text.replace("{", "{{").replace("}", "}}")

        # Keep LangChain's actual variable unescaped
        escaped = escaped.replace("{{context}}", "{context}")

        return escaped

email_coach_bot = EmailCoachBot()
