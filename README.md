# codex-fast-proxy

Codex App 本地 Fast proxy。主要面向“让 Codex 里的 AI 帮用户安装、启用、检查、卸载”的使用方式。

## 给工程师的一句话

把这句话贴给 Codex：

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md
```

安装完成后，重启 Codex App 并回到这个对话，或新开 CLI 实例，然后直接说：

```text
启用 Codex Fast proxy
```

也可以说：

- `查看 Codex Fast proxy 状态`
- `停止 Codex Fast proxy`
- `卸载 Codex Fast proxy`

## 行为

Agent 会自动读取 `~/.codex/config.toml` 当前 provider，把原 `base_url` 保存为 upstream，再把该 provider 指向本地 proxy。

安装 skill 本身不会切换代理。真正启用时，工具会先启动本地 proxy，再最后一步修改 Codex config；如果启动或切换失败，会恢复备份，避免把 Codex 指到不可用地址。

运行中的 Codex 进程不会热切换 provider config：从原始 URL 启用代理后，需要重启 Codex App，或新开 CLI 实例，才会使用代理；Codex App 重启后可以回到原对话继续。反过来，如果当前进程已经在走代理，直接停止代理可能打断当前对话；卸载流程会先恢复 config 并延后停代理，等 App 重启或新 CLI 实例启动后再完成清理。

安装、升级、卸载通常会触发 Codex 的沙箱/权限确认，因为 Agent 需要 clone GitHub、安装 Python 包、写 `~/.codex`、创建 `~/.agents` junction、启动或停止后台代理。遇到这些确认时，让 Agent 按当前动作申请授权，不要让它绕过沙箱策略。

## 行为边界

- 只改 `POST /v1/responses`，其他路径仅透明转发。
- 只在 `service_tier` 字段缺失时注入，已有值保持不变。
- 不改 `model`、`reasoning`、`tools`、`input` 等字段。
- SSE 响应按字节转发，不解析、不重写 event/data。
- 日志不记录请求头、Authorization、Cookie、请求体或 prompt 内容。

## Agent 命令

```powershell
python -m codex_fast_proxy doctor
python -m codex_fast_proxy install --start
python -m codex_fast_proxy status
python -m codex_fast_proxy stop --force
python -m codex_fast_proxy uninstall
python -m codex_fast_proxy uninstall --defer-stop
```

默认结果：

- 本地 Codex `base_url`：`http://127.0.0.1:8787/v1`
- 上游 provider：自动读取当前 `~/.codex/config.toml` 里的 active provider 原 `base_url`
- 注入字段：`service_tier = "priority"`
- 安装目录：`$HOME\.codex\codex-fast-proxy`
- 运行状态目录：`$HOME\.codex\codex-fast-proxy-state`
- 日志目录：`$HOME\.codex\codex-fast-proxy-state\state`

`install` 会备份 `~/.codex/config.toml` 到 `$HOME\.codex\backups\codex-fast-proxy`，并在运行状态目录写入 `install-manifest.json` 记录回滚哈希。`uninstall` 优先安全恢复：如果 config 没变，直接还原备份；如果用户期间改过 config 但该 provider 仍指向本地 proxy，只把这个 provider 的 `base_url` 改回 upstream，保留其它改动；如果该 provider 已经不再指向 proxy，则拒绝自动回滚，避免覆盖用户配置。

`install` 必须配合 `--start` 才会切换 Codex config；单独运行会拒绝执行，避免把 Codex 指到未启动的代理。`status` 会显示本地 health check，确认正在运行的代理和保存的 upstream/service tier 一致。

`stop` 默认会拒绝在 config 仍指向代理时停服务，避免留下不可用配置；明确知道风险时才使用 `stop --force`。`uninstall --defer-stop` 用于当前 Codex 进程可能还在走代理的场景：先恢复 config，保留代理运行，让当前回复能完成；重启 Codex App，或新开 CLI 实例后，再次执行 `uninstall` 完成停服务和文件清理。

## 开发调试

```powershell
python -m pip install --user -e .
python -m codex_fast_proxy doctor
python -m unittest discover -s tests -p "test_*.py"
```

直接前台运行代理：

```powershell
python -m codex_fast_proxy serve `
  --host 127.0.0.1 `
  --port 8787 `
  --proxy-base /v1 `
  --upstream-base https://api.example.com/v1 `
  --service-tier priority
```
