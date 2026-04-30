# codex-fast-proxy upstream URL change for Codex

Use these instructions when an engineer asks Codex to change the provider URL used by an already
enabled Codex Fast proxy.

Do not edit the active provider `base_url` in `~/.codex/config.toml` directly while the proxy is
enabled. That field should keep pointing to the local proxy. API keys, model, reasoning, and other
Codex settings can still be edited in `config.toml` as usual.

If the user did not provide the new upstream URL, ask for it. Do not guess provider URLs.

If the Codex environment uses sandbox or approval controls, request approval/escalation because this
flow may write under `%USERPROFILE%\.codex`, edit `%USERPROFILE%\.codex\hooks.json`, restart the
background proxy, and update the uninstall recovery baseline.

Run this block after replacing `<UPSTREAM_BASE_URL>` with the user-provided URL:

```powershell
$statusJson = python -m codex_fast_proxy status
$status = $statusJson | ConvertFrom-Json
if ($status.config_matches -ne $true) {
    $statusJson
    throw 'Codex config no longer points to the recorded local proxy. Review ~/.codex/config.toml before changing upstream.'
}

$resultJson = python -m codex_fast_proxy set-upstream --upstream-base '<UPSTREAM_BASE_URL>'
$resultJson
python -m codex_fast_proxy status
```

Report the set-upstream JSON and the final status JSON. The key fields are `provider`, `base_url`,
`previous_upstream_base`, `upstream_base`, `config_matches`, `restart_required`, and `start_result`.

Do not use `--restart` unless the user explicitly accepts that restarting the proxy can interrupt
current proxy-backed Codex sessions. If `restart_required=true`, tell the user to restart Codex App,
open a new CLI process, or run `python -m codex_fast_proxy start` later to apply the new upstream.

If the user also changed API key environment variables, model, reasoning, or other Codex config, tell
them to restart Codex App or open a new CLI process so Codex reloads those settings.
