---
name: codex-fast-proxy
description: Installs, enables, checks, stops, or uninstalls Codex App Fast proxy. Use when the user asks for Codex App Fast, priority service_tier, PackyAPI Fast, provider acceleration, or says phrases like "启用 Codex Fast proxy", "让 Codex App 使用 Fast", "查看 Fast proxy 状态", or "停止 Codex Fast proxy".
---

Use this skill when the user wants Codex to manage the local Fast proxy for Codex App.

## Trigger patterns

- Natural language enable requests such as `启用 Codex Fast proxy`
- App Fast requests such as `让 Codex App 使用 Fast`
- Provider-specific requests such as `PackyAPI 开 Fast`
- Maintenance requests such as `查看 Fast proxy 状态`, `停止 Fast proxy`, `卸载 Fast proxy`

## How to execute

Run the manager as the source of truth:

```powershell
python -m codex_fast_proxy doctor
python -m codex_fast_proxy install --start
python -m codex_fast_proxy status
python -m codex_fast_proxy autostart --quiet
python -m codex_fast_proxy stop --force
python -m codex_fast_proxy uninstall --defer-stop
python -m codex_fast_proxy uninstall
```

## Safety model

- Installing the repo or skill must not change Codex provider config.
- Enable with `install --start`; it starts the local proxy before switching Codex config.
- Enable also installs one user-level Codex `SessionStart` hook in `~/.codex/hooks.json` and sets
  `features.codex_hooks = true`; the hook starts or refreshes the proxy on future Codex sessions
  only when the recorded provider still points to the local proxy.
- After an enabled update, `install --start` compares the running proxy runtime with the installed
  code and restarts stale proxy runtime before returning when config still points to the local proxy.
  The `SessionStart` hook keeps the same runtime check as a backup. Codex may fire this hook for
  each new or resumed session; `autostart --quiet` does not log normal no-op checks.
- Do not run plain `install` to enable the proxy; the manager rejects config switching without `--start`.
- If proxy startup or config switching fails, the manager restores the backed-up config before returning.
- Running Codex processes do not hot-switch provider config. After enable, restart Codex App and resume the same conversation if desired, or open a new CLI process.
- If the current process is already using the proxy, stopping the proxy can interrupt the conversation. Disable with `uninstall --defer-stop`, tell the user to restart Codex App or open a new CLI process, then run uninstall again to finish cleanup.
- Uninstall removes only the `codex-fast-proxy` hook and must preserve unrelated hooks.
- Do not run `stop` while Codex config still points to the proxy unless the user explicitly accepts that current and future sessions may fail.
- `status` and `doctor` include a local health check and runtime check; treat `healthy=false` as a
  reason to stop and diagnose before continuing. If `status.needs_restart=true` after update, tell
  the user to restart Codex App or open a new CLI process so the startup hook can restart stale runtime.
- After a successful enable, report the JSON result and avoid chaining unrelated work in the same turn.

## Sandbox and approval discipline

- Operations that clone from GitHub, install with `pip`, create `~/.agents` junctions, write `~/.codex/config.toml`, write `~/.codex/hooks.json`, start a background proxy, or remove installed files may need user approval or elevated sandbox permissions.
- If the harness supports escalation, request approval for the intended command instead of trying alternate paths.
- If a command fails because of network, permissions, sandbox write limits, junction creation, or background-process restrictions, stop and rerun the same intended action with approval. Do not invent workarounds that bypass the user's sandbox policy.
- Do not edit `auth.json`, print secrets, copy API keys, or change unrelated Codex config fields.

## User handoff messages

- After `.codex/INSTALL.md` or `.codex/UPDATE.md` changes skill files, explicitly tell the user: `请重启 Codex App 并回到这个对话，或新开 CLI 实例，让它重新扫描 ~/.agents/skills；然后再说“启用 Codex Fast proxy”。`
- After `.codex/UNINSTALL.md`, explicitly tell the user: `请重启 Codex App，或新开 CLI 实例，让它从 skill 列表中移除 codex-fast-proxy。`
- After a successful `install --start`, explicitly tell the user: `Fast proxy 已启用，但当前 Codex 进程不会热切换；请重启 Codex App 并回到这个对话，或新开 CLI 实例后继续使用。`
- After `uninstall --defer-stop`, explicitly tell the user: `配置已恢复直连，代理暂时保留运行以避免打断当前进程；请重启 Codex App 并回到这个对话，或新开 CLI 实例后再次执行卸载完成清理。`

Use `--provider <name>` only when the user names a provider or when `doctor` reports that no active provider can be selected.

Use `--upstream-base <url>` only when Codex config does not contain a usable provider `base_url` or the user explicitly wants a different upstream.

## Result handling

- Treat the JSON output as the source of truth.
- Report `provider`, `base_url`, `upstream_base`, `running`, and backup or restore status.
- Do not print API keys, `auth.json`, request bodies, prompts, or Codex history.
- If install or update changed the skill files, tell the user to restart Codex.

## Expected behavior

- `install --start` backs up `~/.codex/config.toml`.
- The selected provider's original `base_url` becomes `upstream_base`.
- The selected provider's `base_url` becomes `http://127.0.0.1:8787/v1`.
- A `SessionStart` hook calls `python -m codex_fast_proxy autostart --quiet` on future Codex sessions.
- The proxy only injects `service_tier="priority"` into `POST /v1/responses` when that field is absent.
- `uninstall` restores the full backup when the current config still matches the installed state.
- If the config changed but the selected provider still points to the local proxy, `uninstall` restores only that provider's `base_url` to `upstream_base` and preserves other config changes.
- If `uninstall` reports `config_restore="skipped_config_changed"`, do not delete the package or repo; the selected provider no longer points to the recorded proxy, so ask the user before using `--force`.
