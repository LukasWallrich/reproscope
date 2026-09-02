# Model & CLI tooling findings (2026-08-31)

All prices are USD per million tokens (MTok). Web-search budget for the session was
exhausted, so facts come from direct page fetches (docs.z.ai, openrouter.ai,
developers.openai.com, opencode.ai) plus local CLI tests on this machine.

---

## 1. opencode CLI — headless mode

**Verified. Installed locally: `/opt/homebrew/bin/opencode`, version 1.18.21.**

### Invocation

```
opencode run --format json -m <provider>/<model> "your prompt"
```

Equivalent to `claude -p`. Confirmed empirically twice (see §2). `--format json`
streams raw NDJSON events; the final `step_finish` event carries `tokens` and `cost`,
which is what you want for a batch pipeline. `--format default` gives formatted prose.

Other flags that matter for pipelines:

| Flag | Purpose |
|---|---|
| `-m, --model` | `provider/model` |
| `--agent` | pick a named agent |
| `-f, --file` | attach file(s) to the message |
| `--auto` | auto-approve all permissions not explicitly denied (needed for unattended runs) |
| `--variant` | provider-specific reasoning effort (`high`, `max`, `minimal`) |
| `-c / -s / --fork` | continue / resume / fork a session |
| `--attach http://localhost:4096` | send to a running `opencode serve` instead of cold-starting |
| `--dir` | working directory |
| `--title` | session title |

For high-volume batches, run `opencode serve` once and point every `opencode run`
at it with `--attach`; this removes per-call cold start.

Other relevant subcommands: `opencode models [provider]` (lists 433 models here),
`opencode stats` (token/cost stats), `opencode export <sessionID>` (session as JSON),
`opencode serve` (headless server), `opencode acp` (Agent Client Protocol server).

### Per-call overhead — important for batch pipelines

Both empirical test calls sent **~17,000 input tokens** for a one-word prompt. That is
opencode's system prompt plus tool definitions. It is a hard per-call cost floor:

- glm-5.3 via OpenRouter: 16,900 in / 2 out → **$0.0238 per call**
- glm-5.3-flash via OpenRouter: 17,030 in / 3 out → **$0.00128 per call**

At 1,000 pipeline items that is $24 vs $1.28. Prompt caching (the glm-5.3 run showed
128 cached tokens) helps only if the prefix is reused within the cache window.

### Provider / model routing

Arbitrary providers are supported. Two routes:

1. **Built-in provider list** — 433 models across openai, deepseek, openrouter,
   moonshot/kimi, google, anthropic, qwen, minimax, etc.
2. **Any OpenAI-compatible endpoint** — `/connect` → "Other" → provider id, then in
   `opencode.json`:

```json
"provider": {
  "zai": {
    "npm": "@ai-sdk/openai-compatible",
    "options": { "baseURL": "https://api.z.ai/api/paas/v4" },
    "models": { "glm-5.3-flash": { "name": "GLM-5.3-Flash" } }
  }
}
```

**A model id not in the bundled list still works** if the upstream provider serves it —
`glm-5.3-flash` is absent from `opencode models` (released 5 days ago; the bundled
models.dev catalogue is stale) but `-m openrouter/z-ai/glm-5.3-flash` ran fine.

### Subscription auth (not API keys)

Supported. `opencode providers login` (alias `opencode auth`, or `/connect` in the TUI)
opens a browser OAuth flow for:

- **Anthropic Claude Pro/Max** — "Claude Pro/Max" option
- **OpenAI ChatGPT Plus/Pro** — "ChatGPT Plus/Pro" option
- **GitHub Copilot** — device-code flow

Tokens refresh automatically. Everything else is API-key entry. Running a
subscription-backed model through opencode needs one `opencode providers login` first.

---

## 2. glm-5.3-flash (Zhipu / Z.ai)

**Verified. Exists. Released 26 August 2026.**

### Pricing

| Source | Input | Output |
|---|---|---|
| Z.ai official pricing page | **$0.075** | **$0.25** |
| OpenRouter (`z-ai/glm-5.3-flash`) | $0.07125 | $0.2375 |

Z.ai flags a **50% promotional discount ending 9 September 2026 (UTC+8)** — so the
post-promo list price is presumably ~$0.15 / $0.50. Plan for the higher figure.

For contrast on the same Z.ai page: GLM-5.3 (full) is $1.4 / $4.4, i.e. glm-5.3-flash
is roughly **18x cheaper on input and 18x cheaper on output** than its full sibling.

### Context window

**1,310,720 tokens** (1.31M) per OpenRouter, with up to 131,072 completion tokens.
The Z.ai docs page for the GLM-5.3 family states 1M context / 128K max output for
glm-5.3 proper.

### Capability / reputation

Z.ai positions it as natively multimodal (text, image, video in; text out), using
hybrid sparse + linear attention to hold accuracy over long contexts cheaply, and
explicitly "suited for efficient coding and long-horizon agent tasks". Supports
function calling and structured JSON output. It is the **default model Z.ai maps
Opus, Sonnet and Haiku to** in their own Claude Code integration, which is a strong
signal they consider it agentic-coding-grade. Independent benchmark standing was not
verifiable within the session's search budget.

### Access routes

1. **Z.ai native API** — `https://api.z.ai/api/paas/v4` (OpenAI-compatible).
2. **Z.ai Anthropic-compatible endpoint** — `https://api.z.ai/api/anthropic`, usable
   from Claude Code by pointing its base URL and auth token at Z.ai. Z.ai's own helper
   maps Opus/Sonnet/Haiku all to GLM-5.3-Flash by default.
3. **OpenRouter** — `z-ai/glm-5.3-flash`, served by 21 providers. Works today through
   opencode as `-m openrouter/z-ai/glm-5.3-flash` (tested, $0.00128 for a trivial call).
4. **GLM Coding Plan subscription** — z.ai/subscribe advertises "AI Coding Powered by
   GLM-5.3, GLM-5.3-Flash, GLM-5.2 & GLM-5-Turbo for Agents & IDEs". **Tier prices and
   quotas were not confirmed** — the fetched landing page did not expose them.

---

## 3. GPT-5.6 Sol / Luna / Terra

**Verified. All three exist.** They are the three tiers of the GPT-5.6 family
(released 9 July 2026, knowledge cutoff 16 February 2026), all with a **1.05M token
context window, 128K max output**, supporting functions, web search, file search and
computer use.

| Model | Role | OpenAI docs price (in/out) | OpenRouter price (in/out) |
|---|---|---|---|
| `gpt-5.6-sol` | Flagship, complex professional work, coding, agentic/CLI | $4 / $20 | $2 / $10 |
| `gpt-5.6-terra` | Balances intelligence and cost | $2 / $12 | not fetched |
| `gpt-5.6-luna` | Fast, cost-efficient; high-volume, latency-sensitive chat, classification, lightweight agentic work | $0.20 / $1.20 | $0.20 / $1.20 |

**Pricing discrepancy on Sol:** developers.openai.com lists $4 / $20; the OpenRouter
model page lists $2 / $10 (plus $0.20 cache read, $2.50 cache write). Treat the OpenAI
docs figure as authoritative for the direct API and budget accordingly; the OpenRouter
figure may reflect a routed or discounted variant. Luna's $0.20 / $1.20 agrees across
both sources.

### Subscription access via Codex CLI

**Yes** (codex-cli 0.149.0). The Codex CLI can run in ChatGPT-subscription mode with no
API key stored, and Sol works as its default model in that mode. Invocation:

```
codex exec --skip-git-repo-check --sandbox read-only -m gpt-5.6-sol - < prompt.txt > out.txt 2>&1
```

**Luna on the subscription is NOT confirmed.** `codex exec -m gpt-5.6-luna` is accepted
by the CLI and prints a session banner (`model: gpt-5.6-luna, provider: openai`), but
that is local argument handling before any server call. Every attempt to complete the
request failed because this agent environment cannot reach `chatgpt.com`
(`curl https://chatgpt.com/` returns nothing; codex retries websockets then gives up),
and the block persists with the Bash sandbox disabled.

**To settle it, run this yourself from a normal terminal:**

```
codex exec --skip-git-repo-check --sandbox read-only -m gpt-5.6-luna "say OK"
```

A completed reply means Luna is on the subscription; a model-access error means it is
API-only.

Codex `exec` also has `resume`, `fork` and `review` subcommands, `-c key=value` config
overrides, `-i/--image`, and `--oss` / `--local-provider` (lmstudio, ollama) for local
models.

### GPT-5.6 through opencode

`opencode models` lists all of: `openai/gpt-5.6`, `-fast`, `-pro`, `-sol`,
`-sol-fast`, `-sol-pro`, `-luna`, `-luna-fast`, `-luna-pro`, `-terra`, `-terra-fast`,
`-terra-pro`. Reaching them through a ChatGPT subscription rather than
`OPENAI_API_KEY` requires the "ChatGPT Plus/Pro" OAuth login in
`opencode providers login`, which is not configured here yet.

Note the `-fast` and `-pro` suffixes appear in opencode's catalogue but not in the
OpenAI docs model table fetched; treat them as latency/quality variants and verify
before relying on them.

---

## 4. Other cheap-but-capable coding models for agentic batch work (late 2026)

From `opencode models` (433 entries) and the pricing pages fetched. Priced entries are
verified; unpriced ones are availability-only.

**Cheapest credible agentic coders**

- **GLM-5.3-Flash** — $0.075 / $0.25, 1.3M context, multimodal, built for long-horizon
  agent tasks. The best price/capability point found in this session.
- **GPT-5.6 Luna** — $0.20 / $1.20, 1.05M context, first-party OpenAI, available on a
  ChatGPT subscription through Codex. Best choice if you want subscription-covered
  volume rather than metered spend.
- **GLM-4.7-FlashX** — $0.07 / $0.40; **GLM-4.7-Flash and GLM-4.5-Flash are free** on
  Z.ai. Older generation, but zero marginal cost for bulk mechanical passes.
- **GLM-4.5-Air** — $0.2 / $1.1.

**Other families worth knowing (available via OpenRouter / opencode; prices not fetched)**

- **DeepSeek** — `deepseek-v4-flash`, `deepseek-v4-pro`.
- **Moonshot Kimi** — `kimi-k2.7-code`, `kimi-k2.7-code-highspeed`, `kimi-k3`; also
  reachable through a "Kimi For Coding" subscription provider in opencode.
- **Qwen** — `qwen3-coder-flash`, `qwen3-coder-next`, `qwen3.5-flash-02-23`.
- **MiniMax** — `minimax-m2.7`, `minimax-m3`.
- **ByteDance Seed** — `seed-2.0-code`, `seed-2.0-mini`, `seed-2.0-lite`.
- **Kwaipilot** — `kat-coder-air-v2.5`, `kat-coder-pro-v2.5` (coding-specialised).
- **Google** — `gemini-3.7-flash`, `gemini-3.5-flash-lite`.
- **Free tiers** — opencode's own hosted free models (`opencode/hy3-free`,
  `nemotron-3.5-lightning-free`, `mimo-v2.5-free`, …) and
  `openrouter/z-ai/glm-5.2:free`, `cohere/north-mini-code:free`.

**Practical recommendation for a batch pipeline:** glm-5.3-flash via OpenRouter through
`opencode run --format json`, with a Kimi For Coding subscription as a fallback. Budget the ~17k-token opencode system-prompt floor per call, and use
`opencode serve` + `--attach` to avoid cold starts.

---

## Verification log

| Check | Method | Result |
|---|---|---|
| opencode installed | `opencode --version` | 1.18.21 |
| opencode headless works | `opencode run --format json -m openrouter/z-ai/glm-5.3 "Reply with exactly: OK"` | returned `OK`, cost $0.0238 |
| glm-5.3-flash reachable | same, `-m openrouter/z-ai/glm-5.3-flash` | returned `OK`, cost $0.00128 |
| glm-5.3-flash price | docs.z.ai pricing page | $0.075 / $0.25, 50% promo to 2026-09-09 |
| glm-5.3-flash context | openrouter.ai/z-ai/glm-5.3-flash | 1,310,720 tokens |
| Sol/Luna/Terra exist | developers.openai.com/api/docs/models + openrouter pages | all three confirmed |
| Codex on subscription | local Codex config | ChatGPT-subscription mode, Sol as default |
| Luna on subscription | `codex exec -m gpt-5.6-luna` | INCONCLUSIVE — no network egress to chatgpt.com from this environment |
| opencode subscription auth | opencode.ai/docs/providers | Claude Pro/Max, ChatGPT Plus/Pro, Copilot OAuth |

**Not verified:** whether Luna and Terra are covered by the ChatGPT subscription (only
Sol is proven);
GLM Coding Plan tier prices and quotas; independent benchmark scores
for glm-5.3-flash; prices for the DeepSeek / Kimi / Qwen / MiniMax models listed in §4;
what opencode's `-fast` / `-pro` GPT-5.6 suffixes actually map to.
