"""seep_prompt_library

Revision ID: 2eb5216ab58b
Revises: 85295ed727ae
Create Date: 2026-06-08 18:15:34.698904

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2eb5216ab58b'
down_revision: Union[str, None] = '85295ed727ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROMPTS = [
    {
        "id": 1,
        "category": "DISCOVERY",
        "title": "D1 - Discovery Needs Discovery Guide",
        "description": "Uncover hidden clinical and operational needs with sharper discovery questions.",
        "prompt_content": (
            "Help me uncover unmet clinical or operational needs for this account.\n"
            "Create a discovery guide with: likely pain points, stakeholder-specific questions, "
            "workflow gaps to explore, clinical challenges, operational inefficiencies, adoption "
            "barriers, current-state assumptions to validate, signs of urgency, and possible "
            "next-step commitments.\n"
            "Help me distinguish symptoms from root causes.\n"
            "Make the questions consultative, concise, and relevant across clinical, economic, "
            "and workflow stakeholders.\n"
            "Stay aligned to approved materials and compliance rules.\n"
            "Do not suggest clinical decisions.\n\n"
            "Inputs:\n"
            "{Product/device or solution}\n"
            "{Customer/site}\n"
            "{Stakeholder role}\n"
            "{Procedure, department, or workflow}\n"
            "{Known context}\n"
            "{Current competitor or status quo}\n"
            "{Meeting objective}"
        ),
    },
    {
        "id": 2,
        "category": "DISCOVERY",
        "title": "D2 - Customer Success Criteria Builder",
        "description": "Define measurable success criteria that align stakeholders and guide next steps.",
        "prompt_content": (
            "Help me define customer success criteria for this opportunity.\n"
            "Create clear, measurable criteria across clinical outcomes, workflow impact, adoption, "
            "training readiness, economic value, stakeholder expectations, timeline, and evidence needed.\n"
            "Separate must-have criteria from nice-to-have criteria.\n"
            "Include how success should be measured, who should validate it, and what next step "
            "should follow if criteria are met.\n"
            "Keep recommendations practical, customer-centered, and aligned to approved materials "
            "and compliance rules. Do not suggest clinical decisions.\n\n"
            "Inputs:\n"
            "{Product/device or solution}\n"
            "{Customer/site}\n"
            "{Stakeholders involved}\n"
            "{Current problem or goal}\n"
            "{Evaluation, pilot, or implementation stage}\n"
            "{Timeline}\n"
            "{Known customer priorities}"
        ),
    },
    {
        "id": 3,
        "category": "DISCOVERY",
        "title": "D3 - Patient Selection Criteria Guide",
        "description": "Prepare compliant discussions around patient fit, criteria, risks, and evidence needs.",
        "prompt_content": (
            "Help me prepare for a patient selection discussion for this product or procedure.\n"
            "Create a concise guide covering: approved selection criteria, appropriate-use "
            "considerations, contraindications or exclusions from approved materials, required "
            "clinical information to discuss, stakeholder questions, common misconceptions, "
            "workflow implications, and escalation triggers.\n"
            "Keep this focused on supporting clinician understanding, not making patient-specific "
            "recommendations.\n"
            "Stay aligned to IFU, approved labeling, hospital policy, and compliance rules. "
            "Flag anything requiring medical affairs, clinical leadership, or quality review.\n\n"
            "Inputs:\n"
            "{Product/device}\n"
            "{Procedure or use case}\n"
            "{Customer/site}\n"
            "{Clinical stakeholder}\n"
            "{Patient population or scenario}\n"
            "{Known questions or concerns}"
        ),
    },
    {
        "id": 4,
        "category": "DISCOVERY",
        "title": "D4 - Adoption Barrier Finder",
        "description": "Identify what may slow adoption and create a practical plan to remove friction.",
        "prompt_content": (
            "Help me identify adoption barriers for this product or solution.\n"
            "Analyze potential barriers across clinical confidence, workflow disruption, training "
            "readiness, stakeholder alignment, evidence needs, economic concerns, IT or operational "
            "constraints, competitive resistance, and change fatigue.\n"
            "Prioritize the biggest risks, explain why each matters, and recommend practical next "
            "steps to reduce friction and accelerate adoption. Include stakeholder-specific questions "
            "and escalation triggers.\n"
            "Stay aligned to approved materials, IFU, hospital policy, and compliance rules. "
            "Do not suggest clinical decisions.\n\n"
            "Inputs:\n"
            "{Product/device or solution}\n"
            "{Customer/site}\n"
            "{Department or workflow}\n"
            "{Current adoption stage}\n"
            "{Stakeholders involved}\n"
            "{Known concerns or objections}\n"
            "{Competitor or status quo}\n"
            "{Desired adoption goal}"
        ),
    },
    {
        "id": 5,
        "category": "DISCOVERY",
        "title": "D5 - Workflow Mapper",
        "description": "Understand how the customer works today and where Imagio could fit.",
        "prompt_content": (
            "Help me map the customer's current diagnostic breast imaging workflow, based on my input below.\n"
            "Summarize:\n"
            "- How suspicious breast findings are handled today\n"
            "- Where diagnostic uncertainty shows up\n"
            "- Where BI-RADS 3, 4A, or low 4B cases create friction\n"
            "- When the customer uses follow-up, MRI, CEM, or biopsy\n"
            "- What workflow, staffing, IT, or training issues could affect adoption\n"
            "- Where Imagio may fit in the pathway\n"
            "- What I still need to validate with the customer\n\n"
            "End with a short current-state summary, a likely Imagio-fit hypothesis, and the best "
            "next question to ask.\n\n"
            "#My Input\n"
            "Account name and what I know so far: [type brief notes]"
        ),
    },
 
    # ── MESSAGING ──────────────────────────────────────────────────────────
    {
        "id": 6,
        "category": "MESSAGING",
        "title": "M1 - Total Value Story",
        "description": "Prepare a clear, decision-ready package for value analysis and executive approval.",
        "prompt_content": (
            "Help me prepare a value analysis package for this SENO opportunity, based on my input below.\n"
            "Create a concise package outline that helps the customer make a confident decision. Include:\n"
            "- The customer problem Imagio is solving\n"
            "- The clinical rationale\n"
            "- The workflow fit\n"
            "- The economic case\n"
            "- Reimbursement assumptions and risks\n"
            "- Training and adoption plan\n"
            "- Key risks and how to reduce them\n"
            "- Missing information before submission\n"
            "- Recommended next step\n\n"
            "Keep it practical, account-specific, and approval-ready. Avoid generic product claims.\n\n"
            "# My Input\n"
            "- Account name and what I know so far: [type brief notes]\n"
            "- Known concerns: [clinical, workflow, economic, reimbursement, IT, adoption]"
        ),
    },
    {
        "id": 7,
        "category": "MESSAGING",
        "title": "M2 - Competitive Positioning",
        "description": "Position product against the customer's current pathway without sounding defensive or dismissive.",
        "prompt_content": (
            "Help me position Imagio against the customer's current alternative, based on my input below.\n"
            "Give me:\n"
            "- The best way to acknowledge their current approach\n"
            "- The specific gap or burden to explore\n"
            "- How to position Imagio simply and credibly\n"
            "- One sharp question to create insight\n"
            "- The best next step to advance the conversation\n\n"
            "Keep it practical, respectful, and focused on the customer's workflow, not product comparison.\n\n"
            "# My Input\n"
            "- Account name and what I know so far: [type brief notes]\n"
            "- Customer alternative: [ultrasound-only / MRI / CEM / biopsy-first / ABUS / screening AI / do nothing]\n"
            "- Personas: [persona]"
        ),
    },
    {
        "id": 8,
        "category": "MESSAGING",
        "title": "M3 - HCP-Specific Product Story",
        "description": "Tailor product messaging for physicians or nurses based on their priorities.",
        "prompt_content": (
            "Help me tailor the product story for this HCP audience.\n"
            "Create a concise message that connects the product's value to their clinical role, "
            "workflow priorities, patient-care goals, common concerns, and adoption needs.\n"
            "Include a short talk track, likely questions, objection responses, proof points, "
            "and a recommended next step.\n"
            "Make the message relevant, respectful, and practical for either physicians or nurses.\n"
            "Stay aligned to approved materials, labeling, IFU, and compliance rules. "
            "Avoid unsupported claims or clinical decision-making.\n\n"
            "Inputs:\n"
            "{Product/device or solution}\n"
            "{HCP type: physician or nurse}\n"
            "{Specialty or role}\n"
            "{Customer/site}\n"
            "{Clinical or workflow priority}\n"
            "{Known concerns}\n"
            "{Approved claims/evidence}\n"
            "{Desired next step}"
        ),
    },
    {
        "id": 9,
        "category": "MESSAGING",
        "title": "M4 - Product Demo or Discussion",
        "description": "Prepare a focused, customer-relevant product demo or discussion.",
        "prompt_content": (
            "Help me prepare a product demonstration or presentation for this customer.\n"
            "Create a concise plan covering: audience priorities, meeting objective, recommended flow, "
            "opening message, key product capabilities to show, clinical or workflow value points, "
            "proof points, likely questions, objections, and clear next steps.\n"
            "Include tips to keep the demo practical, interactive, and tied to the customer's "
            "real-world needs.\n"
            "Stay aligned to approved materials, labeling, IFU, and compliance rules. "
            "Avoid unsupported claims or clinical decision-making.\n\n"
            "Inputs:\n"
            "{Product/device or solution}\n"
            "{Customer/site}\n"
            "{Audience roles}\n"
            "{Meeting objective}\n"
            "{Clinical or workflow priority}\n"
            "{Demo format: live, virtual, slides, hands-on}\n"
            "{Known concerns or objections}\n"
            "{Approved claims/evidence}"
        ),
    },
    {
        "id": 10,
        "category": "MESSAGING",
        "title": "M5 - Objection Response",
        "description": "Respond to customer resistance in the right tone for the moment.",
        "prompt_content": (
            "Help me handle this customer objection, based on my input below.\n"
            "Give me:\n"
            "- What the customer is really worried about\n"
            "- The best response for this situation\n"
            "- One smart follow-up question\n"
            "- A low friction next step to engage\n"
            "- What I should avoid saying\n\n"
            "Keep it concise, natural, and focused on reducing risk, not winning an argument.\n\n"
            "My Input:\n"
            "- Objection and context: [insert customer objection and notes]\n"
            "- Persona: [persona]\n"
            "- How I plan to respond: [hallway conversation / live meeting / email]"
        ),
    },
 
    # ── BUYING PROCESS ─────────────────────────────────────────────────────
    {
        "id": 11,
        "category": "BUYING_PROCESS",
        "title": "B1 - Get Deal Unstuck",
        "description": "Diagnose why an opportunity is not moving and what to do next.",
        "prompt_content": (
            "Help me figure out why this deal is stuck, based on my input below.\n"
            "Tell me:\n"
            "- What is most likely causing the stall\n"
            "- Whether the issue is clinical, workflow, economic, political, or indecision-related\n"
            "- What I should avoid doing next\n"
            "- The best next move\n"
            "- The exact message I should send or say to restart momentum\n\n"
            "Keep it direct, practical, and focused on advancing the deal.\n\n"
            "# My Input\n"
            "- Account name and what I know so far: [type brief notes]\n"
            "- Stage: [stage]"
        ),
    },
    {
        "id": 12,
        "category": "BUYING_PROCESS",
        "title": "B2 - Next Best Action",
        "description": "Choose the safest, smartest next move to advance a deal.",
        "prompt_content": (
            "Help me choose the best next action to move this deal forward, based on my input below.\n"
            "Tell me:\n"
            "- Where the customer appears to be in the buying journey\n"
            "- Whether the deal is ready to advance, or if more discovery is needed\n"
            "- The best next action to recommend\n"
            "- Why this action reduces customer risk\n"
            "- Which actions I should avoid for now\n"
            "- What customer decision this next step should support\n"
            "- The exact wording I should use with the customer\n\n"
            "Use JOLT principles. Help me diagnose indecision, offer clear guidance, avoid too many "
            "options, and reduce risk.\n"
            "Do not recommend advancing the deal based on enthusiasm alone. Make sure the next step "
            "is tied to a real customer decision.\n\n"
            "# My Input\n"
            "- Customer situation: [type brief notes]\n"
            "- Options I am considering: [demo / workflow meeting / finance review / evidence review "
            "/ IT review / proposal / other]\n"
            "- Known risks: [clinical / workflow / economic / IT / political / reimbursement / indecision]"
        ),
    },
    {
        "id": 13,
        "category": "BUYING_PROCESS",
        "title": "B3 - Shared Buying Plan",
        "description": "Create a buying plan when the customer is engaged but the path to decision is unclear.",
        "prompt_content": (
            "Build a simple mutual action plan for this SENO opportunity, based on my input below.\n"
            "Create a clear path from interest to decision. Include:\n"
            "- The next 4 to 6 milestones\n"
            "- Who needs to be involved at each step\n"
            "- What output each step should produce\n"
            "- What customer decision each step supports\n"
            "- What risk each step reduces\n"
            "- Where the deal should not advance yet\n\n"
            "Keep it practical, customer-ready, and focused on real decision progress.\n\n"
            "# My Input\n"
            "- Account and current stage: [type account and stage]\n"
            "- Customer goal: [goal]\n"
            "- Known decision process: [brief notes]\n"
            "- Key risks: [clinical / workflow / economic / IT / political / reimbursement / indecision]"
        ),
    },
    {
        "id": 14,
        "category": "BUYING_PROCESS",
        "title": "B4 - Stakeholder Power Maps",
        "description": "Help reps identify who drives the decision, who can stall it, and who can move it forward.",
        "prompt_content": (
            "Help me build a stakeholder power map for this opportunity, based on my input below.\n"
            "Identify:\n"
            "- Who likely has economic, clinical, workflow, technical, and political influence\n"
            "- Who may be the champion, mobilizer, coach, blocker, skeptic, or hidden decision-maker\n"
            "- What each person likely cares about\n"
            "- What risk each person may raise\n"
            "- Who is missing from the buying group\n"
            "- The next best action to strengthen the power map\n\n"
            "End with the top three stakeholder moves I should make next. "
            "Keep it practical, specific, and focused on moving the deal forward.\n\n"
            "# My Input\n"
            "- Account and current stage: [type account and stage]\n"
            "- Current contacts: [names, roles, notes]\n"
            "- What I know so far: [brief notes]"
        ),
    },
    {
        "id": 15,
        "category": "BUYING_PROCESS",
        "title": "B5 - Buying Process",
        "description": "Map approval steps, stakeholders, evidence needs, paperwork, and timelines.",
        "prompt_content": (
            "Help me understand this account's buying and approval process.\n"
            "Map the likely steps from interest to approval, including committees, decision makers, "
            "influencers, required paperwork, evidence needs, budget path, procurement steps, "
            "IT/security review if relevant, contracting requirements, and expected timeline.\n"
            "Identify missing information, likely bottlenecks, stakeholder questions, and the next "
            "best action to clarify or advance the process.\n"
            "Keep guidance practical, customer-centered, and compliant.\n\n"
            "Inputs:\n"
            "{Product/device or solution}\n"
            "{Customer/site}\n"
            "{Business type: capital, procedure-heavy, consumable, digital/SaaS}\n"
            "{Current opportunity stage}\n"
            "{Known stakeholders}\n"
            "{Known approval steps}\n"
            "{Known objections or delays}\n"
            "{Target decision date}"
        ),
    },
 
    # ── CASE SUPPORT & TRAINING ────────────────────────────────────────────
    {
        "id": 16,
        "category": "CASE_SUPPORT_TRAINING",
        "title": "C1 - Build My Launch Plan",
        "description": "Creates a simple customer onboarding plan for go-live readiness.",
        "prompt_content": (
            "Create a simple Imagio onboarding plan for this customer.\n"
            "Focus on what must happen before first use, first 10 cases, and first 50 cases.\n"
            "Include roles, training steps, workflow readiness, IT/PACS readiness, and adoption checkpoints.\n"
            "Keep it practical and easy for the customer team to follow.\n\n"
            "Inputs:\n"
            "Customer/site: {customer_site}\n"
            "Users to train: {radiologists_sonographers_admins}\n"
            "Target go-live date: {date}\n"
            "Known risks: {risks}\n"
            "Current readiness: {readiness_notes}"
        ),
    },
    {
        "id": 17,
        "category": "CASE_SUPPORT_TRAINING",
        "title": "C2 - Train This User Role",
        "description": "Tailors training priorities by customer role.",
        "prompt_content": (
            "Create a role-specific Imagio training guide for this user.\n"
            "Explain what they need to know, what they need to do, what risks to avoid, and how "
            "success should be measured.\n"
            "Keep the guidance simple, role-specific, and focused on confident adoption.\n\n"
            "Inputs:\n"
            "Role: {radiologist / sonographer / administrator / IT / navigator}\n"
            "Experience level: {new / intermediate / experienced}\n"
            "Site workflow notes: {workflow_notes}\n"
            "Training goal: {goal}\n"
            "Known concerns: {concerns}"
        ),
    },
    {
        "id": 18,
        "category": "CASE_SUPPORT_TRAINING",
        "title": "C3 - Prepare Case Review",
        "description": "Helps customers organize cases for review and learning.",
        "prompt_content": (
            "Help prepare for an Imagio case review session.\n"
            "Organize the cases, identify learning themes, flag interpretation or workflow questions, "
            "and suggest discussion points.\n"
            "Focus on helping the team improve confidence, consistency, and adoption.\n\n"
            "Inputs:\n"
            "Review type: {first_10_cases / first_50_cases / ongoing_review}\n"
            "Number of cases: {case_count}\n"
            "Case themes: {themes}\n"
            "Questions from users: {questions}\n"
            "Known challenges: {challenges}\n"
            "Desired outcome: {outcome}"
        ),
    },
    {
        "id": 19,
        "category": "CASE_SUPPORT_TRAINING",
        "title": "C4 - Check Adoption Health",
        "description": "Assesses whether the site is moving toward sustained use.",
        "prompt_content": (
            "Assess Imagio adoption health for this site.\n"
            "Identify what is working, what may be limiting utilization, which users need support, "
            "and what action should happen next.\n"
            "Focus on practical steps to improve consistency, confidence, and sustained use.\n\n"
            "Inputs:\n"
            "Site: {site_name}\n"
            "Time since go-live: {timeframe}\n"
            "Utilization notes: {utilization_notes}\n"
            "Trained users: {users}\n"
            "Barriers observed: {barriers}\n"
            "Success metrics: {metrics}"
        ),
    },
    {
        "id": 20,
        "category": "CASE_SUPPORT_TRAINING",
        "title": "C5 - Fix Adoption Friction",
        "description": "Diagnoses workflow friction and recommends next actions.",
        "prompt_content": (
            "Help troubleshoot an Imagio adoption issue.\n"
            "Identify the likely root cause, whether it is clinical, workflow, training, IT/PACS, "
            "staffing, communication, or utilization-related.\n"
            "Recommend the simplest next action and who should own it.\n\n"
            "Inputs:\n"
            "Issue observed: {issue}\n"
            "When it happens: {timing}\n"
            "Roles involved: {roles}\n"
            "Impact on workflow: {impact}\n"
            "Actions already tried: {actions_tried}\n"
            "Urgency: {low / medium / high}"
        ),
    },
 
    # ── MANAGER TOOLKIT ────────────────────────────────────────────────────
    {
        "id": 21,
        "category": "MANAGER_TOOLKIT",
        "title": "MT1 - After Action Review Facilitator",
        "description": "Turn recent field activity into lessons, coaching, and better execution.",
        "prompt_content": (
            "Help me conduct an After Action Review with my rep or team.\n"
            "Compare what was expected, what actually happened, why it happened, and what we should "
            "do differently next time.\n"
            "Identify wins to reinforce, execution gaps, missed customer signals, stakeholder or "
            "workflow issues, coaching opportunities, and follow-up actions.\n"
            "Keep the review constructive, specific, and focused on learning rather than blame.\n"
            "Include discussion questions, key takeaways, owner assignments, and next-step commitments.\n\n"
            "Inputs:\n"
            "{Rep or team}\n"
            "{Account/customer}\n"
            "{Event or interaction reviewed}\n"
            "{Original objective}\n"
            "{What happened}\n"
            "{Outcome}\n"
            "{Observed strengths}\n"
            "{Observed gaps}\n"
            "{Next milestone}"
        ),
    },
    {
        "id": 22,
        "category": "MANAGER_TOOLKIT",
        "title": "MT2 - Pre-Ride Coaching Plan",
        "description": "Prepare a targeted coaching plan before observing a rep in the field.",
        "prompt_content": (
            "Help me prepare for a field ride or customer observation with this rep.\n"
            "Create a coaching plan focused on what to observe, what good looks like, likely coaching "
            "moments, customer-facing risks, deal or account objectives, and questions I should ask "
            "before and after the interaction.\n"
            "Prioritize 2-3 coaching themes that could most improve rep performance.\n"
            "Include what I should avoid over-coaching in the moment. "
            "Keep guidance practical, specific, and compliant.\n\n"
            "Inputs:\n"
            "{Rep name}\n"
            "{Customer/account}\n"
            "{Interaction type}\n"
            "{Opportunity stage}\n"
            "{Rep experience level}\n"
            "{Known strengths}\n"
            "{Known development areas}\n"
            "{Manager objective}"
        ),
    },
    {
        "id": 23,
        "category": "MANAGER_TOOLKIT",
        "title": "MT3 - Customer Call Debrief",
        "description": "Debrief a customer interaction with a rep to identify coaching priorities.",
        "prompt_content": (
            "Help me debrief this customer interaction with my rep.\n"
            "Identify what the rep did well, where the conversation lost momentum, missed discovery "
            "opportunities, stakeholder signals, objection-handling gaps, next-step quality, and "
            "coaching priorities.\n"
            "Create a balanced debrief with: positive reinforcement, 2-3 improvement areas, specific "
            "examples, coaching questions, and one practical assignment before the next customer interaction.\n"
            "Keep the tone constructive and focused on behavior, not personality.\n\n"
            "Inputs:\n"
            "{Rep name}\n"
            "{Customer/account}\n"
            "{Call notes or transcript}\n"
            "{Call objective}\n"
            "{Customer signals}\n"
            "{Rep self-assessment}\n"
            "{Deal stage}\n"
            "{Desired next step}"
        ),
    },
    {
        "id": 24,
        "category": "MANAGER_TOOLKIT",
        "title": "MT4 - 1:1 Coaching",
        "description": "Turn rep performance, pipeline, and behavior patterns into a focused coaching conversation.",
        "prompt_content": (
            "Help me prepare a high-impact 1:1 coaching conversation with this rep.\n"
            "Review performance, pipeline quality, deal risks, account execution, customer-facing "
            "behaviors, CRM discipline, and skill development needs.\n"
            "Create a focused agenda with: wins to reinforce, patterns to address, 2-3 coaching "
            "questions, priority deals to inspect, one skill to practice, and clear commitments "
            "before the next 1:1.\n"
            "Make it direct, supportive, and action-oriented.\n\n"
            "Inputs:\n"
            "{Rep name}\n"
            "{Recent performance}\n"
            "{Pipeline summary}\n"
            "{Key deals/accounts}\n"
            "{Observed strengths}\n"
            "{Observed gaps}\n"
            "{CRM or forecast concerns}\n"
            "{Upcoming customer moments}\n"
            "{Manager priority}"
        ),
    },
    {
        "id": 25,
        "category": "MANAGER_TOOLKIT",
        "title": "MT5 - Account & Deal Assessment",
        "description": "Diagnose deal and account health, stakeholder power, risks, and next best actions.",
        "prompt_content": (
            "Help me assess this account or deal and coach the rep on how to advance it.\n"
            "Evaluate stakeholder alignment, champion strength, decision power, blockers, "
            "buying-process clarity, clinical need, urgency, economic case, workflow fit, evidence "
            "gaps, competitive pressure, procurement path, implementation readiness, and rep execution.\n"
            "Identify the top risks, missing information, likely root causes of stalled momentum, "
            "and the safest next best action.\n"
            "Include a power map, deal-health score, coaching questions, and a practical engagement "
            "plan by stakeholder.\n\n"
            "Inputs:\n"
            "{Rep name}\n"
            "{Product/solution}\n"
            "{Customer/account}\n"
            "{Opportunity stage}\n"
            "{Time in stage or time stalled}\n"
            "{Known stakeholders and roles}\n"
            "{Champion or sponsor}\n"
            "{Known blockers or skeptics}\n"
            "{Buying process status}\n"
            "{Customer need or pain point}\n"
            "{Known objections or delays}\n"
            "{Competitor or status quo}\n"
            "{Rep's proposed next step}\n"
            "{Target decision or next milestone}"
        ),
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    # Insert prompts into prompt_master
    for prompt in PROMPTS:
        conn.execute(
            sa.text("""
                INSERT INTO prompt_master (
                    category,
                    title,
                    description,
                    prompt_content,
                    created_by,
                    last_updated_by,
                    created_at,
                    last_updated_at,
                    is_deleted
                )
                SELECT
                    :category,
                    :title,
                    :description,
                    :prompt_content,
                    'migration',
                    'migration',
                    NOW(),
                    NOW(),
                    false
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM prompt_master
                    WHERE title = :title
                )
            """),
            {
                "category": prompt["category"],
                "title": prompt["title"],
                "description": prompt["description"],
                "prompt_content": prompt["prompt_content"],
            },
        )

    # Insert all prompts for all users
    conn.execute(
        sa.text("""
        INSERT INTO prompt_user (
            user_id,
            category,
            title,
            description,
            prompt_content,
            created_by,
            last_updated_by,
            created_at,
            last_updated_at,
            is_deleted
        )
        SELECT
            u.id,
            pm.category,
            pm.title,
            pm.description,
            pm.prompt_content,
            'migration',
            'migration',
            NOW(),
            NOW(),
            false
        FROM "user" u
        CROSS JOIN prompt_master pm
        WHERE pm.title = ANY(:titles)
        AND NOT EXISTS (
            SELECT 1
            FROM prompt_user pu
            WHERE pu.user_id = u.id
              AND pu.title = pm.title
        )
    """),
        {"titles": [p["title"] for p in PROMPTS]},
    )

    # Fix sequences
    conn.execute(sa.text("""
        SELECT setval(
            pg_get_serial_sequence('prompt_master', 'id'),
            COALESCE((SELECT MAX(id) FROM prompt_master), 1),
            true
        )
    """))

    conn.execute(sa.text("""
        SELECT setval(
            pg_get_serial_sequence('prompt_user', 'id'),
            COALESCE((SELECT MAX(id) FROM prompt_user), 1),
            true
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()

    titles = [p["title"] for p in PROMPTS]

    conn.execute(
        sa.text("""
            DELETE FROM prompt_user
            WHERE title = ANY(:titles)
        """),
        {"titles": titles},
    )

    conn.execute(
        sa.text("""
            DELETE FROM prompt_master
            WHERE title = ANY(:titles)
        """),
        {"titles": titles},
    )

