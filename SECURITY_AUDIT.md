# Security Audit Report — NLThinkingPanel

Date: 2026-02-12
Scope: static review of Python source code and dependency manifest.

## Methodology
- Manual code review of bot core, cogs, modules, and configuration.
- Pattern-based checks for common dangerous primitives (code execution, shell usage, unsafe deserialization, secret leakage vectors).
- Dependency review based on `requirements.txt` versions (best-effort, without online CVE DB access in this environment).

## Executive Summary
The project has no direct RCE primitives (no `eval/exec`, no shell execution, no unsafe `pickle/yaml.load`).
Main risks are **operational abuse and data exposure** in Discord context:
1. Mass-mention abuse through AI-generated outputs.
2. Internal error disclosure to end users.
3. Cost-amplification/DoS via oversized user prompts.
4. Collection of broad guild context (presence/message snippets) with privacy implications.

## Findings

### 1) Mass-mention abuse in generated responses (HIGH)
**Risk:** AI responses could include `@everyone`, `@here`, or role mentions, leading to notification abuse and social-engineering vectors.

**Attack scenario:** An attacker asks the model to include mention strings; bot relays them as-is to channel.

**Mitigation applied:** global mention suppression with `allowed_mentions=discord.AllowedMentions.none()` in bot initialization.

### 2) Internal exception text exposed to users (MEDIUM)
**Risk:** Returning raw exception strings can leak provider errors, model details, stack hints, or sensitive internals useful for reconnaissance.

**Mitigation applied:** replaced user-facing raw error output with generic messages in command handlers and global command error handler.

### 3) Prompt-cost amplification via long user inputs (MEDIUM)
**Risk:** Users can send very long prompts, increasing API cost/latency and risking service degradation.

**Mitigation applied:** introduced configurable `MAX_USER_INPUT_CHARS` with validation and enforced checks in `ask`, `quick`, and `web` commands.

### 4) Privacy and data minimization concerns (MEDIUM, architectural)
**Risk:** Bot collects member statuses/activities and recent message excerpts for AI context. This may exceed least-privilege/privacy expectations in some communities.

**Recommendation:**
- Add opt-in/opt-out by guild/channel.
- Limit which data points are included (e.g., no activity titles by default).
- Add retention policy and transparent disclosure command.

### 5) Admin authorization model is env-ID based only (LOW-MEDIUM)
**Risk:** Admin powers are controlled solely by `ADMIN_IDS`; no fallback to Discord role/permission checks.

**Recommendation:** require both `ADMIN_IDS` and Discord permission (e.g., `manage_guild`), or provide configurable strategy.

### 6) Dependency security checks not fully verifiable offline (WARNING)
**Risk:** Current environment cannot access package indexes/CVE sources, so automated vuln scan could not be completed.

**Recommendation:** run `pip-audit`/`safety` in CI with internet access and lock dependencies.

## Hardening Recommendations (next steps)
1. Add an explicit privacy mode (default minimal context).
2. Add per-command cooldown overrides and max concurrency to reduce abuse.
3. Implement structured security logging with redaction.
4. Pin dependencies with hashes (`pip-tools` / `poetry lock`) and schedule periodic audits.
5. Consider content filtering before sending model output to Discord.

## Patched Items in This Branch
- Mention suppression added globally.
- Raw exception exposure removed from user-facing command responses.
- Input-length guardrail added and validated via config.
- Correct timeout exception handling in profile delete flow (`asyncio.TimeoutError`).
