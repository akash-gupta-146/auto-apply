"""How alike two questions are, with no AI: the words they share, where a word few of your questions use counts for more.

Used to choose which of your saved answers are worth showing an AI (there may be more than fit), and which saved questions are
worth asking it about (so it is never sent seventy lines to find one pair).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import List, Sequence

STOPWORDS = frozenset("the you your are what how will for this that with have any please enter which would does can and from "
                      "been such their them they our not but all who was were into per in of to or is do an at on be it as by if "
                      "we my me us".split())


def words(text: str) -> set:
    """The words that carry a question's meaning: lower-cased, plurals folded, small filler words dropped."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w
            for w in re.findall(r"[a-z0-9+#.]{2,}", text.lower()) if w not in STOPWORDS}


def similarity(question: str, wordings: Sequence[str]) -> List[float]:
    """One score per wording: 0 shares nothing with the question; more shared and rarer words score higher."""
    asked = words(question)
    uses = Counter(word for wording in wordings for word in words(wording))
    return [sum(math.log(1 + len(wordings) / uses[word]) for word in words(wording) & asked) for wording in wordings]


def nearest(question: str, wordings: Sequence[str], count: int) -> List[str]:
    """The `count` wordings most like the question, best first. A wording that shares nothing with it is never included."""
    scores = similarity(question, wordings)
    ranked = sorted((i for i, score in enumerate(scores) if score > 0), key=lambda i: (-scores[i], i))
    return [wordings[i] for i in ranked[:count]]
