# codex-fast-proxy upstream URL change for Codex

Use these instructions when an engineer asks Codex to change the provider URL used by an already
enabled Codex Fast proxy.

Do not edit the active provider `base_url` in `~/.codex/config.toml` directly while the proxy is
enabled. That field should keep pointing to the local proxy. API keys, model, reasoning, and other
Codex settings can still be edited in `config.toml` as usual.

If the user only wants to change Fast policy or ChatGPT-login upstream auth, a new upstream URL is
not required. If they want to change provider URL and did not provide the new upstream URL, ask for
it. Do not guess provider URLs.

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

`set-upstream` verifies the candidate route before writing settings by sending one side-path
Codex-style `POST /v1/responses` request with `stream=true` to the candidate upstream and auth
source. This is real provider traffic and can consume a small amount of quota. If verification
fails, do not retry with `--no-verify` unless the user explicitly accepts that the next Codex session
may be unable to reach the model.

If the user asks to verify first without changing local state, run:

```powershell
python -m codex_fast_proxy verify-upstream --upstream-base '<UPSTREAM_BASE_URL>'
```

Report the JSON result and stop. `verify-upstream` must not write settings, edit Codex config,
install hooks, or restart the proxy.

For ChatGPT login compatibility without changing the upstream URL, ask for the environment variable
name that already contains the third-party provider API key. Do not ask the user to paste the key
value into chat. This affects only provider API requests that already go through the local proxy; it
must not intercept ChatGPT plugin/GitHub/App connector traffic. In override mode, the proxy replaces
provider `Authorization` and drops unexpected `Cookie` headers before forwarding upstream.

If the user does not already have a provider key environment variable, run a dry run first:

```powershell
python -m codex_fast_proxy prepare-chatgpt-login
```

Report only the non-secret JSON fields. If the dry run found the current working provider key in
`auth.json` or the environment, ask before applying:

```powershell
python -m codex_fast_proxy prepare-chatgpt-login --target-env '<ENV_NAME>' --apply
```

The apply step writes a Windows user environment variable through the manager, does not print the
key, and does not change proxy settings. After it succeeds, continue with `set-upstream` so the
manager verifies a streaming `/v1/responses` request before saving the auth override.

```powershell
$statusJson = python -m codex_fast_proxy status
$status = $statusJson | ConvertFrom-Json
if ($status.config_matches -ne $true) {
    $statusJson
    throw 'Codex config no longer points to the recorded local proxy. Review ~/.codex/config.toml before changing upstream auth.'
}

$resultJson = python -m codex_fast_proxy set-upstream --upstream-api-key-env '<ENV_NAME>'
$resultJson
python -m codex_fast_proxy status
```

To clear a previously configured upstream auth environment override and return to preserving Codex's
original provider `Authorization` header, run:

```powershell
python -m codex_fast_proxy set-upstream --clear-upstream-api-key-env
python -m codex_fast_proxy status
```

For explicit global Fast injection without changing the upstream URL, confirm that the user accepts
that Codex App's Fast UI toggle will no longer control requests whose `service_tier` is missing, then
run:

```powershell
python -m codex_fast_proxy set-upstream --service-tier-policy inject_missing
python -m codex_fast_proxy status
```

To return to UI-controlled Fast behavior, run:

```powershell
python -m codex_fast_proxy set-upstream --service-tier-policy preserve
python -m codex_fast_proxy status
```

For the default automatic behavior, where API-key mode can use global priority but ChatGPT-login or
unclear states preserve the App/CLI choice, run:

```powershell
python -m codex_fast_proxy set-upstream --service-tier-policy auto
python -m codex_fast_proxy status
```

Report the set-upstream JSON and the final status JSON. The key fields are `provider`, `base_url`,
`previous_upstream_base`, `upstream_base`, `service_tier_policy`, `upstream_auth`, `config_matches`,
`verification`, `restart_required`, `start_result`, and `next_user_action`.

Do not use `--restart` unless the user explicitly accepts that restarting the proxy can interrupt
current proxy-backed Codex sessions. If `restart_required=true`, tell the user to restart Codex App,
open a new CLI process, or run `python -m codex_fast_proxy start` later to apply the new upstream.

For ChatGPT-login preparation, `restart_required=true` or final `status.needs_restart=true` is a
hard stop before login. The provider auth split has been verified and saved, but the running proxy
has not loaded the new auth override yet. Tell the user to restart Codex App, or explicitly allow
`python -m codex_fast_proxy start`, before signing in with ChatGPT. Do not tell the user they can
switch to ChatGPT login while `needs_restart=true`; model requests may still fail with 401.

After provider auth split is active and final `status.needs_restart=false`, the user can sign in
with ChatGPT if they want the full Codex App UI. Also mention this Windows login troubleshooting
path: if ChatGPT login fails with `OSError: [WinError 10013] ... socket ...`, ask the user to retry
after running these commands in an Administrator PowerShell:

```powershell
net stop winnat
netsh interface ipv4 show excludedportrange protocol=tcp
net start winnat
netsh interface ipv4 show excludedportrange protocol=tcp
```

If the user changed API key environment variables, model, reasoning, or other Codex config, tell
them to restart Codex App or open a new CLI process so Codex reloads those settings. The proxy can
read Windows user environment variables directly when possible, but already-running Codex processes
still may need a restart to reload their own config and environment.
