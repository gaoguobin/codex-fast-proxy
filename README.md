# Codex Model Gateway

[![CI](https://github.com/gaoguobin/codex-fast-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/gaoguobin/codex-fast-proxy/actions/workflows/ci.yml)

Codex Model Gateway is the user-facing name for the `codex-fast-proxy` repo and Python package. It
lets Codex App stay signed in with ChatGPT for the full App UI while model requests continue to use
your third-party OpenAI-compatible provider.

[中文指南](docs/README.zh-CN.md) · [Quick Start](#quick-start) · [Control UI](#control-ui) · [Common Workflows](#common-workflows) · [Diagnostics](#diagnostics) · [Safety](#safety) · [Advanced Usage](docs/advanced-usage.md) · [Sponsor](#sponsor)

![Codex Model Gateway overview](docs/assets/codex-fast-proxy-promo.gif)

## Why

Codex App features such as plugin marketplace, GitHub/Apps connectors, manual Fast controls, status
hints, and voice input are tied to signing in with ChatGPT. Users of third-party providers still
need model requests to use the provider endpoint and API key.

This project keeps those concerns separate. Codex App can stay signed in with ChatGPT for UI and
connector features, while `/v1/responses` model traffic continues through your configured provider.
Fast/Priority routing is treated as a provider capability that should be measured, not assumed.

## What It Does

- Routes Codex provider traffic from an automatically selected local `127.0.0.1` port to your saved
  upstream provider.
- Optionally replaces proxied provider `Authorization` with a key from a proxy-managed local auth
  file, so ChatGPT account auth is not forwarded to the third-party provider.
- Preserves request bodies, tools, model choices, reasoning settings, and SSE frames.
- Patches `service_tier` only for `POST /v1/responses`, and only when the configured Fast policy
  allows it.
- Preserves Codex App's manual Fast controls when the App sends its own `service_tier`.
- Installs a trusted Codex `SessionStart` hook so future sessions can start the proxy and Control UI.
- Provides a local Control UI for status, providers, request records, diagnostics, update, and
  uninstall.

## Quick Start

Paste this into Codex:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md
```

The installer clones the repo, installs the Python package, links the Codex skill, and starts the
local Control UI. It does not switch your provider, start the data proxy, or install hooks until you
click `启用`.

After the UI reports that setup is ready, restart Codex App or open a new Codex CLI process so Codex
reloads its provider config. Future sessions use the installed startup hook.

## Control UI

Start it at any time:

```powershell
python -m codex_fast_proxy ui
```

On macOS/Linux, use `python3` if `python` is not installed.

The Control UI is a lightweight Python SSR page with native JavaScript. It has no React or Vite
runtime. It supports Chinese, English, and Japanese, plus system, light, and dark appearances.
Chinese is the default language.

Pages:

- `概览`: running state, primary action, and a compact 2x2 summary.
- `供应商`: before enable, read-only entries from Codex `config.toml`; after enable, provider add,
  edit, switch, delete, and masked API-key reveal.
- `请求记录`: recent `/v1/responses` records, provider checks, and quick/strict benchmark results.
- `高级`: status summary, log paths, self-check, copy diagnostics, and JSON export.
- `设置`: language, appearance, update checks, and updates.

When Codex is signed in with ChatGPT, proxy-side speed controls are hidden because speed selection
is controlled by Codex App's native UI. The summary shows `App 控制` for that state.

## Common Workflows

Most users should operate this through natural language in Codex:

| Goal | Say this to Codex |
| --- | --- |
| Install from GitHub | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md` |
| Open Control UI | `Open Codex Model Gateway Control UI` |
| Enable | Open the Control UI and click `启用` |
| Check status | `Show Codex Model Gateway status` |
| Open diagnostics | Open the Control UI and go to `高级` |
| Prepare ChatGPT login | `Prepare Codex Model Gateway for ChatGPT account login` |
| Run A/B benchmark | `Run the Codex Model Gateway A/B benchmark` |
| Change provider | Open the Control UI, go to `供应商`, then add/edit/switch provider |
| Check for updates | `Check Codex Model Gateway updates` |
| Update | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md` |
| Uninstall | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UNINSTALL.md` |

Advanced command-line usage lives in [docs/advanced-usage.md](docs/advanced-usage.md).

## After Enable

A healthy setup should show `运行正常` in the Control UI and `working` in the status snapshot.
Diagnostics should report:

- `healthy=true`
- `config_matches=true`
- `startup_hook=true`
- `startup_hook_trust.ready=true`
- `runtime_matches=true`
- `needs_restart=false`

The local proxy URL is an internal detail. Ordinary users should use only the Control UI URL and the
model service URL shown on the provider page.

In API-key mode, the default `auto` policy can inject priority when Codex omits `service_tier`. In
ChatGPT-login or unclear states, the default behavior is conservative and preserves Codex's own Fast
choice.

## Sign In With ChatGPT

Signing in with ChatGPT is optional. Use it if you want the full Codex App UI, such as plugin
marketplace, GitHub/Apps/connectors, manual Fast controls, status hints, or voice input. The proxy's
auth split keeps model requests on your third-party provider after that sign-in.

Before switching Codex App to ChatGPT login, ask Codex to prepare provider auth:

```text
Prepare Codex Model Gateway for ChatGPT account login
```

The manager copies the current working third-party provider key into
`~/.codex/codex-fast-proxy-state/provider-auth.json` without printing the key. If it reports
`needs_restart=true`, do not log in yet. First restart Codex App, open a new CLI, or run:

```powershell
python -m codex_fast_proxy start
```

If ChatGPT login on Windows fails with `OSError: [WinError 10013] ... socket ...`, retry after
running these commands in an Administrator PowerShell:

```powershell
net stop winnat
netsh interface ipv4 show excludedportrange protocol=tcp
net start winnat
netsh interface ipv4 show excludedportrange protocol=tcp
```

## Diagnostics

Use the Control UI `高级` page for normal diagnostics. It summarizes runtime, config, auth, startup
hook, telemetry, and next action. `运行自检` calls the same manager doctor path as the CLI. `复制诊断`
and `导出 JSON` include redacted status only; they do not include API keys.

CLI source of truth:

```powershell
python -m codex_fast_proxy status
python -m codex_fast_proxy doctor
```

The old proxy-hosted dashboard remains an advanced read-only fallback. It shows local proxy status,
upstream URL, Fast policy, auth mode, recent `/v1/responses` traffic, metadata checks, and benchmark
summary if one exists. It does not show prompts, request bodies, response content, API keys,
cookies, or headers.

## Fast Effect

Fast/Priority is important, but it is not a local guarantee. This gateway can send the priority
hint, but the real latency effect depends on the upstream OpenAI-compatible provider. Some providers
accept `service_tier="priority"` without making the measured workload faster, and some may not echo
priority metadata in the response.

Use the built-in A/B benchmark as a local observation tool for your current provider and model:

```text
Run the Codex Model Gateway A/B benchmark
```

The Control UI offers a quick 3-pair benchmark and a stricter 12-pair benchmark. Strict mode uses
direct API sampling, balanced random order, per-sample prompt cache isolation, and paired statistics.
Results separate provider support signals from latency observations: whether priority requests were
accepted, whether provider response metadata explicitly confirmed priority, and whether this run
showed statistically meaningful acceleration. Latency alone is not treated as proof of fast support.

## Safety

- The proxy handles provider API requests only; it does not intercept ChatGPT plugin marketplace,
  GitHub, Apps, connectors, or ChatGPT cookies.
- Service-tier changes are limited to `POST /v1/responses`.
- SSE streaming responses are passed through unchanged.
- Logs are redacted and contain only operational metadata such as path, status, latency, stream
  flag, and whether `service_tier` was injected.
- Provider API keys are stored only in the proxy-managed auth file with owner-only permissions when
  supported by the OS.
- Uninstall is confirmation-gated when ChatGPT login is active and restoring direct upstream could
  make future model requests fail with 401.

## Agent Skill And Discovery

This repository includes an Agent Skill for Codex:

- Skill name: `codex-fast-proxy`
- Skill path: `skills/codex-fast-proxy/SKILL.md`
- Primary use case: install, enable, verify, benchmark, update, change provider, prepare ChatGPT
  login compatibility, and uninstall this gateway.

The supported installation path today is still the Codex-managed install prompt above. Plugin
metadata does not install hooks, change provider config, start the proxy, or imply official
marketplace listing.

## Sponsor

If this project saves you time, consider [sponsoring the author](https://gaoguobin.github.io/sponsor)
or supporting the project from the GitHub Sponsors button.

## License

MIT
