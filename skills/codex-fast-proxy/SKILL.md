---
name: codex-fast-proxy
description: Codex Model Gateway for Codex App auth-split with third-party OpenAI-compatible APIs. Supports ChatGPT sign-in compatibility, provider management, priority service_tier, Responses API benchmark, enable/check/update/uninstall.
---

Use this skill when the user wants Codex to manage Codex Model Gateway, the local auth-split and
provider gateway for Codex App.

## Default workflow

Prefer the Control UI for normal users:

```powershell
python -m codex_fast_proxy ui
```

If sandbox or approval controls apply, request approval/escalation for this command because it starts
a local background Control UI server that must stay alive after the launcher exits. Report the
printed URL as plain text and ask the user to open it in an external browser. Do not use browser
automation for this handoff. The UI defaults to Chinese, supports English/Japanese and light/dark
appearance, and delegates to manager actions for enable, update, provider management, diagnostics,
benchmark, and safe restore/uninstall.

## Manager fallback

Use CLI commands only for automation, diagnostics, or when the UI cannot be opened:

```powershell
python -m codex_fast_proxy doctor
python -m codex_fast_proxy status
python -m codex_fast_proxy install --start
python -m codex_fast_proxy install --start --use-provider-auth-file
python -m codex_fast_proxy update
python -m codex_fast_proxy check-update
python -m codex_fast_proxy verify-upstream --upstream-base https://api.example.com/v1
python -m codex_fast_proxy set-upstream --upstream-base https://api.example.com/v1
python -m codex_fast_proxy prepare-chatgpt-login
python -m codex_fast_proxy prepare-chatgpt-login --apply
python -m codex_fast_proxy set-upstream --use-provider-auth-file
python -m codex_fast_proxy uninstall --defer-stop
python -m codex_fast_proxy uninstall
```

Do not edit the active provider `base_url` directly while the proxy is enabled. It should keep
pointing to the local proxy; use Control UI provider management or `set-upstream` to change the
saved upstream route.

## Safety rules

- Installing the repo or skill must not change Codex provider config; ordinary users enable from UI.
- `install --start` starts the local proxy before switching Codex config and installs the
  `SessionStart` hook. That hook starts or reuses both the proxy and Control UI on future sessions,
  and emits only short non-secret context when it actually starts, restarts, or detects a problem.
- First enable prepares provider auth for future ChatGPT account login when a provider key is
  available, then asks the user to restart Codex because running Codex processes do not hot-switch
  provider config.
- `update` owns `git pull --ff-only`, editable reinstall, skill link refresh, enabled-runtime
  refresh, and final status reporting. Do not duplicate the old UPDATE.md script in chat.
- `set-upstream`, provider save, and provider switch verify a streaming `POST /v1/responses` route
  before committing settings. This is real provider traffic and may consume a small amount of quota.
- API keys must not be pasted back into chat. Prefer the proxy-managed provider auth file; never
  print API key values, provider-auth file contents, `auth.json` contents, ChatGPT tokens, cookies,
  request bodies, or prompts.
- Do not pass `--restart` or run `stop --force` unless the user accepts that restarting/stopping the
  proxy can interrupt proxy-backed Codex sessions.
- If uninstall reports `confirmation_required`, no uninstall changes were applied. Explain the
  ChatGPT-login direct-upstream 401 risk and wait for explicit confirmation before continuing.
- After skill files change, tell the user to restart Codex App or open a new CLI process so Codex
  rescans `~/.agents/skills`.

## Result handling

Treat JSON output as the source of truth. Report user-facing fields such as `provider`,
`upstream_base`, `service_tier_policy`, `upstream_auth`, `config_matches`, `runtime_matches`,
`needs_restart`, `startup_hook`, `verification`, `backup_path`, `config_restore`, and
`next_user_action` when present.

For normal users, do not surface the proxy `base_url` unless they are explicitly asking for
diagnostics. Use "Control UI URL" for the browser page and "model service URL" for the upstream
provider endpoint. When ChatGPT login is active, explain that speed is App controlled and proxy-side
speed controls are hidden.

For benchmark requests, run `benchmark` only after the user explicitly accepts the cost. Report
sample counts, medians, observed speedup, `priority_accepted`, `priority_support_assessment`,
`statistical_test`, and provider-confirmed priority metadata when present. Treat latency as an
observation; do not present it as proof of provider fast support unless the provider confirms
priority through response metadata, billing, dashboard state, or documentation.
