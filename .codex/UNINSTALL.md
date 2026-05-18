# codex-fast-proxy uninstall for Codex

Use these instructions when an engineer asks Codex to uninstall Codex App Fast proxy.

## Normal path

Open the Control UI and let the user click `停用并恢复`:

```powershell
python -m codex_fast_proxy ui
```

If sandbox or approval controls apply, request approval/escalation for this command because it
starts a local background Control UI server that must stay alive after the launcher exits.

Report the printed URL as plain text. The UI uses the manager uninstall path:

- if Codex still points to the local proxy, it restores Codex config first and defers stopping the
  proxy so the current conversation is not cut off;
- after the user restarts Codex or opens a new CLI, clicking again completes cleanup and schedules
  removal of the local runtime state, editable package, repository checkout, skill link, and backup
  directory;
- if ChatGPT login is active and direct upstream may return 401, the manager returns
  `confirmation_required` before changing files.

The normal Control UI path restores the user's familiar Codex model-service setup first, returns a
final success state to the page, and only then lets the Control UI shut down while a delayed cleanup
removes the installed repository, editable Python package, skill link, runtime state, and local
backup directory.

## CLI fallback

Use this only when the UI cannot be opened or the user explicitly asks Codex to perform cleanup. If
sandbox or approval controls apply, request approval because uninstall may restore
`~/.codex/config.toml`, edit `~/.codex/hooks.json`, and stop a background proxy.

```powershell
$pythonCmd = if (Get-Command python -ErrorAction SilentlyContinue) {
    'python'
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    'python3'
} else {
    throw 'Python 3 is required before uninstalling codex-fast-proxy.'
}
$repoRoot = Join-Path (Join-Path $HOME '.codex') 'codex-fast-proxy'
$statusJson = & $pythonCmd -m codex_fast_proxy status
$status = $statusJson | ConvertFrom-Json
if ($status.config_matches -eq $true) {
    & $pythonCmd -m codex_fast_proxy uninstall --defer-stop
    Write-Host 'restart_required_before_cleanup=true'
    return
}
& $pythonCmd -m codex_fast_proxy uninstall
```

If uninstall returns `confirmation_required`, no uninstall changes were applied. Report
`direct_upstream_auth_warning` and ask whether the user wants to keep the proxy enabled, switch back
to API-key/third-party provider auth before uninstalling, or explicitly continue despite the
ChatGPT-login direct-upstream 401 risk.

After cleanup, tell the user to restart Codex App or open a new CLI process so Codex reloads the
restored provider config. If the UI cannot be used and the user explicitly asks for complete
cleanup after the proxy has already been disabled, use the manager-owned skill unlink before
deleting files:

```powershell
if (Test-Path $repoRoot) {
    & $pythonCmd -m codex_fast_proxy unlink-skill --repo-root $repoRoot
}
& $pythonCmd -m pip uninstall -y codex-fast-proxy
if (Test-Path $repoRoot) {
    Remove-Item -LiteralPath $repoRoot -Recurse -Force
}
$backupDir = Join-Path (Join-Path (Join-Path $HOME '.codex') 'backups') 'codex-fast-proxy'
if (Test-Path $backupDir) {
    Remove-Item -LiteralPath $backupDir -Recurse -Force
}
```

Never print API key values, `auth.json` contents, ChatGPT tokens, cookies, request bodies, or prompts.
