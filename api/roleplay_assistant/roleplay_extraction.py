import asyncio
import json
from typing import Dict, Any, Optional, Tuple   
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from schemas.roleplay_schema import ExtractionResponse
import configparser

config = configparser.ConfigParser()
config.read("config.ini")
gpt_model = config["openAI_config"]["model"]
openai_api_key = config["openAI_config"]["key"]

class ExtractionBot:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=gpt_model,
            api_key=openai_api_key,
            temperature=0
        )

        self.parser = PydanticOutputParser(
            pydantic_object=ExtractionResponse
        )

    def _build_prompt(self) -> str:
        return """
You are an expert information extraction system.

Extract structured Persona and Scenario fields from the input text.


Before generating the output, infer the likely sales situation from the available context.
Consider:
Who the rep is likely meeting with.
What the customer probably cares about.
What commercial outcome matters most.
What objections or risks may surface.
What the rep must learn, uncover, or influence.
What buying stage the account appears to be in.
What product, service, or strategic initiative is most relevant.
What failure mode would most likely hurt the deal.
The user input may be incomplete. You should make intelligent, commercially reasonable inferences.
When inferring missing information:
Stay consistent with the organization context and playbook.
Prefer realistic healthcare commercial dynamics over generic sales situations.
Use specific customer language where possible.
Avoid unsupported claims about clinical outcomes, pricing, reimbursement, or regulatory status.
Do not invent customer-specific facts unless they are framed as plausible role-play context.
Do not contradict uploaded documents, the playbook, or approved messaging.


Commercial Significance Filter
Prioritize role plays involving one or more of the following:
A skeptical economic buyer.
A clinical champion who needs support.
A stalled or at-risk opportunity.
A product launch or adoption barrier.
A competitive threat.
A workflow change that requires stakeholder alignment.
A customer objection that reps frequently mishandle.
A meeting that could influence access, utilization, conversion, expansion, or renewal.
A complex buying committee or multi-stakeholder decision.
A high-value account, strategic segment, or must-win customer type.
Avoid low-value role plays such as casual check-ins, generic product overviews, or overly easy customer conversations.



Persona Field Guidance

title:
Use a short label for the persona.
Example: “Skeptical Interventional Cardiologist” or “Cost-Conscious Service Line Director.”
personaName:
Create a realistic name.
Avoid names of real people unless explicitly provided by the user.
role:
Use the persona’s functional role or job title.
Make it specific to the healthcare setting.
primaryGoals:
List measurable or observable priorities.
Include clinical, operational, economic, workflow, or strategic goals when relevant.
challenges:
Identify real obstacles the persona faces.
These should connect to the customer’s environment and the sales situation.
objections:
Include specific phrases the persona might say during the role play.
Make these natural, skeptical, and realistic.
motivations:
Describe what professionally motivates the persona.
Include what would make them interested in change.
fears:
Identify the underlying worries that could block action.
Include reputational, clinical, financial, operational, workflow, or adoption concerns.
communicationStyle:
Describe how the persona prefers to communicate.
Include tone, level of detail, and decision style.
behavioralTendencies:
Describe how the persona behaves during sales conversations.
Include skepticism level, openness to data, urgency, political behavior, or decision patterns.


Scenario Creation Instructions

Create one scenario that helps the rep prepare for the self-described customer situation.
The scenario must be specific, realistic, and commercially meaningful.
It should require the rep to practice discovery, value communication, objection handling, and next-step advancement.
The scenario should not be a simple pitch. It should simulate a real customer conversation with tension, uncertainty, and competing priorities.
Scenario Field Guidance
title:
Give the scenario a short, clear name.
It should reflect the training context.
description:
Briefly explain the situation and purpose of the role play.
Include why this conversation matters.
trainee's Mission:
Define the role of the trainee.
State what the rep must accomplish during the conversation.
Include both relationship and commercial objectives.
sellingMethodology:
Use the company playbook’s preferred methodology when available.
If no methodology is specified, select the most appropriate methodology for the situation.
Examples: Consultative Selling, Challenger, SPIN, MEDDICC, Integrity Selling, Value-Based Selling.
evaluationCriteriaRecommendation:
Recommend the most appropriate evaluation criteria from the organization context if available.
If no criteria are available, recommend criteria aligned to the role play.
Focus on skills that can be observed and scored.
topicsToCover:
List the core themes the rep must address.
Include discovery, customer priorities, value proposition, objection handling, proof points, risk mitigation, and next steps when relevant.
idealSalesOutcome:
Define the best realistic outcome from the conversation.
This should usually be a specific next step, not a closed sale.
Examples: agreement to pilot, stakeholder mapping, follow-up meeting with decision makers, access to data, workflow assessment, economic review, or clinical champion alignment.
currentState:
Summarize the customer’s likely current situation before the rep engages.
Include status quo, workflow, beliefs, constraints, or buying stage.
barriersToChange:
List the main reasons the customer may resist action.
Include practical, emotional, economic, clinical, operational, and political barriers.
criticalCustomerQuestions:
Include questions the persona is likely to ask.
These should test the rep’s readiness.
Include tough questions around value, evidence, workflow, risk, economics, adoption, and differentiation.

Write the trainee's mission as a direct action-oriented objective from the sales rep perspective.

Do NOT write:
- "Guide the rep to..."
- "Help the trainee..."
- "Coach the salesperson to..."
- instructional or trainer language

Instead write concise business objectives such as:
- Uncover operational barriers and secure agreement to a workflow workshop.
- Preserve trust while addressing compliance concerns.
- Align stakeholders on a realistic evaluation pathway.

MANDATORY RULES:

- ALL fields MUST be populated
- If information is explicitly present → extract it
- If information is missing → intelligently infer based on:
  - context
  - role
  - industry
  - common business patterns

INFERENCE RULES:

- Inference MUST be realistic and professional
- Do NOT use placeholders like "unknown"
- Do NOT leave null values
- Do NOT copy generic filler text
- Keep inferred values short and meaningful

CONFIDENCE RULES:

- Prefer reasonable assumptions over leaving fields empty
- If unsure, infer a safe, neutral, and commonly applicable value

EXAMPLES OF INFERENCE:

- If role = "VP Sales" → likely:
  - goal = "Increase revenue and sales efficiency"
  - challenges = "Pipeline visibility, team performance"
  - objections = "Budget constraints, ROI concerns"

- If scenario unclear → default:
  - title = "Sales Discovery Conversation"
  - description = "Initial discussion to understand customer needs"

OUTPUT REQUIREMENTS:

- NEVER return null
- ALWAYS return complete structured data
- Keep responses concise and business-relevant

STRICT RULES:
- If information is explicitly present, extract it exactly.
- If information is missing, infer it realistically from the scenario context.
- Do not invent unrealistic or unsupported facts.
- Never return null for required fields.
- Keep answers concise
- Output MUST follow the given format
- For multi-value fields, return arrays of strings
- For single-value fields, return strings
- The field "ai_trainer_opening" does NOT mean a conversational opener or scripted dialogue.
- It represents the trainee's mission/objective for the meeting.

PERSONA FIELD RULES:
- thumbnail = persona name
- role = job title or role
- primary_goal = goals or KPIs
- challenges = pain points or difficulties
- objections = resistance statements or objections
- motivations = drivers or positive reasons to act
- fears = risks, worries, or concerns
- communication_style = communication behavior
- behavioral_tendencies = behavior patterns

SCENARIO FIELD RULES:
- title = scenario or meeting title
- description = summary of the situation
- trainee's mission = concise statement of what the sales rep is trying to achieve in the meeting.
Focus on discovery, stakeholder alignment, objection handling, advancing the opportunity, or securing a realistic next step.
This is NOT dialogue and NOT an opening line.
- selling_methodology = sales methodology
- ideal_sales_outcome = desired outcome
- topics_to_cover = topics that should be discussed
- current_state = existing process or situation
- barriers_to_change = blockers or resistance
- critical_questions = questions the salesperson should ask

TEXT:
{input}

FORMAT:
{format_instructions}

"""

    async def extract(
        self,
        description: str,
        company_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:

        final_input = description

        if company_context:
            final_input = f"""
            COMPANY CONTEXT:
            {company_context}

            USER INPUT:
            {description}
        """

        prompt = PromptTemplate(
            template=self._build_prompt(),
            input_variables=["input"],
            partial_variables={
                "format_instructions": self.parser.get_format_instructions()
            }
        )

        formatted_prompt = prompt.format(input=final_input)

        # response = await asyncio.to_thread(
        #     self.llm.invoke,
        #     formatted_prompt
        # )


        response = await self.llm.ainvoke(formatted_prompt)

        content = response.content

        try:
            parsed = self.parser.parse(content)
            result = parsed.model_dump()
        except Exception:
            result = {
                "persona": {
                    "thumbnail": None,
                    "role": None,
                    "primary_goal": None,
                    "challenges": None,
                    "objections": None,
                    "motivations": None,
                    "fears": None,
                    "communication_style": None,
                    "behavioral_tendencies": None
                },
                "scenario": {
                    "title": None,
                    "description": None,
                    "ai_trainer_opening": None,
                    "selling_methodology": None,
                    "ideal_sales_outcome": None,
                    "topics_to_cover": None,
                    "current_state": None,
                    "barriers_to_change": None,
                    "critical_questions": None
                }
            }

        token_usage = None

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            token_usage = response.usage_metadata
        elif hasattr(response, "response_metadata"):
            token_usage = response.response_metadata.get("token_usage")

        return result, token_usage


extraction_bot = ExtractionBot()