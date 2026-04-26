# codex-fast-proxy update for Codex

Use these instructions when an engineer asks Codex to update Codex App Fast proxy.

## One-paste prompt for engineers

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md
```

## Update steps

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
} else {
    python -m codex_fast_proxy doctor
}
```

Report the final JSON result. If the skill was newly linked or changed, explicitly tell the user:

```text
请重启 Codex App 并回到这个对话，或新开 CLI 实例，让它重新扫描 ~/.agents/skills；然后再说“启用 Codex Fast proxy”。
```

If `install --start` ran during update, it refreshes `~/.codex/hooks.json` and enables Codex `SessionStart` autostart for future App/CLI starts. If a proxy process was already running before the update, do not claim that the running process has hot-reloaded. The update affects future manager commands and future proxy starts. Use `status` to report the current running state.
