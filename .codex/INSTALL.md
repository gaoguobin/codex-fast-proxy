# codex-fast-proxy install for Codex

Use these instructions when an engineer asks Codex to install or enable Codex App Fast proxy.

## One-paste prompt for engineers

Paste this into Codex:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md
```

## What this installs

- Git repo: `%USERPROFILE%\.codex\codex-fast-proxy`
- Python package: editable user install of `codex-fast-proxy`
- Skill namespace junction: `%USERPROFILE%\.agents\skills\codex-fast-proxy -> %USERPROFILE%\.codex\codex-fast-proxy\skills`
- Runtime state after enable: `%USERPROFILE%\.codex\codex-fast-proxy-state`

## Install steps

This install only installs files and the skill. It must not switch Codex App to the proxy.

If the Codex environment uses sandbox or approval controls, request approval/escalation for the install block because it clones from GitHub, installs a Python package, writes under `%USERPROFILE%\.codex`, and creates a junction under `%USERPROFILE%\.agents`.

If any command fails because of network, permissions, sandbox write limits, or junction creation, do not try unrelated workarounds. Ask for approval and rerun the same intended install step.

Run this PowerShell block exactly:

```powershell
$repoRoot = Join-Path $HOME '.codex\codex-fast-proxy'
$skillsRoot = Join-Path $HOME '.agents\skills'
$skillNamespace = Join-Path $skillsRoot 'codex-fast-proxy'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'git is required before installing codex-fast-proxy.'
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'python is required before installing codex-fast-proxy.'
}

if (Test-Path $repoRoot) {
    throw 'codex-fast-proxy is already installed. Follow UPDATE.md instead.'
}

if (Test-Path $skillNamespace) {
    throw 'The skill namespace junction already exists. Remove it or follow UNINSTALL.md before reinstalling.'
}

New-Item -ItemType Directory -Force -Path $skillsRoot | Out-Null
git clone https://github.com/gaoguobin/codex-fast-proxy.git $repoRoot
python -m pip install --user -e $repoRoot
cmd /d /c "mklink /J `"$skillNamespace`" `"$repoRoot\skills`""
```

## After install

Run this check in the same Codex turn:

```powershell
python -m codex_fast_proxy doctor
```

Report the JSON result in the reply. When `"ok": true`, explicitly tell the user:

```text
请重启 Codex App 并回到这个对话，或新开 CLI 实例，让它重新扫描 ~/.agents/skills；然后再说“启用 Codex Fast proxy”。
```

Do not claim the skill is available before the restart.

After restarting Codex App or opening a new CLI process, the user can ask:

- `启用 Codex Fast proxy`
- `让 Codex App 使用 Fast`
- `查看 Codex Fast proxy 状态`
- `停止 Codex Fast proxy`

## Existing install

If the repository already exists, fetch and follow:

- `https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md`
