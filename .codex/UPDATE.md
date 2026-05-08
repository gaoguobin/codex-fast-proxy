# codex-fast-proxy update for Codex

Use these instructions when an engineer asks Codex to update Codex App Fast proxy.

## One-paste prompt for engineers

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md
```

## Update steps

If the user only asks to check whether an update is available, run this read-only command and stop:

```powershell
python -m codex_fast_proxy check-update
```

Report the JSON, including `relation`, `update_available`, `local_changes`, and `next_action`. If
`relation=local_ahead`, do not report it as an available update. Do not pull, install, restart the
proxy, edit Codex config, or write proxy state unless the user then explicitly asks to update.

If the Codex environment uses sandbox or approval controls, request approval/escalation for the update block because it fetches from GitHub, installs a Python package, may write under `%USERPROFILE%\.codex`, may write `%USERPROFILE%\.codex\hooks.json`, and may create a junction under `%USERPROFILE%\.agents`.

If any command fails because of network, permissions, sandbox write limits, or junction creation, do not try unrelated workarounds. Ask for approval and rerun the same intended update step.

Run this PowerShell block exactly:

```powershell
$repoRoot = Join-Path $HOME '.codex\codex-fast-proxy'
$skillNamespace = Join-Path $HOME '.agents\skills\codex-fast-proxy'
$status = $null

if (-not (Test-Path $repoRoot)) {
    throw 'codex-fast-proxy is not installed. Follow INSTALL.md first.'
}

git -C $repoRoot pull --ff-only
python -m pip install --user -e $repoRoot

if (-not (Test-Path $skillNamespace)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $skillNamespace) | Out-Null
    cmd /d /c "mklink /J `"$skillNamespace`" `"$repoRoot\skills`""
}

$statusJson = python -m codex_fast_proxy status
$status = $statusJson | ConvertFrom-Json
if ($status.config_matches -eq $true) {
    python -m codex_fast_proxy install --start
    python -m codex_fast_proxy status
} else {
    python -m codex_fast_proxy doctor
}
```

Report the install JSON and the final status JSON when the proxy was already enabled; use the final
status JSON as the current state. If the skill was newly linked or changed, explicitly tell the user:

```text
Restart Codex App and return to this conversation, or open a new CLI process, so Codex can rescan ~/.agents/skills. Then ask Codex to enable Codex Fast proxy.
```

If `install --start` ran during update, it refreshes `~/.codex/hooks.json` and enables Codex `SessionStart` autostart for future App/CLI starts. It also compares the running proxy runtime with the installed code; if the proxy is healthy but stale, explicit `install --start`/`start` may restart the proxy before returning. Use the final `status` output to report `runtime_matches` and `needs_restart`. If `status.needs_restart` is still `true`, tell the user to restart Codex App, open a new CLI process after the old proxy is gone, or run `python -m codex_fast_proxy start` when it is safe to refresh runtime code. Codex may fire `SessionStart` for each new or resumed session; `autostart --quiet` does not restart an already healthy proxy just because runtime code is stale, and it does not log normal no-op checks.

Current Codex builds may require trusted user hooks. After update, `startup_hook: true` means the
hook exists, is enabled, and its current command hash is trusted. If `startup_hook_trust` reports
`modified` or `untrusted`, rerun `python -m codex_fast_proxy install --start` before asking the user
to rely on autostart.

Current behavior after update:

- New installs default to `auto`: ChatGPT-login or unclear states preserve Codex App/CLI Fast UI
  choices, while API-key mode can use global priority when Codex omits `service_tier`.
- Existing `service_tier_policy` and `upstream_api_key_env` settings are preserved during
  `install --start`.
- Older installs that never recorded `service_tier_policy` and do not have `upstream_api_key_env`
  are treated as `inject_missing` to keep their previous global Fast behavior. Missing policy plus
  `upstream_api_key_env` is treated as App-controlled `preserve`, because that shape belongs to the
  ChatGPT-login auth split path. If the user explicitly wants auto behavior, run:

```powershell
python -m codex_fast_proxy set-upstream --service-tier-policy auto
```

  Do not pass `--restart` unless the user accepts interrupting current proxy-backed Codex sessions.

- For ChatGPT login compatibility after update, first prepare the provider key env without printing
  the key, then configure only the upstream API key environment variable name:

```powershell
python -m codex_fast_proxy prepare-chatgpt-login
python -m codex_fast_proxy prepare-chatgpt-login --target-env PACKY_API_KEY --apply
python -m codex_fast_proxy set-upstream --upstream-api-key-env PACKY_API_KEY
```

  The first command is a dry run. Run the `--apply` command only after the user approves writing a
  Windows user environment variable. Do not pass `--restart` unless the user accepts interrupting
  current proxy-backed Codex sessions.

Never print API key values, `auth.json` contents, ChatGPT tokens, cookies, request bodies, or prompts.
