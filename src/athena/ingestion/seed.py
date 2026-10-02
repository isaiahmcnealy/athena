"""A bounded, repeatable catalog expansion plan; no network activity on import."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    name: str
    arxiv: str
    openalex: str


AI = '(all:"machine learning" OR all:"artificial intelligence" OR all:"deep learning")'
TOPICS = (
    Topic("Machine learning", "cat:cs.LG", "machine learning"),
    Topic("Natural language processing", "cat:cs.CL", "natural language processing"),
    Topic("Computer vision", "cat:cs.CV", "computer vision"),
    Topic("Robotics", "cat:cs.RO", "robot learning"),
    Topic("Reinforcement learning", 'all:"reinforcement learning"', "reinforcement learning"),
    Topic("Information retrieval", "cat:cs.IR", "neural information retrieval"),
    Topic("Responsible AI", f"{AI} AND (all:fairness OR all:explainability)", "responsible AI"),
    Topic("AI agents", 'all:"language model" AND all:agent', "large language model agents"),
    Topic("Graph learning", 'all:"graph neural"', "graph neural networks"),
    Topic("Healthcare", f"{AI} AND (all:medical OR all:clinical)", "machine learning healthcare"),
    Topic("Biology and drug discovery", f"{AI} AND (all:protein OR all:drug)", "AI drug discovery"),
    Topic("Finance", f"{AI} AND (all:finance OR all:financial)", "machine learning finance"),
    Topic("Climate", f"{AI} AND (all:climate OR all:weather)", "machine learning climate"),
    Topic("Energy", f"{AI} AND (all:energy OR all:grid)", "machine learning renewable energy"),
    Topic("Agriculture", f"{AI} AND (all:agriculture OR all:crop)", "machine learning agriculture"),
    Topic("Manufacturing", f"{AI} AND all:manufacturing", "machine learning manufacturing"),
    Topic("Education", f"{AI} AND all:education", "artificial intelligence education"),
    Topic("Cybersecurity", f"{AI} AND (all:cybersecurity OR all:intrusion)", "AI cybersecurity"),
    Topic("Transportation", f"{AI} AND (all:traffic OR all:transportation)", "AI transportation"),
    Topic(
        "Scientific computing", f"{AI} AND all:simulation", "machine learning scientific computing"
    ),
    # Append new topics here; inserting earlier would renumber jobs for --start-at.
    Topic(
        "Oil and gas",
        f'{AI} AND (all:petroleum OR all:"oil and gas" OR all:hydrocarbon OR all:drilling)',
        "machine learning oil and gas",
    ),
)


def seed_plan(per_query: int = 125, source: str = "all") -> list[dict]:
    if not 1 <= per_query <= 1000:
        raise ValueError("per_query must be between 1 and 1000")
    if source not in {"all", "arxiv", "openalex"}:
        raise ValueError("Unknown source")
    return [
        {
            "topic": topic.name,
            "source": provider,
            "query": getattr(topic, provider),
            "limit": per_query,
        }
        for topic in TOPICS
        for provider in ("arxiv", "openalex")
        if source in {"all", provider}
    ]
