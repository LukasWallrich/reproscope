"""The only place reproscope talks to models.

`call()` dispatches on a route from models.toml and writes one ledger row per
attempt, so retries are visible in cost audits. Structured calls validate against
a pydantic model and retry once with the validation error appended. Non-agentic
calls whose estimated input exceeds `MAX_INPUT_TOKENS` are refused before any
network or subprocess work.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from . import config, ledger

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEYS_ENV = Path.home() / ".claude" / "api_keys.env"

ROUTES = ("openrouter", "claude_p", "codex", "opencode")

#: Estimated input tokens above which a non-agentic call is refused.
MAX_INPUT_TOKENS = 60_000


class LLMError(RuntimeError):
    """A route failure. `stats` and `log` carry whatever the route got before failing."""

    def __init__(self, message: str, *, stats: dict[str, Any] | None = None, log: str = ""):
        super().__init__(message)
        self.stats = stats or {}
        self.log = log


@dataclass
class LLMResult:
    text: str
    parsed: BaseModel | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_reasoning: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    route: str = ""
    model: str = ""
    ok: bool = True
    error: str | None = None
    ledger_id: str | None = None
    raw: Any = field(default=None, repr=False)


# --- keys -----------------------------------------------------------------


def openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    if API_KEYS_ENV.exists():
        for line in API_KEYS_ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "OPENROUTER_API_KEY":
                key = value.strip().strip("'\"")
                os.environ["OPENROUTER_API_KEY"] = key
                return key
    raise LLMError(f"OPENROUTER_API_KEY not in env and not found in {API_KEYS_ENV}")


# --- JSON helpers ---------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def strip_fences(text: str) -> str:
    return _FENCE.sub("", text.strip()).strip()


def first_json_object(text: str) -> str:
    """Return the first balanced {...} block, so prose around the JSON is tolerated."""
    text = strip_fences(text)
    start = text.find("{")
    if start < 0:
        return text
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a pydantic JSON schema acceptable to OpenAI-style `strict: true`.

    Every object must forbid extra properties and list every property as required.
    """
    if isinstance(schema, dict):
        out = {k: strictify(v) for k, v in schema.items() if k != "default"}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out
    if isinstance(schema, list):
        return [strictify(v) for v in schema]
    return schema


def strict_safe(schema: dict[str, Any]) -> bool:
    """Whether a strictified schema is still acceptable to `strict: true` mode.

    Open maps (pydantic's `dict[str, Any]` fields) keep `additionalProperties` open
    and cannot be closed without changing the model, so those go through
    prompt-level instruction and client-side validation instead.
    """
    if isinstance(schema, dict):
        ap = schema.get("additionalProperties")
        if ap is not False and "additionalProperties" in schema:
            return False
        return all(strict_safe(v) for v in schema.values())
    if isinstance(schema, list):
        return all(strict_safe(v) for v in schema)
    return True


def schema_payload(schema: type[BaseModel]) -> tuple[dict[str, Any], bool]:
    s = strictify(schema.model_json_schema())
    return s, strict_safe(s)


def schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "\n\nRespond with only a JSON object matching this schema:\n"
        + json.dumps(schema.model_json_schema())
    )


def validate(schema: type[BaseModel], text: str) -> BaseModel:
    return schema.model_validate_json(first_json_object(text))


# --- route implementations ------------------------------------------------


def _image_parts(images: list[Path]) -> list[dict[str, Any]]:
    parts = []
    for p in images:
        suffix = Path(p).suffix.lstrip(".").lower() or "png"
        mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix}"
        b64 = base64.b64encode(Path(p).read_bytes()).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return parts


def _openrouter(
    prompt: str,
    model: str,
    *,
    schema: type[BaseModel] | None,
    images: list[Path] | None,
    system: str | None,
    timeout_s: int,
    reasoning_max_tokens: int | None,
) -> tuple[str, dict[str, Any]]:
    import httpx

    content: Any = prompt
    if images:
        content = [{"type": "text", "text": prompt}] + _image_parts(images)
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": content}
    ]
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "usage": {"include": True},
        "provider": {
            "sort": "price",
            "preferred_min_throughput": 40,
            "require_parameters": bool(schema),
        },
    }
    if schema is not None:
        # A structured reply is a small JSON object; without a cap the cheap
        # reasoning models spend most of their output budget thinking about it.
        if reasoning_max_tokens is not None:
            body["reasoning"] = {"max_tokens": reasoning_max_tokens}
        payload, strict = schema_payload(schema)
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "strict": strict,
                "schema": payload if strict else schema.model_json_schema(),
            },
        }
    headers = {"Authorization": f"Bearer {openrouter_key()}", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout_s) as client:
        r = client.post(OPENROUTER_URL, headers=headers, json=body)
        if r.status_code == 400 and schema is not None:
            # Some providers reject the strict schema shape; pydantic still validates.
            body["response_format"]["json_schema"]["strict"] = False
            body["response_format"]["json_schema"]["schema"] = schema.model_json_schema()
            r = client.post(OPENROUTER_URL, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    if "choices" not in data:
        raise LLMError(f"openrouter returned no choices: {json.dumps(data)[:500]}")
    # message.reasoning is deliberately ignored; only message.content is the answer.
    text = data["choices"][0]["message"].get("content") or ""
    usage = data.get("usage") or {}
    stats = {
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
        "tokens_reasoning": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
        "cost_usd": float(usage.get("cost") or 0.0),
        "raw": data,
    }
    return text, stats


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    return env


def _run(cmd: list[str], prompt: str, cwd: Path | None, timeout_s: int, env: dict[str, str]):
    return subprocess.run(
        cmd,
        input=prompt,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def _claude_p(
    prompt: str,
    model: str,
    *,
    schema: type[BaseModel] | None,
    images: list[Path] | None,
    system: str | None,
    cwd: Path | None,
    agentic: bool,
    timeout_s: int,
    max_turns: int | None,
) -> tuple[str, dict[str, Any], str]:
    # Project settings only: the user's global CLAUDE.md would otherwise steer every call
    # (orchestration, advisor, deviation flagging), which contaminates blind replicas.
    cmd = ["claude", "-p", "--model", model, "--setting-sources", "project"]
    if agentic and max_turns is not None:
        cmd += ["--max-turns", str(max_turns)]
    if agentic:
        # stream-json + verbose logs every tool call, so the blinding audit can grep the
        # transcript for reads outside the work directory.
        cmd += [
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "bypassPermissions",
            "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep",
        ]
    else:
        cmd += ["--output-format", "json", "--allowedTools", "Read"]
    if system:
        cmd += ["--append-system-prompt", system]
    if schema is not None:
        payload, strict = schema_payload(schema)
        if strict:
            cmd += ["--json-schema", json.dumps(payload)]
        else:
            prompt += schema_instruction(schema)
    if images:
        listing = "\n".join(f"- {Path(p).resolve()}" for p in images)
        prompt = f"{prompt}\n\nRead these image files with the Read tool before answering:\n{listing}"
    proc = _run(cmd, prompt, cwd, timeout_s, _subprocess_env())
    log = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    # The result event is parsed before any failure is raised, so a crashed or
    # error-reporting session still ledgers the tokens it burned.
    data = _claude_result(proc.stdout or "", agentic)
    stats = _claude_stats(data)
    if proc.returncode != 0:
        raise LLMError(
            f"claude exited {proc.returncode}: {proc.stderr[-800:]}", stats=stats, log=log
        )
    if data is None:
        raise LLMError(f"claude gave non-JSON output: {proc.stdout[:500]}", stats=stats, log=log)
    if data.get("is_error"):
        raise LLMError(
            f"claude reported an error: {str(data.get('result'))[:500]}", stats=stats, log=log
        )
    structured = data.get("structured_output")
    text = json.dumps(structured) if structured is not None else (data.get("result") or "")
    return text, stats, log


def _claude_result(stdout: str, agentic: bool) -> dict[str, Any] | None:
    """The final `result` object from a claude -p run, or None if stdout has none."""
    try:
        if agentic:
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            return next((e for e in reversed(events) if e.get("type") == "result"), None)
        return json.loads(stdout) if stdout.strip() else None
    except json.JSONDecodeError:
        return None


def _claude_stats(data: dict[str, Any] | None) -> dict[str, Any]:
    if data is None:
        return {"tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0, "cost_usd": 0.0, "raw": None}
    usage = data.get("usage") or {}
    return {
        "tokens_in": (usage.get("input_tokens", 0) or 0)
        + (usage.get("cache_read_input_tokens", 0) or 0)
        + (usage.get("cache_creation_input_tokens", 0) or 0),
        "tokens_out": usage.get("output_tokens", 0) or 0,
        "tokens_reasoning": (usage.get("output_tokens_details") or {}).get("thinking_tokens", 0) or 0,
        # Charged to the subscription seat; the ledger keeps this as cost_usd_equiv.
        "cost_usd": float(data.get("total_cost_usd") or 0.0),
        "raw": data,
    }


_TOKENS_USED = re.compile(r"tokens used\s*[:\n]?\s*([\d,]+)", re.IGNORECASE)


def _codex(
    prompt: str,
    model: str,
    *,
    schema: type[BaseModel] | None,
    cwd: Path | None,
    agentic: bool,
    timeout_s: int,
) -> tuple[str, dict[str, Any], str]:
    import tempfile

    workdir = Path(cwd) if cwd else Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        last = Path(tmp) / "last_message.txt"
        cmd = ["codex", "exec", "--skip-git-repo-check", "-m", model, "-C", str(workdir)]
        cmd += (
            ["--dangerously-bypass-approvals-and-sandbox"]
            if agentic
            else ["--sandbox", "read-only"]
        )
        cmd += ["-o", str(last)]
        if schema is not None:
            payload, strict = schema_payload(schema)
            if strict:
                sfile = Path(tmp) / "schema.json"
                sfile.write_text(json.dumps(payload))
                cmd += ["--output-schema", str(sfile)]
            else:
                prompt += schema_instruction(schema)
        cmd.append("-")
        proc = _run(cmd, prompt, workdir, timeout_s, _subprocess_env())
        # Run non-interactively, codex puts the answer on stdout and the banner,
        # transcript and token count on stderr.
        log = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
        stats = _codex_stats(log)
        if proc.returncode != 0:
            raise LLMError(
                f"codex exited {proc.returncode}: {proc.stderr[-800:]}", stats=stats, log=log
            )
        text = last.read_text().strip() if last.exists() else _codex_tail(log)
    return text, stats, log


def _codex_stats(log: str) -> dict[str, Any]:
    m = _TOKENS_USED.search(log)
    total = int(m.group(1).replace(",", "")) if m else 0
    # codex reports one total only; it is booked as input so totals stay honest.
    return {"tokens_in": total, "tokens_out": 0, "tokens_reasoning": 0, "cost_usd": 0.0, "raw": None}


def _codex_tail(stdout: str) -> str:
    """Fallback: the answer sits between the last bare `codex` line and `tokens used`."""
    lines = (stdout or "").splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == "codex"]
    if not starts:
        return (stdout or "").strip()
    start = starts[-1] + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].strip().lower().startswith("tokens used")),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()


def _opencode(
    prompt: str,
    model: str,
    *,
    cwd: Path | None,
    agentic: bool,
    timeout_s: int,
) -> tuple[str, dict[str, Any], str]:
    workdir = Path(cwd) if cwd else Path.cwd()
    cmd = ["opencode", "run", "--format", "json", "-m", f"openrouter/{model}", "--dir", str(workdir)]
    if agentic:
        cmd.append("--auto")
    cmd.append(prompt)
    env = _subprocess_env()
    env["OPENROUTER_API_KEY"] = openrouter_key()
    proc = _run(cmd, "", workdir, timeout_s, env)  # prompt is the positional arg; stdin stays empty
    log = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    texts, stats = _opencode_stream(proc.stdout or "")
    if proc.returncode != 0:
        raise LLMError(
            f"opencode exited {proc.returncode}: {proc.stderr[-800:]}", stats=stats, log=log
        )
    if not texts:
        raise LLMError(
            f"opencode produced no text parts: {(proc.stdout or '')[:500]}", stats=stats, log=log
        )
    return "\n".join(texts).strip(), stats, log


def _opencode_stream(stdout: str) -> tuple[list[str], dict[str, Any]]:
    """Text parts and usage from the NDJSON stream, parsed however the run ended."""
    texts: list[str] = []
    stats: dict[str, Any] = {
        "tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0, "cost_usd": 0.0, "raw": None,
    }
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") or {}
        if ev.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
        elif ev.get("type") == "step_finish":
            tok = part.get("tokens") or {}
            cache = tok.get("cache") or {}
            # Cached input is billed and prompted with, so it belongs in tokens_in.
            stats["tokens_in"] += (
                int(tok.get("input") or 0)
                + int(cache.get("read") or 0)
                + int(cache.get("write") or 0)
            )
            stats["tokens_out"] += int(tok.get("output") or 0)
            stats["tokens_reasoning"] += int(tok.get("reasoning") or 0)
            stats["cost_usd"] += float(part.get("cost") or 0.0)
    return texts, stats


# --- the public entry point ----------------------------------------------


def call(
    step: str,
    prompt: str,
    *,
    paper_id: str,
    stage: str,
    tier: str | None = None,
    route: str | None = None,
    model: str | None = None,
    schema: type[BaseModel] | None = None,
    images: list[Path] | None = None,
    system: str | None = None,
    cwd: Path | None = None,
    agentic: bool = False,
    timeout_s: int = 1800,
    log_path: Path | None = None,
    extra: dict[str, Any] | None = None,
    max_turns: int | None = None,
    large_context: bool = False,
    reasoning_max_tokens: int | None = 512,
) -> LLMResult:
    """Route one call and ledger every attempt.

    `max_turns` caps agentic claude_p sessions. `large_context` opts a non-agentic
    call out of the `MAX_INPUT_TOKENS` refusal. `reasoning_max_tokens` caps hidden
    reasoning on OpenRouter structured calls; it applies to calls that pass a
    `schema` only, and `None` leaves the provider default in place.

    Token and cost figures on the returned result sum across attempts;
    `ledger_id` is the id of the last attempt's row.

    Raises `LLMError` for an unknown route and for an oversize non-agentic input,
    after writing one ledger row so the refusal shows up in cost audits.
    """
    if tier is not None:
        spec = config.tier(tier)
        route, model = route or spec.route, model or spec.model
    if not route or not model:
        raise ValueError("call() needs either tier= or both route= and model=")

    started = time.monotonic()
    totals = {"tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0, "cost_usd": 0.0}
    logs: list[str] = []
    ledger_id: str | None = None

    def book(attempt: int, stats: dict[str, Any], error: str | None, seconds: float) -> str:
        for key in totals:
            totals[key] += stats.get(key, 0) or 0
        return ledger.record(
            paper_id,
            {
                "stage": stage,
                "step": step,
                "route": route,
                "model": model,
                "attempt": attempt,
                "tokens_in": stats.get("tokens_in", 0),
                "tokens_out": stats.get("tokens_out", 0),
                "tokens_reasoning": stats.get("tokens_reasoning", 0),
                "cost_usd": stats.get("cost_usd", 0.0),
                "duration_s": round(seconds, 2),
                "ok": error is None,
                "error": error,
                **(extra or {}),
            },
        )

    if route not in ROUTES:
        message = f"unknown route {route!r}; have {list(ROUTES)}"
        book(1, {}, message, time.monotonic() - started)
        raise LLMError(message)

    if not agentic and not large_context:
        estimate = (len(prompt) + len(system or "")) // 4
        if estimate > MAX_INPUT_TOKENS:
            message = (
                f"input of about {estimate} tokens exceeds the {MAX_INPUT_TOKENS} limit for a "
                f"non-agentic call; shrink the prompt or pass large_context=True"
            )
            book(1, {}, message, time.monotonic() - started)
            raise LLMError(message)

    text = ""
    stats: dict[str, Any] = {}
    parsed: BaseModel | None = None
    error: str | None = None
    attempt_prompt = prompt

    for attempt in (1, 2):
        attempt_started = time.monotonic()
        stats, error, retry_prompt, transient = {}, None, None, False
        try:
            if route == "openrouter":
                text, stats = _openrouter(
                    attempt_prompt, model,
                    schema=schema, images=images, system=system, timeout_s=timeout_s,
                    reasoning_max_tokens=reasoning_max_tokens,
                )
            elif route == "claude_p":
                text, stats, log = _claude_p(
                    attempt_prompt, model,
                    schema=schema, images=images, system=system,
                    cwd=cwd, agentic=agentic, timeout_s=timeout_s, max_turns=max_turns,
                )
                logs.append(log)
            elif route == "codex":
                text, stats, log = _codex(
                    attempt_prompt, model,
                    schema=schema, cwd=cwd, agentic=agentic, timeout_s=timeout_s,
                )
                logs.append(log)
            else:
                text, stats, log = _opencode(
                    attempt_prompt, model, cwd=cwd, agentic=agentic, timeout_s=timeout_s
                )
                logs.append(log)
        except subprocess.TimeoutExpired as e:
            error = f"timeout after {timeout_s}s"
            logs.append(_decode(e.stdout) + _decode(e.stderr))
        except Exception as e:  # noqa: BLE001 - every failure must still be ledgered
            error = f"{type(e).__name__}: {e}"
            stats = getattr(e, "stats", None) or {}
            if getattr(e, "log", ""):
                logs.append(e.log)
            # CLI routes fail transiently (rate limits, concurrent sessions); retry once.
            transient = route != "openrouter" and not agentic
        else:
            if schema is not None:
                try:
                    parsed = validate(schema, text)
                except ValidationError as e:
                    error = f"schema validation failed: {e}"
                    retry_prompt = (
                        f"{prompt}\n\nYour previous reply did not validate against the required "
                        f"schema. Fix it and reply with the JSON object only.\n"
                        f"Previous reply:\n{text[:4000]}\n\nValidation error:\n{e}"
                    )

        ledger_id = book(attempt, stats, error, time.monotonic() - attempt_started)
        if error is None or attempt == 2:
            break
        if retry_prompt is not None:
            attempt_prompt = retry_prompt
            continue
        if not transient:
            break
        time.sleep(20)

    duration = time.monotonic() - started
    if log_path is not None and logs:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n\n---- next attempt ----\n\n".join(logs))

    return LLMResult(
        text=text,
        parsed=parsed,
        tokens_in=totals["tokens_in"],
        tokens_out=totals["tokens_out"],
        tokens_reasoning=totals["tokens_reasoning"],
        cost_usd=0.0 if route in config.SUBSCRIPTION_ROUTES else totals["cost_usd"],
        duration_s=duration,
        route=route,
        model=model,
        ok=error is None,
        error=error,
        ledger_id=ledger_id,
        raw=stats.get("raw"),
    )


def _decode(stream: Any) -> str:
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream or ""
