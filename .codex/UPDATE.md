# Codex Model Gateway update for Codex

Use these instructions when an engineer asks Codex to update Codex Model Gateway
(`codex-fast-proxy` package and repo).

## Bootstrap gate

Older installed versions may not yet have the Control UI update button or the `update` manager
command. Always run this gate first:

If the Codex environment uses sandbox or approval controls, request approval/escalation before
running the gate because it may fetch from GitHub, reinstall the package, refresh hooks or skill
links, and start a local background Control UI server.

```powershell
$pythonCmd = if (Get-Command python -ErrorAction SilentlyContinue) {
    'python'
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    'python3'
} else {
    throw 'Python 3 is required before updating codex-fast-proxy.'
}
$repoRoot = Join-Path (Join-Path $HOME '.codex') 'codex-fast-proxy'
if (-not (Test-Path $repoRoot)) {
    throw 'codex-fast-proxy is not installed. Follow INSTALL.md first.'
}
$hasManagerUpdate = $false
try {
    & $pythonCmd -m codex_fast_proxy update --help *> $null
    $hasManagerUpdate = ($LASTEXITCODE -eq 0)
} catch {
    $hasManagerUpdate = $false
}
if (-not $hasManagerUpdate) {
    git -C $repoRoot pull --ff-only
    & $pythonCmd -m pip install --user -e $repoRoot
    & $pythonCmd -m codex_fast_proxy update --repo $repoRoot --skip-self-update
} else {
    $checkJson = & $pythonCmd -m codex_fast_proxy check-update --repo $repoRoot
    $check = $checkJson | ConvertFrom-Json
    if ($check.update_available -eq $true) {
        & $pythonCmd -m codex_fast_proxy update --repo $repoRoot
    } else {
        & $pythonCmd -m codex_fast_proxy ui
    }
}
```

If the gate ran `update`, report the returned update JSON. That bootstrap is the update; after it
succeeds, tell the user future updates should use the Control UI.

If the gate opened the Control UI, report the printed URL and ask the user to click `更新`. Do not
run another UI command in the same turn.

## Normal path

Open the Control UI and let the user click `更新`:

```powershell
python -m codex_fast_proxy ui
```

If sandbox or approval controls apply, request approval/escalation for this command because it
starts a local background Control UI server that must stay alive after the launcher exits.

Report the printed URL as plain text:

```text
请在外部浏览器中打开：http://127.0.0.1:<port>/
```

The UI action delegates to `python -m codex_fast_proxy update`; it owns git pull, editable reinstall,
skill link refresh, enabled-runtime refresh, and final status reporting. Do not reimplement those
steps in chat. If local changes exist, the update must stop with `status=blocked` and
`code=local_changes`; do not overwrite the user's worktree.

After an update, reopen or reload the Control UI and verify the visible user state. The current UI
uses pages for Overview, Providers, Requests, Advanced, and Settings. The Advanced page should
expose status summary, log paths, self-check, copy diagnostics, and diagnostic file export. The
Settings page should expose language, appearance, check-update, and update controls from the
lower-left navigation entry.

## Check only

If the user only asks whether an update is available, run this read-only command and stop:

```powershell
python -m codex_fast_proxy check-update
```

Report `relation`, `update_available`, `local_changes`, and `next_action`.

## CLI fallback

Use this only when the Control UI cannot be opened or the user explicitly asks Codex to perform the
update.

If the Codex environment uses sandbox or approval controls, request approval/escalation because this
fetches from GitHub, reinstalls a Python package, writes under `~/.codex`, may refresh
`~/.codex/hooks.json`, and may create a skill link under `~/.agents`.

```powershell
& $pythonCmd -m codex_fast_proxy update --repo $repoRoot --skip-self-update
```

Use the returned JSON as the source of truth. Tell the user to restart Codex only when
`restart_required=true`, final `needs_restart=true`, or the result explicitly reports that Codex must
rescan skills. If the update refreshed skill files, also mention that a Codex App restart or new CLI
process may be needed before natural-language skill discovery sees the latest instructions.

Never print API key values, `auth.json` contents, provider-auth file contents, ChatGPT tokens,
cookies, request bodies, or prompts.
