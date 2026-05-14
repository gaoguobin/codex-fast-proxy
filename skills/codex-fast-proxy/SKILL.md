---
name: codex-fast-proxy
description: Codex App Fast proxy and auth-split for third-party OpenAI-compatible APIs. Supports Sign in with ChatGPT, priority service_tier, Responses API benchmark, enable/check/update/uninstall.
---

Use this skill when the user wants Codex to manage the local auth-split and Fast proxy for Codex App.

## Trigger patterns

- Enable requests such as "enable Codex Fast proxy".
- App Fast requests such as "make Codex App use Fast".
- Provider-specific requests such as "enable Fast for PackyAPI".
- ChatGPT login compatibility requests such as "plugins work but model requests return 401".
- Benchmark requests such as "run the Fast proxy benchmark" or "check whether my provider supports Fast".
- Upstream URL changes such as "set the Codex Fast proxy upstream to https://api.example.com/v1".
- Control UI requests such as "open Codex Fast proxy Control UI" or "configure Codex Fast proxy".
- Maintenance requests such as "show status", "check updates", "stop", or "uninstall".

## How to execute

Run the manager as the source of truth:

```powershell
python -m codex_fast_proxy doctor
python -m codex_fast_proxy install --start
python -m codex_fast_proxy install --start --use-provider-auth-file
python -m codex_fast_proxy prepare-chatgpt-login
python -m codex_fast_proxy prepare-chatgpt-login --apply
python -m codex_fast_proxy verify-upstream --upstream-base https://api.example.com/v1
python -m codex_fast_proxy set-upstream --upstream-base https://api.example.com/v1
python -m codex_fast_proxy set-upstream --use-provider-auth-file
python -m codex_fast_proxy set-upstream --clear-upstream-auth
python -m codex_fast_proxy set-upstream --service-tier-policy auto
python -m codex_fast_proxy set-upstream --service-tier-policy inject_missing
python -m codex_fast_proxy status
python -m codex_fast_proxy ui
python -m codex_fast_proxy check-update
python -m codex_fast_proxy benchmark
python -m codex_fast_proxy autostart --quiet
python -m codex_fast_proxy stop --force
python -m codex_fast_proxy uninstall --defer-stop
python -m codex_fast_proxy uninstall
```

## Safety model

- Installing the repo or skill must not change Codex provider config.
- After file-only install, open the Chinese Control UI with `python -m codex_fast_proxy ui`. It starts
  an independent local UI and returns a URL. Give that URL to the user as plain text and ask them to
  open it in an external browser. Do not use browser automation for this handoff, and do not treat
  this as enabling model traffic.
- Ordinary users should click the UI's `启用` button. That first-run action prepares provider auth for
  future ChatGPT login and then enables the current provider route through the manager lifecycle.
- Enable with `install --start`; it starts the local proxy before switching Codex config.
- Enable also installs one user-level Codex `SessionStart` hook in `~/.codex/hooks.json` and enables
  the Codex hooks feature flag. Newer Codex builds use `features.hooks = true`; older docs/builds
  may refer to `features.codex_hooks`. During the CLI/App transition, write both keys and treat
  either key as enabled. The hook starts a missing proxy on future Codex sessions only when the
  recorded provider still points to the local proxy. It must not restart an already healthy proxy
  just because runtime code is stale. Current Codex builds may also require a trusted hook state
  entry, so treat `startup_hook: true` as installed, enabled, and trusted; if `startup_hook_trust`
  reports `modified` or `untrusted`, rerun enable/update instead of relying on `~/.codex/hooks.json`
  alone.
- After an enabled update, `install --start` compares the running proxy runtime with the installed
  code and restarts stale proxy runtime before returning when config still points to the local proxy.
  Codex may fire `SessionStart` for each new or resumed session; `autostart --quiet` does not log
  normal no-op checks and does not refresh stale runtime implicitly.
- Do not run plain `install` to enable the proxy; the manager rejects config switching without `--start`.
- Default service tier policy is `auto`: ChatGPT-login or unclear states preserve Codex App/CLI Fast
  choices, while API-key mode can inject priority when Codex omits `service_tier` because the App
  Fast UI may not be available. Use `--service-tier-policy inject_missing` only when the user
  explicitly asks for global Fast injection and accepts that Codex App's Fast UI toggle will no
  longer control missing tiers. Use `--service-tier-policy preserve` only when the user explicitly
  wants no proxy-side Fast injection.
- Before first enable or model-path setting changes, `install --start` verifies the candidate
  upstream and auth source with one side-path Codex-style `POST /v1/responses` request using
  `stream=true`. If verification fails, do not pass `--no-verify` unless the user explicitly accepts
  that future Codex model requests may fail.
- Existing enabled installs that do not yet have `service_tier_policy` in settings are legacy
  global-Fast installs when they do not also have split upstream auth; preserve that behavior as
  `inject_missing` unless the user explicitly asks for App-controlled Fast. Missing policy plus
  split upstream auth belongs to the ChatGPT-login auth split path and should be treated as
  App-controlled `preserve`.
- For ChatGPT account login compatibility, prefer the proxy-managed provider auth file over editing
  `auth.json`, passing literal keys, or writing global user environment variables. This makes the
  proxy replace the upstream model-provider `Authorization` header for requests already routed
  through the local proxy while leaving ChatGPT plugin/GitHub/App connector requests alone. In this
  override mode, the proxy also drops unexpected `Cookie` headers before forwarding provider API
  requests. Existing `--upstream-api-key-env <ENV_NAME>` installs remain supported as an advanced
  compatibility path.
- When the user wants ChatGPT login compatibility, run `prepare-chatgpt-login` as a dry run first.
  It may find the current working provider key in `auth.json` or the environment, but it must not
  print the key. Report the non-secret JSON fields, ask for approval, then run
  `prepare-chatgpt-login --apply`. After apply, run `set-upstream --use-provider-auth-file` so a
  streaming `/v1/responses` side-path verification succeeds before settings are saved.
- If `set-upstream --use-provider-auth-file` returns `restart_required=true` or a following
  `status` reports `needs_restart=true`, do not tell the user they can sign in with ChatGPT yet.
  Explain that provider auth was verified and saved, but the running proxy has not loaded the new
  override yet. The user must restart Codex App or explicitly allow `python -m codex_fast_proxy start`
  before signing in with ChatGPT.
- After provider auth split is active and `status.needs_restart=false`, tell the user they can sign
  in with ChatGPT, and report the `chatgpt_login_windows_troubleshooting` JSON field when present.
- If proxy startup or config switching fails, the manager restores the backed-up config before returning.
- Use `set-upstream` when the user wants to change the provider URL, upstream auth source, or
  service tier policy while the proxy is already enabled. It must keep Codex config pointed at the
  local proxy, update the saved settings and uninstall baseline, and refuse to run if config no
  longer points to the recorded proxy.
  Do not pass `--restart` unless the user explicitly accepts that restarting the proxy can interrupt
  current proxy-backed Codex sessions. Without `--restart`, tell the user to restart Codex App, open a
  new CLI process, or run `start` later to apply the new upstream.
- Use `verify-upstream` when the user asks to test a candidate upstream or auth source without
  changing local state. It must run the same streaming `/v1/responses` side-path check as
  `set-upstream`, then stop without writing settings, editing Codex config, installing hooks, or
  restarting the proxy.
- Do not edit the active provider `base_url` directly while the proxy is enabled. For ChatGPT login
  compatibility, configure upstream provider auth with `prepare-chatgpt-login --apply` and
  `set-upstream --use-provider-auth-file` rather than editing `auth.json`. Model, reasoning, and other Codex config fields can still be
  edited directly by the user or agent.
- Running Codex processes do not hot-switch provider config. After enable, restart Codex App and resume the same conversation if desired, or open a new CLI process.
- If the current process is already using the proxy, stopping the proxy can interrupt the conversation. Disable with `uninstall --defer-stop`, tell the user to restart Codex App or open a new CLI process, then run uninstall again to finish cleanup.
- If uninstall output has `status="confirmation_required"`, no uninstall changes were applied.
  Report `direct_upstream_auth_warning` first. Ask whether the user wants to keep the proxy enabled,
  switch Codex App back to API-key/third-party provider auth before uninstalling, or explicitly
  continue despite the ChatGPT-login direct-upstream 401 risk. Only after explicit confirmation,
  rerun with `--confirm-chatgpt-direct-uninstall`.
- If confirmed uninstall output includes `direct_upstream_auth_warning`, report it before any restart
  instruction. Restored direct upstream mode no longer has the proxy auth override; if Codex App
  remains signed in with ChatGPT, a third-party provider may receive ChatGPT auth and return 401.
  Tell the user to switch back to API-key/third-party provider auth before restarting, or keep the
  proxy enabled if they want ChatGPT-login UI with a third-party provider.
- Uninstall removes only the `codex-fast-proxy` hook and must preserve unrelated hooks.
- Do not run `stop` while Codex config still points to the proxy unless the user explicitly accepts that current and future sessions may fail.
- Run `benchmark` only when the user explicitly asks for an A/B check or confirms the cost. The
  default benchmark uses `codex-cli` mode: it starts a local forwarding capture proxy, launches real
  `codex exec` requests, and runs three interleaved default-vs-priority pairs against the saved
  upstream. It can consume noticeable token quota. It uses existing Codex/provider authentication
  when available, records upstream latency without storing response content, and should compare
  full-response latency even when the provider response does not expose `service_tier`.
- When the user asks whether their provider supports Fast/Priority, run or request enough input to run
  `benchmark` with the default `full` profile. Do not use normal proxy logs, `service_tier_injected=true`, or HTTP 200 responses as
  proof of provider Fast support; those only prove the proxy sent a successful request. If automatic
  auth discovery cannot find a key in env/provider config/`~/.codex/auth.json`, ask the user for the
  API key environment variable name and rerun with `--api-key-env`.
- The default benchmark timeout is 600 seconds per sample. If `full` benchmark reports
  `TimeoutExpired`, rerun with a larger explicit timeout such as `--timeout 900` before drawing a
  stability conclusion.
- `status` and `doctor` include a local health check and runtime check; treat `healthy=false` as a
  reason to stop and diagnose before continuing. If `status.needs_restart=true` after update, tell
  the user to restart Codex App, open a new CLI process after the old proxy is gone, or run
  `python -m codex_fast_proxy start` when it is safe to refresh runtime code. The startup hook should
  not restart an already healthy proxy just because runtime code is stale.
- If the user asks only to check for updates, run `check-update` and stop. It is read-only and must
  not pull, install, restart the proxy, edit Codex config, or write proxy state.
- After a successful enable, report the JSON result, the top-level `next_user_action`, and the
  `chatgpt_login_hint` message. If `chatgpt_login_hint.status=optional_setup_available`, tell the
  user they can keep API-key mode for third-party API plus global Fast, and should run
  `prepare-chatgpt-login` before switching Codex App to ChatGPT login for plugin marketplace,
  GitHub/Apps/connectors, manual Fast controls, status hints, and voice input. Avoid chaining
  unrelated work in the same turn.

## Sandbox and approval discipline

- Operations that clone from GitHub, install with `pip`, create `~/.agents` skill links, write `~/.codex/config.toml`, write `~/.codex/hooks.json`, start a background proxy, or remove installed files may need user approval or elevated sandbox permissions.
- If the harness supports escalation, request approval for the intended command instead of trying alternate paths.
- If a command fails because of network, permissions, sandbox write limits, skill link creation, or background-process restrictions, stop and rerun the same intended action with approval. Do not invent workarounds that bypass the user's sandbox policy.
- Do not print API keys, request bodies, prompts, or Codex history. Do not edit `auth.json` unless
  the user explicitly asks for a recovery action; prefer copying the current working provider key to
  the proxy-managed provider auth file with `prepare-chatgpt-login --apply`.

## User handoff messages

- After `.codex/INSTALL.md` or `.codex/UPDATE.md` changes skill files, explicitly tell the user to restart Codex App and return to the conversation, or open a new CLI process, so Codex can rescan `~/.agents/skills`; then ask Codex to enable Codex Fast proxy.
- After `.codex/UNINSTALL.md`, explicitly tell the user to restart Codex App, or open a new CLI process, so Codex removes `codex-fast-proxy` from the skill list.
- After a successful `install --start`, explicitly tell the user that Fast proxy is enabled, but the current Codex process will not hot-switch; they should restart Codex App and return to the conversation, or open a new CLI process.
- After a successful `install --start`, always append this optional ChatGPT-login UI note even if
  the status summary is already long: the user may keep API-key mode for third-party API plus global Fast. If they want richer Codex App UI such as plugin marketplace, GitHub/Apps/connectors, manual Fast controls, status hints, and voice input, they should run `prepare-chatgpt-login` before switching Codex App to ChatGPT login; switching directly may cause 401.
- After `uninstall --defer-stop` returns `status="confirmation_required"`, explicitly tell the user
  no uninstall changes were applied because ChatGPT login appears active and direct upstream may
  return 401. Do not tell the user to restart yet.
- After `uninstall --defer-stop` returns `status="uninstalled"`, explicitly tell the user that Codex
  config has been restored to direct upstream, and the proxy was left running temporarily to avoid
  interrupting the current process. They should restart Codex App and return to the conversation, or
  open a new CLI process, then run uninstall again to finish cleanup.
- If `direct_upstream_auth_warning` is present after a confirmed uninstall, first warn that ChatGPT
  login appears active. After direct upstream restore, requests no longer pass through the proxy
  upstream auth override. Keeping ChatGPT login may send ChatGPT auth to the third-party provider
  and return 401. The user should switch back to API-key/third-party provider auth before
  restarting, or keep the proxy enabled for ChatGPT-login UI with a third-party provider.

Use `--provider <name>` only when the user names a provider or when `doctor` reports that no active provider can be selected.

Use `--upstream-base <url>` only when Codex config does not contain a usable provider `base_url` or the user explicitly wants a different upstream.
Use `--upstream-api-key-env <ENV_NAME>` only as an advanced compatibility path with an environment variable name, never a literal key value.
Use `--clear-upstream-auth` when the user wants to stop overriding upstream Authorization and
return to Codex's original provider auth behavior.

For upstream URL changes after enable, prefer `set-upstream --upstream-base <url>` over rerunning
`install --start --upstream-base <url>`.

## Result handling

- Treat the JSON output as the source of truth.
- Report `provider`, `base_url`, `upstream_base`, `service_tier_policy`, `upstream_auth`, `running`,
  `diagnosis`, `provider_auth_preparation`, `chatgpt_login_hint`, `next_user_action`,
  `chatgpt_login_windows_troubleshooting` when present, `runtime_matches`, `needs_restart`, and
  backup or restore status.
- Use `status.runtime` when diagnosing stale runtime, wrong Python executable, or a startup hook that
  points at a different checkout. Do not infer hook readiness from `~/.codex/hooks.json` alone.
- For App-specific traffic checks, use recent `/v1/responses` events as model-generation evidence.
  Treat `GET /v1/models` as provider metadata checks; do not report isolated `/v1/models` failures as
  model-generation failure unless `/v1/responses` also fails.
- Do not print API keys, `auth.json`, request bodies, prompts, or Codex history.
- For benchmark results, report profile, medians, observed speedup, `priority_accepted`,
  `observed_priority_effective`, provider-confirmed priority metadata when present, sample counts,
  `service_tier_control.valid`, and errors. Prioritize full-response total latency and first-output
  latency over first-event/TTFB.
  Treat `priority_accepted=true` as proof that the wire parameter is accepted, and
  `observed_priority_effective=true` as proof that this measured workload benefited. Report
  `benchmark_mode` and do not present Codex CLI/app-server benchmark results as an App-specific
  guarantee. For App-specific verification, use recent diagnostics/proxy traffic after the user sends
  an App message. `priority_accepted=true` means at least one priority sample succeeded; always
  report the displayed `ok/count` sample counts with it. Do not claim a guaranteed speedup from a
  single run.
- If install or update changed the skill files, tell the user to restart Codex.

## Expected behavior

- `install --start` backs up `~/.codex/config.toml`.
- The selected provider's original `base_url` becomes `upstream_base`.
- The selected provider's `base_url` becomes `http://127.0.0.1:8787/v1`.
- Before switching config on first enable, `install --start` verifies a streaming `/v1/responses`
  request against the candidate upstream/auth route unless the user explicitly accepted
  `--no-verify`.
- `verify-upstream` reports the same candidate route validation without changing persistent state.
- `set-upstream` updates the saved `upstream_base`, service tier policy, upstream auth source, and
  uninstall recovery baseline without changing model, reasoning, tools, input, or literal
  API key values. Before writing settings, it sends one side-path Codex-style `POST /v1/responses`
  request with `stream=true` to the candidate upstream/auth source. This is real provider traffic;
  if it fails, do not add `--no-verify` unless the user explicitly accepts that future Codex
  requests may break. It applies immediately only when the proxy is not running or the user
  explicitly accepted `--restart`; otherwise it defers restarting a running proxy to avoid cutting
  off the current response.
- A `SessionStart` hook calls the current Python executable with
  `-m codex_fast_proxy autostart --quiet` on future Codex sessions.
- By default `auto` preserves Codex App/CLI `service_tier` choices in ChatGPT-login or unclear
  states, and can inject `service_tier="priority"` in API-key mode when that field is absent. Only
  explicit `inject_missing` forces global Fast regardless of login mode.
- Optional upstream auth split applies to proxied provider API requests, not to ChatGPT plugin,
  GitHub, Apps, connector, cookie, or token traffic; override mode replaces `Authorization` and drops
  unexpected `Cookie` headers before forwarding upstream.
- `benchmark` compares synthetic Codex-style requests with no `service_tier` against
  `service_tier="priority"`. The default `codex-cli` mode is intended to measure real Codex
  acceleration; `--profile smoke` is only for low-cost connectivity checks, and `--mode direct` is a
  less representative fallback when Codex CLI is unavailable. It stores only redacted metrics in
  `~/.codex/codex-fast-proxy-state/state/fast_proxy.benchmark.json`. Local diagnostics show the
  latest saved benchmark summary and never starts benchmark runs.
- `uninstall` restores the full backup when the current config still matches the installed state.
- If the config changed but the selected provider still points to the local proxy, `uninstall` restores only that provider's `base_url` to `upstream_base` and preserves other config changes.
- If ChatGPT login is active and uninstall would newly restore direct upstream, `uninstall` returns
  `status="confirmation_required"` before changing config, hooks, proxy process, or files unless
  `--confirm-chatgpt-direct-uninstall` is explicit.
- If `uninstall` reports `config_restore="skipped_config_changed"`, do not delete the package or repo; the selected provider no longer points to the recorded proxy, so ask the user before using `--force`.
