# codex-fast-proxy

[![CI](https://github.com/gaoguobin/codex-fast-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/gaoguobin/codex-fast-proxy/actions/workflows/ci.yml)

Local Fast proxy for Codex App and Codex CLI. It lets Codex use providers that
support `service_tier="priority"` even when the official Codex App does not send
that field.

[中文说明](#中文说明) · [Install](#install) · [Safety](#safety-model) · [Sponsor](#sponsor)

## What It Does

- Injects `service_tier="priority"` only into `POST /v1/responses` requests when the field is absent.
- Leaves `model`, `reasoning`, `tools`, `input`, and all existing request fields unchanged.
- Preserves SSE streaming responses without parsing or rewriting `event:` / `data:` frames.
- Reads the active Codex provider from `~/.codex/config.toml` and saves the original `base_url` as the upstream.
- Backs up Codex config, restores safely, and avoids overwriting user edits during uninstall.
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
process reloads `~/.codex/config.toml`.

## Common Commands

Agents should run the manager as the source of truth:

```powershell
python -m codex_fast_proxy doctor
python -m codex_fast_proxy install --start
python -m codex_fast_proxy status
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
| Logs | `~/.codex/codex-fast-proxy-state/state/fast_proxy.jsonl` |
| Config backups | `~/.codex/backups/codex-fast-proxy` |

## Safety Model

- `install --start` starts the local proxy first, health-checks it, then switches Codex config.
- Plain `install` refuses to switch config without a running proxy.
- If startup or config switching fails, the manager restores the backed-up config.
- Running Codex processes do not hot-switch provider config. Restart Codex App and return to the
  same conversation, or open a new CLI process.
- `stop` refuses to stop while Codex config still points to the proxy unless `--force` is explicit.
- `uninstall --defer-stop` restores config first and leaves the proxy running so a proxy-backed
  current process can finish its response.
- If users edited `~/.codex/config.toml` after enabling the proxy, uninstall preserves those edits
  when possible: if the recorded provider still points to the local proxy, only that provider's
  `base_url` is restored to the saved upstream. If the provider no longer points to the recorded
  proxy, uninstall stops and asks for user confirmation instead of overwriting config.

## Privacy

The proxy never logs authorization headers, cookies, request bodies, prompts, tool arguments, or
response contents. Logs include only operational metadata such as path, status, duration, stream
flag, and whether `service_tier` was injected.

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

### 行为边界

- 只修改 `POST /v1/responses`。
- 只在缺失 `service_tier` 时补 `priority`，已有值不覆盖。
- 不改 `model`、`reasoning`、`tools`、`input`。
- SSE 流式响应原样透传。
- 日志脱敏，不记录 API key、Cookie、请求体、prompt 或响应内容。
- provider 通用：自动读取当前 active provider 的原始 `base_url` 作为 upstream。

### 卸载和回滚

卸载会优先保护用户配置：

- config 没变：还原安装前备份。
- config 改过，但 provider 仍指向本地 proxy：只把该 provider 的 `base_url` 改回 upstream，其它改动保留。
- provider 已经不指向记录的 proxy：停止自动回滚，要求用户确认，避免覆盖用户配置。

如果当前 Codex 进程可能还在走 proxy，先执行 `uninstall --defer-stop`，重启 Codex App
并回到原对话，或新开 CLI 实例后，再执行 `uninstall` 完成停服务和清理。

## Sponsor

If `codex-fast-proxy` saves you time, consider [sponsoring the author](https://gaoguobin.github.io/sponsor)
to help cover API token and maintenance costs.

如果这个工具帮你节省了时间，可以通过 [赞赏作者](https://gaoguobin.github.io/sponsor) 支持后续维护和 API token 成本。

## License

MIT - see [LICENSE](LICENSE).
