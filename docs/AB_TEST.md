# M5 A/B test: does adding retrieved examples help the Ask agent write SQL?

Order of work (times in DEVLOG, 2026-10-14 entry): this file's Question and Design were written first, then arm A
was run, then the Power analysis below was computed from arm A's accuracy and written down, and only then was
arm B run. Results and Decision come last. `uv run --group agent python -m eval.ab --check` recomputes every number
in the Results section from the committed summaries and fails if any differs.

## Question

Does giving `llama3.1:8b` five retrieved example questions with their gold SQL, in the SQL-writing prompt only,
raise the agent's execution accuracy on the fixed eval set compared with today's prompt?

## Power analysis

Written at 2026-10-15 01:31 UTC (2026-10-14 18:31 PDT), after arm A and before arm B was run.
`uv run --group agent python -m eval.ab --power --json` on arm A's summary (`summary-ollama-A-20261015T013021Z.json`):

- **Inputs:** n = 66 in-scope questions; arm A got 18 right, so p_A = 0.2727 (18 A-right, 48 A-wrong). The
  simulated B breaks each A-right question with g = 0.05 and fixes each A-wrong one with probability f, chosen so
  the expected improvement is the target: f = (Δ·66 + 0.05·18) / 48. Power is the share of 10,000 simulations
  (seed 0) in which B is ahead and the exact McNemar p < 0.05, i.e. the decision rule's first two conditions.

| Expected improvement | f (fix rate) | Power |
|---|---|---|
| +5 points | 0.088 | 0.114 |
| +10 points | 0.156 | 0.532 |
| +15 points | 0.225 | 0.856 |
| +20 points | 0.294 | 0.970 |

- **Minimum detectable improvement at 80% power: +14 points** (power 0.804; +13 points gives 0.747). The
  Architect's hand estimate was about +15, so the simulation agrees.
- **What it means:** this test can reliably detect a lift of about 14 points or more (18/66 → about 27/66). A real
  lift of 5 points would be missed nearly 9 times in 10, so a "keep k = 0" result says "no large effect", not "no
  effect". The minimum detectable improvement is under the plan's +25-point bar, so the test is not called
  underpowered for the effect sizes it was designed to find.

## Design (pre-registered, fixed before any arm-B run)

Fixed by the build-loop Architect on 2026-10-14 and copied here as written.

- **Question set:** `eval/questions.yaml`, unchanged (sha256 `45e5a1f238dbfa1363605a6f7c4dfb778be42d29e3437ac69c9e4b79b557277c`):
  66 in-scope gold-SQL questions + 10 refusals. Scoring: `eval/scoring.py`, unchanged (sha256
  `e1323f1b793e6c97916c2d6ba03b9517421a973f6a5124360a88154f4d15ba02`).
- **Model:** local Ollama `llama3.1:8b`, temperature 0. Both arms run in the same session, back to back, and each
  summary records the Ollama version (`GET /api/version`). Arm A is re-run here, not reused from Oct 9.
- **Arm A** is today's prompts. With `examples_k = 0` the prompts are byte-identical to the prompts before this
  change (prompt fingerprint `85a1cbe83b159f665eb9457e5daed9359678ac6f8688de44f4b773071824da56`, checked by
  `accept-ab-arm-a-prompt-unchanged`).
- **Arm B** is arm A plus **5 retrieved examples (question + gold SQL)**, in the SQL-writing prompt only. The route
  and answer prompts are unchanged.
  - **Pool:** the in-scope `route: sql` questions of `eval/questions.yaml` (63), exported to
    `api/agent/examples.json` (id, question, sql, tags) by `python -m eval.examples --write`, with a test that keeps
    it in sync, so the API image has the pool without depending on `eval/`.
  - **Leave-one-out:** when the eval scores question *q*, *q*'s own id is excluded from retrieval. Production (no
    exclusion) uses the whole pool.
  - **Retrieval:** BM25 (k1 = 1.2, b = 0.75) over lower-cased word tokens of the question text, standard library
    only. Ties go to pool order. Deterministic, no network, and it works on Cloud Run with Gemini.
- **Setting:** `Settings.agent_examples_k` (env `TP_AGENT_EXAMPLES_K`), wired through `AgentDeps` and
  `service.get_agent`. Eval CLI: `--arm A|B` (A → k = 0, B → k = 5). Summaries (`--save-summary`) add `arm`,
  `examples_k`, `eval_sha256`, `ollama_version` and `per_question`.
- **Primary outcome:** execution accuracy on the 66 in-scope questions.
  - **Test:** exact two-sided McNemar on the discordant pairs (binomial, p = 0.5), α = 0.05.
  - **Effect:** acc_B − acc_A, with a 95% paired percentile bootstrap over questions (10,000 resamples, seed 0).
- **Power analysis** (before arm B): n = 66 and p_A = arm A's observed accuracy. The simulated B fixes each
  A-wrong question with probability f and breaks each A-right one with g = 0.05. Power for expected improvements
  of +5/+10/+15/+20 points and the minimum detectable improvement at 80% power: 10,000 simulations, seed 0,
  `python -m eval.ab --power`. The Architect's hand estimate of the minimum detectable improvement: about +15
  points.
- **Decision rule.** Ship B, i.e. set the default `agent_examples_k = 5`, **iff** all three hold: McNemar p < 0.05;
  acc_B > acc_A; B's refusal accuracy ≥ 0.9. Otherwise keep k = 0 and say why.
- **Secondary, reported but not part of the decision:** per-tag accuracy, refusal accuracy, errors, in-scope
  refused, latency p50/p95 and the mean SQL-prompt length in characters.

## Results

Both arms ran on 2026-10-15 UTC (2026-10-14 PDT), back to back on Ollama 0.40.4 with `llama3.1:8b`, against the
local DuckDB warehouse: arm A `summary-ollama-A-20261015T013021Z.json` (01:26:42–01:30:24 UTC), arm B
`summary-ollama-B-20261015T013355Z.json` (01:31:20–01:33:57 UTC). Arm A reproduces the earlier runs exactly: each of
the 76 questions has the same correct/wrong outcome as in all 8 local llama3.1:8b runs of Oct 9–10, as temperature 0
should.

| | Arm A (no examples) | Arm B (5 retrieved examples) |
|---|---|---|
| Execution accuracy (66 in-scope) | 18/66 = 0.2727 | 33/66 = 0.5000 |
| Refusal accuracy (10 off-topic) | 10/10 | 10/10 |
| Errors (a query failed twice) | 11 | 7 |
| In-scope questions refused | 7 | 7 |
| Guardrail rejections | 0 | 0 |
| Latency p50 / p95 | 2.46 s / 6.71 s | 1.74 s / 4.71 s |
| Mean SQL-prompt length | 3,423 characters | 4,595 characters |

Per tag (in-scope questions; k11 counts as both kpi and station):

| Tag | n | Arm A | Arm B |
|---|---|---|---|
| kpi | 15 | 0.27 | 0.53 |
| station | 17 | 0.47 | 0.47 |
| trend | 15 | 0.07 | 0.40 |
| bikes | 11 | 0.18 | 0.36 |
| od | 6 | 0.00 | 0.67 |
| forecast | 6 | 0.50 | 0.50 |

**Paired test.** Discordant pairs: b = 5 (A right, B wrong: s02, s04, s13, s14, t07) and c = 20 (A wrong, B right:
k04, k05, k06, k15, s01, s03, s05, s06, t01, t04, t05, t06, t09, t11, b03, b10, o01, o03, o04, o05).
McNemar exact p = 0.00408 (two-sided).
Effect: acc_B - acc_A = +0.2273, 95% paired bootstrap CI [+0.0909, +0.3636] (10,000 resamples, seed 0).

`uv run --group agent python -m eval.ab --json` prints these numbers; `--check` fails if any line above disagrees
with them.

## Decision

**Ship B: the default `agent_examples_k` is now 5.** All three pre-registered conditions hold:
1. McNemar p = 0.00408 < 0.05;
2. acc_B (0.5000) > acc_A (0.2727);
3. B's refusal accuracy is 1.0 ≥ 0.9.

- **Size of the effect.** +22.7 points (18 → 33 of 66), with a CI of +9.1 to +36.4 points. The lower end is below
  the +14-point minimum detectable improvement, so the precise size is uncertain; the direction is not.
- **Cost.** B's SQL prompt is about 1,170 characters (34%) longer. It is not slower: p50 fell from 2.5 s to 1.7 s
  and p95 from 6.7 s to 4.7 s, probably because fewer queries failed (errors 11 → 7); attempts per question are
  not recorded. So the plan's "B's p95 > 2× A's" cost flag does not apply.
- **Where it helped.** Trend (+5 questions), OD flows (+4) and KPI (+4) questions, the ones that need a specific
  mart or join. Station questions are flat: B fixed 4 and broke 4.
- **What ships.** Production retrieves from the whole pool (no exclusion), so the API image carries
  `api/agent/examples.json`. Set `TP_AGENT_EXAMPLES_K=0` to go back to arm A without a code change.

## Limitations

- **Near-twin questions.** With leave-one-out, near-twin questions (e.g. a "most" and a "fewest" day) give B easy
  neighbours, so the lift is an upper-ish estimate for questions unlike any in the pool.
- **Near-twins in practice.** For 8 of the 20 questions B fixed (k05, k06, s05, t04, t05, t06, b03, o05), the top
  retrieved example is the same question with a word or two changed (most/fewest, highest/lowest, average/total,
  each year/lowest year, e-bikes/members, one station pair for another). A visitor's question that resembles nothing in the pool will
  gain less.
- **Production uses Gemini, not llama3.1.** The live agent (when the owner turns it on) runs `gemini-2.5-flash`, a
  much stronger model, for which the lift may be smaller. The optional Gemini A/B with the owner's key is in
  `docs/OWNER_STEPS.md`.
- **One model, one run per arm.** Temperature 0 makes each arm deterministic on this Ollama version (arm A matched
  the Oct 9 run exactly), so re-running adds no information; a different Ollama or model build can move both arms.
- **The eval set doubles as the pool.** The 63 pool questions are the eval's own in-scope `sql` questions, so the
  test measures leave-one-out retrieval from a pool written by the same author in the same style.

## Arm C (M6, not run)

The QLoRA fine-tune (M6) is deferred to its own build loop (see `docs/OWNER_STEPS.md`, "start M6"). The harness is
ready for it: arm C adds `"C": 0` (examples off) to `ARMS` in `eval/run_eval.py`, then
`TP_OLLAMA_MODEL=<name> uv run --group agent python -m eval.run_eval --llm ollama --arm C --save-summary`, and
`eval.ab.compare` pairs that summary with arm A's (or B's) by question id with the same McNemar and bootstrap code.
