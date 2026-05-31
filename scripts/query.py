"""
Query the knowledge base using index-guided retrieval (no RAG).

The LLM reads the index, picks relevant articles, and synthesizes an answer.
No vector database, no embeddings, no chunking - just structured markdown
and an index the LLM can reason over.

This is the narrative-layer query path. For structural / cross-cutting lookups
(god nodes, community bridges, call graphs), use `/graphify query "..."` instead;
see knowledge/concepts/infra/knowledge-system-layering.md for the division of
labor between the two layers.

Usage:
    uv run python scripts/query.py "How should I handle auth redirects?"
"""

from __future__ import annotations

# Recursion prevention: set this BEFORE any imports that might trigger Claude
# Code hooks when the Agent SDK spawns a subprocess.
import os
os.environ.setdefault("CLAUDE_INVOKED_BY", "knowledge_base_query")

import argparse
import asyncio
from pathlib import Path

from utils import load_state, read_all_wiki_content, save_state

ROOT_DIR = Path(__file__).resolve().parent.parent


async def run_query(question: str) -> str:
    """Query the narrative knowledge base and return the synthesized answer.

    Sends the full KB content (index + all article bodies) to the LLM along
    with the user's question. The LLM reads the index first, selects relevant
    articles, and synthesizes an answer with wikilink citations.

    Read-only by design: the narrative layer no longer files query answers as
    Q&A articles. To persist a query answer into compounding knowledge, use
    `graphify save-result` — it stores the answer in the atlas layer, which
    graphify re-extracts as a node on the next `--update`.

    max_turns=15 is sufficient because the query agent only needs to read files
    and synthesize an answer; it doesn't compile multi-article outputs like
    compile.py does.

    Args:
        question: The natural-language question to answer.

    Returns:
        The LLM's answer as a plain string, or an error message on failure.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    wiki_content = read_all_wiki_content()

    prompt = f"""You are a knowledge base query engine. Answer the user's question by
consulting the knowledge base below.

## How to Answer

1. Read the INDEX section first - it lists every article with a one-line summary
2. Identify 3-10 articles that are relevant to the question
3. Read those articles carefully (they're included below)
4. Synthesize a clear, thorough answer
5. Cite your sources using [[wikilinks]] (e.g., [[concepts/general/some-topic]])
6. If the knowledge base doesn't contain relevant information, say so honestly

## Knowledge Base

{wiki_content}

## Question

{question}
"""

    answer = ""
    cost = 0.0

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT_DIR),
                system_prompt={"type": "preset", "preset": "claude_code"},
                allowed_tools=["Read", "Glob", "Grep"],
                permission_mode="acceptEdits",
                max_turns=15,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        answer += block.text
            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0.0
    except Exception as e:
        answer = f"Error querying knowledge base: {e}"

    # Update state
    state = load_state()
    state["query_count"] = state.get("query_count", 0) + 1
    state["total_cost"] = state.get("total_cost", 0.0) + cost
    save_state(state)

    return answer


def main():
    """Entry point for the query CLI.

    Reads the user's question from CLI args, runs the async query, and prints
    the answer. Narrative queries are read-only; use `graphify save-result` to
    persist an answer into the atlas layer.
    """
    parser = argparse.ArgumentParser(description="Query the personal knowledge base")
    parser.add_argument("question", help="The question to ask")
    args = parser.parse_args()

    print(f"Question: {args.question}")
    print("-" * 60)

    answer = asyncio.run(run_query(args.question))
    print(answer)


if __name__ == "__main__":
    main()
