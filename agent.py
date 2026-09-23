"""LangGraph agent with router → retrieve → grade → generate workflow."""

import os
import sys
from pathlib import Path
from typing import TypedDict

try:
    # Windows' console defaults to cp1252, which can't encode characters an
    # LLM response may contain (e.g. non-breaking hyphens) — crashes the
    # debug print()s below with UnicodeEncodeError otherwise.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END

from rag_tools import search_govt_schemes, detect_scheme
from rag_core import build_vector_store, query_vector_store

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ── LLM ──────────────────────────────────────────────────────────────────
MODEL_NAME = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
llm = ChatGroq(model=MODEL_NAME, temperature=0, max_tokens=4096)

MAX_RETRIES = 2

LANG_NAMES = {
    "hi": "Hindi (हिंदी)",
    "kn": "Kannada (ಕನ್ನಡ)",
    "te": "Telugu (తెలుగు)",
    "en": "English",
}


def get_language_instruction(lang_code: str) -> str:
    if lang_code and lang_code in LANG_NAMES and lang_code != "en":
        lang_name = LANG_NAMES[lang_code]
        return f"\nCRITICAL LANGUAGE MANDATE: You MUST write your ENTIRE final response in {lang_name}. Do NOT answer in English.\n"
    return ""


# ── State ─────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    question: str
    chat_history: list
    language: str
    rewritten_query: str
    retrieved_text: str
    route: str            # "retrieve" | "direct"
    relevance: str        # "relevant" | "not_relevant"
    retries: int
    answer: str


# ── Node: router ──────────────────────────────────────────────────────────
def router(state: AgentState) -> AgentState:
    """Classify the question as scheme-related or off-topic."""
    question = state["question"]
    history = state.get("chat_history", [])
    rewritten_query = state.get("rewritten_query", "")

    # Contextualize query if there is history
    if history and not rewritten_query:
        history_lines = [f"{m.get('sender', 'User')}: {m.get('text', '')}" for m in history[-4:]]
        history_str = "\n".join(history_lines)
        response = llm.invoke(
            f"""Given the following conversation and a follow up question, rephrase the follow up question to be a standalone question, in its original language, that includes all relevant context (especially the names of any schemes being discussed). If the follow up question is already standalone, just return it.

Chat History:
{history_str}

Follow Up Question: {question}

Standalone Question:"""
        )
        contextualized_question = response.content.strip()
    else:
        contextualized_question = rewritten_query or question

    response = llm.invoke(
        f"""You are a classifier. Given the user question below, decide if it 
is about Indian government financial schemes, loans, subsidies, or related 
eligibility/application topics.

Reply with EXACTLY one word: "retrieve" if it is scheme-related, or "direct" 
if it is off-topic, a greeting, or unrelated to government schemes.

User question: {contextualized_question}"""
    )
    route = response.content.strip().lower()
    if route not in ("retrieve", "direct"):
        route = "retrieve"  # default to retrieval if unsure
    print(f"  [router] question='{question}' -> contextualized='{contextualized_question}' -> route={route}")
    return {**state, "route": route, "retries": state.get("retries", 0), "rewritten_query": contextualized_question}


# ── Node: retrieve ────────────────────────────────────────────────────────
def retrieve(state: AgentState) -> AgentState:
    """Call query_vector_store with optional scheme-name filtering."""
    query = state.get("rewritten_query") or state["question"]
    schemes = detect_scheme(query) or detect_scheme(state["question"])

    if len(schemes) == 1:
        scheme_filter = schemes[0]
        n_results = 3
        print(f"  [retrieve] single scheme filter: '{scheme_filter}'")
    elif len(schemes) >= 2:
        scheme_filter = schemes
        n_results = 4
        print(f"  [retrieve] multi-scheme filter: {schemes}")
    else:
        scheme_filter = None
        n_results = 4
        print(f"  [retrieve] general discovery query (no filter, n_results=4)")

    print(f"  [retrieve] searching with query='{query}'")
    retrieved_text = query_vector_store(
        build_vector_store(), query, n_results=n_results, scheme_filter=scheme_filter,
    )
    print(f"  [retrieve] got {len(retrieved_text)} chars of context")
    return {**state, "retrieved_text": retrieved_text}


# ── Node: grade ───────────────────────────────────────────────────────────
def grade(state: AgentState) -> AgentState:
    """Judge whether retrieved text is relevant enough to answer the question."""
    question = state["question"]
    retrieved_text = state["retrieved_text"]

    schemes_detected = detect_scheme(question)
    if schemes_detected:
        scheme_instruction = (
            f"The user specifically asked about: {', '.join(schemes_detected)}. "
            "Check if the retrieved context contains relevant details about at least one of these specific schemes."
        )
    else:
        scheme_instruction = (
            "The user is asking a general or recommendation question about schemes, loans, or subsidies. "
            "The retrieved context may contain chunks from multiple DIFFERENT schemes. This is completely NORMAL and EXPECTED. "
            "Mark as 'relevant' if any of the retrieved chunks provide information on government schemes, loans, subsidies, or eligibility that could help answer the user's intent."
        )

    response = llm.invoke(
        f"""You are a relevance grader for an Indian government financial scheme assistant.
Given the user question and the retrieved context below, decide if the context contains enough information to answer the question meaningfully.

GUIDELINES:
{scheme_instruction}

Reply with EXACTLY one word: "relevant" or "not_relevant".

User question: {question}

Retrieved context:
{retrieved_text[:1500]}"""
    )
    relevance = response.content.strip().lower()
    if relevance not in ("relevant", "not_relevant"):
        relevance = "relevant"  # default to proceeding

    retries = state.get("retries", 0)
    rewritten_query = state.get("rewritten_query", "")

    if relevance == "not_relevant" and retries < MAX_RETRIES:
        # Rewrite the query for a retry with domain expansion
        rewrite_response = llm.invoke(
            f"""The user asked: "{question}"
The initial vector search returned insufficient results. Rewrite this user question into an expanded search query targeting Indian government financial scheme documents.
Include relevant domain terms, business category synonyms (e.g. street vendor, micro credit, working capital, small enterprise, collateral free loan, PM SVANidhi, PMEGP, Stand-Up India, Udyogini), and key loan terms if applicable.
Return ONLY the expanded search query string, nothing else."""
        )
        rewritten_query = rewrite_response.content.strip()
        retries += 1
        print(f"  [grade] relevance=not_relevant, retry {retries}/{MAX_RETRIES}, rewritten_query='{rewritten_query}'")
    else:
        print(f"  [grade] relevance={relevance}, retries={retries}")

    return {
        **state,
        "relevance": relevance,
        "retries": retries,
        "rewritten_query": rewritten_query,
    }


# ── Node: generate ────────────────────────────────────────────────────────
def generate(state: AgentState) -> AgentState:
    """Generate grounded answer from context."""
    question = state["question"]
    retrieved_text = state["retrieved_text"][:2500]
    exhausted_retries = (state.get("relevance") == "not_relevant")
    lang_code = state.get("language", "en")
    lang_inst = get_language_instruction(lang_code)

    history = state.get("chat_history", [])
    history_str = ""
    if history:
        history_lines = [f"{m.get('sender', 'User')}: {m.get('text', '')}" for m in history[-4:]]
        history_str = "\nRecent Conversation History:\n" + "\n".join(history_lines) + "\n"

    if exhausted_retries:
        print(f"  [generate] max retries exhausted & still not_relevant — cautious answer")
        response = llm.invoke(
            f"""You are a helpful assistant for a government scheme navigator called Setu. 
The user asked the question below, but after searching our database we could NOT find a clearly matching scheme.
{lang_inst}
Tell the user honestly that no closely matching scheme was found. If the retrieved context below contains anything loosely related, you may mention it as "possibly related" — but do NOT present it as a definitive answer. Suggest they check official portals (myscheme.gov.in) or contact their local Common Service Centre for accurate information.

{history_str}
CONTEXT:
{retrieved_text}

USER QUESTION: {question}

INSTRUCTION: Keep your response clear, structured, and helpful in Markdown. Use bullet points where appropriate. Bold key terms."""
        )
    else:
        print(f"  [generate] producing grounded answer in lang={lang_code}")
        response = llm.invoke(
            f"""You are a helpful assistant for a government scheme navigator called Setu. 
Answer using ONLY relevant information below — ignore any chunks that don't relate to the question. Be clear, empathetic, and conversational.
{lang_inst}
CRITICAL: Every specific number you state (loan amount, subsidy percentage, age limit, income limit, interest rate, etc.) MUST come from the text explicitly labeled with that scheme's name in the context below. If the context contains multiple [Scheme: ...] sections, NEVER attribute a number from one scheme's section to a different scheme. If you are unsure which scheme a number belongs to, do not state it — say the information wasn't found in that scheme's context instead.

{history_str}
CONTEXT:
{retrieved_text}

USER QUESTION: {question}

INSTRUCTION: Provide a well-structured answer in clean Markdown. Use headings (e.g. ### Eligibility Criteria), bullet points (- item), and bold key figures (loan limits, subsidy %, interest rates). Ensure headings use standard Markdown (e.g. ### Header)."""
        )

    return {**state, "answer": response.content}


# ── Node: generate_direct ─────────────────────────────────────────────────
def generate_direct(state: AgentState) -> AgentState:
    """Respond directly without retrieval (off-topic / greetings)."""
    question = state["question"]
    lang_code = state.get("language", "en")
    lang_inst = get_language_instruction(lang_code)
    print(f"  [generate_direct] responding without retrieval in lang={lang_code}")
    response = llm.invoke(
        f"""You are a helpful assistant for a government scheme navigator 
called Setu. The user sent a message that is not about government schemes.
{lang_inst}
Respond politely and briefly, then remind them you can help with questions 
about Indian government financial schemes, loans, and subsidies.

User message: {question}

INSTRUCTION: Respond politely and concisely in a few friendly sentences. Always finish your last sentence completely."""
    )
    return {**state, "answer": response.content}


# ── Conditional edges ─────────────────────────────────────────────────────
def route_after_router(state: AgentState) -> str:
    """Route to retrieve or generate_direct based on router's decision."""
    return "retrieve" if state["route"] == "retrieve" else "generate_direct"


def route_after_grade(state: AgentState) -> str:
    """Route to generate, or back to retrieve for a retry."""
    if state["relevance"] == "not_relevant" and state["retries"] < MAX_RETRIES:
        # grade node already incremented retries, so if retries < MAX_RETRIES
        # it means the increment just happened and we should retry
        return "retrieve"
    return "generate"


# ── Build the graph ───────────────────────────────────────────────────────
def build_agent():
    """Construct and compile the LangGraph agent."""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("router", router)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade", grade)
    graph.add_node("generate", generate)
    graph.add_node("generate_direct", generate_direct)

    # Edges
    graph.set_entry_point("router")
    graph.add_conditional_edges("router", route_after_router)
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", route_after_grade)
    graph.add_edge("generate", END)
    graph.add_edge("generate_direct", END)

    return graph.compile()


agent = build_agent()
