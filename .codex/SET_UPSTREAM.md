# Codex Model Gateway model service settings for Codex

Use these instructions when an engineer asks Codex to change the model service URL or API key used
by an already enabled Codex Model Gateway installation.

## Normal path

Open the Control UI and let the user manage the provider from `供应商`:

```powershell
python -m codex_fast_proxy ui
```

If sandbox or approval controls apply, request approval/escalation for this command because it
starts a local background Control UI server that must stay alive after the launcher exits.

Report the printed URL as plain text. The UI saves through the manager, verifies a streaming
`POST /v1/responses` route before committing settings, stores API keys only in the proxy-managed
provider auth file, and never prints the key. It supports provider add, edit, switch, delete, and
masked key reveal after the proxy is enabled.
Save, edit, and switch actions verify both the upstream URL and the target key before committing.
Successful changes immediately refresh the running proxy so the next model request uses the new
URL/key; this can briefly interrupt in-flight proxy-backed requests.

Do not edit the active provider `base_url` in `~/.codex/config.toml` directly while the proxy is
enabled. That field should keep pointing to the local proxy.

## CLI fallback

Use fallback commands only when the UI cannot be opened or the user explicitly asks for automation.
If sandbox or approval controls apply, request approval because these commands may write under
`~/.codex`, refresh hooks, and update the uninstall recovery baseline.

Verify a candidate URL without changing local state:

```powershell
python -m codex_fast_proxy verify-upstream --upstream-base '<UPSTREAM_BASE_URL>'
```

Save a new upstream URL:

```powershell
python -m codex_fast_proxy set-upstream --upstream-base '<UPSTREAM_BASE_URL>'
python -m codex_fast_proxy status
```

Prepare ChatGPT-login compatible provider auth without asking the user to paste a key into chat:

```powershell
python -m codex_fast_proxy prepare-chatgpt-login
python -m codex_fast_proxy prepare-chatgpt-login --apply
python -m codex_fast_proxy set-upstream --use-provider-auth-file
python -m codex_fast_proxy status
```

Clear a proxy-managed upstream auth override:

```powershell
python -m codex_fast_proxy set-upstream --clear-upstream-auth
python -m codex_fast_proxy status
```

Do not use `--restart` unless the user explicitly accepts that restarting the proxy can interrupt
current proxy-backed Codex sessions. If `restart_required=true` or final `status.needs_restart=true`,
tell the user to restart Codex App, open a new CLI process, or run `python -m codex_fast_proxy start`
later to apply the new settings.

Never print API key values, `auth.json` contents, provider-auth file contents, ChatGPT tokens,
cookies, request bodies, or prompts.
