"""Test the LangGraph agent with diverse queries."""

import sys
sys.stdout.reconfigure(encoding='utf-8')

from agent import agent

TEST_QUERIES = [
    "I'm just starting a tiny tea stall and need a very small loan, around 20,000 rupees",
]


def run_test(question: str):
    print(f"\n{'='*70}", flush=True)
    print(f"QUERY: {question}", flush=True)
    print("-" * 70, flush=True)
    result = agent.invoke({
        "question": question,
        "rewritten_query": "",
        "retrieved_text": "",
        "route": "",
        "relevance": "",
        "retries": 0,
        "answer": "",
    })
    print("-" * 70, flush=True)
    print(f"Route: {result.get('route')}", flush=True)
    print(f"Relevance: {result.get('relevance')}", flush=True)
    print(f"Retries: {result.get('retries')}", flush=True)
    print(f"\nFINAL ANSWER:\n{result['answer']}", flush=True)


if __name__ == "__main__":
    for q in TEST_QUERIES:
        run_test(q)

