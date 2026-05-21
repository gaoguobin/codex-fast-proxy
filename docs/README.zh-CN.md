# Codex Model Gateway 中文指南

`Codex Model Gateway` 是 `codex-fast-proxy` 这个仓库和 Python 包面向用户的名称。它面向使用兼容 OpenAI API 的第三方供应商的 Codex App 用户：Codex App 可以保持 ChatGPT 账户登录，继续使用插件市场、GitHub/Apps/connectors、Fast 手动选择、状态提示和语音输入等 UI 能力，同时把模型请求转到第三方上游。

Fast/Priority 是否真的加速取决于上游供应商支持情况。基准测试可以判断本轮是否有显著加速迹象，但是否支持 fast 优先看 provider 是否确认 `priority`。

[返回英文 README](../README.md)

## 快速开始

把这句话贴给 Codex：

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md
```

安装会克隆仓库、安装 Python 包、链接 Codex skill，并启动本地 Control UI。它不会在安装阶段切换 provider、启动数据代理或安装 hook。你需要在 Control UI 里点击：

```text
启用
```

页面提示准备完成后，重启 Codex App，或者新开 CLI，让 Codex 重新加载 provider 配置。

## Control UI

随时可以打开：

```powershell
python -m codex_fast_proxy ui
```

macOS/Linux 如果没有 `python`，使用 `python3`。

Control UI 是轻量 Python SSR + 原生 JavaScript，没有 React/Vite 运行时。默认中文，支持中文、英文、日语，以及跟随系统、浅色、深色外观。

页面结构：

- `概览`：运行状态、主操作和 2x2 摘要。
- `供应商`：启用前只读显示 Codex `config.toml` 入口；启用后支持新增、编辑、切换、删除 provider，API key 默认 mask，右侧 eye icon 可显示/隐藏。
- `请求记录`：最近 `/v1/responses`、Provider 检查，以及快速/严格 benchmark 结果。
- `高级`：状态摘要、日志路径、自检、复制诊断、导出文件。
- `设置`：左侧底部入口，管理语言、外观、检查更新和更新。

ChatGPT 账户登录态下，代理侧速度控制会隐藏，因为速度选择由 Codex App 原生 UI 接管，概览里会显示 `App 控制`。

## 常用自然语言流程

| 目标 | 对 Codex 说 |
| --- | --- |
| 安装 | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md` |
| 打开 Control UI | `打开 Codex Model Gateway Control UI` |
| 启用 | 打开 Control UI，点击 `启用` |
| 查看状态 | `查看 Codex Model Gateway 状态` |
| 打开诊断 | 打开 Control UI，进入「高级」 |
| 准备 ChatGPT 登录 | `准备 Codex Model Gateway 的 ChatGPT 账户登录兼容性` |
| 跑 A/B 基准测试 | `跑一下 Codex Model Gateway A/B benchmark` |
| 管理供应商 | 打开 Control UI，进入「供应商」新增、编辑、切换或删除 |
| 检查更新 | `检查 Codex Model Gateway 更新` |
| 更新 | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md` |
| 卸载 | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UNINSTALL.md` |

高级命令、基准测试细节、模型服务和鉴权配置、恢复命令见 [高级用法](advanced-usage.md)。

## ChatGPT 登录提示

如果你想使用插件市场、GitHub/Apps/connectors、Fast 手动选择、状态提示和语音输入等 Codex App UI，先让 Codex 准备供应商鉴权：

```text
准备 Codex Model Gateway 的 ChatGPT 账户登录兼容性
```

这一步会把当前可用的第三方供应商 key 复制到 proxy 自己的本地鉴权文件
`~/.codex/codex-fast-proxy-state/provider-auth.json`，不会打印 key，也不会改 Codex 的
`auth.json`。

如果结果里有 `needs_restart=true`，先重启 Codex App，或让 Codex 执行 `python -m codex_fast_proxy start` 刷新代理，再登录 ChatGPT。不要在代理还没加载新鉴权设置时直接切换登录，否则模型请求仍可能 401。

Windows 上如果登录 ChatGPT 时遇到 `OSError: [WinError 10013] ... socket ...`，可以在管理员 PowerShell 里依次执行：

```powershell
net stop winnat
netsh interface ipv4 show excludedportrange protocol=tcp
net start winnat
netsh interface ipv4 show excludedportrange protocol=tcp
```

## 诊断

普通用户优先看 Control UI 的「高级」页。它会把运行时、配置入口、登录与密钥、启动钩子、请求日志和下一步操作合并成状态摘要，不需要先读原始状态。

`运行自检` 使用与 CLI `doctor` 相同的 manager 检查。`复制诊断` 和 `导出文件` 只包含脱敏状态，不包含 API key、Cookie、请求体、prompt、tool 参数或响应内容。

CLI 源数据：

```powershell
python -m codex_fast_proxy status
python -m codex_fast_proxy doctor
```

## 更新和卸载

更新优先走 Control UI 左侧底部的「设置」页。先点 `检查更新`，再按需点 `更新`。如果本地有未提交改动，更新会安全暂停，不会覆盖你的工作区。

卸载优先走 Control UI 的 `停用并恢复`。如果当前是 ChatGPT 登录态，且恢复直连第三方上游可能导致 401，卸载会先返回确认页，不会立刻修改配置。你可以保持代理启用、先切回 API-key/第三方鉴权，或明确确认继续。

## 安全边界

- 只在允许时修改 `POST /v1/responses` 的 `service_tier`。
- 不改 `model`、`reasoning`、`tools`、`input`、请求体或 SSE 帧。
- 不记录 API key、Cookie、请求体、prompt、tool 参数或响应内容。
- 不拦截 ChatGPT 插件市场、GitHub、Apps/connectors 或 ChatGPT cookies。
- Provider API key 存在 proxy 管理的本地 auth 文件里；支持的系统上使用 owner-only 权限。
- 卸载有 ChatGPT 直连风险保护，避免把正在使用 ChatGPT 登录的 Codex 直接切回第三方上游后 401。

## Fast 基准测试

Control UI 的请求记录页提供两种测试：

- 快速测试：3 对 default/priority 请求，适合低成本观察。
- 严格测试：12 对 direct API 请求，使用平衡随机顺序、每样本 prompt cache 隔离和配对统计检验。

结果会拆成三层看：priority 参数是否被接受、provider 响应是否确认 `priority`、本轮延迟是否统计上更快。延迟更快只代表本轮观测，不单独证明 provider 支持 fast。
