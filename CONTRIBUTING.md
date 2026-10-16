# Contributing

## Setup

```bash
make setup          # venv + dependencies
cp .env.example .env
make up             # Postgres + API in Docker
make ingest         # load the demo corpus
make check          # lint, typecheck, tests
```

`make` on its own lists every target.

## The one rule that matters here

**Do not claim a number you have not measured.**

The README reports recall, MRR, abstention accuracy, latency and cost. Every
one of them is reproducible from a committed JSON file in
`evaluation/results/`, and the reproduce command is printed next to them. A
plausible-sounding number that nobody ran is worse than no number, because it
cannot be checked and it poisons the ones that are real.

The same applies to performance claims. "Faster" means two measurements of the
same command under stated conditions, not an impression.

If a change is supposed to improve retrieval, run the benchmark before and
after and commit both results:

```bash
make eval                                      # free, no model calls
python -m scripts.compare_eval before.json after.json
```

A change that does not move the metrics is a fine thing to ship — the
cross-encoder reranker is in this repo, measured, and disabled because it cost
55x latency for no gain. Say so rather than hiding it.

## Tests

| | |
|---|---|
| `tests/unit` | no database, fast, run constantly |
| `tests/integration` | real Postgres, real index |
| `tests/security` | the adversarial leak suite |

Integration tests **skip** when the database is down so a fresh clone is green,
but CI sets `REQUIRE_INTEGRATION=1` so they fail instead of skipping. A
security suite that silently skips proves nothing.

A new permission rule needs a test that fails when the rule is removed. If
deleting the behaviour keeps the suite green, the test is decorative — several
in this repo were, and were rewritten.

## Style

`ruff` and `mypy` are enforced in CI and there is nothing to argue about:

```bash
make format
```

Comments should explain *why*, not restate the code. The useful ones in this
repo are the ones recording what went wrong and what it cost — those are the
ones that stop the next person re-making the decision badly.
