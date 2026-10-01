"""Grounding verification: is each claim actually supported by its source?

Citation validation proves a citation points at a real passage. It does not
prove the passage says what the sentence claims. A model can cite [2]
correctly and still describe [2] wrongly, and that failure is invisible to
every check upstream of this one.

So each sentence is scored against the passages it cites, using two signals
that fail differently:

* **Lexical overlap** catches the numbers and identifiers that matter most in
  enterprise answers - "$85", "3600 seconds", "L5". An embedding will happily
  call "$85 per day" and "$75 per day" near-identical; token overlap will not.
* **Embedding similarity** catches faithful paraphrase, which lexical overlap
  scores near zero.

The two are combined by taking the max: a sentence is supported if *either*
signal says so, because each is a valid way for a claim to be grounded.

This runs locally in single-digit milliseconds and costs nothing. It is not
an entailment model - it cannot detect a sentence that reuses the passage's
vocabulary to state the opposite ("the cap is NOT $85"). Catching that needs
an NLI model or a second model call, which belongs in the offline evaluation
harness where latency does not matter, not in the request path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from app.core.config import get_settings
from app.generation.citations import extract_numbers, split_sentences
from app.generation.context import ContextBundle
from app.retrieval.ports import Embedder

_WORD = re.compile(r"[a-z0-9$%.:/-]+")

#: Words too common to be evidence of anything.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
        "which",
        "this",
        "these",
        "those",
        "they",
        "their",
        "our",
        "we",
        "you",
        "your",
        "not",
        "but",
        "if",
        "then",
        "than",
        "can",
        "may",
        "must",
        "should",
        "would",
        "could",
        "into",
        "over",
        "under",
    ]
)


@dataclass(slots=True)
class SentenceVerdict:
    sentence: str
    cited: list[int]
    support: float
    supported: bool


@dataclass(slots=True)
class GroundingReport:
    score: float
    supported: int
    total_claims: int
    verdicts: list[SentenceVerdict] = field(default_factory=list)
    passed: bool = False

    @property
    def unsupported_sentences(self) -> list[str]:
        return [v.sentence for v in self.verdicts if not v.supported]

    def to_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 3),
            "supported": self.supported,
            "total_claims": self.total_claims,
            "passed": self.passed,
            "unsupported": self.unsupported_sentences,
        }


#: Weighting of the two signals. Lexical dominates deliberately - see verify().
_LEXICAL_WEIGHT = 0.65
_SEMANTIC_WEIGHT = 0.35


def _content_words(text: str) -> set[str]:
    words = set()
    for raw in _WORD.findall(text.lower()):
        # Strip trailing/leading punctuation the character class swept up, or
        # "day." and "day," compare as different words and every sentence that
        # ends on a shared term loses the match.
        word = raw.strip(".,:;/-")
        if word and word not in _STOPWORDS and len(word) > 2:
            words.add(word)
    return words


def lexical_support(sentence: str, passage: str) -> float:
    """Fraction of the sentence's content words that appear in the passage."""
    claim = _content_words(sentence)
    if not claim:
        return 0.0
    return len(claim & _content_words(passage)) / len(claim)


def verify(
    answer: str,
    bundle: ContextBundle,
    embedder: Embedder | None = None,
) -> GroundingReport:
    """Score every claim sentence against the passages it cites."""
    settings = get_settings()
    sentences = [s for s in split_sentences(answer) if len(s.split()) >= 6]

    if not sentences:
        # Nothing claimed, nothing to falsify.
        return GroundingReport(score=1.0, supported=0, total_claims=0, passed=True)

    verdicts: list[SentenceVerdict] = []

    # Embed once for the whole answer rather than per sentence-passage pair.
    embeddings: dict[str, np.ndarray] = {}
    if embedder is not None:
        texts = sentences + [b.candidate.content for b in bundle.blocks]
        try:
            vectors = embedder.embed_documents(texts)
            embeddings = dict(zip(texts, vectors, strict=True))
        except Exception:  # embedding is an optimisation, not a requirement
            embeddings = {}

    for sentence in sentences:
        cited = [n for n in extract_numbers(sentence) if n in bundle.valid_numbers]
        # An uncited claim is scored against every passage: the model may have
        # simply forgotten the marker on a sentence that is perfectly grounded,
        # and penalising that would punish formatting rather than accuracy.
        targets = cited or sorted(bundle.valid_numbers)

        best = 0.0
        for number in targets:
            candidate = bundle.candidate_for(number)
            if candidate is None:
                continue
            passage = candidate.content
            lexical = lexical_support(sentence, passage)

            # Weighted blend, NOT max(). Taking the max lets semantic
            # similarity alone carry a sentence, and semantic similarity
            # cannot tell a faithful paraphrase from a plausible invention on
            # the same topic - "authentication uses biometric retina scanning"
            # sits close to a genuine passage about authentication. What
            # separates them is whether the sentence's specific terms actually
            # appear in the source, which is exactly what lexical overlap
            # measures. So semantics can lift a paraphrase over the line, but
            # it cannot rescue a sentence whose content words are absent.
            score = lexical
            if sentence in embeddings and passage in embeddings:
                cosine = float(np.dot(embeddings[sentence], embeddings[passage]))
                score = _LEXICAL_WEIGHT * lexical + _SEMANTIC_WEIGHT * max(cosine, 0.0)

            best = max(best, score)

        verdicts.append(
            SentenceVerdict(
                sentence=sentence,
                cited=cited,
                support=round(best, 3),
                supported=best >= settings.grounding_support_threshold,
            )
        )

    supported = sum(1 for v in verdicts if v.supported)
    score = supported / len(verdicts)

    return GroundingReport(
        score=score,
        supported=supported,
        total_claims=len(verdicts),
        verdicts=verdicts,
        passed=score >= settings.grounding_pass_threshold,
    )
