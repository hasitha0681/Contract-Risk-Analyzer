"""Q&A over AtliQ's contracts (FR-32 to FR-35).

Retrieval runs across all four collections; the answer must come from that
context and cite [file, section]. Requests for legal advice, for signing or
sending a contract, and off-topic requests are refused. The clear-cut cases
are caught in code before any LLM call, so the refusal does not depend on the
model; the model handles anything subtler under the same rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

import config
import llm
import prompts

NOT_FOUND = "I could not find that in AtliQ's contracts or notes."

REFUSALS = [
    (
        "legal_advice",
        re.compile(r"\benforceab|\bis (this|it|that|the \w+) (legal|lawful|valid)\b|\blegal advice\b|\bhold up in court\b|\b(valid|void) under\b|\blawful\b|\bcan (they|we) sue\b|\bwill (we|i) win\b", re.IGNORECASE),
        "I can't give legal advice or opinions on enforceability. Please ask outside counsel "
        "(Mehta Rao & Associates in India, or Calloway Stern LLP in the US).",
    ),
    (
        "sign_or_send",
        re.compile(r"^\s*(please\s+)?(sign|approve|send|e-?mail|execute|countersign|submit)\b|\b(can|could|will) you (please )?(sign|approve|send|e-?mail|execute|countersign)\b|\b(sign|approve|send)\b.*\bfor me\b", re.IGNORECASE),
        "I can't sign, approve or send contracts. Only the CEO signs; you can review the "
        "contract in the 'Review a contract' tab and record your decision there.",
    ),
    (
        "off_topic",
        re.compile(r"\b(plan|book|organi[sz]e)\b.*\b(trip|holiday|vacation|itinerary)\b|\bitinerary\b|\brecipe\b|\bweather\b|\bwrite (me )?a (poem|story|song)\b", re.IGNORECASE),
        "That's outside the scope of AtliQ's contracts. Ask me about AtliQ's contracts, "
        "negotiations, principles or commitments.",
    ),
]


def refusal_for(question: str) -> tuple[str, str] | None:
    for kind, pattern, message in REFUSALS:
        if pattern.search(question):
            return kind, message
    return None


@dataclass
class Answer:
    text: str
    sources: list[str] = field(default_factory=list)
    refused: str | None = None


def retrieve(question: str) -> tuple[str, list[str]]:
    from ingest import get_store

    blocks, sources = [], []
    for name in config.COLLECTIONS:
        for doc in get_store(name).similarity_search(question, k=config.TOP_K):
            label = f"{doc.metadata.get('source_file', '?')}, {doc.metadata.get('section', '')}".strip(", ")
            blocks.append(f"[{label}]\n{doc.page_content}")
            if label not in sources:
                sources.append(label)
    return "\n\n".join(blocks), sources


def to_messages(history: list[dict[str, str]]) -> list[BaseMessage]:
    recent = history[-2 * config.QA_HISTORY_EXCHANGES :]
    return [AIMessage(m["content"]) if m["role"] == "assistant" else HumanMessage(m["content"]) for m in recent]


def ask(question: str, history: list[dict[str, str]] | None = None, on_wait=None) -> Answer:
    refusal = refusal_for(question)
    if refusal:
        return Answer(text=refusal[1], refused=refusal[0])

    context, sources = retrieve(question)
    text = llm.invoke(
        prompts.QA_SYSTEM.format(context=context),
        question,
        config.MAX_TOKENS_QA,
        history=to_messages(history or []),
        on_wait=on_wait,
    ).strip()
    if NOT_FOUND.lower() in text.lower():
        return Answer(text=NOT_FOUND)
    # Show only the sources the answer actually cites, when it cites any.
    cited = [s for s in sources if s.split(",")[0] in text]
    return Answer(text=text, sources=cited or sources)
