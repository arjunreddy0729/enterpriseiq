"""Keyword retrieval over PostgreSQL full-text search.

Why keyword search still matters when you have embeddings: an embedding
compresses meaning into 768 floats, and that compression is lossy in one
specific way - it discards rare, exact tokens. `JIRA-4821`, `client_id`,
`X-Cardinal-Signature`, `payments:refund`, a version number, an error code.
Semantically an identifier carries almost no meaning, so the embedding barely
encodes it. Keyword search is the mirror image: IDF weights rare terms *most*
heavily, so identifiers are exactly what it is best at.

The two retrievers fail on disjoint query sets. That is what makes fusing them
worth more than tuning either one.

**On ranking honesty.** This uses `ts_rank_cd`, which is not BM25. It has no
term-frequency saturation curve and normalises document length differently.
The corpus statistics needed for real BM25 are already modelled (term_stats,
corpus_stats) and rescoring the candidate set is a small amount of work - but
until that lands, this is cover-density ranking and is described as such.
What Postgres FTS does give us today, and an in-memory BM25 index would not,
is the ACL predicate evaluated inside the same query plan.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Text, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session

from app.db.models import Chunk
from app.retrieval.filters import build_where
from app.retrieval.types import Candidate, RetrievalQuery, RetrieverKind
from app.retrieval.vector import candidate_columns, row_to_candidate

#: ts_rank_cd normalisation flags, bitwise-ORed:
#:   2  divide rank by document length
#:  32  rank / (rank + 1), squashing into (0, 1)
#: Length normalisation matters because our chunks vary from ~40 to ~700
#: tokens, and without it long chunks win on term count alone.
_RANK_NORMALISATION = 2 | 32

#: A leading hyphen is websearch syntax for "must not contain".
_HAS_NEGATION = re.compile(r"(?:^|\s)-\w")


def build_tsquery(text_query: str) -> Any:
    """Turn a natural-language question into a tsquery worth running.

    `websearch_to_tsquery` is the right parser - it accepts what people
    actually type, handles "quoted phrases" and -negation, and never raises on
    stray punctuation the way `to_tsquery` does. But it joins every term with
    AND, which is wrong for retrieval: "What are the salary bands and bonus
    targets by level?" becomes

        'salari' & 'band' & 'bonus' & 'target' & 'level'

    and demands one chunk containing all five. On this corpus that matches
    nothing at all, so the keyword half of a hybrid search silently
    contributes zero and the system quietly degrades to pure vector search.

    So we keep the parser and swap the operator: the same query ORed matches 56
    chunks, and `ts_rank_cd` sorts out which of them matched more, and rarer,
    terms. Requiring every term is the job of ranking, not of matching.

    Explicit negation is left alone - ORing a NOT term (`a | !b`) would match
    almost the entire corpus, which is worse than the problem being fixed.
    """
    base = func.websearch_to_tsquery("english", text_query)
    if _HAS_NEGATION.search(text_query):
        return base
    # Phrase operators (<->) inside quoted spans survive this untouched.
    return func.cast(func.replace(func.cast(base, Text), "&", "|"), TSQUERY)


class KeywordRetriever:
    """Full-text search with the access predicate inside the query."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def kind(self) -> str:
        return RetrieverKind.KEYWORD

    def search(self, query: RetrievalQuery) -> list[Candidate]:
        if query.sees_nothing or not query.text.strip():
            return []

        tsquery = build_tsquery(query.text)
        rank = func.ts_rank_cd(Chunk.tsv, tsquery, _RANK_NORMALISATION)

        statement = (
            candidate_columns()
            .add_columns(rank.label("rank"))
            .where(build_where(query))
            .where(Chunk.tsv.op("@@")(tsquery))
            .order_by(rank.desc(), Chunk.id)
            .limit(query.limit)
        )

        candidates: list[Candidate] = []
        for position, row in enumerate(self._session.execute(statement), start=1):
            candidate = row_to_candidate(row)
            candidate.keyword_score = float(row.rank)
            candidate.keyword_rank = position
            candidates.append(candidate)
        return candidates

    def explain(self, query: RetrievalQuery) -> dict[str, Any]:
        """What the query parsed to - useful when a search returns nothing."""
        parsed: object = self._session.execute(select(build_tsquery(query.text))).scalar_one()
        return {"tsquery": str(parsed)}
