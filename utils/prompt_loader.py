def render_company_context(org) -> str:
    if not org:
        return ""

    parts = []

    parts.append(f"""
[COMPANY PROFILE]
- Overview: {org.get("organization_overview", "")}
- Customer Segments: {org.get("customer_segments", "")}
""")

    if org.get("int_user_ext_stakeholder"):
        parts.append(f"""
[CUSTOMERS & STAKEHOLDERS]
{org.get("int_user_ext_stakeholder")}
""")

    if org.get("brand_voice"):
        parts.append(f"""
[BRAND VOICE]
{org.get("brand_voice")}
""")

    if org.get("compliance_guardrails"):
        parts.append(f"""
[COMPLIANCE GUARDRAILS]
{org.get("compliance_guardrails")}
""")

    if org.get("additional_context"):
        parts.append(f"""
[ADDITIONAL CONTEXT]
{org.get("additional_context")}
""")

    parts.append("""
[IMPORTANT INSTRUCTIONS]
- Always follow brand guidelines
- Tailor responses to the target customers
- Never violate constraints
""")

    return "\n".join(parts)


def inject_company_context(base_prompt: str, company_context, org_name) -> str:
    if not company_context:
        return base_prompt
    
    if not isinstance(company_context, dict) or not any(company_context.values()):
        return base_prompt

    formatted_context = render_company_context(company_context)

    if not formatted_context.strip():
        return base_prompt

    #Final injected prompt
    return f"""
{org_name}

{base_prompt}

{formatted_context}

[IMPORTANT]
Always follow company constraints and guidelines while responding.
"""