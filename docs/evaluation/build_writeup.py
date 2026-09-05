"""Build docs/evaluation/PILOT_EVALUATION.html from pilot_eval.json and cost_table.json.

Tables come from the two JSON files; the prose is written here. Rerun after
`python -m reproscope.evaluate` and `docs/evaluation/cost_table.py`:
    .venv/bin/python docs/evaluation/build_writeup.py
"""
from __future__ import annotations

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = json.loads((HERE / "pilot_eval.json").read_text())
COST = json.loads((HERE / "cost_table.json").read_text())

SHORT = {
    "Ohtsubo_EvoHumanBehavior_2014_zlm2": "Ohtsubo",
    "Hurst_EvoHumanBehavior_2017_yypJ": "Hurst",
    "Axt_JournExpSocPsych_2018_zK2": "Axt",
    "Petersen_Cognition_2017_yJwG": "Petersen",
    "Hertel_ClinPsychSci_2018_YabW": "Hertel",
}
ORDER = list(SHORT)
FAMILY_ORDER = ["opus", "fable", "sol", "luna", "glm", "deepseek"]
FAMILY_ROUTE = {"opus": "Claude Opus (claude -p)", "fable": "Claude Fable (claude -p)",
                "sol": "GPT-5.6 Sol (codex)", "luna": "GPT-5.6 Luna (codex)",
                "glm": "GLM-5.3-flash (opencode)", "deepseek": "DeepSeek-v4-flash (opencode)"}


def pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def num(x, d=2):
    return "n/a" if x is None else f"{x:.{d}f}"


def esc(s):
    return html.escape(str(s))


def table(headers, rows, cls=""):
    h = "".join(f"<th>{esc(c)}</th>" for c in headers)
    b = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


# --- data views -------------------------------------------------------------

def family_rows(entries):
    rows = []
    for e in sorted(entries, key=lambda e: FAMILY_ORDER.index(e["label"]) if e["label"] in FAMILY_ORDER else 99):
        m = e["match"]["all"]
        hl = e["match"]["headline"]
        fo = e["match"]["focal"]
        rows.append([
            esc(e["label"]), e["launched"], e["ran"], e["failed"],
            m["n"], m["n_abstained"], pct(m["share_a"]), pct(m["share_ab"]),
            pct(hl["share_ab"]), pct(fo["share_ab"]),
        ])
    return rows


FAMILY_HEAD = ["family", "launched", "ran", "failed", "pairs", "abstained", "A", "A+B", "headline A+B", "focal A+B"]

per_paper = {p["paper_id"]: p for p in EVAL["per_paper"]}

# --- sections ---------------------------------------------------------------

def sec_summary():
    fam = {e["label"]: e for e in EVAL["families"]}
    tiers = {e["label"]: e for e in EVAL["tiers"]}
    fr, ch = tiers["frontier"]["match"]["all"], tiers["cheap"]["match"]["all"]
    return f"""
<h2 id="summary">Summary</h2>
<p>Five Multi100 psychology papers went through the full pipeline: claim extraction and blinding (Stage 0),
blind reproduction by ten replica agents per paper (Stage 1), an analysis review scoped to the focal claim
(Stage 2) and a specification curve on the focal claim (Stage 3). Stage 0 and the replica agent runs are the
ones from the 2026-09-02 pilot; matching, the targeted arm, the reviews, the multiverse and the reports were
rebuilt on 2026-09-03 with the efficiency and correctness fixes listed in <a href="#bugs">Correctness bugs</a>.</p>
<ul>
<li><b>Reproduction.</b> Over every scored claim × replica pair, frontier families reach band A on {pct(fr["share_a"])}
and A or B on {pct(fr["share_ab"])}; the cheap families reach {pct(ch["share_a"])} and {pct(ch["share_ab"])}.
On the focal claim alone, every family is at or above {min(pct(e["match"]["focal"]["share_ab"]) for e in EVAL["families"])} A+B.</li>
<li><b>Cheap versus frontier.</b> Where a paper's numbers are reachable from the deposited data, GLM and DeepSeek land
on the same values as Opus and Fable. The Claude families are the only ones with no hard-coded
result in the audit (GLM, DeepSeek, Luna and Sol have two or three each), and DeepSeek is the only family whose scripts
failed re-execution (two, both importing scipy); the numbers reproduced do not separate the tiers.</li>
<li><b>Two papers carry a real finding.</b> Ohtsubo's reported statistics need one participant excluded whom the
deposited workbook does not mark; the targeted arm recovers all seven reported quantities by identifying the record.
Hurst's Mini-K correlation table contains cells that no defensible specification reproduces, and one that is
arithmetically inconsistent with the subscale values printed beside it (this finding came from a targeted run under
the old, broader trigger; it is kept under <code>runs/logs/superseded/</code>).</li>
<li><b>Cost.</b> A single clean pass of Stages 1 to 3 on the rebuilt code costs USD {min(p["rerun_single_pass"]["cash"] for p in COST["papers"].values()):.2f}–{max(p["rerun_single_pass"]["cash"] for p in COST["papers"].values()):.2f}
metered and {min(p["rerun_single_pass"]["equiv"] for p in COST["papers"].values()):.1f}–{max(p["rerun_single_pass"]["equiv"] for p in COST["papers"].values()):.1f} list-equivalent per paper on top of the replica runs,
against {min(p["before"]["total"]["equiv"] for p in COST["papers"].values()):.0f}–{max(p["before"]["total"]["equiv"] for p in COST["papers"].values()):.0f} list-equivalent per paper in the pilot as run. See <a href="#cost">Cost</a>.</li>
</ul>
"""


def sec_lineup():
    rows = [[esc(f), esc(FAMILY_ROUTE[f]), "2, kept on disk (lineup: 1)" if f == "opus" else "1, kept on disk (lineup: dropped)" if f == "sol" else "2" if f in ("luna", "glm", "deepseek") else "1"] for f in FAMILY_ORDER]
    return f"""
<h2 id="lineup">Corpus and lineup</h2>
<p>The corpus is the five papers set up in <code>docs/PILOT_NOTES.md</code>: Ohtsubo (independent-samples t, n = 29),
Hurst (partial correlations, n = 138), Axt (t on IAT D-scores, n = 856), Petersen (paired t on TVA parameters, n = 28)
and Hertel (2×2 mixed ANOVA, n = 54). Each manifest fixes the Multi100 focal claim and, for Axt, the claim id.</p>
<p>Replicas ran once, on 2026-09-02, with the calibration lineup below. The comparison tables use every replica that
has a trace on disk, so sol and the second Opus run are still counted even though the development lineup in
<code>models.toml</code> is opus×1, fable×1, luna×2, glm×2, deepseek×2.</p>
{table(["family", "model (route)", "runs per paper"], rows)}
"""


def sec_families():
    return f"""
<h2 id="families">Reproduction by family</h2>
<p>Match shares are over every claim × replica pair Stage 1 scored, restricted to replicas whose script re-executed.
A pair is <em>abstained</em> when the replica wrote no value for the claim or the link step failed; abstained pairs are
outside every denominator. Bands: A relative difference under 2%, B under 20%, C under 40%, fail otherwise, with
quantity-specific rules for p-values, ratios and sample sizes (<code>docs/PILOT_DESIGN.md</code>, Matching rules).</p>
{table(FAMILY_HEAD, family_rows(EVAL["families"]) + family_rows(EVAL["tiers"]))}
<p>The last two rows pool every replica in a tier (frontier = the subscription routes, cheap = opencode via OpenRouter).
Luna's lower A share comes almost entirely from Hurst, where it disagreed with the other families on the correlation
table's supporting cells; on the focal claims it matches the others.</p>
"""


def paper_block(pid):
    p = per_paper[pid]
    foc = p.get("focal") or {}
    fq = foc.get("quantity") or {}
    vals = foc.get("values") or {}
    fam_means = foc.get("family_means") or {}
    tg = p.get("targeted") or {}
    m100 = p.get("multi100") or {}
    rows = family_rows(p["families"])
    focal_line = ""
    if fq:
        vlist = ", ".join(f"{esc(k)} {num(v, 3)}" for k, v in sorted(vals.items()))
        focal_line = (f"<p><b>Focal quantity</b> {esc(fq.get('kind'))} = {num(fq.get('reported_value'), 3)} "
                      f"(claim {esc(fq.get('claim_id'))}). Replicas: {vlist or 'none'}.</p>")
    m100_line = ""
    if m100.get("analyst_d"):
        d = m100["analyst_d"]
        m100_line = (f"<p><b>Multi100 analysts</b> (n = {m100.get('n_analysts')}): d from {num(d.get('min'), 2)} "
                     f"to {num(d.get('max'), 2)}, median {num(d.get('median'), 2)}.</p>")
    tg_line = ""
    if tg:
        tg_line = (f"<p><b>Targeted reconstruction</b> {esc(tg.get('outcome'))}"
                   + (f": {esc((tg.get('notes') or '')[:600])}" if tg.get("triggered") else "") + "</p>")
    return f"""
<h3 id="paper-{SHORT[pid].lower()}">{SHORT[pid]} <small>{esc(pid)}</small></h3>
<p>Claims scored: {p.get('n_claims_scored')}. Decision agreement across replicas: {num(p.get('decision_agreement_mean'), 2)};
median numeric CV: {num(p.get('numeric_cv_median'), 3)}.</p>
{table(FAMILY_HEAD, rows)}
{focal_line}{m100_line}{tg_line}
"""


def sec_papers():
    return "<h2 id=\"papers\">Match tables per paper</h2>" + "".join(paper_block(pid) for pid in ORDER)


def sec_cases():
    return """
<h2 id="cases">Cases</h2>

<h3>Ohtsubo: the unmarked exclusion</h3>
<p>Eight of nine replicas computed exactly the same numbers: t(28) = 6.20 and d = 2.26 against the reported t(27) = 5.91
and d = 2.20 (band B). The deposited sheet holds 30 rows; the Method excludes one participant for suspecting deception,
and no column marks that participant. The blind analysts had every modelling choice right and could not
operationalise the exclusion. The targeted arm, given the reported values, narrowed the candidates to two
interchangeable records from the reported sample description and reached all seven reported quantities exactly.
Outcome: <em>reachable</em>, with one added choice (which record is excluded). The Stage 2 review flags the same gap
as its first major finding. Stage 3 lists the exclusion as unimplementable with the deposited data and varies what it can
(pooled versus Welch t, two d formulas, sex as a covariate): six specifications with d from 2.21 to 2.26, all significant,
the paper's 2.20 at rank 1.</p>

<h3>Hurst: cells no specification reaches</h3>
<p>The focal partial correlation r = −.51 reproduces exactly in every family. Under the broader trigger in use when
Hurst first ran, the targeted arm nevertheless fired (a neighbouring cell in the same sentence missed) and spent
eight attempts on the correlation table. It reproduced 22 of the 30 cells exactly and found five that no defensible
route reaches. One of them fails an arithmetic identity: total attachment is the sum of three subscales, so the
reported Mini-K total (−.42) is consistent with the computed subscales, not with the subscales printed next to it,
and the odd cell (−.39) is the value printed one row above it. That is a plausible transcription error in the paper's
table. The rerun under the corrected trigger records <em>not triggered</em>; the earlier output is kept under
<code>runs/logs/superseded/</code>.</p>

<h3>Petersen: a multiverse with nothing to vary</h3>
<p>The supplied data are first-stage output: per-participant TVA parameter estimates. The focal paired t on those
columns reproduces to six decimals in every replica. Every factor that could move the estimate belongs to the model fit
the data have already absorbed; the enumerator lists six of them as unimplementable (non-report trial coding, estimator
bounds and start values, session pooling, the variance-explained definition, first-stage uncertainty). What remains
executable is one inference branch, Bonferroni across the three parameter tests, so the curve has two specifications
with the identical estimate, both significant. Reporting-only choices (the sign convention of the paired difference,
the dz formula) are pinned to one level; executed as factors they had mirrored the estimate and halved the
"same sign" share for no analytical reason.</p>

<h3>Axt and Hertel: where families differ</h3>
<p>On Axt every replica, cheap or frontier, produced the same profile. Eight claims had failed for every replica under
the first matching rule: one analysis reported with the opposite sign convention (t = 25.19 and 9.01 for good- versus
bad-focal D scores, reproduced as −25.19 and −9.01) and its confidence-interval bounds. The matcher now grades a
reversed two-group contrast on the flipped value and mirrors its bounds, and marks the row "sign flipped"; seven of
the eight are band A. The eighth, the printed upper bound of .93 in "d = .45 [.42, .93]", stays failed under every
rule: the interval is inconsistent with its own d, whose mirrored upper bound is about .49.</p>
<p>On Hertel the focal F(1, 48) = 6.20 reproduces in all ten replicas. Differences sit in the supporting claims:
Opus and GLM's first run are at 100% band A, most others at 83–92%, and GLM's second run at 73%: its model for the
cue-type analysis diverged (F = 8.6 against the reported 24.9, with the matching p and partial eta-squared), while its
focal analysis and the rest of the table matched. The two replicas the isolation-path bug had marked as failed
(one Opus, one DeepSeek) re-execute cleanly once the checker runs the script inside the isolation copy the agent wrote
it for.</p>
"""


def sec_cost():
    rows = []
    for pid in ORDER:
        p = COST["papers"][pid]
        b, sp, l, c = p["before"]["total"], p["rerun_single_pass"], p["lineup_replica_runs"], p["clean_v01_stages123"]
        rows.append([SHORT[pid], f"{b['cash']:.2f}", f"{b['equiv']:.1f}", f"{sp['cash']:.2f}", f"{sp['equiv']:.1f}",
                     f"{l['cash']:.2f}", f"{l['equiv']:.1f}", f"{c['cash']:.2f}", f"{c['equiv']:.1f}"])
    return f"""
<h2 id="cost">Cost per paper before and after the fixes</h2>
<p>USD, from <code>runs/&lt;paper&gt;/ledger.jsonl</code>. <em>Metered</em> is OpenRouter spend; <em>list-equivalent</em>
is what the subscription calls (Claude, Codex) would cost at API list price, as reported by the CLI for Claude and
from a placeholder shadow price of USD 2.5 per million tokens for Codex. <em>Pilot as run</em> is every call before the
rebuild, including retries and the repair cascade the audit describes. <em>Single pass</em> is the last successful call
per step of the rebuilt Stages 1 to 3 (matching, targeted arm, review, multiverse, report), which excludes the repeats
caused by Opus overload retries and by trace changes during the rebuild. <em>Replica runs</em> are the eight-replica
development lineup's agent runs from the pilot ledger. Stage 0 was not rerun; its post-fix cost is projected below.</p>
{table(["paper", "pilot as run: metered", "list-equiv", "single pass S1–3: metered", "list-equiv", "replica runs: metered", "list-equiv", "clean S1–3 total: metered", "list-equiv"], rows)}
<p><b>Stage 0, measured on one paper.</b> Stage 0 was rerun on a copy of Hertel under a fixture id (rerunning it in
place would renumber the claim ids the replica outputs are keyed by). One clean pass: 22 calls, USD 0.06 metered and 2.29
list-equivalent (pilot: USD 14 list-equivalent per paper). Arbitration merged 82 of the 97 and 89 extracted entries
deterministically and sent the 3 conflicts and 16 singletons in one cheap vision batch, with no strong call; the combined
contracts-plus-methods call was one Opus call of USD 1.61; readiness on Sonnet USD 0.68; one cheap leak repair; the scan
was clean and the focal F = 6.20 bound by number. The pass produced 101 claims (pilot: 105) and 27 contracts (pilot: 12),
of which readiness could bind 11 to the data (pilot: 3). Extraction runs without the reasoning cap: GLM answers a capped
structured call with reasoning only and no content.</p>
<p><b>Where the remaining list-equivalent goes.</b> The Stage 2 broad review is the largest single strong call
(about USD 1.2–1.9 list-equivalent), then the targeted arm when it triggers (USD 1–3), the diagnosis fallback when the
arm does not run (USD 0.2–0.4), and the Stage 3 interpretation (USD 0.2). Every other step is on the cheap tier or
deterministic. Expected total for a clean v0.1 run of a paper like Hertel: about USD 0.4 metered and 8 list-equivalent,
of which the replica agent runs are USD 0.27 and 3.4.</p>
"""


def sec_bugs():
    return """
<h2 id="bugs">Correctness bugs found and fixed</h2>
<ul>
<li><b>Stage 2 reviewed the wrong claim on Axt and Hurst.</b> Its focal lookup matched the manifest value by string
equality and fell back to the first claim. All stages now bind the focal claim through one shared function that honours the
manifest's claim id.</li>
<li><b>A failed link call, or a replica that omitted a claim, was graded as a failed replication.</b> Both are now abstained
rows outside every denominator.</li>
<li><b>Stale artifacts were blessed as current.</b> A prompt edit cleared the stage marker, the steps reused their old
outputs, and a fresh marker was written. Every step now records the content hashes of its inputs and its prompt versions
and rebuilds when either changed; stage markers hash analytical payloads, not files with timestamps.</li>
<li><b>A crashed targeted agent was recorded as "not reachable".</b> An absent or invalid outcome is now <em>abstained</em>;
<em>not reachable</em> is only ever the agent's own verdict.</li>
<li><b>The targeted arm triggered on every claim sharing a number with the focal sentence.</b> Petersen (15 such claims)
and Hurst (6) triggered although their focal quantity reproduced exactly. It now triggers on the focal quantity alone.</li>
<li><b>Seven replicas were marked failed by the re-execution harness, not by their scripts.</b> Scripts that hard-code the
isolation path, or read data relative to their own directory, failed when re-run elsewhere. The checker re-executes in the
isolation copy and retries from the script's directory; five of the seven now pass. The remaining two (DeepSeek on Petersen)
import scipy, which the re-execution interpreter lacks: an environment finding, since replicas run without a pinned image.</li>
<li><b>Stage 1 could never close on a paper with one genuinely failed replica</b>, and deleting a trace did not reopen it.
A replica counts as run once it has a trace; a lineup replica without one reopens the stage.</li>
<li><b>Token accounting was a lower bound.</b> Retries were not ledgered, opencode cache reads were dropped (10–18×
understated), Codex calls carried no price. Every attempt is now a ledger row, cache tokens count, and Codex has a
configurable shadow price.</li>
<li><b>Focal binding misread leading-decimal numbers</b> (".42" as 42) and comparator strings ("&lt; .001").</li>
<li><b>A DeepSeek script that needed scipy failed re-execution in the checker's own interpreter.</b> Replicas now declare
packages beyond the base stack in <code>out/requirements.txt</code> or <code>out/r_packages.txt</code>; the checker builds a
per-replica environment from the declaration and records an install failure as an environment abstention, not a script
failure.</li>
</ul>
"""


def sec_limits():
    return """
<h2 id="limits">What the pilot cannot yet say</h2>
<ul>
<li><b>The leak audit does not discriminate.</b> The deterministic scan is clean on all five papers under the rule as it
stands (inferential kinds, headline claims, and every numeric claim of an analysis that carries either, with
significant-digit thresholds), but the model-based audit rates leakage "strong" on every paper for structural reasons: the
claim inventory itself reveals which analyses carry p-values. The widened rule ran clean on the fresh Stage 0 pass on Hertel.</li>
<li><b>MDE covers three designs</b> (two-group, paired, correlation) and abstains on the rest; on Hertel and Hurst it abstains.</li>
<li><b>Stage 3 abstains when nothing can move the estimate or its significance.</b> The enumerator lists factors it cannot
implement with the supplied data, the screen marks each level as affecting the estimate, the inference or only reporting,
and a grid with no defensible level in the first two classes is recorded as an abstention with those lists instead of an
executed point mass (Petersen).</li>
<li><b>Opus availability.</b> During the rebuild, Claude Opus returned "529 Overloaded" on 15 strong-call attempts (each after
about 200 s); a retry runner completed them in later passes. An early-failing agentic call is now retried once, but a strong-tier
outage still stalls the targeted arm, the broad review and the interpretation.</li>
<li><b>Stage 3 interpretation receives the rank statistics</b> alongside specs.csv, which the design describes as a
specs-only prompt. Left as is; flagged for a decision.</li>
<li><b>The OpenRouter reasoning cap is unusable with GLM-5.3-flash.</b> Every capped structured call returned reasoning
tokens and no content after about 900 s; the cap is opt-in and no step uses it. The pilot's per-claim link calls, which
motivated it, are gone.</li>
<li><b>Codex list-equivalents use the input list price</b> (Sol USD 4, Luna USD 0.20 per million tokens) because Codex
reports one token total per call; output tokens are priced as input.</li>
</ul>
"""


def sec_refs():
    return """
<h2 id="refs">Sources</h2>
<ul>
<li><code>docs/evaluation/pilot_eval.md</code> and <code>pilot_eval.json</code>: every table above, regenerated by
<code>python -m reproscope.evaluate</code>.</li>
<li><code>docs/evaluation/cost_table.json</code>: the cost table, from <code>docs/evaluation/cost_table.py</code> over the ledgers.</li>
<li><code>docs/EFFICIENCY_AUDIT.html</code> and <code>docs/evaluation/audits/</code>: the pilot cost audit the fixes answer.</li>
<li><code>docs/PILOT_DESIGN.md</code>: the mechanics of every stage as built.</li>
<li><code>runs/&lt;paper&gt;/report/report.html</code>: the per-paper reports (not tracked in git).</li>
<li><code>corpus/&lt;paper&gt;/manifest.json</code>: the Multi100 focal claim, reported statistic and analyst effect-size range per paper.</li>
</ul>
"""


STYLE = """
<style>
:root{--fg:#1d1d1f;--muted:#5b5b60;--line:#e2e2e6;--bg:#fff;--acc:#2b5f8a}
body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--fg);background:var(--bg);margin:0}
main{max-width:980px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:1.7em;margin:.2em 0 .1em}h2{font-size:1.25em;margin:1.8em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:.2em}
h3{font-size:1.05em;margin:1.3em 0 .4em}h3 small{font-weight:normal;color:var(--muted);font-size:.8em;margin-left:.5em}
p{margin:.5em 0}ul{margin:.4em 0 .8em 1.2em}li{margin:.25em 0}
.tbl{overflow-x:auto;margin:.6em 0}table{border-collapse:collapse;font-size:.9em;white-space:nowrap}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:right}th:first-child,td:first-child{text-align:left}
th{background:#f4f4f7;font-weight:600}code{font-size:.9em;background:#f4f4f7;padding:1px 4px;border-radius:3px}
.meta{color:var(--muted);font-size:.9em}nav a{margin-right:12px}nav{font-size:.9em;margin:.4em 0 1em}
a{color:var(--acc)}
</style>
"""


def build():
    gen = EVAL.get("generated", "")
    body = "".join([sec_summary(), sec_lineup(), sec_families(), sec_papers(), sec_cases(), sec_cost(), sec_bugs(), sec_limits(), sec_refs()])
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>reproscope pilot — evaluation</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧪</text></svg>">
{STYLE}</head><body><main>
<h1>reproscope v0 pilot — evaluation</h1>
<p class="meta">Five Multi100 papers; replica runs 2026-09-02, everything downstream rebuilt 2026-09-03 after the efficiency
fixes. Evaluation tables generated {esc(gen[:19])} UTC.</p>
<nav><a href="#summary">Summary</a><a href="#lineup">Corpus and lineup</a><a href="#families">By family</a>
<a href="#papers">Per paper</a><a href="#cases">Cases</a><a href="#cost">Cost</a><a href="#bugs">Bugs</a>
<a href="#limits">Limits</a><a href="#refs">Sources</a></nav>
{body}
</main></body></html>
"""
    out = HERE / "PILOT_EVALUATION.html"
    out.write_text(page)
    print(f"wrote {out} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    build()
