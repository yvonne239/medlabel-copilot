"""Small standard-library adapter for the notebook's TF-IDF baseline."""
from collections import Counter
import csv
from dataclasses import asdict, dataclass
from io import StringIO
import json
from math import sqrt
import re

INDEX = json.loads(MATCHER_JSON)
SYMPTOMS = tuple(INDEX["symptoms"])
OUTSIDE = "outside catalog"
STOP_WORDS = frozenset(INDEX["stop_words"])


def normalize(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def suggest_symptom(text):
    exact = normalize(text)
    if exact in SYMPTOMS:
        return exact
    terms = [word for word in re.findall(r"\b\w\w+\b", text.lower()) if word not in STOP_WORDS]
    bigrams = [f"{left} {right}" for left, right in zip(terms, terms[1:])]
    query = {
        term: count * INDEX["idf"][term]
        for term, count in Counter(terms + bigrams).items() if term in INDEX["idf"]
    }
    norm = sqrt(sum(weight * weight for weight in query.values()))
    if not norm:
        return OUTSIDE
    scores = [
        sum(weight * doc.get(term, 0) for term, weight in query.items()) / norm
        for doc in INDEX["docs"]
    ]
    best = max(range(len(scores)), key=scores.__getitem__)
    return SYMPTOMS[best] if scores[best] >= INDEX["threshold"] else OUTSIDE
