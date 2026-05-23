# Codex Model Gateway install for Codex

Use these instructions when an engineer asks Codex to install or enable Codex Model Gateway
(`codex-fast-proxy` package and repo).

## One-paste prompt for engineers

Paste this into Codex:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md
```

## What this installs

- Git repo: `~/.codex/codex-fast-proxy`
- Python package: editable user install of `codex-fast-proxy`
- Skill namespace link: `~/.agents/skills/codex-fast-proxy -> ~/.codex/codex-fast-proxy/skills`
- Runtime state after enable: `~/.codex/codex-fast-proxy-state`
- Startup hook after enable: `~/.codex/hooks.json`

File-only install does not modify Codex model-service settings. First enable from the Control UI may
later update `~/.codex/config.toml`, write proxy-owned provider auth state under
`~/.codex/codex-fast-proxy-state`, install the `SessionStart` hook in `~/.codex/hooks.json`, and
create restore backups under `~/.codex/backups/codex-fast-proxy`.

## Install steps

This install only installs files and the skill. It must not switch Codex App to the proxy.
The startup hook is installed later by `python -m codex_fast_proxy install --start`, not by this file-only install.

If the Codex environment uses sandbox or approval controls, request approval/escalation for the install block because it clones from GitHub, installs a Python package, writes under `~/.codex`, and creates a skill link under `~/.agents`.

If any command fails because of network, permissions, sandbox write limits, or skill link creation, do not try unrelated workarounds. Ask for approval and rerun the same intended install step.

On Windows PowerShell, run this block exactly:

```powershell
$pythonCmd = if (Get-Command python -ErrorAction SilentlyContinue) {
    'python'
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    'python3'
} else {
    throw 'Python 3 is required before installing codex-fast-proxy.'
}
$repoRoot = Join-Path (Join-Path $HOME '.codex') 'codex-fast-proxy'
$skillsRoot = Join-Path (Join-Path $HOME '.agents') 'skills'
$skillNamespace = Join-Path $skillsRoot 'codex-fast-proxy'
$installRef = 'main'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'git is required before installing codex-fast-proxy.'
}

if (Test-Path $repoRoot) {
    throw 'codex-fast-proxy is already installed. Follow UPDATE.md instead.'
}

if (Test-Path $skillNamespace) {
    throw 'The skill namespace link already exists. Remove it or follow UNINSTALL.md before reinstalling.'
}

git clone --branch $installRef --single-branch https://github.com/gaoguobin/codex-fast-proxy.git $repoRoot
& $pythonCmd -m pip install --user -e $repoRoot
& $pythonCmd -m codex_fast_proxy link-skill --repo-root $repoRoot
```

On macOS/Linux shell, run this block exactly:

```sh
python_cmd="$(command -v python3 || command -v python || true)"
if [ -z "$python_cmd" ]; then
  echo "Python 3 is required before installing codex-fast-proxy." >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "git is required before installing codex-fast-proxy." >&2
  exit 1
fi

repo_root="$HOME/.codex/codex-fast-proxy"
skill_namespace="$HOME/.agents/skills/codex-fast-proxy"
install_ref="main"

if [ -e "$repo_root" ]; then
  echo "codex-fast-proxy is already installed. Follow UPDATE.md instead." >&2
  exit 1
fi
if [ -e "$skill_namespace" ]; then
  echo "The skill namespace link already exists. Remove it or follow UNINSTALL.md before reinstalling." >&2
  exit 1
fi

git clone --branch "$install_ref" --single-branch https://github.com/gaoguobin/codex-fast-proxy.git "$repo_root"
"$python_cmd" -m pip install --user -e "$repo_root"
"$python_cmd" -m codex_fast_proxy link-skill --repo-root "$repo_root"
```

## After install

Run this check and start the Control UI in the same Codex turn. If sandbox or approval controls
apply, request approval/escalation for this block too because `ui` starts a local background Control
UI server that must stay alive after the launcher command exits.

```powershell
$pythonCmd = if (Get-Command python -ErrorAction SilentlyContinue) {
    'python'
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    'python3'
} else {
    throw 'Python 3 is required before checking codex-fast-proxy.'
}
& $pythonCmd -m codex_fast_proxy doctor
& $pythonCmd -m codex_fast_proxy ui
```

On macOS/Linux shell:

```sh
python_cmd="$(command -v python3 || command -v python || true)"
if [ -z "$python_cmd" ]; then
  echo "Python 3 is required before checking codex-fast-proxy." >&2
  exit 1
fi
"$python_cmd" -m codex_fast_proxy doctor
"$python_cmd" -m codex_fast_proxy ui
```

Report the non-secret JSON results in the reply. The `ui` command starts the independent Control UI
on an automatically selected local port and returns its local URL. Do not use browser automation for
this handoff, and do not mention or explain the internal data-proxy port in the normal user reply.
Give the user the returned `url` and say:

```text
请在外部浏览器中打开：<url>
```

If the `ui` command returns `status=error`, report the returned `error` and do not invent a URL.

Do not claim the data proxy is enabled after file-only install. The user should use the Control UI
and click `启用`. The UI defaults to Chinese, supports English and Japanese, and includes system,
light, and dark appearances. It prepares the current provider path, automatically selects an
available internal data-proxy port, prepares ChatGPT-login compatibility, then tells the user when
to restart Codex.

If the skill files were installed or updated, also tell the user that a Codex App restart or new CLI
process may be needed before the natural-language skill is discoverable. The Control UI link remains
usable from the external browser while Codex restarts.

After restarting Codex App or opening a new CLI process, the user can ask:

- `Open Codex Model Gateway Control UI`
- `Enable Codex Model Gateway`
- `Prepare Codex Model Gateway for ChatGPT account login`
- `Enable global Fast injection for Codex Model Gateway`
- `Show Codex Model Gateway status`
- `Stop Codex Model Gateway`

Default enable uses `--service-tier-policy auto`. In ChatGPT-login or unclear states this respects
Codex App/CLI Fast UI choices; in API-key mode it may inject the priority tier when Codex omits
`service_tier`, because the App Fast UI may not be available. Use
`--service-tier-policy inject_missing` only when the user explicitly asks for global Fast injection,
and `--service-tier-policy preserve` only when they explicitly want no proxy-side Fast injection. If
the user wants ChatGPT login compatibility for plugins/GitHub/Apps/connectors while model requests
still use a third-party provider, first enable from the Control UI prepares the proxy provider auth
file automatically when a working provider key is available. Use `prepare-chatgpt-login` and
`set-upstream --use-provider-auth-file` only for old installs, CLI fallback, or recovery. Do not ask
the user to paste API keys into chat and do not edit `auth.json` unless they explicitly request
recovery. This auth override applies only to provider API
requests that already go through the local proxy; it must not intercept or modify ChatGPT
plugin/GitHub/App connector traffic. In override mode, the proxy replaces provider `Authorization`
and drops unexpected `Cookie` headers before forwarding upstream.

If Codex currently works through a third-party provider and the user wants to prepare for ChatGPT
login outside the Control UI first-enable path, run `python -m codex_fast_proxy
prepare-chatgpt-login` first as a dry run. Report the non-secret JSON fields, then ask before
running `python -m codex_fast_proxy prepare-chatgpt-login --apply`. The apply step copies the
currently working provider key into
`~/.codex/codex-fast-proxy-state/provider-auth.json`, does not print the key, does not change proxy
settings, and does not edit `auth.json`. After apply, run
`python -m codex_fast_proxy set-upstream --use-provider-auth-file` so the manager verifies
`POST /v1/responses` with `stream=true` before saving the auth split. Tell the user to restart Codex
App or open a new CLI process if the result reports `needs_restart=true`.

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

The installed Control UI pages are:

- `概览`: running state and compact summary.
- `供应商`: read-only Codex config before enable; proxy-managed provider add/edit/switch/delete
  after enable, with masked key reveal.
- `请求记录`: recent requests, provider checks, and benchmark summary.
- `高级`: status summary, log paths, self-check, copy diagnostics, and diagnostic file export.
- `设置`: lower-left settings entry with segmented language and appearance controls, plus one
  software-update action that checks first and updates only when a release is available.

When ChatGPT account login is detected, proxy-side speed controls are hidden because speed selection
is handled by the Codex App native UI.

Enable also writes the canonical Codex hook feature flag (`[features].hooks = true`) and a trusted
hook state entry. Treat
`startup_hook: true` as installed, enabled, and trusted; if `startup_hook_trust` reports `modified`
or `untrusted`, rerun enable/update instead of assuming `~/.codex/hooks.json` is enough.
The hook runs `codex_fast_proxy autostart --quiet --hook-summary` on future `SessionStart` events and
starts or reuses both the proxy and Control UI when the recorded provider still points to the local
proxy. Normal no-op runs stay silent; starts, restarts, stale runtime warnings, or Control UI
autostarts may emit a short non-secret hook context summary.

## Existing install

If the repository already exists, fetch and follow:

- `https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md`
