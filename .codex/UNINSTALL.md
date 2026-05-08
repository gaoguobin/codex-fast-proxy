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
$confirmationRequired = $false

if (Test-Path $repoRoot) {
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $statusJson = python -m codex_fast_proxy status
    $status = $statusJson | ConvertFrom-Json
    if ($status.config_matches -eq $true) {
        $uninstallJson = python -m codex_fast_proxy uninstall --defer-stop
        $uninstallResult = $uninstallJson | ConvertFrom-Json
        $uninstallJson
        if ($uninstallResult.status -eq 'confirmation_required') {
            Write-Host 'uninstall_confirmation_required=true'
            $confirmationRequired = $true
        } else {
            Write-Host 'restart_required_before_cleanup=true'
            $deferred = $true
        }
    } else {
        $uninstallJson = python -m codex_fast_proxy uninstall
        $uninstallResult = $uninstallJson | ConvertFrom-Json
        $uninstallJson
        if ($uninstallResult.status -eq 'confirmation_required') {
            Write-Host 'uninstall_confirmation_required=true'
            $confirmationRequired = $true
        } elseif ($uninstallResult.config_restore -eq 'skipped_config_changed') {
            throw 'Codex config changed after proxy install, and the selected provider no longer points to the recorded proxy. The proxy was not stopped and files were not removed. Review ~/.codex/config.toml or rerun uninstall with --force if you want to restore the recorded backup.'
        }
    }
}

if ((-not $deferred) -and (-not $confirmationRequired)) {
    python -m pip uninstall -y codex-fast-proxy

    if (Test-Path $skillNamespace) {
        cmd /d /c "rmdir `"$skillNamespace`""
    }

    if (Test-Path $repoRoot) {
        Remove-Item -LiteralPath $repoRoot -Recurse -Force
    }
}
```

Report the uninstall JSON result when available.

If the block printed `uninstall_confirmation_required=true`, no uninstall changes were applied.
Report `direct_upstream_auth_warning`, then ask the user whether they want to keep the proxy enabled
or explicitly continue uninstalling. Continue only after the user clearly accepts the ChatGPT-login
direct-upstream 401 risk; then rerun the manager with `--confirm-chatgpt-direct-uninstall`.

If the uninstall JSON has `status="uninstalled"` and includes `direct_upstream_auth_warning`, report
it before telling the user to restart Codex. This means Codex config has been restored to the direct
third-party upstream, but the current Codex auth state still looks like ChatGPT account login. Direct
upstream mode no longer has the proxy auth override, so model requests may send ChatGPT auth to the
third-party provider and fail with 401. Tell the user to switch Codex App back to
API-key/third-party provider auth before restarting, or keep the proxy enabled if they want
ChatGPT-login UI with a third-party provider.

When cleanup completed without `restart_required_before_cleanup=true`, explicitly tell the user:

```text
Restart Codex App, or open a new CLI process, so Codex removes codex-fast-proxy from the skill list.
```

If the block printed `restart_required_before_cleanup=true`, explicitly tell the user:

```text
Codex config has been restored to direct upstream, and the proxy was left running temporarily to avoid interrupting the current process. Restart Codex App and return to this conversation, or open a new CLI process, then run uninstall again to finish cleanup.
```

If the block printed `uninstall_confirmation_required=true`, explicitly tell the user:

```text
No uninstall changes were applied because ChatGPT login appears active and direct upstream mode may return 401. Keep the proxy enabled for ChatGPT-login UI with a third-party provider, switch Codex App back to API-key/third-party provider auth before uninstalling, or explicitly confirm that you want to continue uninstalling anyway.
```

If `status="uninstalled"` and `direct_upstream_auth_warning` is present, add this before the restart
instruction:

```text
Warning: ChatGPT login appears to be active. After uninstall restores direct upstream, requests no longer pass through the proxy upstream auth override. If Codex keeps using ChatGPT auth, the third-party provider may receive a ChatGPT token and return 401. Switch back to API-key/third-party provider auth before restarting, or keep the proxy enabled for ChatGPT-login UI with a third-party provider.
```
