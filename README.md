# codex-fast-proxy

[![CI](https://github.com/gaoguobin/codex-fast-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/gaoguobin/codex-fast-proxy/actions/workflows/ci.yml)

Local Fast proxy for Codex App and Codex CLI. It lets Codex use providers that
support `service_tier="priority"` even when the official Codex App does not send
that field.

[中文说明](#中文说明) · [Install](#install) · [Update](#update) · [Uninstall](#uninstall) · [Safety](#safety-model) · [Sponsor](#sponsor)

## What It Does

- Injects `service_tier="priority"` only into `POST /v1/responses` requests when the field is absent.
- Leaves `model`, `reasoning`, `tools`, `input`, and all existing request fields unchanged.
- Preserves SSE streaming responses without parsing or rewriting `event:` / `data:` frames.
- Reads the active Codex provider from `~/.codex/config.toml` and saves the original `base_url` as the upstream.
- Backs up Codex config, restores safely, and avoids overwriting user edits during uninstall.
- Installs a Codex `SessionStart` hook after enable, so future Codex App/CLI startups restart the
  proxy before the first provider request when config still points to the proxy.
- Serves a read-only local status page for browser visits to the proxy root or base URL.
- Writes redacted JSONL logs without headers, API keys, cookies, request bodies, or prompts.
- Ships with a Codex skill so users can ask Codex to install, enable, check, update, or uninstall it.

## Compatibility

- Windows-first, tested with the official Codex App and Codex CLI on Windows.
- Python 3.11+.
- Any OpenAI-compatible Responses API provider can be used as the upstream, as long as it accepts
  `service_tier="priority"`.
- PackyAPI Fast / priority has been verified end to end.

## Install

Paste this into Codex:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md
```

The install flow clones this repository to `~/.codex/codex-fast-proxy`, installs the Python package
in editable user mode, and links the bundled skill into `~/.agents/skills`.

After installation, restart Codex App and return to the same conversation, or open a new Codex CLI
process. Then ask:

```text
启用 Codex Fast proxy
```

After enabling, restart Codex App again, or open a new Codex CLI process, so the running Codex
process reloads `~/.codex/config.toml`. Future Codex starts use the installed `SessionStart` hook
to restart the proxy automatically when the recorded provider still points to the local proxy.

## Verify

Ask Codex:

```text
查看 Codex Fast proxy 状态
```

Or run:

```powershell
python -m codex_fast_proxy status
```

A healthy enabled setup should report `healthy: true`, `config_matches: true`, and
`startup_hook: true`. After sending a Codex App message, the redacted log should contain a
`POST /v1/responses` entry with `service_tier_before="<absent>"`,
`service_tier_after="priority"`, `service_tier_injected=true`, and
`response_content_type="text/event-stream"`.

You can also open `http://127.0.0.1:8787/v1` in a browser. Browser-style HTML requests show a
read-only dashboard with local proxy status and recent redacted events; API requests continue to be
forwarded normally.

## Benchmark

Ask Codex:

```text
跑一下 Codex Fast proxy A/B benchmark
```

Or run:

```powershell
python -m codex_fast_proxy benchmark --pairs 3
```

The benchmark is opt-in because it sends synthetic Responses API requests and consumes provider
quota. It compares requests without `service_tier` against requests with `service_tier="priority"`
directly against the saved upstream, then reports median latency, observed speedup, and whether the
provider response confirmed `service_tier="priority"`. If the provider config does not define an API
key environment field, rerun with `--api-key-env NAME`. The dashboard shows a read-only summary of
the latest saved benchmark result.

## Update

Paste this into Codex:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md
```

The update flow pulls the installed repository, reinstalls the editable Python package, refreshes
the skill junction if needed, and runs `doctor`. If the proxy is already enabled, the update flow
runs `install --start` after confirming the current config still points to the proxy. That command
compares the running proxy runtime with the installed code and restarts a stale proxy before it
returns, so the local dashboard and future requests use the updated code.

Restart Codex App, or open a new Codex CLI process, after an update that changes skill files. The
installed `SessionStart` hook keeps the same runtime check as a backup. Codex fires `SessionStart`
per new or resumed session; in quiet mode normal no-op checks are not logged, while start, restart,
and error events are still recorded. Use `status` to inspect `runtime_matches` and `needs_restart`.

## Uninstall

Paste this into Codex:

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UNINSTALL.md
```

Uninstall is intentionally two-phase when the current Codex process may still be using the proxy:

1. The first run restores Codex config to the upstream provider and removes the startup hook, but
   leaves the proxy process running so the current response can finish.
2. Restart Codex App, return to the same conversation if desired, or open a new Codex CLI process.
3. Run the same uninstall prompt again. The second run stops the remaining proxy process, removes
   runtime state, uninstalls the Python package, removes the skill junction, and deletes
   `~/.codex/codex-fast-proxy`.

If uninstall reports `config_restore="skipped_config_changed"`, Codex config no longer points to
the recorded local proxy. Review `~/.codex/config.toml` before using `--force`; the manager avoids
overwriting user edits in that state.

## Common Commands

Agents should run the manager as the source of truth:

```powershell
python -m codex_fast_proxy doctor
python -m codex_fast_proxy install --start
python -m codex_fast_proxy status
python -m codex_fast_proxy benchmark --pairs 3
python -m codex_fast_proxy autostart --quiet
python -m codex_fast_proxy stop --force
python -m codex_fast_proxy uninstall --defer-stop
python -m codex_fast_proxy uninstall
```

Default paths:

| Item | Path |
| --- | --- |
| Local proxy base URL | `http://127.0.0.1:8787/v1` |
| Repository install | `~/.codex/codex-fast-proxy` |
| Runtime state | `~/.codex/codex-fast-proxy-state` |
| Startup hook | `~/.codex/hooks.json` |
| Logs | `~/.codex/codex-fast-proxy-state/state/fast_proxy.jsonl` |
| Config backups | `~/.codex/backups/codex-fast-proxy` |

## Safety Model

- `install --start` starts the local proxy first, health-checks it, then switches Codex config.
- Enable also sets `features.codex_hooks = true` and adds one user-level `SessionStart` hook. The
  hook calls `codex-fast-proxy autostart --quiet`, starts or refreshes the proxy only when Codex
  config still points to the recorded local proxy, and otherwise exits quietly. Codex may run this
  hook for each new or resumed session; normal no-op checks do not write autostart log entries.
- Plain `install` refuses to switch config without a running proxy.
- If startup or config switching fails, the manager restores the backed-up config.
- Running Codex processes do not hot-switch provider config. Restart Codex App and return to the
  same conversation, or open a new CLI process.
- `stop` refuses to stop while Codex config still points to the proxy unless `--force` is explicit.
- `uninstall --defer-stop` restores config first and leaves the proxy running so a proxy-backed
  current process can finish its response.
- `uninstall` removes only the `codex-fast-proxy` hook from `~/.codex/hooks.json` and preserves
  unrelated user hooks.
- If users edited `~/.codex/config.toml` after enabling the proxy, uninstall preserves those edits
  when possible: if the recorded provider still points to the local proxy, only that provider's
  `base_url` is restored to the saved upstream. If the provider no longer points to the recorded
  proxy, uninstall stops and asks for user confirmation instead of overwriting config.

## Privacy

The proxy never logs authorization headers, cookies, request bodies, prompts, tool arguments, or
response contents. Logs include only operational metadata such as path, status, duration, stream
flag, and whether `service_tier` was injected.

Benchmark sends a fixed synthetic prompt only. It stores redacted metrics such as status, latency,
and response `service_tier`; it does not store the API key or response content. The dashboard reads
only this saved redacted summary.

## Development

```powershell
python -m pip install --user -e .
python -m codex_fast_proxy doctor
python -m unittest discover -s tests -p "test_*.py"
```

Run the proxy in the foreground:

```powershell
python -m codex_fast_proxy serve `
  --host 127.0.0.1 `
  --port 8787 `
  --proxy-base /v1 `
  --upstream-base https://api.example.com/v1 `
  --service-tier priority
```

## 中文说明

`codex-fast-proxy` 是一个本地 Fast 代理，面向 Codex App 和 Codex CLI。它解决的核心问题是：
Codex App 发送 `POST /v1/responses` 时可能没有 `service_tier` 字段，而部分上游 provider
需要 `service_tier="priority"` 才会进入 Fast / priority 通道。

### 快速安装

把这句话贴给 Codex：

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md
```

安装完成后，重启 Codex App 并回到原对话，或新开 CLI 实例，然后说：

```text
启用 Codex Fast proxy
```

启用完成后，再重启 Codex App 或新开 CLI 实例，让 Codex 重新读取 provider config。

### 状态检查

对 Codex 说：

```text
查看 Codex Fast proxy 状态
```

或直接运行：

```powershell
python -m codex_fast_proxy status
```

健康状态应包含 `healthy: true`、`config_matches: true`、`startup_hook: true`。App 发出消息后，
日志里应出现 `/v1/responses`，并显示 `service_tier_before="<absent>"`、
`service_tier_after="priority"`、`service_tier_injected=true`、`response_content_type="text/event-stream"`。

### Benchmark

对 Codex 说：

```text
跑一下 Codex Fast proxy A/B benchmark
```

或直接运行：

```powershell
python -m codex_fast_proxy benchmark --pairs 3
```

Benchmark 是手动触发的，因为它会发送少量合成 Responses API 请求并消耗 provider quota。它会直接打
已保存的 upstream，对比不带 `service_tier` 和带 `service_tier="priority"` 的请求，输出 median
latency、观测到的 speedup，以及供应商响应是否确认 `service_tier="priority"`。如果 provider 配置里
没有 API key 环境变量字段，使用 `--api-key-env NAME` 指定。dashboard 会只读展示最近一次已保存的
benchmark 摘要。

### 更新

把这句话贴给 Codex：

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md
```

更新会拉取 GitHub 仓库、重新安装 editable Python 包、补齐 skill junction，并运行 `doctor`。
如果当前已经启用了代理，更新流程会运行 `install --start`：它会比较运行中 proxy 的代码指纹和
已安装代码，如果发现旧运行时且 config 仍指向本地 proxy，会在命令返回前重启代理。因此本地
dashboard 和后续请求会直接使用新代码。

更新 skill 文件后仍需要重启 Codex App，或新开 CLI 实例，让 Codex 重新扫描 skill。已安装的
`SessionStart` hook 会作为兜底继续做 runtime 检查。Codex 可能在每个新建或恢复的会话触发这个
hook；quiet 模式下正常 no-op 不写 autostart 日志，只记录启动、重启和错误。

### 卸载

把这句话贴给 Codex：

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UNINSTALL.md
```

如果当前 Codex 进程可能还在走 proxy，卸载是两阶段：

1. 第一次执行会先把 config 恢复直连，并移除 startup hook，但暂时保留 proxy 进程，避免打断当前会话。
2. 重启 Codex App 并回到原对话，或新开 CLI 实例。
3. 第二次执行同一个卸载入口，会停止残留 proxy、卸载 pip 包、删除 skill junction、删除 repo 和 state。

如果返回 `config_restore="skipped_config_changed"`，说明当前 provider 已经不指向记录的本地 proxy。
这时工具会保守停止，避免覆盖用户手动改过的配置；确认后再考虑 `--force`。

### 行为边界

- 只修改 `POST /v1/responses`。
- 只在缺失 `service_tier` 时补 `priority`，已有值不覆盖。
- 不改 `model`、`reasoning`、`tools`、`input`。
- SSE 流式响应原样透传。
- 日志脱敏，不记录 API key、Cookie、请求体、prompt 或响应内容。
- Benchmark 只发送固定合成 prompt，只保存 status、latency、response `service_tier` 等脱敏指标。
- dashboard 只读取最近一次 benchmark 的脱敏摘要，不提供会消耗 quota 的启动按钮。
- 浏览器打开 `http://127.0.0.1:8787/v1` 时显示只读本地状态页；API 请求仍按原逻辑转发。
- provider 通用：自动读取当前 active provider 的原始 `base_url` 作为 upstream。
- 启用后写入 Codex `SessionStart` hook；后续 Codex App/CLI 新建或恢复会话时，如果配置仍指向本地
  proxy，会自动启动或刷新代理。用户手动改回直连时 hook 会静默跳过，正常 no-op 不写日志。

### 回滚保护

卸载会优先保护用户配置：

- config 没变：还原安装前备份。
- config 改过，但 provider 仍指向本地 proxy：只把该 provider 的 `base_url` 改回 upstream，其它改动保留。
- provider 已经不指向记录的 proxy：停止自动回滚，要求用户确认，避免覆盖用户配置。

卸载只移除 `codex-fast-proxy` 自己写入的 hook，保留用户已有的其它 Codex hooks。

## Sponsor

If `codex-fast-proxy` saves you time, consider [sponsoring the author](https://gaoguobin.github.io/sponsor)
to help cover API token and maintenance costs.

如果这个工具帮你节省了时间，可以通过 [赞赏作者](https://gaoguobin.github.io/sponsor) 支持后续维护和 API token 成本。

## License

MIT - see [LICENSE](LICENSE).
