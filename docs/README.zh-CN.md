# codex-fast-proxy 中文指南

`codex-fast-proxy` 面向使用兼容 OpenAI API 的第三方供应商的 Codex App 用户。核心用途是让 Codex App 可以保持 ChatGPT 账户登录，继续使用插件市场、GitHub/Apps/connectors、Fast 手动选择、状态提示和语音输入等 UI 能力，同时把模型请求转到第三方上游。

Fast/Priority 是重要能力，但实际是否加速取决于上游 API 提供商是否支持；请以 A/B benchmark 的结果为准。

[返回英文 README](../README.md)

## 快速开始

把这句话贴给 Codex：

```text
Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md
```

安装完成后，Codex 会返回一个本地 Control UI 链接。用外部浏览器打开这个链接。普通用户只需要记住这个控制面板地址；本地代理地址是内部细节，不需要打开或复制。

在 Control UI 里点击：

```text
启用
```

页面提示准备完成后，再重启 Codex App，或者新开 CLI，让 Codex 重新加载 provider 配置。

## 常用自然语言流程

| 目标 | 对 Codex 说 |
| --- | --- |
| 安装 | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/INSTALL.md` |
| 打开 Control UI | `打开 Codex Fast proxy Control UI` |
| 启用 | 打开 Control UI，点击 `启用` |
| 查看状态 | `查看 Codex Fast proxy 状态` |
| 打开诊断 | 打开 Control UI 里的「诊断」 |
| 准备 ChatGPT 登录 | `准备一下，我想登录 ChatGPT 账户` |
| 跑 A/B 基准测试 | `跑一下 Codex Fast proxy A/B benchmark` |
| 更换上游 URL | `把 Codex Fast proxy 的上游切到 https://api.example.com/v1` |
| 检查更新 | `检查 Codex Fast proxy 更新` |
| 更新 | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UPDATE.md` |
| 卸载 | `Fetch and follow instructions from https://raw.githubusercontent.com/gaoguobin/codex-fast-proxy/main/.codex/UNINSTALL.md` |

高级命令、基准测试细节、模型服务和鉴权配置、恢复命令见 [高级用法](advanced-usage.md)。

## ChatGPT 登录提示

如果你想使用插件市场、GitHub/Apps/connectors、Fast 手动选择和状态提示、语音输入等 Codex App UI，先让 Codex 准备供应商鉴权：

```text
准备一下，我想登录 ChatGPT 账户
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

## 安全边界

- 只在允许时修改 `POST /v1/responses` 的 `service_tier`。
- 不改 `model`、`reasoning`、`tools`、`input`。
- 不记录 API key、Cookie、请求体、prompt、tool 参数或响应内容。
- 不拦截 ChatGPT 插件市场、GitHub、Apps/connectors 或 ChatGPT cookies。
- 卸载保持两阶段，避免打断当前仍依赖 proxy 的会话。
