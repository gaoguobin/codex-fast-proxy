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
- Startup hook after enable: `%USERPROFILE%\.codex\hooks.json`

## Install steps

This install only installs files and the skill. It must not switch Codex App to the proxy.
The startup hook is installed later by `python -m codex_fast_proxy install --start`, not by this file-only install.

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
Restart Codex App and return to this conversation, or open a new CLI process, so Codex can rescan ~/.agents/skills. Then ask Codex to enable Codex Fast proxy.
```

Do not claim the skill is available before the restart.

After restarting Codex App or opening a new CLI process, the user can ask:

- `Enable Codex Fast proxy`
- `Prepare Codex Fast proxy for ChatGPT account login`
- `Enable global Fast injection for Codex Fast proxy`
- `Show Codex Fast proxy status`
- `Stop Codex Fast proxy`

Default enable uses `--service-tier-policy auto`. In ChatGPT-login or unclear states this respects
Codex App/CLI Fast UI choices; in API-key mode it may inject the priority tier when Codex omits
`service_tier`, because the App Fast UI may not be available. Use
`--service-tier-policy inject_missing` only when the user explicitly asks for global Fast injection,
and `--service-tier-policy preserve` only when they explicitly want no proxy-side Fast injection. If
the user wants ChatGPT login compatibility for plugins/GitHub/Apps/connectors while model requests
still use a third-party provider, configure an upstream key environment variable with
`--upstream-api-key-env <ENV_NAME>`; do not ask the user to paste API keys into chat and do not edit
`auth.json` unless they explicitly request recovery. This auth override applies only to provider API
requests that already go through the local proxy; it must not intercept or modify ChatGPT
plugin/GitHub/App connector traffic. In override mode, the proxy replaces provider `Authorization`
and drops unexpected `Cookie` headers before forwarding upstream.

If Codex currently works through a third-party provider and the user wants to prepare for ChatGPT
login, run `python -m codex_fast_proxy prepare-chatgpt-login` first as a dry run. Report the
non-secret JSON fields, then ask before running `python -m codex_fast_proxy prepare-chatgpt-login
--target-env <ENV_NAME> --apply`. The apply step writes the provider key through the Windows user
environment API, does not print the key, does not change proxy settings, and does not edit
`auth.json`. After apply, run `python -m codex_fast_proxy set-upstream --upstream-api-key-env
<ENV_NAME>` so the manager verifies `POST /v1/responses` with `stream=true` before saving the auth
split. Tell the user to restart Codex App or open a new CLI process after any user environment
variable change.

After a successful `install --start`, report the non-secret top-level `next_user_action` and
`chatgpt_login_hint` fields. When `chatgpt_login_hint.status=optional_setup_available`, tell the
user they can keep the current API-key mode for third-party API plus global Fast, and that they
should ask Codex to run `prepare-chatgpt-login` before switching Codex App to ChatGPT login for
plugin marketplace, GitHub/Apps/connectors, manual Fast controls, status hints, and voice input.

Before first enable or model-path setting changes, `install --start` verifies the candidate upstream
and auth source by sending one Codex-style `POST /v1/responses` request with `stream=true`. This is
real provider traffic and can consume a small amount of quota. If verification fails, do not retry
with `--no-verify` unless the user explicitly accepts that the next Codex session may be unable to
reach the model.

Enable also writes the Codex hook feature flags and a trusted hook state entry. Treat
`startup_hook: true` as installed, enabled, and trusted; if `startup_hook_trust` reports `modified`
or `untrusted`, rerun enable/update instead of assuming `~/.codex/hooks.json` is enough.

## Existing install

If the repository already exists, fetch and follow:

- `https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md`
