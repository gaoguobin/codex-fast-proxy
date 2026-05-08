# Advanced Usage

This document keeps command-level details out of the main README. Most users should prefer the
natural-language workflows in [README.md](../README.md).

## Common Commands

Run the manager as the source of truth:

```powershell
python -m codex_fast_proxy doctor
python -m codex_fast_proxy install --start
python -m codex_fast_proxy status
python -m codex_fast_proxy check-update
python -m codex_fast_proxy benchmark
python -m codex_fast_proxy start
python -m codex_fast_proxy stop --force
python -m codex_fast_proxy uninstall --defer-stop
python -m codex_fast_proxy uninstall
```

Default paths:

| Item | Path |
| --- | --- |
| Local proxy base URL | `http://127.0.0.1:8787/v1` |
| Repository install | `~/.codex/codex-fast-proxy` |
| Runtime state | `~/.codex/codex-fast-proxy-state` |
| Startup hook | `~/.codex/hooks.json` |
| Logs | `~/.codex/codex-fast-proxy-state/state/fast_proxy.jsonl` |
| Config backups | `~/.codex/backups/codex-fast-proxy` |

## Status And Dashboard

```powershell
python -m codex_fast_proxy status
```

Healthy enabled state should include:

- `healthy=true`
- `config_matches=true`
- `startup_hook=true`
- `startup_hook_trust.ready=true`
- `runtime_matches=true`
- `needs_restart=false`

Useful status fields:

- `diagnosis`: top-level operational judgment.
- `fast_behavior`: `app_controlled`, `auto_global_priority`, `global_priority`, `preserve_only`, or
  `unknown_conservative`.
- `provider_auth_preparation`: whether provider auth is ready for optional ChatGPT login.
- `chatgpt_login_hint` and `next_user_action`: user-facing next step.
- `runtime`: manager source path, running proxy runtime, and startup hook command.

Dashboard URL:

```text
http://127.0.0.1:8787/v1
```

The dashboard is read-only and redacted. It groups `GET /v1/models` as provider metadata checks so
they do not crowd out real model-generation traffic.

## ChatGPT Login Compatibility

Codex App plugin, GitHub, Apps/connectors, manual Fast controls, status hints, and voice input can
depend on ChatGPT account login. Third-party provider model requests should still use the provider
key, not ChatGPT account auth.

Dry-run provider key discovery:

```powershell
python -m codex_fast_proxy prepare-chatgpt-login
```

Apply a Windows user environment variable after reviewing the dry-run result:

```powershell
python -m codex_fast_proxy prepare-chatgpt-login --target-env PACKY_API_KEY --apply
```

Save and verify proxy auth split:

```powershell
python -m codex_fast_proxy set-upstream --upstream-api-key-env PACKY_API_KEY
python -m codex_fast_proxy status
```

If `restart_required=true` or final `status.needs_restart=true`, do not sign in with ChatGPT yet.
Restart Codex App, open a new CLI process, or explicitly refresh the proxy:

```powershell
python -m codex_fast_proxy start
```

To clear an auth override and return to Codex's original provider `Authorization` behavior:

```powershell
python -m codex_fast_proxy set-upstream --clear-upstream-api-key-env
```

Windows login callback troubleshooting:

```powershell
net stop winnat
netsh interface ipv4 show excludedportrange protocol=tcp
net start winnat
netsh interface ipv4 show excludedportrange protocol=tcp
```

Use those commands only if ChatGPT login fails with `OSError: [WinError 10013] ... socket ...`.

## Change Upstream Or Fast Policy

Do not edit the active provider `base_url` directly while the proxy is enabled. It should keep
pointing to the local proxy. Change the saved upstream instead:

```powershell
python -m codex_fast_proxy set-upstream --upstream-base https://api.example.com/v1
```

Read-only upstream verification:

```powershell
python -m codex_fast_proxy verify-upstream --upstream-base https://api.example.com/v1
```

Fast policy:

```powershell
python -m codex_fast_proxy set-upstream --service-tier-policy auto
python -m codex_fast_proxy set-upstream --service-tier-policy preserve
python -m codex_fast_proxy set-upstream --service-tier-policy inject_missing
```

Policy meaning:

- `auto`: API-key mode can inject missing priority; ChatGPT-login or unclear states preserve Codex's
  choice.
- `preserve`: never inject service tier.
- `inject_missing`: inject `service_tier="priority"` only when missing.

`set-upstream` sends one side-path Codex-style `POST /v1/responses` request with `stream=true`
before writing settings unless explicitly told otherwise. This is real provider traffic and can
consume a small amount of quota.

## Benchmark

Natural-language trigger:

```text
Run the Codex Fast proxy A/B benchmark
```

Command:

```powershell
python -m codex_fast_proxy benchmark
```

The default benchmark uses `codex-cli` mode. It launches real `codex exec` requests through a local
capture proxy and compares interleaved default-vs-priority samples. It stores redacted metrics only.

Useful options:

```powershell
python -m codex_fast_proxy benchmark --timeout 900
python -m codex_fast_proxy benchmark --profile smoke
python -m codex_fast_proxy benchmark --mode direct
python -m codex_fast_proxy benchmark --api-key-env PACKY_API_KEY
```

Interpretation:

- `priority_accepted=true`: at least one priority sample succeeded.
- `observed_priority_effective=true`: the measured workload benefited.
- `provider_confirmed_priority=true`: provider response metadata explicitly confirmed priority when
  available.
- Always read those flags together with sample counts and errors.

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

If an update changes skill files, restart Codex App or open a new CLI process so skill discovery
reloads. If the proxy is enabled, the update workflow reruns `install --start`; it may refresh stale
runtime when safe.

## Uninstall

Follow the remote uninstall workflow:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UNINSTALL.md
```

Two-phase uninstall:

1. If ChatGPT login is active and direct upstream may 401, the first run stops with
   `status="confirmation_required"` before changing config, hooks, proxy process, or files.
2. After explicit confirmation, or when no ChatGPT direct-upstream risk is detected, the first run
   restores Codex config to direct upstream and removes the startup hook.
3. It may leave the proxy process alive so the current proxy-backed session can finish.
4. Restart Codex App or open a new CLI process.
5. Run uninstall again to stop the remaining proxy and remove files.

If uninstall reports `status="confirmation_required"`, no uninstall changes were applied. Keep the
proxy enabled, switch Codex App back to API-key/third-party auth before uninstalling, or explicitly
continue with:

```powershell
python -m codex_fast_proxy uninstall --defer-stop --confirm-chatgpt-direct-uninstall
```

If a confirmed uninstall reports `direct_upstream_auth_warning`, Codex config has been restored to
direct upstream while ChatGPT auth still appears active. Switch back to API-key/third-party auth
before restarting, or keep the proxy enabled if you want ChatGPT-login UI with a third-party
provider.

## Terminal Recovery

Use these outside Codex if model requests are broken:

```powershell
python -m codex_fast_proxy status
python -m codex_fast_proxy start
python -m codex_fast_proxy set-upstream --clear-upstream-api-key-env
python -m codex_fast_proxy uninstall --defer-stop
```

## Safety Model

- `install --start` verifies upstream `/v1/responses` streaming route before switching config.
- The startup hook runs `codex_fast_proxy autostart --quiet` on `SessionStart`.
- The hook starts a missing proxy only when the recorded provider still points to the local proxy.
- A healthy proxy is not restarted just because runtime code is stale; use explicit `start` when you
  are ready to refresh runtime.
- `stop` refuses while Codex config still points to the proxy unless `--force` is explicit.
- Uninstall removes only the `codex-fast-proxy` hook and preserves unrelated hooks.
- Logs never include API keys, cookies, request bodies, prompts, tool arguments, or response content.

## Development

```powershell
python -m pip install --user -e .
python -m codex_fast_proxy doctor
python -m pytest
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
