"""AI-assisted free-text requirement interpretation.

Scoped strictly to turning free text into *draft* structured fields for the
requirement form — the frontend must show these back to the user for
confirmation/edit before they ever reach the calculator or rule engine.
This endpoint never decides eligibility or computes money; it only drafts.
"""

import json
import re

from fastapi import APIRouter

import activity_taxonomy
import llm_client
from schemas import InterpretRequest, InterpretResponse

router = APIRouter(prefix="/api", tags=["interpret"])


PROMPT = """You extract structured financing-requirement details from a citizen's
free-text description, for a Scheduled Caste welfare loan platform.

Return ONLY a JSON object with these keys (use null for anything not mentioned):
- "purpose": "business" or "education"
- "project_type": short description of the business activity (business only)
- "estimated_cost": number in INR (business only, no currency symbols/commas)
- "course_name": name of the course/degree (education only)
- "course_fee": number in INR (education only)

Text: {text}

JSON:"""


@router.post("/interpret", response_model=InterpretResponse)
def interpret(req: InterpretRequest):
    # Raises llm_client.LLMUnavailableError without GROQ_API_KEY → 503 (see api.py).
    llm = llm_client.get_llm(max_tokens=512)
    response = llm.invoke(PROMPT.format(text=req.text))
    raw = response.content.strip()

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return InterpretResponse(
            confidence_note="Could not extract structured fields — please fill the form manually."
        )

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return InterpretResponse(
            confidence_note="Could not parse a structured response — please fill the form manually."
        )

    # The activity category is classified deterministically from the drafted
    # project type (or the raw text), never taken from the LLM.
    purpose = data.get("purpose")
    activity = None
    if purpose != "education":
        activity = (activity_taxonomy.classify(data.get("project_type")).category
                    or activity_taxonomy.classify(req.text).category)

    return InterpretResponse(
        purpose=purpose,
        project_type=data.get("project_type"),
        activity_category=activity,
        estimated_cost=data.get("estimated_cost"),
        course_name=data.get("course_name"),
        course_fee=data.get("course_fee"),
        confidence_note="AI-drafted from your description — please review and correct before continuing.",
    )
