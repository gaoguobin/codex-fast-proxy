# codex-fast-proxy uninstall for Codex

Use these instructions when an engineer asks Codex to uninstall Codex App Fast proxy.

## One-paste prompt for engineers

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UNINSTALL.md
```

## Uninstall steps

Running Codex processes do not hot-switch provider config. If this process is using the proxy, stopping it can interrupt the conversation. The block below first restores config and defers stopping when needed; after the user restarts Codex App and returns to the same conversation, or opens a new CLI process, running the same instructions finishes cleanup.

If the user changed `~/.codex/config.toml` after enabling the proxy, the manager preserves those changes when it can: when the recorded provider still points to the local proxy, it restores only that provider's `base_url` to the saved upstream.

Uninstall removes only the `codex-fast-proxy` entry from `~/.codex/hooks.json`; unrelated user hooks must be preserved.

If the Codex environment uses sandbox or approval controls, request approval/escalation for uninstall because it may restore `~/.codex/config.toml`, edit `~/.codex/hooks.json`, stop a background proxy, uninstall a Python package, remove a junction under `%USERPROFILE%\.agents`, and delete `%USERPROFILE%\.codex\codex-fast-proxy`.

If any command fails because of permissions, sandbox write limits, process locks, or junction removal, do not try unrelated workarounds. Ask for approval and rerun the same intended uninstall step.

Run this PowerShell block exactly:

```powershell
$repoRoot = Join-Path $HOME '.codex\codex-fast-proxy'
$skillNamespace = Join-Path $HOME '.agents\skills\codex-fast-proxy'
$uninstallJson = $null
$uninstallResult = $null
$status = $null
$deferred = $false

if (Test-Path $repoRoot) {
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $statusJson = python -m codex_fast_proxy status
    $status = $statusJson | ConvertFrom-Json
    if ($status.config_matches -eq $true) {
        $uninstallJson = python -m codex_fast_proxy uninstall --defer-stop
        $uninstallJson
        Write-Host 'restart_required_before_cleanup=true'
        $deferred = $true
    } else {
        $uninstallJson = python -m codex_fast_proxy uninstall
        $uninstallResult = $uninstallJson | ConvertFrom-Json
        if ($uninstallResult.config_restore -eq 'skipped_config_changed') {
            $uninstallJson
            throw 'Codex config changed after proxy install, and the selected provider no longer points to the recorded proxy. The proxy was not stopped and files were not removed. Review ~/.codex/config.toml or rerun uninstall with --force if you want to restore the recorded backup.'
        }
    }
}

if (-not $deferred) {
    python -m pip uninstall -y codex-fast-proxy

    if (Test-Path $skillNamespace) {
        cmd /d /c "rmdir `"$skillNamespace`""
    }

    if (Test-Path $repoRoot) {
        Remove-Item -LiteralPath $repoRoot -Recurse -Force
    }

    if ($uninstallJson) {
        $uninstallJson
    }
}
```

Report the uninstall JSON result when available.

When cleanup completed without `restart_required_before_cleanup=true`, explicitly tell the user:

```text
请重启 Codex App，或新开 CLI 实例，让它从 skill 列表中移除 codex-fast-proxy。
```

If the block printed `restart_required_before_cleanup=true`, explicitly tell the user:

```text
配置已恢复直连，代理暂时保留运行以避免打断当前进程；请重启 Codex App 并回到这个对话，或新开 CLI 实例后再次执行卸载完成清理。
```
