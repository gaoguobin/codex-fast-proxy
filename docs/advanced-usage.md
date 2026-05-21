# Advanced Usage

This document keeps command-level details out of the main README. Most users should prefer the
Control UI and natural-language workflows in [README.md](../README.md).

## Common Commands

Run the manager as the source of truth:

```powershell
python -m codex_fast_proxy ui
python -m codex_fast_proxy status
python -m codex_fast_proxy doctor
python -m codex_fast_proxy install --start
python -m codex_fast_proxy install --start --use-provider-auth-file
python -m codex_fast_proxy start
python -m codex_fast_proxy check-update
python -m codex_fast_proxy update
python -m codex_fast_proxy benchmark
python -m codex_fast_proxy benchmark --kind strict
python -m codex_fast_proxy uninstall
```

On macOS/Linux, use `python3 -m codex_fast_proxy ...` if `python` is not installed.

Default paths:

| Item | Path |
| --- | --- |
| Control UI | Auto-selected `http://127.0.0.1:8786/` unless the port is busy |
| Local proxy base URL | Auto-selected `http://127.0.0.1:<port>/v1`, starting at `8787` |
| Repository install | `~/.codex/codex-fast-proxy` |
| Runtime state | `~/.codex/codex-fast-proxy-state` |
| Provider auth file | `~/.codex/codex-fast-proxy-state/provider-auth.json` |
| Startup hook | `~/.codex/hooks.json` |
| Logs | `~/.codex/codex-fast-proxy-state/state/fast_proxy.jsonl` |
| Config backups | `~/.codex/backups/codex-fast-proxy` |

## Control UI

Start the independent Control UI:

```powershell
python -m codex_fast_proxy ui
```

The UI is a lightweight Python SSR page with native JavaScript. It supports:

- Chinese, English, and Japanese locale switching. Chinese is the default.
- System, light, and dark appearance.
- Overview, Providers, Requests, Advanced, and Settings pages.
- Settings stays in the lower-left navigation area on desktop, uses segmented language and
  appearance controls, and exposes one software-update action that checks first and updates only
  when a release is available.
- Provider management after the proxy is enabled.
- Provider availability checks from the Providers page.
- Masked API keys with explicit reveal.
- Advanced self-check via `/api/doctor`.
- Copy and diagnostic file export for redacted diagnostics.

Proxy-side speed controls appear inline on Overview only when they are useful. If Codex is signed in
with ChatGPT, speed is handled by Codex App's native UI and the proxy-side control is hidden.

The UI writes through token-protected loopback endpoints only. It rejects non-loopback hosts and
cross-origin writes.

## Status And Diagnostics

```powershell
python -m codex_fast_proxy status
python -m codex_fast_proxy doctor
```

Healthy enabled state should include:

- `healthy=true`
- `config_matches=true`
- `startup_hook=true`
- `startup_hook_trust.ready=true`
- `runtime_matches=true`
- `needs_restart=false`
- `upstream_api_key_source="provider_auth_file"` when ChatGPT login uses provider-auth split

Useful status fields:

- `diagnosis`: top-level operational judgment.
- `user_state`: Control UI state, primary action, and user-facing message.
- `providers`: provider inventory shown in the Providers page.
- `fast_behavior`: `app_controlled`, `auto_global_priority`, `global_priority`, `preserve_only`, or
  `unknown_conservative`.
- `provider_auth_preparation`: whether provider auth is ready for optional ChatGPT login.
- `chatgpt_login_hint` and `next_user_action`: user-facing next step.
- `runtime`: manager source path, running proxy runtime, and startup hook command.

The old proxy-hosted diagnostics page remains an advanced read-only fallback. It groups
`GET /v1/models` as provider metadata checks so they do not crowd out real model-generation
traffic. Ordinary users should open the independent Control UI instead.

## Provider Management

Before enable, the Providers page is read-only and shows provider entries from Codex `config.toml`.

After enable, the Providers page manages proxy-owned provider state:

- Add provider: saves upstream URL and API key to the provider auth file after verification.
- Edit current provider: updates the saved upstream and restarts the proxy after verification.
- Switch provider: verifies the target and updates proxy settings without mutating Codex
  `config.toml`.
- Delete provider: removes an inactive proxy-owned saved entry. The current provider cannot be
  deleted.

Do not edit the active provider `base_url` directly while the proxy is enabled. It should keep
pointing to the local proxy. Change the saved upstream through the UI or:

```powershell
python -m codex_fast_proxy set-upstream --upstream-base https://api.example.com/v1
```

`set-upstream`, provider save, and provider switch send one side-path Codex-style
`POST /v1/responses` request with `stream=true` before writing settings unless explicitly told
otherwise. This is real provider traffic and can consume a small amount of quota.

## ChatGPT Login Compatibility

Codex App plugin marketplace, GitHub, Apps/connectors, manual Fast controls, status hints, and
voice input can depend on ChatGPT account login. Third-party provider model requests should still
use the provider key, not ChatGPT account auth.

Dry-run provider key discovery:

```powershell
python -m codex_fast_proxy prepare-chatgpt-login
```

Copy the current working provider key into the proxy provider auth file after reviewing the dry-run
result:

```powershell
python -m codex_fast_proxy prepare-chatgpt-login --apply
```

Save and verify proxy auth split:

```powershell
python -m codex_fast_proxy set-upstream --use-provider-auth-file
python -m codex_fast_proxy status
```

The auth file is proxy-owned, not part of Codex's `auth.json`, and key values are never printed by
status, doctor, diagnostics export, or logs. Existing `--upstream-api-key-env <ENV_NAME>` setups
remain supported as an advanced compatibility path.

If `restart_required=true` or final `status.needs_restart=true`, do not sign in with ChatGPT yet.
Restart Codex App, open a new CLI process, or refresh the proxy:

```powershell
python -m codex_fast_proxy start
```

To clear an auth override and return to Codex's original provider `Authorization` behavior:

```powershell
python -m codex_fast_proxy set-upstream --clear-upstream-auth
```

Windows login callback troubleshooting:

```powershell
net stop winnat
netsh interface ipv4 show excludedportrange protocol=tcp
net start winnat
netsh interface ipv4 show excludedportrange protocol=tcp
```

Use those commands only if ChatGPT login fails with `OSError: [WinError 10013] ... socket ...`.

## Fast Policy

Fast policy:

```powershell
python -m codex_fast_proxy set-upstream --service-tier-policy auto
python -m codex_fast_proxy set-upstream --service-tier-policy preserve
python -m codex_fast_proxy set-upstream --service-tier-policy inject_missing
```

Policy meaning:

- `auto`: API-key mode can inject missing priority; ChatGPT-login or unclear states preserve
  Codex's choice.
- `preserve`: never inject service tier.
- `inject_missing`: inject `service_tier="priority"` only when missing.

When ChatGPT login is detected, the Control UI hides proxy-side speed controls and reports
`App 控制`, because Codex App owns the speed choice.

## Benchmark

Natural-language trigger:

```text
Run the Codex Model Gateway A/B benchmark
```

Commands:

```powershell
python -m codex_fast_proxy benchmark
python -m codex_fast_proxy benchmark --kind strict
```

The default quick benchmark runs 3 direct API request pairs. Strict mode runs 12 direct request pairs
with balanced random order, per-sample prompt cache isolation, and a paired sign test. Both modes
store redacted metrics only and spend real provider quota.

Useful options:

```powershell
python -m codex_fast_proxy benchmark --timeout 900
python -m codex_fast_proxy benchmark --profile smoke
python -m codex_fast_proxy benchmark --pairs 6
python -m codex_fast_proxy benchmark --mode codex-cli
python -m codex_fast_proxy benchmark --api-key-env PACKY_API_KEY
```

Interpretation:

- `service_tier_control.valid=true`: default samples omitted `service_tier` and priority samples
  sent the expected value.
- `priority_accepted=true`: at least one priority sample succeeded.
- `priority_support_assessment.conclusion`: support-oriented result such as `confirmed`,
  `accepted_unconfirmed`, `accepted_different_tier`, or `not_accepted`.
- `statistical_test.conclusion`: latency-oriented result such as `priority_faster`,
  `no_significant_speedup`, or `insufficient_sample_size`.
- `provider_confirmed_priority=true`: provider response metadata explicitly confirmed priority when
  available.
- `observed_priority_effective=true`: legacy compatibility flag for a simple latency threshold.
- Always read those fields together with sample counts and errors. Latency is an observation, not
  proof that the provider supports fast; provider response metadata, billing, dashboard state, or
  provider documentation are stronger support signals.

Normal proxy logs with `service_tier_injected=true` and HTTP 200 prove only that the proxy sent a
successful request. Benchmark results are the stronger signal for speed impact.

## Update

Read-only update check:

```powershell
python -m codex_fast_proxy check-update
```

Follow the remote update workflow:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md
```

The Settings page software-update action checks first. When a release is available, the same button
switches to update and delegates to `python -m codex_fast_proxy update`. The update path owns
`git pull --ff-only`, editable reinstall, skill link refresh, enabled-runtime refresh, and final
status reporting.

If local changes exist, update returns `status="blocked"` with `code="local_changes"` and does not
overwrite the worktree.

If an update changes skill files, restart Codex App or open a new CLI process so skill discovery
reloads.

## Uninstall

Follow the remote uninstall workflow:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UNINSTALL.md
```

Two-phase uninstall:

1. If ChatGPT login is active and direct upstream may 401, the first run stops with
   `status="confirmation_required"` before changing config, hooks, proxy process, or files.
2. After explicit confirmation, or when no ChatGPT direct-upstream risk is detected, uninstall
   restores Codex config to direct upstream and removes the startup hook.
3. When the current session may still depend on the proxy, the UI path can defer stopping the proxy
   until after Codex restarts.
4. Restart Codex App or open a new CLI process.
5. Run uninstall again only if cleanup is still pending.

If uninstall reports `status="confirmation_required"`, no uninstall changes were applied. Keep the
proxy enabled, switch Codex App back to API-key/third-party auth before uninstalling, or explicitly
continue with:

```powershell
python -m codex_fast_proxy uninstall --defer-stop --confirm-chatgpt-direct-uninstall
```

If confirmed uninstall reports `direct_upstream_auth_warning`, Codex config has been restored to
direct upstream while ChatGPT auth still appears active. Switch back to API-key/third-party auth
before restarting, or keep the proxy enabled if you want ChatGPT-login UI with a third-party
provider.

## Terminal Recovery

Use these outside Codex if model requests are broken:

```powershell
python -m codex_fast_proxy status
python -m codex_fast_proxy start
python -m codex_fast_proxy set-upstream --clear-upstream-auth
python -m codex_fast_proxy uninstall --defer-stop
```

## Safety Model

- `install --start` verifies upstream `/v1/responses` streaming route before switching config.
- The startup hook runs `codex_fast_proxy autostart --quiet --hook-summary` on `SessionStart`.
- The hook starts a missing proxy and opens/reuses the independent Control UI only when the recorded
  provider still points to the local proxy.
- Quiet no-op hook runs stay silent. Starts, restarts, stale runtime warnings, or Control UI
  autostarts may emit a short non-secret hook context summary for the current Codex turn.
- A healthy proxy is not restarted just because runtime code is stale; use explicit `start` when you
  are ready to refresh runtime.
- `stop` refuses while Codex config still points to the proxy unless `--force` is explicit.
- Uninstall removes only the `codex-fast-proxy` hook and preserves unrelated hooks.
- Logs and diagnostics never include API keys, cookies, request bodies, prompts, tool arguments, or
  response content.

## Development

```powershell
python -m pip install --user -e .
python -m codex_fast_proxy doctor
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
```

Run the proxy in the foreground:

```powershell
python -m codex_fast_proxy serve `
  --host 127.0.0.1 `
  --port 8787 `
  --proxy-base /v1 `
  --upstream-base https://api.example.com/v1 `
  --service-tier priority `
  --service-tier-policy auto
```
