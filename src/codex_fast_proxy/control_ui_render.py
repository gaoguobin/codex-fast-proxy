from __future__ import annotations

import html
import json
from typing import Any


CONTROL_TOKEN_HEADER = "X-Codex-Fast-Proxy-Token"

UI_TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh": {
        "page.title": "Codex 控制面板",
        "brand.name": "Codex Model Gateway",
        "brand.subtitle": "控制台",
        "toolbar.language": "语言",
        "toolbar.theme": "外观",
        "theme.system": "跟随系统",
        "theme.light": "浅色",
        "theme.dark": "深色",
        "nav.overview": "概览",
        "nav.providers": "供应商",
        "nav.requests": "请求记录",
        "nav.advanced": "高级",
        "nav.settings": "设置",
        "button.update": "更新",
        "button.checkUpdate": "检查更新",
        "button.updateNow": "立即更新",
        "button.recheckUpdate": "重新检查",
        "button.checkProvider": "检查",
        "button.runBenchmark": "运行基准测试",
        "button.confirmBenchmark": "运行快速测试",
        "button.confirmStrictBenchmark": "运行严格测试",
        "button.diagnostics": "打开高级诊断",
        "button.uninstall": "停用并恢复",
        "button.confirmUninstall": "仍要停用",
        "button.cancelUninstall": "先不停用",
        "button.finishCleanup": "完成清理",
        "button.saveProvider": "保存",
        "button.updateProvider": "更新",
        "button.saveSpeed": "保存",
        "button.add": "添加",
        "button.cancel": "取消",
        "button.edit": "编辑",
        "button.save": "保存",
        "button.switch": "启用",
        "button.delete": "删除",
        "button.confirmDelete": "确认删除",
        "button.enable": "启用",
        "button.reenable": "重新启用",
        "button.refresh": "刷新状态",
        "summary.proxy": "代理",
        "summary.login": "登录",
        "summary.speed": "速度",
        "summary.recentRequests": "最近请求",
        "auth.chatgpt": "ChatGPT 账户登录",
        "auth.key": "接口密钥 / 第三方登录",
        "value.unknown": "未知",
        "value.key": "密钥",
        "value.notEnabled": "未启用",
        "value.notConfigured": "未配置",
        "value.notSelected": "未选择",
        "value.noRequests": "暂无",
        "value.notRun": "未运行",
        "value.normal": "正常",
        "value.abnormal": "异常",
        "value.running": "运行中",
        "value.restartPending": "待重启",
        "value.needsAttention": "需处理",
        "value.restored": "已恢复",
        "value.notManaged": "未接管",
        "value.managed": "已接管",
        "value.appControlled": "App 控制",
        "value.fast": "快速",
        "value.standard": "标准",
        "value.proxyFast": "代理加速",
        "value.notRecorded": "未记录",
        "value.saved": "已保存",
        "value.missing": "未保存",
        "value.inUse": "使用中",
        "value.pending": "待应用",
        "value.effective": "有效",
        "value.accepted": "已接受",
        "value.confirmed": "已确认",
        "value.observedFaster": "观测更快",
        "value.unconfirmed": "未确认",
        "value.invalid": "无效",
        "value.notAccepted": "未接受",
        "providers.title": "供应商",
        "providers.note.manage": "管理本地代理使用的模型服务。",
        "providers.note.readonly": "代理启用前，这里只显示来自 Codex config.toml 的只读入口。",
        "providers.note.empty": "还没有检测到 Codex config.toml 里的供应商入口。",
        "providers.empty": "还没有可显示的供应商。请先在 Codex config.toml 配置 provider。",
        "config.title": "Codex 配置",
        "config.readonly": "来自 config.toml · 只读",
        "config.currentEntry": "当前入口",
        "config.modelServiceUrl": "模型服务地址",
        "config.note": "启用前这里不管理 Codex 配置里的供应商；如需增删改，请继续使用你熟悉的配置工具。",
        "provider.header": "供应商",
        "provider.note": "已启用后，这里只管理本地代理配置；不会改写 Codex config.toml。",
        "provider.saved": "已保存",
        "provider.name": "名称",
        "provider.modelServiceUrl": "模型服务地址",
        "provider.apiKey": "接口密钥",
        "provider.apiKeyPlaceholder": "留空则不修改已保存的 key",
        "provider.keyPrefix": "密钥：",
        "provider.unnamed": "未命名",
        "provider.noService": "未设置模型服务",
        "provider.keyEnv": "环境变量",
        "provider.keyCodexSaved": "Codex 已保存",
        "provider.showKey": "显示接口密钥",
        "provider.hideKey": "隐藏接口密钥",
        "provider.editor.edit": "编辑",
        "provider.editor.add": "添加",
        "provider.form.invalidName": "先填写供应商名称。",
        "provider.form.invalidUrl": "模型服务地址需要是 http 或 https URL。",
        "provider.check.checking": "检查中",
        "provider.check.checkingMessage": "正在验证这个模型服务。",
        "provider.check.ok": "正常",
        "provider.check.warn": "异常",
        "speed.inlineHint": "快速会在请求未指定 service_tier 时使用 priority；标准保持原始请求。",
        "requests.title": "请求记录",
        "requests.description": "查看最近请求、Provider 检查和性能基准。",
        "requests.section": "请求",
        "requests.recent": "最近请求",
        "requests.recentDescription": "使用首响应、首文本和完整耗时三个口径。",
        "requests.empty": "还没有请求记录。",
        "requests.ops": "运行细节",
        "requests.opsTitle": "Provider 检查与性能基准",
        "requests.opsDescription": "这些记录来自本地代理日志，不包含密钥。",
        "requests.benchmarkConfirmTitle": "选择基准测试强度",
        "requests.benchmarkConfirmText": "快速测试运行 3 对请求，适合低成本观察；严格测试运行 12 对请求，使用平衡随机顺序和配对统计检验。",
        "requests.benchmarkCost": "两种模式都会消耗真实额度；严格测试成本更高，但更适合判断本轮是否存在统计意义的加速迹象。",
        "requests.providerCheck": "Provider 检查",
        "requests.benchmark": "性能基准",
        "requests.check": "检查",
        "requests.noProviderCheck": "还没有 /v1/models 检查记录。",
        "requests.benchmarkNotRun": "尚未运行基准测试。",
        "benchmark.totalGain": "总耗时收益",
        "benchmark.firstTextGain": "首文本收益",
        "benchmark.priorityDuration": "优先耗时",
        "benchmark.firstText": "首文本",
        "benchmark.caveat": "延迟结果只代表本轮观测，受缓存、网络和负载影响；是否支持 fast 优先看响应是否确认 priority。",
        "benchmark.statsPrefix": "统计",
        "table.time": "时间",
        "table.request": "请求",
        "table.status": "状态",
        "table.duration": "耗时",
        "table.firstResponse": "首响应",
        "table.firstText": "首文本",
        "table.totalDuration": "完整耗时",
        "table.speedMode": "速度模式",
        "advanced.title": "高级",
        "advanced.description": "用于排查的原始状态和诊断信息。",
        "advanced.diagnostics": "诊断",
        "advanced.diagnosticsTitle": "高级诊断",
        "advanced.warning": "这里汇总运行时、配置、登录、启动钩子和日志路径；诊断导出不包含密钥。",
        "advanced.viewDiagnostics": "查看诊断",
        "advanced.runDoctor": "运行自检",
        "advanced.copy": "复制诊断",
        "advanced.download": "导出文件",
        "advanced.refresh": "刷新状态",
        "advanced.copyDone": "诊断已复制。",
        "advanced.copyFailed": "浏览器没有允许复制，请改用导出文件。",
        "advanced.exportDone": "诊断文件已生成。",
        "advanced.doctorRunning": "正在运行自检...",
        "advanced.doctorPassed": "自检通过。",
        "advanced.doctorWarnings": "功能链路正常，有权限安全建议。",
        "advanced.doctorFailed": "自检发现需要处理的项目。",
        "advanced.doctorIdle": "还没有运行自检。",
        "advanced.summary": "状态摘要",
        "advanced.summaryDescription": "优先看这里判断下一步，不需要先读原始状态。",
        "advanced.runtime": "运行时",
        "advanced.config": "配置入口",
        "advanced.auth": "登录与密钥",
        "advanced.hook": "启动钩子",
        "advanced.telemetry": "请求与日志",
        "advanced.nextAction": "下一步",
        "advanced.logPaths": "日志路径",
        "advanced.logPathsDescription": "这些路径便于排查代理进程、控制面板和请求记录。",
        "advanced.rawJson": "原始快照",
        "advanced.safeNote": "诊断信息已做状态化展示；请不要在聊天里粘贴密钥、auth.json、完整请求体或提示词。",
        "advanced.providerReady": "已检测到 provider",
        "advanced.noProvider": "未检测到 provider",
        "advanced.noProviderDetail": "请先在 Codex config.toml 配置可接管的第三方模型服务。",
        "advanced.noProxySettings": "代理尚未启用，因此没有本地代理设置。",
        "advanced.runtimeSource": "运行来源",
        "advanced.logsReady": "日志路径已准备",
        "advanced.requestsCount": "请求 {count} 条",
        "advanced.metadataCount": "检查 {count} 条",
        "advanced.hooksTrusted": "已信任 {count} 条",
        "advanced.benchmarkReady": "已有性能基准",
        "advanced.benchmarkMissing": "未运行性能基准",
        "advanced.pathLog": "请求日志",
        "advanced.pathStdout": "代理输出",
        "advanced.pathStderr": "代理错误",
        "advanced.pathControlStdout": "控制台输出",
        "advanced.pathControlStderr": "控制台错误",
        "advanced.checks": "自检结果",
        "advanced.check.python": "Python",
        "advanced.check.codex_config": "Codex 配置",
        "advanced.check.active_provider": "Codex 当前 provider",
        "advanced.check.codex_model_provider": "Codex 配置 provider",
        "advanced.check.codex_proxy_provider": "本地代理入口",
        "advanced.check.proxy_upstream_provider": "上游供应商",
        "advanced.check.provider_route": "请求路径",
        "advanced.check.provider_base_url": "模型服务地址",
        "advanced.check.runtime_source": "运行时来源",
        "advanced.check.login_mode": "登录方式",
        "advanced.check.user_file_permissions": "用户文件权限",
        "advanced.check.proxy_settings": "代理设置",
        "advanced.check.config_points_to_proxy": "配置指向代理",
        "advanced.check.upstream_saved": "上游服务已保存",
        "advanced.check.service_tier_policy": "速度策略",
        "advanced.check.upstream_auth": "上游认证",
        "advanced.check.proxy_health": "代理健康",
        "advanced.check.proxy_pending_restart": "待重启状态",
        "advanced.check.proxy_runtime": "代理运行时",
        "advanced.check.hooks_enabled": "Hooks 开关",
        "advanced.check.startup_hook": "启动钩子",
        "settings.title": "设置",
        "settings.description": "控制面板偏好和版本更新。",
        "settings.preferences": "偏好",
        "settings.preferencesDescription": "语言和外观只影响这个本地控制面板。",
        "settings.updates": "版本更新",
        "settings.updatesDescription": "先检查远端状态，再决定是否更新本地代理。",
        "settings.updateIdle": "还没有检查更新。",
        "settings.updateTitleIdle": "软件更新",
        "settings.updateNote": "检查更新是只读操作；更新会拉取代码并刷新本地运行时。",
        "danger.eyebrow": "停用确认",
        "danger.title": "先确认登录路径",
        "danger.confirmNote": "继续停用后，当前 ChatGPT 登录可能无法直接使用第三方模型服务。建议先切回接口密钥或第三方服务登录，重启 Codex 后再恢复。",
        "danger.currentRoute": "当前路径",
        "danger.afterRoute": "停用后",
        "danger.currentRouteDetail": "ChatGPT 登录 · 本地代理接管",
        "danger.afterRouteDetail": "直连第三方模型服务",
        "danger.illustrationLabel": "登录路径示意",
        "hint.chatgptSpeed": "已检测到 ChatGPT 账户登录，速度控制由 Codex App 原生界面接管。",
        "action.enable.prepare.label": "正在准备环境...",
        "action.enable.prepare.message": "正在读取当前 Provider 并准备环境。",
        "action.enable.verify.label": "正在验证模型服务...",
        "action.enable.verify.message": "正在连接当前模型服务，首次启用可能需要几十秒。",
        "action.enable.slow.label": "模型服务响应较慢...",
        "action.enable.slow.message": "仍在等待模型服务响应，完成后页面会自动更新。",
        "action.update.start.label": "正在更新...",
        "action.update.start.message": "正在拉取更新并刷新本地代理，页面会在完成后自动恢复。",
        "action.update.runtime.label": "正在刷新运行时...",
        "action.update.runtime.message": "正在重新安装并刷新代理进程，这一步可能需要十几秒。",
        "action.update.slow.label": "更新仍在继续...",
        "action.update.slow.message": "仍在等待本地更新完成，请保持控制面板打开。",
        "action.update.waitUi.label": "正在等待新版界面...",
        "action.update.waitUi.message": "更新已完成后会自动切换到新版控制面板，请不要手动刷新。",
        "action.checkUpdate.start.label": "正在检查...",
        "action.checkUpdate.start.message": "正在读取远端分支和本地工作区状态。",
        "action.saveProvider.start.label": "正在保存并验证...",
        "action.saveProvider.start.message": "正在保存，并验证模型服务是否可用。",
        "action.saveProvider.verify.message": "正在发起一次真实响应接口流式检查，完成后会自动更新页面。",
        "action.saveProvider.slow.message": "仍在等待模型服务响应；如果验证失败，当前设置会保持不变。",
        "action.verifyProvider.start.label": "正在检查...",
        "action.verifyProvider.start.message": "正在发起一次真实 Responses 流式检查。",
        "action.verifyProvider.slow.label": "检查仍在继续...",
        "action.verifyProvider.slow.message": "模型服务响应较慢，请保持页面打开。",
        "action.switchProvider.start.label": "正在切换...",
        "action.switchProvider.start.message": "正在切换，并验证新的模型服务。",
        "action.deleteProvider.start.label": "正在删除...",
        "action.deleteProvider.start.message": "正在删除保存项，当前模型服务不会受影响。",
        "action.speed.start.label": "正在保存...",
        "action.speed.start.message": "正在保存当前选择。",
        "action.benchmark.start.label": "正在运行...",
        "action.benchmark.start.message": "正在发起标准和优先请求。",
        "action.benchmark.slow.label": "基准测试仍在继续...",
        "action.benchmark.slow.message": "这一步取决于模型服务响应速度，完成后会刷新结果。",
        "action.uninstall.start.label": "正在恢复直连...",
        "action.uninstall.start.message": "正在恢复 Codex 原模型服务，并准备清理本地代理。",
        "action.uninstall.cleanup.label": "正在清理...",
        "action.uninstall.cleanup.message": "正在移除本地状态、安装文件和 skill 链接，控制面板会最后关闭。",
        "action.default.label": "处理中...",
    },
    "en": {
        "page.title": "Codex Control",
        "brand.name": "Codex Model Gateway",
        "brand.subtitle": "Console",
        "toolbar.language": "Language",
        "toolbar.theme": "Appearance",
        "theme.system": "System",
        "theme.light": "Light",
        "theme.dark": "Dark",
        "nav.overview": "Overview",
        "nav.providers": "Providers",
        "nav.requests": "Requests",
        "nav.advanced": "Advanced",
        "nav.settings": "Settings",
        "button.update": "Update",
        "button.checkUpdate": "Check for updates",
        "button.updateNow": "Update now",
        "button.recheckUpdate": "Check again",
        "button.checkProvider": "Check",
        "button.runBenchmark": "Run benchmark",
        "button.confirmBenchmark": "Run quick test",
        "button.confirmStrictBenchmark": "Run strict test",
        "button.diagnostics": "Open diagnostics",
        "button.uninstall": "Disable and restore",
        "button.confirmUninstall": "Disable anyway",
        "button.cancelUninstall": "Not now",
        "button.finishCleanup": "Finish cleanup",
        "button.saveProvider": "Save",
        "button.updateProvider": "Update",
        "button.saveSpeed": "Save",
        "button.add": "Add",
        "button.cancel": "Cancel",
        "button.edit": "Edit",
        "button.save": "Save",
        "button.switch": "Enable",
        "button.delete": "Delete",
        "button.confirmDelete": "Confirm delete",
        "button.enable": "Enable",
        "button.reenable": "Enable again",
        "button.refresh": "Refresh status",
        "summary.proxy": "Proxy",
        "summary.login": "Login",
        "summary.speed": "Speed",
        "summary.recentRequests": "Recent requests",
        "auth.chatgpt": "ChatGPT account login",
        "auth.key": "Key / third-party login",
        "value.unknown": "Unknown",
        "value.key": "Key",
        "value.notEnabled": "Off",
        "value.notConfigured": "Not configured",
        "value.notSelected": "Not selected",
        "value.noRequests": "None",
        "value.notRun": "Not run",
        "value.normal": "Healthy",
        "value.abnormal": "Issue",
        "value.running": "Running",
        "value.restartPending": "Restart needed",
        "value.needsAttention": "Needs attention",
        "value.restored": "Restored",
        "value.notManaged": "Not managed",
        "value.managed": "Managed",
        "value.appControlled": "App controlled",
        "value.fast": "Fast",
        "value.standard": "Standard",
        "value.proxyFast": "Proxy fast",
        "value.notRecorded": "Not recorded",
        "value.saved": "Saved",
        "value.missing": "Missing",
        "value.inUse": "In use",
        "value.pending": "Pending",
        "value.effective": "Effective",
        "value.accepted": "Accepted",
        "value.confirmed": "Confirmed",
        "value.observedFaster": "Observed faster",
        "value.unconfirmed": "Unconfirmed",
        "value.invalid": "Invalid",
        "value.notAccepted": "Not accepted",
        "providers.title": "Providers",
        "providers.note.manage": "Manage the model services used by the local proxy.",
        "providers.note.readonly": "Before enabling the proxy, this page only shows the read-only entry from Codex config.toml.",
        "providers.note.empty": "No provider entry was found in Codex config.toml.",
        "providers.empty": "No providers to show yet. Configure a provider in Codex config.toml first.",
        "config.title": "Codex config",
        "config.readonly": "From config.toml · read-only",
        "config.currentEntry": "Current entry",
        "config.modelServiceUrl": "Model service address",
        "config.note": "Before enabling, this page does not manage providers in Codex config. Use your usual config tool for edits.",
        "provider.header": "Provider",
        "provider.note": "After enabling, this page manages only the local proxy config; it does not rewrite Codex config.toml.",
        "provider.saved": "Saved",
        "provider.name": "Name",
        "provider.modelServiceUrl": "Model service address",
        "provider.apiKey": "Key",
        "provider.apiKeyPlaceholder": "Leave blank to keep the saved key",
        "provider.keyPrefix": "Key: ",
        "provider.unnamed": "Unnamed",
        "provider.noService": "No model service set",
        "provider.keyEnv": "Environment variable",
        "provider.keyCodexSaved": "Saved by Codex",
        "provider.showKey": "Show key",
        "provider.hideKey": "Hide key",
        "provider.editor.edit": "Edit",
        "provider.editor.add": "Add",
        "provider.form.invalidName": "Enter a provider name first.",
        "provider.form.invalidUrl": "The model service address must be an http or https URL.",
        "provider.check.checking": "Checking",
        "provider.check.checkingMessage": "Verifying this model service.",
        "provider.check.ok": "Normal",
        "provider.check.warn": "Issue",
        "speed.inlineHint": "Fast uses priority when the request does not specify service_tier; Standard keeps the original request.",
        "requests.title": "Requests",
        "requests.description": "Review recent requests, provider checks, and benchmarks.",
        "requests.section": "Requests",
        "requests.recent": "Recent requests",
        "requests.recentDescription": "Uses first response, first text, and total duration.",
        "requests.empty": "No requests yet.",
        "requests.ops": "Operations",
        "requests.opsTitle": "Provider checks and benchmarks",
        "requests.opsDescription": "These records come from local proxy logs and never include keys.",
        "requests.benchmarkConfirmTitle": "Choose benchmark depth",
        "requests.benchmarkConfirmText": "Quick runs 3 request pairs for a low-cost observation. Strict runs 12 pairs with balanced random order and paired statistics.",
        "requests.benchmarkCost": "Both modes spend real quota. Strict costs more, but is better for judging whether this run shows statistically meaningful acceleration.",
        "requests.providerCheck": "Provider check",
        "requests.benchmark": "Benchmark",
        "requests.check": "Check",
        "requests.noProviderCheck": "No /v1/models checks yet.",
        "requests.benchmarkNotRun": "Benchmark has not run yet.",
        "benchmark.totalGain": "Total gain",
        "benchmark.firstTextGain": "First text gain",
        "benchmark.priorityDuration": "Priority duration",
        "benchmark.firstText": "First text",
        "benchmark.caveat": "Latency is only this run's observation and can be affected by cache, network, and load; fast support is best confirmed by a priority response tier.",
        "benchmark.statsPrefix": "Stats",
        "table.time": "Time",
        "table.request": "Request",
        "table.status": "Status",
        "table.duration": "Duration",
        "table.firstResponse": "First response",
        "table.firstText": "First text",
        "table.totalDuration": "Total duration",
        "table.speedMode": "Speed mode",
        "advanced.title": "Advanced",
        "advanced.description": "Raw status and diagnostics for troubleshooting.",
        "advanced.diagnostics": "Diagnostics",
        "advanced.diagnosticsTitle": "Advanced diagnostics",
        "advanced.warning": "Runtime, config, login, startup hook, and log paths are summarized here. Diagnostic export does not include keys.",
        "advanced.viewDiagnostics": "View diagnostics",
        "advanced.runDoctor": "Run self-check",
        "advanced.copy": "Copy diagnostics",
        "advanced.download": "Export file",
        "advanced.refresh": "Refresh status",
        "advanced.copyDone": "Diagnostics copied.",
        "advanced.copyFailed": "Copy was blocked by the browser. Use Export file instead.",
        "advanced.exportDone": "Diagnostic file was generated.",
        "advanced.doctorRunning": "Running self-check...",
        "advanced.doctorPassed": "Self-check passed.",
        "advanced.doctorWarnings": "Functional checks passed; permission advice is available.",
        "advanced.doctorFailed": "Self-check found items that need attention.",
        "advanced.doctorIdle": "Self-check has not run yet.",
        "advanced.summary": "Status summary",
        "advanced.summaryDescription": "Start here for the next step instead of reading the raw state first.",
        "advanced.runtime": "Runtime",
        "advanced.config": "Config entry",
        "advanced.auth": "Login and key",
        "advanced.hook": "Startup hook",
        "advanced.telemetry": "Requests and logs",
        "advanced.nextAction": "Next action",
        "advanced.logPaths": "Log paths",
        "advanced.logPathsDescription": "These paths help inspect the proxy process, control panel, and request records.",
        "advanced.rawJson": "Raw snapshot",
        "advanced.safeNote": "Diagnostics are state-focused. Do not paste keys, auth.json, full request bodies, or prompts into chat.",
        "advanced.providerReady": "Provider detected",
        "advanced.noProvider": "No provider detected",
        "advanced.noProviderDetail": "Configure a manageable third-party model service in Codex config.toml first.",
        "advanced.noProxySettings": "The proxy is not enabled yet, so no local proxy settings exist.",
        "advanced.runtimeSource": "Runtime source",
        "advanced.logsReady": "Log paths ready",
        "advanced.requestsCount": "{count} requests",
        "advanced.metadataCount": "{count} checks",
        "advanced.hooksTrusted": "{count} trusted hooks",
        "advanced.benchmarkReady": "Benchmark available",
        "advanced.benchmarkMissing": "Benchmark not run",
        "advanced.pathLog": "Request log",
        "advanced.pathStdout": "Proxy output",
        "advanced.pathStderr": "Proxy errors",
        "advanced.pathControlStdout": "Console output",
        "advanced.pathControlStderr": "Console errors",
        "advanced.checks": "Self-check result",
        "advanced.check.python": "Python",
        "advanced.check.codex_config": "Codex config",
        "advanced.check.active_provider": "Codex active provider",
        "advanced.check.codex_model_provider": "Codex config provider",
        "advanced.check.codex_proxy_provider": "Local proxy route",
        "advanced.check.proxy_upstream_provider": "Upstream provider",
        "advanced.check.provider_route": "Request route",
        "advanced.check.provider_base_url": "Model service address",
        "advanced.check.runtime_source": "Runtime source",
        "advanced.check.login_mode": "Login method",
        "advanced.check.user_file_permissions": "User file permissions",
        "advanced.check.proxy_settings": "Proxy settings",
        "advanced.check.config_points_to_proxy": "Config points to proxy",
        "advanced.check.upstream_saved": "Upstream saved",
        "advanced.check.service_tier_policy": "Speed policy",
        "advanced.check.upstream_auth": "Upstream auth",
        "advanced.check.proxy_health": "Proxy health",
        "advanced.check.proxy_pending_restart": "Pending restart",
        "advanced.check.proxy_runtime": "Proxy runtime",
        "advanced.check.hooks_enabled": "Hooks enabled",
        "advanced.check.startup_hook": "Startup hook",
        "settings.title": "Settings",
        "settings.description": "Control panel preferences and version updates.",
        "settings.preferences": "Preferences",
        "settings.preferencesDescription": "Language and appearance only affect this local control panel.",
        "settings.updates": "Version updates",
        "settings.updatesDescription": "Check remote status before updating the local proxy.",
        "settings.updateIdle": "Updates have not been checked yet.",
        "settings.updateTitleIdle": "Software update",
        "settings.updateNote": "Checking is read-only. Updating pulls code and refreshes the local runtime.",
        "danger.eyebrow": "Disable confirmation",
        "danger.title": "Check the login path first",
        "danger.confirmNote": "After disabling, the current ChatGPT login may not work directly with the third-party model service. Switch to key or third-party login first, restart Codex, then restore.",
        "danger.currentRoute": "Current path",
        "danger.afterRoute": "After disabling",
        "danger.currentRouteDetail": "ChatGPT login · local proxy managed",
        "danger.afterRouteDetail": "Direct third-party model service",
        "danger.illustrationLabel": "Login path illustration",
        "hint.chatgptSpeed": "ChatGPT account login detected. Speed controls are handled by the Codex App.",
        "action.enable.prepare.label": "Preparing...",
        "action.enable.prepare.message": "Reading the current provider and preparing the environment.",
        "action.enable.verify.label": "Verifying model service...",
        "action.enable.verify.message": "Connecting to the current model service. First enable can take a few dozen seconds.",
        "action.enable.slow.label": "Model service is slow...",
        "action.enable.slow.message": "Still waiting for the model service. The page will update when it completes.",
        "action.update.start.label": "Updating...",
        "action.update.start.message": "Pulling updates and refreshing the local proxy. The page will recover automatically.",
        "action.update.runtime.label": "Refreshing runtime...",
        "action.update.runtime.message": "Reinstalling and refreshing the proxy process. This can take several seconds.",
        "action.update.slow.label": "Update still running...",
        "action.update.slow.message": "Still waiting for the local update. Keep this control panel open.",
        "action.update.waitUi.label": "Waiting for the new UI...",
        "action.update.waitUi.message": "When the update finishes, the page will switch to the new control panel automatically.",
        "action.checkUpdate.start.label": "Checking...",
        "action.checkUpdate.start.message": "Reading the remote branch and local working tree state.",
        "action.saveProvider.start.label": "Saving and verifying...",
        "action.saveProvider.start.message": "Saving and verifying that the model service is usable.",
        "action.saveProvider.verify.message": "Running a real streaming Responses check. The page will update when it completes.",
        "action.saveProvider.slow.message": "Still waiting for the model service. If verification fails, current settings stay unchanged.",
        "action.verifyProvider.start.label": "Checking...",
        "action.verifyProvider.start.message": "Running a real streaming Responses check.",
        "action.verifyProvider.slow.label": "Check still running...",
        "action.verifyProvider.slow.message": "The model service is responding slowly. Keep this page open.",
        "action.switchProvider.start.label": "Switching...",
        "action.switchProvider.start.message": "Switching and verifying the new model service.",
        "action.deleteProvider.start.label": "Deleting...",
        "action.deleteProvider.start.message": "Deleting the saved entry. The current model service is not affected.",
        "action.speed.start.label": "Saving...",
        "action.speed.start.message": "Saving the current selection.",
        "action.benchmark.start.label": "Running...",
        "action.benchmark.start.message": "Sending default and priority request pairs.",
        "action.benchmark.slow.label": "Benchmark still running...",
        "action.benchmark.slow.message": "This depends on model service latency. Results will refresh when it completes.",
        "action.uninstall.start.label": "Restoring direct connection...",
        "action.uninstall.start.message": "Restoring the original Codex model service and preparing local proxy cleanup.",
        "action.uninstall.cleanup.label": "Cleaning up...",
        "action.uninstall.cleanup.message": "Removing local state, install files, and skill links. The control panel will close last.",
        "action.default.label": "Working...",
    },
    "ja": {
        "page.title": "Codex コントロール",
        "brand.name": "Codex Model Gateway",
        "brand.subtitle": "コンソール",
        "toolbar.language": "言語",
        "toolbar.theme": "外観",
        "theme.system": "システム",
        "theme.light": "ライト",
        "theme.dark": "ダーク",
        "nav.overview": "概要",
        "nav.providers": "プロバイダー",
        "nav.requests": "リクエスト",
        "nav.advanced": "詳細",
        "nav.settings": "設定",
        "button.update": "更新",
        "button.checkUpdate": "更新を確認",
        "button.updateNow": "今すぐ更新",
        "button.recheckUpdate": "再確認",
        "button.checkProvider": "確認",
        "button.runBenchmark": "ベンチマーク実行",
        "button.confirmBenchmark": "クイックテスト",
        "button.confirmStrictBenchmark": "厳密テスト",
        "button.diagnostics": "診断を開く",
        "button.uninstall": "無効化して復元",
        "button.confirmUninstall": "無効化を続行",
        "button.cancelUninstall": "今はしない",
        "button.finishCleanup": "クリーンアップ完了",
        "button.saveProvider": "保存",
        "button.updateProvider": "更新",
        "button.saveSpeed": "保存",
        "button.add": "追加",
        "button.cancel": "キャンセル",
        "button.edit": "編集",
        "button.save": "保存",
        "button.switch": "有効化",
        "button.delete": "削除",
        "button.confirmDelete": "削除を確認",
        "button.enable": "有効化",
        "button.reenable": "再度有効化",
        "button.refresh": "状態を更新",
        "summary.proxy": "プロキシ",
        "summary.login": "ログイン",
        "summary.speed": "速度",
        "summary.recentRequests": "最近のリクエスト",
        "auth.chatgpt": "ChatGPT アカウントログイン",
        "auth.key": "キー / サードパーティログイン",
        "value.unknown": "不明",
        "value.key": "キー",
        "value.notEnabled": "無効",
        "value.notConfigured": "未設定",
        "value.notSelected": "未選択",
        "value.noRequests": "なし",
        "value.notRun": "未実行",
        "value.normal": "正常",
        "value.abnormal": "異常",
        "value.running": "実行中",
        "value.restartPending": "再起動待ち",
        "value.needsAttention": "要確認",
        "value.restored": "復元済み",
        "value.notManaged": "未管理",
        "value.managed": "管理中",
        "value.appControlled": "アプリ管理",
        "value.fast": "高速",
        "value.standard": "標準",
        "value.proxyFast": "プロキシ高速化",
        "value.notRecorded": "未記録",
        "value.saved": "保存済み",
        "value.missing": "未保存",
        "value.inUse": "使用中",
        "value.pending": "適用待ち",
        "value.effective": "有効",
        "value.accepted": "受理済み",
        "value.confirmed": "確認済み",
        "value.observedFaster": "高速化を観測",
        "value.unconfirmed": "未確認",
        "value.invalid": "無効",
        "value.notAccepted": "未受理",
        "providers.title": "プロバイダー",
        "providers.note.manage": "ローカルプロキシが使うモデルサービスを管理します。",
        "providers.note.readonly": "プロキシ有効化前は、Codex config.toml の読み取り専用エントリだけを表示します。",
        "providers.note.empty": "Codex config.toml にプロバイダーエントリが見つかりません。",
        "providers.empty": "表示できるプロバイダーはまだありません。先に Codex config.toml で provider を設定してください。",
        "config.title": "Codex 設定",
        "config.readonly": "config.toml 由来 · 読み取り専用",
        "config.currentEntry": "現在のエントリ",
        "config.modelServiceUrl": "モデルサービスアドレス",
        "config.note": "有効化前、この画面は Codex 設定内のプロバイダーを管理しません。変更は普段の設定ツールで行ってください。",
        "provider.header": "プロバイダー",
        "provider.note": "有効化後、この画面はローカルプロキシ設定だけを管理します。Codex config.toml は書き換えません。",
        "provider.saved": "保存済み",
        "provider.name": "名前",
        "provider.modelServiceUrl": "モデルサービスアドレス",
        "provider.apiKey": "キー",
        "provider.apiKeyPlaceholder": "保存済みキーを維持する場合は空欄",
        "provider.keyPrefix": "キー：",
        "provider.unnamed": "名前なし",
        "provider.noService": "モデルサービス未設定",
        "provider.keyEnv": "環境変数",
        "provider.keyCodexSaved": "Codex に保存済み",
        "provider.showKey": "キーを表示",
        "provider.hideKey": "キーを隠す",
        "provider.editor.edit": "編集",
        "provider.editor.add": "追加",
        "provider.form.invalidName": "先にプロバイダー名を入力してください。",
        "provider.form.invalidUrl": "モデルサービスアドレスは http または https URL にしてください。",
        "provider.check.checking": "確認中",
        "provider.check.checkingMessage": "このモデルサービスを確認しています。",
        "provider.check.ok": "正常",
        "provider.check.warn": "異常",
        "speed.inlineHint": "高速はリクエストに service_tier がない場合に priority を使います。標準は元のリクエストを維持します。",
        "requests.title": "リクエスト",
        "requests.description": "最近のリクエスト、プロバイダー確認、ベンチマークを確認します。",
        "requests.section": "リクエスト",
        "requests.recent": "最近のリクエスト",
        "requests.recentDescription": "初回応答、初回テキスト、総所要時間で確認します。",
        "requests.empty": "リクエストはまだありません。",
        "requests.ops": "運用情報",
        "requests.opsTitle": "プロバイダー確認とベンチマーク",
        "requests.opsDescription": "これらの記録はローカルプロキシのログから取得され、キーは含みません。",
        "requests.benchmarkConfirmTitle": "ベンチマークの強度を選択",
        "requests.benchmarkConfirmText": "クイックは 3 ペアで低コストに観測します。厳密は 12 ペアを平衡ランダム順で実行し、ペア統計で判定します。",
        "requests.benchmarkCost": "どちらも実利用枠を消費します。厳密テストは高コストですが、今回の加速傾向をより判断しやすくします。",
        "requests.providerCheck": "プロバイダー確認",
        "requests.benchmark": "ベンチマーク",
        "requests.check": "確認",
        "requests.noProviderCheck": "/v1/models の確認記録はまだありません。",
        "requests.benchmarkNotRun": "ベンチマークはまだ実行されていません。",
        "benchmark.totalGain": "総時間の改善",
        "benchmark.firstTextGain": "初回テキスト改善",
        "benchmark.priorityDuration": "優先時の所要時間",
        "benchmark.firstText": "初回テキスト",
        "benchmark.caveat": "遅延結果は今回の観測値で、キャッシュ、ネットワーク、負荷の影響を受けます。fast 対応は priority の応答 tier で確認するのが確実です。",
        "benchmark.statsPrefix": "統計",
        "table.time": "時刻",
        "table.request": "リクエスト",
        "table.status": "状態",
        "table.duration": "所要時間",
        "table.firstResponse": "初回応答",
        "table.firstText": "初回テキスト",
        "table.totalDuration": "総所要時間",
        "table.speedMode": "速度モード",
        "advanced.title": "詳細",
        "advanced.description": "トラブルシュート用の生の状態と診断情報です。",
        "advanced.diagnostics": "診断",
        "advanced.diagnosticsTitle": "高度な診断",
        "advanced.warning": "ランタイム、設定、ログイン、起動フック、ログパスをまとめて確認できます。診断エクスポートにキーは含みません。",
        "advanced.viewDiagnostics": "診断を見る",
        "advanced.runDoctor": "セルフチェック",
        "advanced.copy": "診断をコピー",
        "advanced.download": "ファイルを書き出す",
        "advanced.refresh": "状態を更新",
        "advanced.copyDone": "診断をコピーしました。",
        "advanced.copyFailed": "ブラウザによりコピーがブロックされました。ファイル書き出しを使ってください。",
        "advanced.exportDone": "診断ファイルを生成しました。",
        "advanced.doctorRunning": "セルフチェックを実行中...",
        "advanced.doctorPassed": "セルフチェックは通過しました。",
        "advanced.doctorWarnings": "機能チェックは正常です。権限の推奨事項があります。",
        "advanced.doctorFailed": "セルフチェックで対応が必要な項目が見つかりました。",
        "advanced.doctorIdle": "セルフチェックはまだ実行されていません。",
        "advanced.summary": "状態サマリー",
        "advanced.summaryDescription": "生の状態を読む前に、まず次のアクションをここで確認します。",
        "advanced.runtime": "ランタイム",
        "advanced.config": "設定エントリ",
        "advanced.auth": "ログインとキー",
        "advanced.hook": "起動フック",
        "advanced.telemetry": "リクエストとログ",
        "advanced.nextAction": "次のアクション",
        "advanced.logPaths": "ログパス",
        "advanced.logPathsDescription": "プロキシプロセス、コントロールパネル、リクエスト記録の確認に使います。",
        "advanced.rawJson": "生スナップショット",
        "advanced.safeNote": "診断は状態中心です。キー、auth.json、完全なリクエスト本文、プロンプトはチャットに貼らないでください。",
        "advanced.providerReady": "provider を検出",
        "advanced.noProvider": "provider 未検出",
        "advanced.noProviderDetail": "まず Codex config.toml に管理可能なサードパーティモデルサービスを設定してください。",
        "advanced.noProxySettings": "プロキシはまだ有効化されていないため、ローカルプロキシ設定はありません。",
        "advanced.runtimeSource": "ランタイムソース",
        "advanced.logsReady": "ログパスは準備済み",
        "advanced.requestsCount": "リクエスト {count} 件",
        "advanced.metadataCount": "確認 {count} 件",
        "advanced.hooksTrusted": "{count} 件信頼済み",
        "advanced.benchmarkReady": "ベンチマークあり",
        "advanced.benchmarkMissing": "ベンチマーク未実行",
        "advanced.pathLog": "リクエストログ",
        "advanced.pathStdout": "プロキシ出力",
        "advanced.pathStderr": "プロキシエラー",
        "advanced.pathControlStdout": "コンソール出力",
        "advanced.pathControlStderr": "コンソールエラー",
        "advanced.checks": "セルフチェック結果",
        "advanced.check.python": "Python",
        "advanced.check.codex_config": "Codex 設定",
        "advanced.check.active_provider": "Codex 現在の provider",
        "advanced.check.codex_model_provider": "Codex 設定 provider",
        "advanced.check.codex_proxy_provider": "ローカルプロキシ経路",
        "advanced.check.proxy_upstream_provider": "上流プロバイダー",
        "advanced.check.provider_route": "リクエスト経路",
        "advanced.check.provider_base_url": "モデルサービスアドレス",
        "advanced.check.runtime_source": "ランタイムソース",
        "advanced.check.login_mode": "ログイン方式",
        "advanced.check.user_file_permissions": "ユーザーファイル権限",
        "advanced.check.proxy_settings": "プロキシ設定",
        "advanced.check.config_points_to_proxy": "設定がプロキシを指す",
        "advanced.check.upstream_saved": "上流サービス保存済み",
        "advanced.check.service_tier_policy": "速度ポリシー",
        "advanced.check.upstream_auth": "上流認証",
        "advanced.check.proxy_health": "プロキシ健全性",
        "advanced.check.proxy_pending_restart": "再起動待ち",
        "advanced.check.proxy_runtime": "プロキシランタイム",
        "advanced.check.hooks_enabled": "Hooks 有効",
        "advanced.check.startup_hook": "起動フック",
        "settings.title": "設定",
        "settings.description": "コントロールパネルの設定とバージョン更新。",
        "settings.preferences": "環境設定",
        "settings.preferencesDescription": "言語と外観はこのローカルコントロールパネルだけに反映されます。",
        "settings.updates": "バージョン更新",
        "settings.updatesDescription": "ローカルプロキシを更新する前に、リモート状態を確認します。",
        "settings.updateIdle": "更新確認はまだ実行していません。",
        "settings.updateTitleIdle": "ソフトウェア更新",
        "settings.updateNote": "更新確認は読み取り専用です。更新はコードを取得し、ローカルランタイムを更新します。",
        "danger.eyebrow": "無効化の確認",
        "danger.title": "先にログイン経路を確認",
        "danger.confirmNote": "無効化すると、現在の ChatGPT ログインではサードパーティのモデルサービスを直接使えない可能性があります。先にキーまたはサードパーティログインへ切り替え、Codex を再起動してから復元してください。",
        "danger.currentRoute": "現在の経路",
        "danger.afterRoute": "無効化後",
        "danger.currentRouteDetail": "ChatGPT ログイン · ローカルプロキシ管理",
        "danger.afterRouteDetail": "サードパーティモデルサービスへ直接接続",
        "danger.illustrationLabel": "ログイン経路の図",
        "hint.chatgptSpeed": "ChatGPT アカウントログインを検出しました。速度制御は Codex App 側で行われます。",
        "action.enable.prepare.label": "準備中...",
        "action.enable.prepare.message": "現在のプロバイダーを読み取り、環境を準備しています。",
        "action.enable.verify.label": "モデルサービスを確認中...",
        "action.enable.verify.message": "現在のモデルサービスへ接続しています。初回有効化には数十秒かかることがあります。",
        "action.enable.slow.label": "モデルサービスの応答が遅いです...",
        "action.enable.slow.message": "まだモデルサービスの応答を待っています。完了後にページを更新します。",
        "action.update.start.label": "更新中...",
        "action.update.start.message": "更新を取得し、ローカルプロキシを更新しています。完了後に自動復帰します。",
        "action.update.runtime.label": "ランタイム更新中...",
        "action.update.runtime.message": "再インストールしてプロキシプロセスを更新しています。数秒かかることがあります。",
        "action.update.slow.label": "更新が続いています...",
        "action.update.slow.message": "ローカル更新の完了を待っています。このコントロールパネルを開いたままにしてください。",
        "action.update.waitUi.label": "新しい画面を待機中...",
        "action.update.waitUi.message": "更新完了後、新しいコントロールパネルへ自動で切り替わります。",
        "action.checkUpdate.start.label": "確認中...",
        "action.checkUpdate.start.message": "リモートブランチとローカル作業ツリーの状態を確認しています。",
        "action.saveProvider.start.label": "保存して確認中...",
        "action.saveProvider.start.message": "保存し、モデルサービスが使えるか確認しています。",
        "action.saveProvider.verify.message": "実際のストリーミング Responses 確認を実行しています。完了後にページを更新します。",
        "action.saveProvider.slow.message": "まだモデルサービスの応答を待っています。確認に失敗した場合、現在の設定は維持されます。",
        "action.verifyProvider.start.label": "確認中...",
        "action.verifyProvider.start.message": "実際のストリーミング Responses 確認を実行しています。",
        "action.verifyProvider.slow.label": "確認が続いています...",
        "action.verifyProvider.slow.message": "モデルサービスの応答が遅いです。このページを開いたままにしてください。",
        "action.switchProvider.start.label": "切り替え中...",
        "action.switchProvider.start.message": "新しいモデルサービスへ切り替えて確認しています。",
        "action.deleteProvider.start.label": "削除中...",
        "action.deleteProvider.start.message": "保存項目を削除しています。現在のモデルサービスには影響しません。",
        "action.speed.start.label": "保存中...",
        "action.speed.start.message": "現在の選択を保存しています。",
        "action.benchmark.start.label": "実行中...",
        "action.benchmark.start.message": "標準と優先のリクエストを送信しています。",
        "action.benchmark.slow.label": "ベンチマークが続いています...",
        "action.benchmark.slow.message": "モデルサービスの応答速度に依存します。完了後に結果を更新します。",
        "action.uninstall.start.label": "直結へ復元中...",
        "action.uninstall.start.message": "Codex 元のモデルサービスへ復元し、ローカルプロキシのクリーンアップを準備しています。",
        "action.uninstall.cleanup.label": "クリーンアップ中...",
        "action.uninstall.cleanup.message": "ローカル状態、インストールファイル、skill リンクを削除しています。最後にコントロールパネルを閉じます。",
        "action.default.label": "処理中...",
    },
}

UI_STATE_TRANSLATIONS: dict[str, dict[str, dict[str, str]]] = {
    "zh": {
        "working": {"title": "运行正常", "message": "Codex 已准备好继续使用当前模型服务。"},
        "restart_required": {"title": "已启用，重启后接管", "message": "当前对话可以继续。Codex 重启后，新会话会走本地代理，并按速度模式处理请求。"},
        "restart_deferred_active": {"title": "已保存，等待当前请求结束", "message": "当前有模型请求正在返回。新设置已保存，请求结束后控制面板会自动应用。"},
        "cleanup_pending": {"title": "已停用", "message": "Codex 已恢复到原模型服务。你可以重新启用，或完成清理并移除本地代理状态。"},
        "ready_to_enable": {"title": "准备启用", "message": "点击启用后，会自动准备当前模型服务路径，并提前准备 ChatGPT 账户登录兼容性。"},
        "missing_provider": {"title": "需要先配置供应商", "message": "没有检测到可接管的第三方模型服务入口；当前还没有发起上游请求。请先在 Codex config.toml 配置 provider，再回到控制面板启用。"},
        "needs_attention": {"title": "需要处理", "message": "当前环境还不能直接完成启用。请打开高级诊断，或让 Codex 根据诊断结果修复。"},
        "update_blocked": {"title": "更新被暂停"},
        "already_current": {"title": "已是最新"},
        "updated": {"title": "更新完成"},
        "update_checked_dirty": {"title": "已检查，有本地改动", "message": "远端检查完成；当前本地有未提交改动，更新会先暂停。"},
        "update_available": {"title": "发现可用更新", "message": "远端有新提交；确认当前工作区状态后，可以在设置里更新。"},
        "provider_saved": {"title": "Provider 已保存", "message": "模型服务地址和接口密钥已保存。需要使用它时，点击切换。"},
        "provider_verified": {"title": "模型服务可用"},
        "benchmark_saved": {"title": "基准测试完成", "message": "已完成 3 组标准和优先请求，结果已保存到请求记录页。"},
        "configured": {"title": "已保存"},
        "confirmation_required": {"title": "停用前需要处理登录方式"},
    },
    "en": {
        "working": {"title": "Running normally", "message": "Codex is ready to keep using the current model service."},
        "restart_required": {"title": "Enabled after restart", "message": "You can continue this conversation. After restarting Codex, new sessions will use the local proxy and the selected speed mode."},
        "restart_deferred_active": {"title": "Saved, waiting for the current request", "message": "A model request is still streaming. The new settings are saved and will be applied automatically after it finishes."},
        "cleanup_pending": {"title": "Disabled", "message": "Codex was restored to the original model service. You can enable again or finish cleanup to remove local proxy state."},
        "ready_to_enable": {"title": "Ready to enable", "message": "Enabling will prepare the current model service route and ChatGPT account compatibility."},
        "missing_provider": {"title": "Configure a provider first", "message": "No third-party model service entry was found, and no upstream requests have been made yet. Configure a provider in Codex config.toml, then return here to enable."},
        "needs_attention": {"title": "Needs attention", "message": "This environment cannot be enabled directly yet. Open diagnostics or let Codex repair it from the diagnostic output."},
        "update_blocked": {"title": "Update paused"},
        "already_current": {"title": "Already current"},
        "updated": {"title": "Update complete"},
        "update_checked_dirty": {"title": "Checked, local changes found", "message": "Remote check completed. Local uncommitted changes will pause updating first."},
        "update_available": {"title": "Update available", "message": "New remote commits are available. After reviewing the workspace, update from Settings."},
        "provider_saved": {"title": "Provider saved", "message": "The model service address and key were saved. Switch to it when you want to use it."},
        "provider_verified": {"title": "Model service is usable"},
        "benchmark_saved": {"title": "Benchmark complete", "message": "3 default and priority request pairs finished. Results were saved to Requests."},
        "configured": {"title": "Saved"},
        "confirmation_required": {"title": "Switch login method before disabling"},
    },
    "ja": {
        "working": {"title": "正常に動作中", "message": "Codex は現在のモデルサービスを引き続き使用できます。"},
        "restart_required": {"title": "再起動後に有効化", "message": "この会話は続行できます。Codex 再起動後、新しいセッションはローカルプロキシと選択した速度モードを使用します。"},
        "restart_deferred_active": {"title": "保存済み、現在のリクエスト待ち", "message": "モデルリクエストがまだストリーミング中です。新しい設定は保存され、完了後に自動適用されます。"},
        "cleanup_pending": {"title": "無効化済み", "message": "Codex は元のモデルサービスに復元されました。再度有効化するか、クリーンアップを完了してローカルプロキシ状態を削除できます。"},
        "ready_to_enable": {"title": "有効化の準備完了", "message": "有効化すると、現在のモデルサービス経路と ChatGPT アカウント互換性を準備します。"},
        "missing_provider": {"title": "先にプロバイダーを設定", "message": "接管できるサードパーティのモデルサービスエントリが見つからず、上流リクエストもまだありません。Codex config.toml に provider を設定してから戻ってください。"},
        "needs_attention": {"title": "確認が必要", "message": "この環境はまだ直接有効化できません。診断を開くか、診断結果をもとに Codex で修復してください。"},
        "update_blocked": {"title": "更新を一時停止"},
        "already_current": {"title": "最新です"},
        "updated": {"title": "更新完了"},
        "update_checked_dirty": {"title": "確認済み、ローカル変更あり", "message": "リモート確認は完了しました。未コミットのローカル変更があるため、更新は先に停止します。"},
        "update_available": {"title": "更新があります", "message": "リモートに新しいコミットがあります。作業ツリー確認後、設定から更新できます。"},
        "provider_saved": {"title": "Provider を保存しました", "message": "モデルサービスアドレスとキーを保存しました。使うときに切り替えてください。"},
        "provider_verified": {"title": "モデルサービスは利用可能です"},
        "benchmark_saved": {"title": "ベンチマーク完了", "message": "標準と優先のリクエスト 3 組が完了し、結果をリクエスト画面に保存しました。"},
        "configured": {"title": "保存しました"},
        "confirmation_required": {"title": "無効化前にログイン方式を確認"},
    },
}


def speed_mode_from_snapshot(snapshot: dict[str, Any]) -> str:
    return "standard" if snapshot.get("service_tier_policy") == "preserve" else "fast"


def speed_mode_label(snapshot: dict[str, Any]) -> str:
    return "标准" if speed_mode_from_snapshot(snapshot) == "standard" else "快速"


def speed_controls_available(snapshot: dict[str, Any]) -> bool:
    state = snapshot.get("user_state") if isinstance(snapshot.get("user_state"), dict) else {}
    terminal_state = state.get("code") in {"cleanup_pending", "uninstalled_deferred", "uninstalled"}
    api_key_login = snapshot.get("api_key_auth") or snapshot.get("login_mode") == "api_key"
    return (
        bool(providers_from_snapshot(snapshot))
        and bool(snapshot.get("base_url"))
        and bool(api_key_login)
        and not bool(snapshot.get("chatgpt_auth"))
        and not terminal_state
    )


def ui_text(key: str) -> str:
    return UI_TRANSLATIONS["zh"].get(key, key)


def script_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def provider_status(snapshot: dict[str, Any]) -> tuple[str, str]:
    if snapshot.get("config_matches") and snapshot.get("healthy") and not snapshot.get("needs_restart"):
        return "运行中", "ok"
    if snapshot.get("config_matches") and snapshot.get("needs_restart"):
        return "待重启", "warn"
    if snapshot.get("config_matches"):
        return "需处理", "warn"
    if snapshot.get("base_url") and not snapshot.get("config_matches"):
        return "已恢复", "idle"
    if snapshot.get("base_url"):
        return "未接管", "idle"
    return "未启用", "idle"


def display_text(value: Any, fallback: str = "未配置") -> str:
    return str(value) if isinstance(value, str) and value else fallback


def display_value(value: Any, fallback: str = "-") -> str:
    return str(value) if value is not None else fallback


def boolean_label(value: Any) -> str:
    return "是" if value else "否"


def provider_key_label(value: Any) -> str:
    if value == "saved":
        return "已保存"
    if isinstance(value, str) and value.startswith("process_env:"):
        return f"环境变量 {value.split(':', 1)[1]}"
    if isinstance(value, str) and value.startswith("windows_user_env:"):
        return f"环境变量 {value.split(':', 1)[1]}"
    if isinstance(value, str) and value.startswith("auth_json:"):
        return f"Codex 已保存 {value.split(':', 1)[1]}"
    return "未保存"


def providers_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("providers")
    providers = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    if providers:
        return providers
    provider = snapshot.get("provider")
    upstream = snapshot.get("upstream_base") or snapshot.get("config_base_url")
    if (isinstance(provider, str) and provider) or upstream or snapshot.get("base_url"):
        return [{
            "name": provider if isinstance(provider, str) and provider else "当前 Provider",
            "base_url": upstream,
            "current": True,
            "active": True,
            "proxy_enabled": bool(snapshot.get("config_matches")),
            "api_key": "saved" if snapshot.get("upstream_api_key_file") else "missing",
        }]
    return []


def status_code(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compact_url(value: Any, fallback: str = "未启用") -> str:
    if not isinstance(value, str) or not value:
        return fallback
    return value.replace("https://", "").replace("http://", "")


def provider_route_chain(snapshot: dict[str, Any]) -> str:
    codex_provider = display_text(
        snapshot.get("codex_model_provider") or snapshot.get("active_provider") or snapshot.get("config_provider"),
        "",
    )
    local_proxy = compact_url(snapshot.get("base_url"), "")
    config_base = compact_url(snapshot.get("config_base_url"), "")
    upstream_provider = display_text(
        snapshot.get("runtime_upstream_provider")
        or snapshot.get("proxy_upstream_provider")
        or snapshot.get("managed_upstream_provider")
        or snapshot.get("provider"),
        "",
    )
    upstream = compact_url(snapshot.get("runtime_upstream_base") or snapshot.get("upstream_base"), "")
    if not (local_proxy and snapshot.get("config_matches")):
        return " -> ".join(part for part in (codex_provider, config_base or upstream) if part)
    route = " -> ".join(part for part in (codex_provider, local_proxy, upstream_provider, upstream) if part)
    pending_provider = display_text(snapshot.get("pending_upstream_provider"), "")
    pending_upstream = compact_url(snapshot.get("upstream_base"), "")
    if pending_provider:
        pending_route = " -> ".join(part for part in (pending_provider, pending_upstream) if part)
        return f"{route} · 待应用 {pending_route}" if pending_route else route
    return route


def short_login_label(snapshot: dict[str, Any]) -> str:
    if snapshot.get("chatgpt_auth"):
        return "ChatGPT"
    if snapshot.get("api_key_auth"):
        return "密钥"
    return "未知"


def short_proxy_label(snapshot: dict[str, Any]) -> str:
    if snapshot.get("config_matches") and snapshot.get("healthy") and not snapshot.get("needs_restart"):
        return "已接管"
    if snapshot.get("config_matches") and snapshot.get("needs_restart"):
        return "待重启"
    if snapshot.get("base_url"):
        return "未接管"
    return "未启用"


def speed_label_for_behavior(behavior: Any) -> str:
    if behavior == "app_controlled":
        return "App 控制"
    if behavior in {"inject_missing", "global_priority", "auto_global_priority"}:
        return "快速"
    if behavior in {"preserve", "preserve_only", "unknown_conservative"}:
        return "标准"
    return "未启用"


def short_speed_label(snapshot: dict[str, Any]) -> str:
    current = speed_label_for_behavior(
        snapshot.get("runtime_fast_behavior") if snapshot.get("settings_pending") else snapshot.get("fast_behavior")
    )
    if snapshot.get("settings_pending"):
        pending = speed_label_for_behavior(snapshot.get("fast_behavior"))
        return f"{current} · 待应用{pending}" if pending != current else f"{current} · 待应用"
    return current


def proxy_summary_tone(snapshot: dict[str, Any]) -> str:
    if snapshot.get("config_matches") and snapshot.get("healthy") and not snapshot.get("needs_restart"):
        return "ok"
    if snapshot.get("config_matches"):
        return "warn"
    return "idle"


def login_summary_tone(snapshot: dict[str, Any]) -> str:
    return "ok" if snapshot.get("chatgpt_auth") or snapshot.get("api_key_auth") else "idle"


def speed_summary_tone(snapshot: dict[str, Any]) -> str:
    return "ok" if short_speed_label(snapshot) != "未启用" else "idle"


def recent_request_summary(snapshot: dict[str, Any]) -> tuple[str, str]:
    events = snapshot.get("recent_response_events")
    event = events[-1] if isinstance(events, list) and events else None
    if not isinstance(event, dict):
        return "暂无", "idle"
    code = status_code(event.get("status"))
    if code is None or code >= 400:
        return "异常", "warn"
    return "正常", "ok"


def format_duration(value: Any) -> str:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{duration / 1000:.3f}s"


def format_optional_duration(value: Any) -> str:
    rendered = format_duration(value)
    return "不适用" if rendered == "-" else rendered


def request_ttft_value(event: dict[str, Any]) -> Any:
    return event.get("ttft_ms", event.get("first_output_ms"))


def timing_header(label: str, _term: str, description: str, label_key: str = "") -> str:
    title = f"{label}：{description}"
    attr = f' data-i18n="{html.escape(label_key, quote=True)}"' if label_key else ""
    return f'<span class="metric-term" title="{html.escape(title, quote=True)}"{attr}>{html.escape(label)}</span>'


def render_time_value(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "n/a"
    text = html.escape(value)
    return f'<time class="local-time" datetime="{text}" title="UTC {text}">{text}</time>'


def request_status_label(event: dict[str, Any] | None) -> tuple[str, str]:
    if not event:
        return "暂无", "idle"
    code = status_code(event.get("status"))
    if code is None:
        return display_text(event.get("status"), "未知"), "warn"
    if code >= 400:
        return "异常", "warn"
    return "正常", "ok"


def request_speed_label(event: dict[str, Any]) -> str:
    effective_policy = event.get("service_tier_effective_policy")
    if effective_policy == "preserve":
        return "App 控制"
    if effective_policy == "inject_missing":
        return "代理加速"
    return display_text(effective_policy, "未记录")


def event_detail(event: dict[str, Any]) -> str:
    fields = (
        "request_id",
        "status",
        "duration_ms",
        "ttfb_ms",
        "ttft_ms",
        "first_event_ms",
        "first_output_ms",
        "service_tier_before",
        "service_tier_after",
        "service_tier_injected",
        "service_tier_effective_policy",
        "stream",
        "response_content_type",
        "json_error",
        "error_type",
    )
    lines = [f"{field}: {event[field]}" for field in fields if event.get(field) is not None]
    return "\n".join(lines)


def title_attr(value: str) -> str:
    return f' title="{html.escape(value, quote=True)}"' if value else ""


def render_status_pill(label: str, tone: str, detail: str = "", label_key: str = "") -> str:
    attr = f' data-i18n="{html.escape(label_key, quote=True)}"' if label_key else ""
    return f'<span class="status-pill {html.escape(tone)}"{title_attr(detail)}{attr}>{html.escape(label)}</span>'


def format_speedup(value: Any) -> str:
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return "-"


def benchmark_summary_value(benchmark: dict[str, Any], tier: str, key: str) -> Any:
    summary = benchmark.get(tier)
    if not isinstance(summary, dict):
        return None
    return summary.get(key)


def benchmark_ttft_value(benchmark: dict[str, Any], tier: str) -> Any:
    value = benchmark_summary_value(benchmark, tier, "median_ttft_ms")
    if value is None:
        value = benchmark_summary_value(benchmark, tier, "median_first_output_ms")
    return value


def benchmark_stat_note(benchmark: dict[str, Any]) -> str:
    test = benchmark.get("statistical_test")
    if not isinstance(test, dict):
        return ""
    total = test.get("metrics", {}).get("total_ms") if isinstance(test.get("metrics"), dict) else None
    if not isinstance(total, dict):
        return ""
    conclusion = test.get("conclusion")
    usable = display_value(total.get("usable_pairs"), "0")
    speed = format_speedup(total.get("median_speedup"))
    p_value = total.get("p_value_one_sided")
    p_text = f"p={p_value}" if isinstance(p_value, (int, float)) else "p=-"
    if conclusion == "priority_faster":
        verdict = "严格测试显示本轮 priority 总耗时显著更低"
    elif conclusion == "no_significant_speedup":
        verdict = "严格测试未发现本轮 priority 总耗时显著更低"
    else:
        verdict = "样本量不足，统计结论仅供参考"
    return f"{verdict}；可用配对 {usable}，中位收益 {speed}，{p_text}。"


def benchmark_label(benchmark: dict[str, Any] | None) -> tuple[str, str, str]:
    if not benchmark:
        return "未运行", "idle", "value.notRun"
    assessment = benchmark.get("priority_support_assessment")
    conclusion = assessment.get("conclusion") if isinstance(assessment, dict) else None
    if conclusion == "invalid":
        return "无效", "warn", "value.invalid"
    if conclusion == "confirmed" or benchmark.get("provider_confirmed_priority") is True:
        return "已确认", "ok", "value.confirmed"
    if conclusion == "accepted_different_tier":
        return "未确认", "warn", "value.unconfirmed"
    if benchmark.get("priority_accepted") is False:
        return "未接受", "warn", "value.notAccepted"
    if benchmark.get("priority_accepted") is True:
        return "已接受", "idle", "value.accepted"
    if benchmark.get("observed_priority_effective") is True:
        return "观测更快", "ok", "value.observedFaster"
    return "未知", "idle", "value.unknown"


def render_signal_metric(label: str, value: str, label_key: str = "") -> str:
    attr = f' data-i18n="{html.escape(label_key, quote=True)}"' if label_key else ""
    return f"""
              <div class="signal-metric">
                <span{attr}>{html.escape(label)}</span>
                <strong>{html.escape(value)}</strong>
              </div>
"""


def render_benchmark_signal(snapshot: dict[str, Any]) -> str:
    raw = snapshot.get("benchmark_result")
    benchmark = raw if isinstance(raw, dict) else None
    label, tone, label_key = benchmark_label(benchmark)
    if not benchmark:
        return f"""
            <section class="signal-card" aria-label="性能基准">
              <div class="signal-head">
                <span data-i18n="requests.benchmark">性能基准</span>
                {render_status_pill(label, tone, label_key=label_key)}
              </div>
              <p class="empty-state" data-i18n="requests.benchmarkNotRun">尚未运行基准测试。</p>
            </section>
"""

    provider = display_text(benchmark.get("provider"), "未知 Provider")
    model = display_text(benchmark.get("model"), "未知模型")
    mode = display_text(benchmark.get("benchmark_mode"), "未知模式")
    profile = display_text(benchmark.get("profile"), "未知负载")
    pairs = display_value(benchmark.get("pairs"), "未知")
    default_ok = benchmark_summary_value(benchmark, "default", "ok")
    default_count = benchmark_summary_value(benchmark, "default", "count")
    priority_ok = benchmark_summary_value(benchmark, "priority", "ok")
    priority_count = benchmark_summary_value(benchmark, "priority", "count")
    priority_total = benchmark_summary_value(benchmark, "priority", "median_total_ms")
    default_ttft = benchmark_ttft_value(benchmark, "default")
    priority_ttft = benchmark_ttft_value(benchmark, "priority")
    stat_note = benchmark_stat_note(benchmark)
    stat_markup = (
        f'<p class="signal-note benchmark-stat">{html.escape(stat_note)}</p>'
        if stat_note else ""
    )
    note = (
        f"{provider} / {model} / {mode} / {profile} / {pairs} 组；"
        f"样本 default {display_value(default_ok)}/{display_value(default_count)}，"
        f"priority {display_value(priority_ok)}/{display_value(priority_count)}。"
    )
    return f"""
            <section class="signal-card" aria-label="性能基准">
              <div class="signal-head">
                <span data-i18n="requests.benchmark">性能基准</span>
                {render_status_pill(label, tone, label_key=label_key)}
              </div>
              <div class="signal-metrics">
                {render_signal_metric("总耗时收益", format_speedup(benchmark.get("observed_speedup_total")), "benchmark.totalGain")}
                {render_signal_metric("首文本收益", format_speedup(benchmark.get("observed_speedup_ttft", benchmark.get("observed_speedup_first_output"))), "benchmark.firstTextGain")}
                {render_signal_metric("优先耗时", format_duration(priority_total), "benchmark.priorityDuration")}
                {render_signal_metric("首文本", f"{format_optional_duration(default_ttft)} -> {format_optional_duration(priority_ttft)}", "benchmark.firstText")}
              </div>
              <p class="signal-note">最近运行 {render_time_value(benchmark.get("ts"))}；{html.escape(note)}</p>
              {stat_markup}
              <p class="signal-note benchmark-caveat" data-i18n="benchmark.caveat">延迟结果只代表本轮观测，受缓存、网络和负载影响；是否支持 fast 优先看响应是否确认 priority。</p>
            </section>
"""


def render_provider_metadata_signal(snapshot: dict[str, Any]) -> str:
    raw = snapshot.get("recent_provider_metadata_events")
    events = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    last_event = events[-1] if events else None
    label, tone = request_status_label(last_event)
    if not events:
        return f"""
            <section class="signal-card" aria-label="Provider 检查">
              <div class="signal-head">
                <span data-i18n="requests.providerCheck">Provider 检查</span>
                {render_status_pill("暂无", "idle", label_key="value.noRequests")}
              </div>
              <p class="empty-state" data-i18n="requests.noProviderCheck">还没有 /v1/models 检查记录。</p>
            </section>
"""

    rows = []
    for event in reversed(events):
        status, status_tone = request_status_label(event)
        method = display_text(event.get("method"), "GET")
        path = display_text(event.get("path"), "n/a")
        detail = event_detail(event)
        rows.append(f"""
                <tr>
                  <td class="time-cell">{render_time_value(event.get("ts"))}</td>
                  <td class="request-route" title="{html.escape(method.lower())} {html.escape(path)}">{html.escape(method.lower())} {html.escape(path)}</td>
                  <td>{render_status_pill(status, status_tone, detail)}</td>
                  <td class="number-cell">{html.escape(format_duration(event.get("duration_ms")))}</td>
                </tr>
""")
    return f"""
            <section class="signal-card" aria-label="Provider 检查">
              <div class="signal-head">
                <span data-i18n="requests.providerCheck">Provider 检查</span>
                {render_status_pill(label, tone, event_detail(last_event))}
              </div>
              <table class="metadata-table">
                <thead>
                  <tr>
                    <th data-i18n="table.time">时间</th>
                    <th data-i18n="requests.check">检查</th>
                    <th data-i18n="table.status">状态</th>
                    <th data-i18n="table.duration">耗时</th>
                  </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </section>
"""


def render_operational_signals(snapshot: dict[str, Any]) -> str:
    return f"""
          <div class="signal-grid">
            {render_provider_metadata_signal(snapshot)}
            {render_benchmark_signal(snapshot)}
          </div>
"""


def render_status_metric(label: str, value: str, tone: str = "idle", label_key: str = "") -> str:
    attr = f' data-i18n="{html.escape(label_key, quote=True)}"' if label_key else ""
    return f"""
            <div class="status-metric {html.escape(tone)}">
              <span{attr}>{html.escape(label)}</span>
              <strong>{html.escape(value)}</strong>
            </div>
"""


def render_speed_metric(snapshot: dict[str, Any]) -> str:
    return render_status_metric(
        "速度",
        short_speed_label(snapshot),
        speed_summary_tone(snapshot),
        "summary.speed",
    )


def render_overview_speed_panel(snapshot: dict[str, Any]) -> str:
    if not speed_controls_available(snapshot):
        return ""
    speed_mode = speed_mode_from_snapshot(snapshot)
    fast_checked = " checked" if speed_mode == "fast" else ""
    standard_checked = " checked" if speed_mode == "standard" else ""
    speed_label = html.escape(speed_mode_label(snapshot))
    return f"""
      <section id="overviewSpeedPreference" class="overview-preference" aria-label="速度模式">
        <div class="preference-copy">
          <span data-i18n="summary.speed">速度</span>
          <strong id="providerSpeed">{speed_label}</strong>
          <p class="speed-hint" data-i18n="speed.inlineHint">快速会在请求未指定 service_tier 时使用 priority；标准保持原始请求。</p>
        </div>
        <form id="speedForm" class="speed-preference-form" aria-label="速度模式">
          <fieldset>
            <div class="segments compact-segments">
              <label><input type="radio" name="speedMode" value="fast"{fast_checked}><span data-i18n="value.fast">快速</span></label>
              <label><input type="radio" name="speedMode" value="standard"{standard_checked}><span data-i18n="value.standard">标准</span></label>
            </div>
          </fieldset>
          <button id="saveSpeed" class="secondary" type="submit" data-i18n="button.saveSpeed">保存</button>
        </form>
      </section>
"""


def runtime_source_label(snapshot: dict[str, Any]) -> str:
    runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}
    manager = runtime.get("manager") if isinstance(runtime.get("manager"), dict) else {}
    layout = display_text(manager.get("source_layout"), "unknown")
    source = manager.get("source_root") or manager.get("module_file")
    if source:
        return f"{layout} · {source}"
    return layout


def diagnostic_runtime(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    if snapshot.get("config_matches") and snapshot.get("healthy") and not snapshot.get("needs_restart"):
        return "运行中", "ok", "value.running", compact_url(snapshot.get("base_url"), "未启用")
    if snapshot.get("base_url"):
        label, tone = provider_status(snapshot)
        return label, tone, "", runtime_source_label(snapshot)
    return "未启用", "idle", "value.notEnabled", ui_text("advanced.noProxySettings")


def diagnostic_config(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    codex_provider = snapshot.get("codex_model_provider") or snapshot.get("config_provider")
    base_url = snapshot.get("config_base_url") or snapshot.get("upstream_base")
    if codex_provider and base_url:
        return "路由已就绪", "ok", "advanced.providerReady", provider_route_chain(snapshot)
    return "未检测到 provider", "warn", "advanced.noProvider", ui_text("advanced.noProviderDetail")


def diagnostic_auth(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    if snapshot.get("chatgpt_auth"):
        detail = "ChatGPT 账户登录"
        if snapshot.get("chatgpt_login_compatible") is True:
            detail = "ChatGPT 账户登录 · provider-auth 已准备"
        elif snapshot.get("chatgpt_login_compatible") is False and snapshot.get("base_url"):
            detail = "ChatGPT 账户登录 · 需要准备 provider-auth"
        return "ChatGPT", "ok", "", detail
    if snapshot.get("api_key_auth"):
        return "密钥", "ok", "value.key", "Codex 使用接口密钥登录"
    return "未知", "idle", "value.unknown", "没有检测到 ChatGPT 或接口密钥登录状态"


def diagnostic_hook(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    trust = snapshot.get("startup_hook_trust") if isinstance(snapshot.get("startup_hook_trust"), dict) else {}
    hooks = trust.get("hooks") if isinstance(trust.get("hooks"), list) else []
    if snapshot.get("startup_hook"):
        return "已就绪", "ok", "value.normal", f"已信任 {len(hooks)} 条"
    if snapshot.get("base_url"):
        return "需处理", "warn", "value.needsAttention", "存在本地代理设置，但启动钩子尚未就绪"
    return "未启用", "idle", "value.notEnabled", "启用代理后会安装并信任启动钩子"


def diagnostic_telemetry(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    response_events = snapshot.get("recent_response_events")
    metadata_events = snapshot.get("recent_provider_metadata_events")
    responses = len(response_events) if isinstance(response_events, list) else 0
    metadata = len(metadata_events) if isinstance(metadata_events, list) else 0
    benchmark = snapshot.get("benchmark_result") if isinstance(snapshot.get("benchmark_result"), dict) else None
    if responses or metadata or benchmark:
        benchmark_label_text = ui_text("advanced.benchmarkReady") if benchmark else ui_text("advanced.benchmarkMissing")
        return ui_text("advanced.logsReady"), "ok", "advanced.logsReady", f"{responses} 条请求 · {metadata} 次检查 · {benchmark_label_text}"
    return "暂无", "idle", "value.noRequests", "日志路径已准备，尚未记录请求或 Provider 检查"


def diagnostic_next_action(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    state = snapshot.get("user_state") if isinstance(snapshot.get("user_state"), dict) else {}
    action = display_text(state.get("title"), "需要处理")
    detail = display_text(state.get("message"), "请打开高级诊断，或让 Codex 根据诊断结果修复。")
    tone = "ok" if state.get("code") == "working" else "warn"
    if state.get("code") in {"cleanup_pending", "ready_to_enable"}:
        tone = "idle"
    return action, tone, "", detail


def render_diagnostic_row(
    row_id: str,
    label: str,
    label_key: str,
    value: str,
    tone: str,
    detail: str,
    value_key: str = "",
) -> str:
    value_attr = f' data-i18n="{html.escape(value_key, quote=True)}"' if value_key else ""
    return f"""
              <div class="diagnostic-row" data-diagnostic-row="{html.escape(row_id, quote=True)}">
                <div>
                  <span data-i18n="{html.escape(label_key, quote=True)}">{html.escape(label)}</span>
                  <p id="diagnostic-{html.escape(row_id, quote=True)}-detail">{html.escape(detail)}</p>
                </div>
                <strong id="diagnostic-{html.escape(row_id, quote=True)}-value" class="status-pill {html.escape(tone)}"{value_attr}>{html.escape(value)}</strong>
              </div>
"""


def render_diagnostic_summary(snapshot: dict[str, Any]) -> str:
    rows = [
        ("runtime", "运行时", "advanced.runtime", *diagnostic_runtime(snapshot)),
        ("config", "配置入口", "advanced.config", *diagnostic_config(snapshot)),
        ("auth", "登录与密钥", "advanced.auth", *diagnostic_auth(snapshot)),
        ("hook", "启动钩子", "advanced.hook", *diagnostic_hook(snapshot)),
        ("telemetry", "请求与日志", "advanced.telemetry", *diagnostic_telemetry(snapshot)),
        ("next", "下一步", "advanced.nextAction", *diagnostic_next_action(snapshot)),
    ]
    return "\n".join(
        render_diagnostic_row(row_id, label, label_key, value, tone, detail, value_key)
        for row_id, label, label_key, value, tone, value_key, detail in rows
    )


def render_diagnostic_path(label: str, label_key: str, value: Any) -> str:
    path = display_text(value, "-")
    return f"""
              <div class="diagnostic-path">
                <span data-i18n="{html.escape(label_key, quote=True)}">{html.escape(label)}</span>
                <code>{html.escape(path)}</code>
              </div>
"""


def render_diagnostic_paths(snapshot: dict[str, Any]) -> str:
    return "\n".join([
        render_diagnostic_path("请求日志", "advanced.pathLog", snapshot.get("log")),
        render_diagnostic_path("代理输出", "advanced.pathStdout", snapshot.get("stdout")),
        render_diagnostic_path("代理错误", "advanced.pathStderr", snapshot.get("stderr")),
    ])


def nav_icon(name: str) -> str:
    paths = {
        "overview": '<rect x="4" y="4" width="6" height="6" rx="1.5"></rect><rect x="14" y="4" width="6" height="6" rx="1.5"></rect><rect x="4" y="14" width="6" height="6" rx="1.5"></rect><rect x="14" y="14" width="6" height="6" rx="1.5"></rect>',
        "providers": '<path d="M8 7h8"></path><path d="M8 17h8"></path><path d="M6 9v6"></path><path d="M18 9v6"></path><circle cx="6" cy="7" r="2"></circle><circle cx="18" cy="7" r="2"></circle><circle cx="6" cy="17" r="2"></circle><circle cx="18" cy="17" r="2"></circle>',
        "speed": '<path d="M4 14a8 8 0 0 1 16 0"></path><path d="M12 14l4-5"></path><path d="M8 20h8"></path>',
        "requests": '<path d="M6 7h12"></path><path d="M6 12h12"></path><path d="M6 17h8"></path><circle cx="3.5" cy="7" r=".8"></circle><circle cx="3.5" cy="12" r=".8"></circle><circle cx="3.5" cy="17" r=".8"></circle>',
        "advanced": '<path d="M4 7h16"></path><path d="M4 17h16"></path><circle cx="9" cy="7" r="2"></circle><circle cx="15" cy="17" r="2"></circle>',
        "settings": '<circle cx="12" cy="12" r="3"></circle><path d="M12 3v3"></path><path d="M12 18v3"></path><path d="m4.8 4.8 2.1 2.1"></path><path d="m17.1 17.1 2.1 2.1"></path><path d="M3 12h3"></path><path d="M18 12h3"></path><path d="m4.8 19.2 2.1-2.1"></path><path d="m17.1 6.9 2.1-2.1"></path>',
    }
    path = paths.get(name, paths["overview"])
    return f'<span class="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24">{path}</svg></span>'


def render_top_summary(snapshot: dict[str, Any]) -> str:
    request_label, request_tone = recent_request_summary(snapshot)
    return f"""
      <div class="hero-summary" aria-label="当前状态摘要">
        {render_status_metric("代理", short_proxy_label(snapshot), proxy_summary_tone(snapshot), "summary.proxy")}
        {render_status_metric("登录", short_login_label(snapshot), login_summary_tone(snapshot), "summary.login")}
        {render_speed_metric(snapshot)}
        {render_status_metric("最近请求", request_label, request_tone, "summary.recentRequests")}
      </div>
"""


def render_recent_events(snapshot: dict[str, Any]) -> str:
    raw = snapshot.get("recent_response_events")
    events = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    if not events:
        return '<p class="empty-state" data-i18n="requests.empty">还没有请求记录。</p>'

    def cell(
        label: str,
        label_key: str,
        value: str,
        *,
        class_name: str = "",
        title: str = "",
    ) -> str:
        class_attr = f' class="{html.escape(class_name, quote=True)}"' if class_name else ""
        title_attr_value = title_attr(title)
        return (
            f"<td{class_attr}{title_attr_value}>"
            f'<span class="mobile-cell-label" data-i18n="{html.escape(label_key, quote=True)}">{html.escape(label)}</span>'
            f'<span class="cell-value">{value}</span>'
            "</td>"
        )

    rows: list[str] = []
    for event in reversed(events):
        status, tone = request_status_label(event)
        method = display_text(event.get("method"), "POST")
        path = display_text(event.get("path"), "n/a")
        detail = event_detail(event)
        route = f"{method.lower()} {path}"
        rows.append(f"""
            <tr>
              {cell("时间", "table.time", render_time_value(event.get("ts")), class_name="time-cell")}
              {cell("请求", "table.request", html.escape(route), class_name="request-route", title=route)}
              {cell("状态", "table.status", render_status_pill(status, tone, detail))}
              {cell("首响应", "table.firstResponse", html.escape(format_duration(event.get("ttfb_ms", event.get("first_event_ms")))), class_name="number-cell", title="首响应：收到上游第一个响应字节或第一个流式事件。")}
              {cell("首文本", "table.firstText", html.escape(format_optional_duration(request_ttft_value(event))), class_name="number-cell", title="首文本：收到第一个可见文本。没有文本输出的请求显示不适用。")}
              {cell("完整耗时", "table.totalDuration", html.escape(format_duration(event.get("duration_ms"))), class_name="number-cell")}
              {cell("速度模式", "table.speedMode", html.escape(request_speed_label(event)), title=detail)}
            </tr>
""")
    return f"""
        <div class="request-table-wrap">
          <table class="request-table">
            <thead>
              <tr>
                <th data-i18n="table.time">时间</th>
                <th data-i18n="table.request">请求</th>
                <th data-i18n="table.status">状态</th>
                <th>{timing_header("首响应", "ttfb", "收到上游第一个响应字节", "table.firstResponse")}</th>
                <th>{timing_header("首文本", "ttft", "收到第一个可见文本", "table.firstText")}</th>
                <th>{timing_header("完整耗时", "e2e", "请求从开始到结束的总耗时", "table.totalDuration")}</th>
                <th data-i18n="table.speedMode">速度模式</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
"""


def render_provider_cards(providers: list[dict[str, Any]], selected_provider: str) -> str:
    cards: list[str] = []
    for item in providers:
        name = str(item.get("name") or "未命名")
        name_attr = html.escape(name, quote=True)
        is_current = bool(item.get("current")) or name == selected_provider
        is_pending = bool(item.get("pending"))
        card_classes = ["provider-card"]
        if is_current:
            card_classes.append("current")
        if is_pending:
            card_classes.append("pending")
        status_pills: list[str] = []
        if is_current:
            status_pills.append(f'<span class="status-pill ok" data-i18n="value.inUse">{ui_text("value.inUse")}</span>')
        if is_pending:
            status_pills.append(f'<span class="status-pill warn" data-i18n="value.pending">{ui_text("value.pending")}</span>')
        status_pill = "".join(status_pills)
        enable_button = "" if is_current or is_pending else (
            f'<button class="provider-enable" type="button" data-provider-action="switch" '
            f'data-provider="{name_attr}" data-i18n="button.switch">{ui_text("button.switch")}</button>'
        )
        can_delete = bool(item.get("deletable"))
        delete_button = "" if not can_delete else (
            f'<button class="provider-delete" type="button" data-provider-action="delete" '
            f'data-provider="{name_attr}" data-i18n="button.delete">{ui_text("button.delete")}</button>'
        )
        check_button = (
            f'<button class="provider-check" type="button" data-provider-action="verify" '
            f'data-provider="{name_attr}" data-i18n="button.checkProvider">{ui_text("button.checkProvider")}</button>'
        )
        cards.append(f"""
            <article class="{' '.join(card_classes)}" data-provider-name="{name_attr}">
              <div class="provider-main">
                <span class="provider-avatar">{html.escape(name[:1] or "?")}</span>
                <div class="provider-info">
                  <strong>{html.escape(name)}</strong>
                  <span class="provider-url">{html.escape(display_text(item.get("base_url"), ui_text("provider.noService")))}</span>
                  <span class="provider-auth-state"><span data-i18n="provider.keyPrefix">{ui_text("provider.keyPrefix")}</span>{html.escape(provider_key_label(item.get("api_key")))}</span>
                  <span class="provider-row-feedback" data-provider-check-feedback role="status" aria-live="polite" hidden></span>
                </div>
              </div>
              <div class="provider-card-actions">
                {status_pill}
                {check_button}
                {enable_button}
                <button class="provider-edit" type="button" data-provider-action="edit" data-provider="{name_attr}" data-i18n="button.edit">{ui_text("button.edit")}</button>
                {delete_button}
              </div>
            </article>
""")
    return "".join(cards)


def render_codex_config_panel(provider: dict[str, Any], terminal_state: bool) -> str:
    if terminal_state or not provider:
        return ""
    name = html.escape(str(provider.get("name") or "未选择"))
    base_url = html.escape(display_text(provider.get("base_url"), "未设置模型服务"))
    return f"""
      <section id="codexConfigPanel" class="detail-panel">
        <div class="detail-panel-head">
          <div>
            <span class="muted" data-i18n="config.title">Codex 配置</span>
            <h2>{name}</h2>
            <p data-i18n="config.readonly">来自 config.toml · 只读</p>
          </div>
        </div>
        <div class="detail-panel-body">
          <div class="readonly-config">
            <span data-i18n="config.currentEntry">当前入口</span>
            <strong>{name}</strong>
            <span data-i18n="config.modelServiceUrl">模型服务地址</span>
            <strong>{base_url}</strong>
          </div>
          <p class="readonly-note" data-i18n="config.note">启用前这里不管理 Codex 配置里的供应商；如需增删改，请继续使用你熟悉的配置工具。</p>
        </div>
      </section>
"""


def render_page(snapshot: dict[str, Any], token: str) -> str:
    user_state = snapshot.get("user_state", {})
    state_code = str(user_state.get("code") or "")
    title = str(user_state.get("title") or "需要处理")
    message = str(user_state.get("message") or "请打开高级诊断，或让 Codex 根据诊断结果修复。")
    primary_action = user_state.get("primary_action")
    primary_label = str(user_state.get("primary_label") or "刷新")
    button = (
        f'<button id="primary" data-action="{html.escape(str(primary_action))}">{html.escape(primary_label)}</button>'
        if primary_action in {"enable", "refresh", "uninstall"}
        else '<button id="primary" class="secondary" data-action="diagnostics">打开高级诊断</button>'
    )
    labels: dict[str, str] = {}
    terminal_state = state_code in {"cleanup_pending", "uninstalled_deferred", "uninstalled"}
    show_runtime_controls = bool(snapshot.get("base_url")) and not terminal_state
    proxy_enabled = show_runtime_controls
    action_buttons = ""
    danger_zone = ""
    labels.update({
        "update": "更新",
        "checkUpdate": "检查更新",
    })
    if show_runtime_controls:
        labels.update({
            "uninstall": "停用并恢复",
            "confirmUninstall": "仍要停用",
            "cancelUninstall": "先不停用",
        })
        if primary_action != "uninstall":
            action_buttons = '<button id="uninstall" class="warn" data-action="uninstall">停用并恢复</button>'
        danger_zone = f"""
      <div id="dangerZone" class="danger-zone" hidden>
        <div class="danger-copy">
          <span class="danger-eyebrow" data-i18n="danger.eyebrow">{ui_text("danger.eyebrow")}</span>
          <strong data-i18n="danger.title">{ui_text("danger.title")}</strong>
          <p data-i18n="danger.confirmNote">{ui_text("danger.confirmNote")}</p>
          <div class="danger-route" aria-label="停用前后路径">
            <div>
              <span data-i18n="danger.currentRoute">{ui_text("danger.currentRoute")}</span>
              <strong data-i18n="danger.currentRouteDetail">{ui_text("danger.currentRouteDetail")}</strong>
            </div>
            <div>
              <span data-i18n="danger.afterRoute">{ui_text("danger.afterRoute")}</span>
              <strong data-i18n="danger.afterRouteDetail">{ui_text("danger.afterRouteDetail")}</strong>
            </div>
          </div>
          <div class="danger-actions">
            <button id="confirmUninstall" class="warn" data-action="confirm-uninstall" data-i18n="button.confirmUninstall">{ui_text("button.confirmUninstall")}</button>
            <button id="cancelUninstall" class="secondary" type="button" data-i18n="button.cancelUninstall">{ui_text("button.cancelUninstall")}</button>
          </div>
        </div>
        <div class="danger-art" role="img" aria-label="{html.escape(ui_text("danger.illustrationLabel"), quote=True)}">
          <svg viewBox="0 0 180 132" aria-hidden="true">
            <path class="art-panel" d="M35 24h72c9 0 16 7 16 16v52c0 9-7 16-16 16H35c-9 0-16-7-16-16V40c0-9 7-16 16-16z"></path>
            <path class="art-panel muted" d="M103 39h43c7 0 12 5 12 12v44c0 7-5 12-12 12h-43c-7 0-12-5-12-12V51c0-7 5-12 12-12z"></path>
            <path class="art-line" d="M46 53h44M46 70h31M46 87h51"></path>
            <path class="art-line" d="M111 62h25M111 79h31"></path>
            <path class="art-bridge" d="M83 30c14-17 41-19 59-4"></path>
            <path class="art-bridge" d="M95 113c16 10 41 8 56-8"></path>
            <path class="art-key" d="M129 20l8 8 13-13"></path>
            <circle class="art-node" cx="34" cy="38" r="4"></circle>
            <circle class="art-node" cx="152" cy="96" r="4"></circle>
          </svg>
        </div>
      </div>
"""
    elif state_code == "cleanup_pending":
        labels["finishCleanup"] = "完成清理"
        action_buttons = '<button id="finishCleanup" class="warn" data-action="uninstall">完成清理</button>'

    providers = providers_from_snapshot(snapshot)
    selected_provider = str(snapshot.get("current_provider") or snapshot.get("provider") or "")
    selected_record = next((item for item in providers if item.get("name") == selected_provider), providers[0] if providers else {})
    provider_name_value = html.escape(str(selected_record.get("name") or selected_provider), quote=True)
    provider_url_value = html.escape(str(selected_record.get("base_url") or ""), quote=True)
    codex_config_panel = render_codex_config_panel(selected_record, terminal_state) if providers and not proxy_enabled else ""
    provider_management = ""
    if providers and proxy_enabled:
        summary_name = html.escape(str(selected_record.get("name") or selected_provider or "未选择"))
        summary_url = html.escape(display_text(selected_record.get("base_url"), "未设置模型服务"))
        labels.update({
            "saveProvider": "保存",
            "confirmDelete": "确认删除",
        })
        selected_provider_name = str(selected_record.get("name") or selected_provider or "")
        provider_management = f"""
      <section id="providerPanel" class="detail-panel provider-workspace">
        <div class="detail-panel-head">
          <div>
            <span class="muted" data-i18n="provider.header">供应商</span>
            <h2 id="providerSummaryName">{summary_name}</h2>
            <p id="providerSummaryUrl">{summary_url}</p>
          </div>
          <button id="newProvider" class="secondary" type="button" data-i18n="button.add">添加</button>
        </div>
        <p class="detail-note provider-note" data-i18n="provider.note">已启用后，这里只管理本地代理配置；不会改写 Codex config.toml。</p>
        <div class="provider-split">
          <div class="provider-list-pane">
          <div class="provider-panel-header">
            <div>
              <h3 data-i18n="provider.saved">已保存</h3>
            </div>
          </div>
          <div id="providerList" class="provider-list">
            {render_provider_cards(providers, selected_provider_name)}
          </div>
          </div>
          <div id="providerEditor" class="provider-editor" hidden>
            <div class="provider-editor-title">
              <h3 id="providerEditorTitle" data-i18n="provider.editor.edit">编辑</h3>
              <button id="cancelProvider" class="provider-edit" type="button" data-i18n="button.cancel">取消</button>
            </div>
            <form id="providerForm" class="provider-form">
              <label><span data-i18n="provider.name">名称</span>
                <input id="providerNameInput" autocomplete="off" value="{provider_name_value}" placeholder="my-provider" required>
              </label>
              <label><span data-i18n="provider.modelServiceUrl">模型服务地址</span>
                <input id="upstreamBase" autocomplete="off" value="{provider_url_value}" placeholder="https://api.example.com/v1" required>
              </label>
              <label id="apiKeyLabel"><span data-i18n="provider.apiKey">接口密钥</span>
                <span class="secret-input-row">
                  <input id="apiKey" type="password" autocomplete="off" aria-labelledby="apiKeyLabel" placeholder="留空则不修改已保存的 key" data-i18n-placeholder="provider.apiKeyPlaceholder">
                  <button id="revealApiKey" class="icon-button" type="button" aria-label="显示接口密钥" aria-controls="apiKey" aria-pressed="false" title="显示接口密钥" data-i18n-title="provider.showKey" data-i18n-aria-label="provider.showKey">
                    <svg class="eye-icon eye-open" data-eye-open viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0"></path>
                      <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                    <svg class="eye-icon eye-off" data-eye-off viewBox="0 0 24 24" aria-hidden="true" hidden>
                      <path d="M10.73 5.08a10.74 10.74 0 0 1 11.21 6.57 1 1 0 0 1 0 .7 10.8 10.8 0 0 1-1.44 2.49"></path>
                      <path d="M14.08 14.16a3 3 0 0 1-4.24-4.24"></path>
                      <path d="M17.48 17.5a10.75 10.75 0 0 1-15.42-5.15 1 1 0 0 1 0-.7 10.75 10.75 0 0 1 4.45-5.14"></path>
                      <path d="m2 2 20 20"></path>
                    </svg>
                  </button>
                </span>
              </label>
              <div class="actions compact">
                <button id="saveProvider" type="submit" data-i18n="button.saveProvider">保存</button>
              </div>
              <p id="providerFormFeedback" class="inline-feedback provider-form-feedback" role="status" aria-live="polite"></p>
            </form>
          </div>
        </div>
      </section>
"""

    if speed_controls_available(snapshot):
        labels["saveSpeed"] = "保存"
    if proxy_enabled:
        labels.update({
            "runBenchmark": "运行基准测试",
            "confirmBenchmark": "运行快速测试",
            "confirmStrictBenchmark": "运行严格测试",
        })
    snapshot_json = html.escape(json.dumps(snapshot, ensure_ascii=False, indent=2))
    initial_snapshot_json = script_json(snapshot)
    translations_json = script_json(UI_TRANSLATIONS)
    state_translations_json = script_json(UI_STATE_TRANSLATIONS)
    token_json = script_json(token)
    labels_json = script_json(labels)
    nav_items = [
        ("overview", "nav.overview", "概览"),
        ("providers", "nav.providers", "供应商"),
    ]
    nav_items.extend([
        ("requests", "nav.requests", "请求记录"),
        ("advanced", "nav.advanced", "高级"),
    ])
    sidebar_nav = "\n".join(
        f'<button class="nav-item{" active" if key == "overview" else ""}" type="button" data-view="{key}">{nav_icon(key)}<span data-i18n="{label_key}">{label}</span></button>'
        for key, label_key, label in nav_items
    )
    settings_nav = f'<button class="nav-item nav-settings" type="button" data-view="settings">{nav_icon("settings")}<span data-i18n="nav.settings">设置</span></button>'
    login_hint = (
        '<p class="hint-line" data-i18n="hint.chatgptSpeed">已检测到 ChatGPT 账户登录，速度控制由 Codex App 原生界面接管。</p>'
        if snapshot.get("chatgpt_auth") and proxy_enabled else ""
    )
    missing_provider_body = '<p class="empty-state" data-i18n="providers.empty">还没有可显示的供应商。请先在 Codex config.toml 配置 provider。</p>'
    provider_page_body = provider_management or codex_config_panel or missing_provider_body
    if provider_management:
        provider_page_note_key = "providers.note.manage"
    elif providers:
        provider_page_note_key = "providers.note.readonly"
    else:
        provider_page_note_key = "providers.note.empty"
    provider_page_note = ui_text(provider_page_note_key)
    benchmark_action = (
        '<div class="panel-actions"><button id="runBenchmark" class="secondary" type="button" '
        'data-i18n="button.runBenchmark">运行基准测试</button></div>'
        if proxy_enabled else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{ui_text("page.title")}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8f9;
      --sidebar: #eef1f4;
      --surface: #ffffff;
      --surface-soft: #f0f3f6;
      --surface-hover: #e8edf2;
      --border: #cfd6dd;
      --border-strong: #aeb8c3;
      --text: #111316;
      --muted: #3f4852;
      --muted-strong: #252b31;
      --blue: #0a84ff;
      --blue-soft: #edf6ff;
      --green: #14866d;
      --green-soft: #eef7f3;
      --green-text: #096651;
      --amber: #78500f;
      --amber-soft: #f6eedf;
      --red: #7a4a43;
      --red-hover: #66413b;
      --red-soft: #f3e9e6;
      --danger-border: #d5b8b1;
      --danger-text: #4f2d28;
      --button-bg: #111316;
      --button-hover: #2b3036;
      --button-text: #ffffff;
      --control-bg: rgba(255, 255, 255, .78);
      --control-hover: #f7f8fa;
      --nav-active: rgba(255, 255, 255, .72);
      --nav-hover: rgba(0, 0, 0, .045);
      --avatar-bg: #2b3036;
      --code-bg: #171717;
      --code-text: #eeeeee;
      --radius: 8px;
      --font-ui: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-display: ui-rounded, "SF Pro Rounded", "Avenir Next", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Consolas, monospace;
      font-family: var(--font-ui);
      letter-spacing: 0;
    }}
    :root[data-theme="dark"] {{
      color-scheme: dark;
      --bg: #111315;
      --sidebar: #181b1e;
      --surface: #1b1e22;
      --surface-soft: #22262b;
      --surface-hover: #2a2f35;
      --border: #343a41;
      --border-strong: #4b535d;
      --text: #f1f3f5;
      --muted: #b4bdc6;
      --muted-strong: #d7dde3;
      --blue: #65a9ff;
      --blue-soft: #182a3b;
      --green: #55c7a4;
      --green-soft: #173229;
      --green-text: #7bd7bb;
      --amber: #e1bd78;
      --amber-soft: #332b1b;
      --red: #c08a82;
      --red-hover: #d09a92;
      --red-soft: #35221f;
      --danger-border: #704842;
      --danger-text: #e5c2bd;
      --button-bg: #f1f3f5;
      --button-hover: #dce2e8;
      --button-text: #101214;
      --control-bg: #1f2328;
      --control-hover: #2a2f35;
      --nav-active: rgba(255, 255, 255, .08);
      --nav-hover: rgba(255, 255, 255, .055);
      --avatar-bg: #e8edf2;
      --code-bg: #0e1012;
      --code-text: #edf0f3;
    }}
    * {{ box-sizing: border-box; }}
    [hidden] {{ display: none !important; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-ui);
      font-size: 15px;
      line-height: 1.48;
    }}
    .app-shell {{
      background: var(--bg);
      display: grid;
      grid-template-columns: 236px minmax(0, 1fr);
      min-height: 100vh;
    }}
    .sidebar {{
      background: var(--sidebar);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 22px;
      height: 100vh;
      overflow-y: auto;
      padding: 24px 14px;
      position: sticky;
      top: 0;
    }}
    .brand {{
      display: grid;
      gap: 3px;
      padding: 0 8px;
    }}
    .brand strong {{
      color: var(--text);
      font-size: 14px;
      font-weight: 480;
    }}
    .brand span {{
      color: var(--muted);
      font-size: 14px;
    }}
    .sidebar-nav {{
      display: grid;
      flex: 1;
      gap: 4px;
      align-content: start;
    }}
    .nav-settings {{
      margin-top: auto;
    }}
    .nav-item {{
      align-items: center;
      background: transparent;
      border: 0;
      border-radius: var(--radius);
      color: var(--muted-strong);
      display: flex;
      font-size: 14px;
      gap: 9px;
      font-weight: 460;
      justify-content: flex-start;
      min-height: 34px;
      padding: 8px 11px;
      position: relative;
      text-align: left;
      width: 100%;
    }}
    .nav-icon {{
      align-items: center;
      color: var(--muted);
      display: inline-flex;
      flex: 0 0 auto;
      height: 18px;
      justify-content: center;
      width: 18px;
    }}
    .nav-icon svg {{
      display: block;
      fill: none;
      height: 18px;
      stroke: currentColor;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-width: 1.75;
      width: 18px;
    }}
    .nav-item:hover:not(:disabled) {{
      background: var(--nav-hover);
      border-color: transparent;
      color: var(--text);
    }}
    .nav-item.active {{
      background: var(--nav-active);
      color: var(--text);
      font-weight: 500;
    }}
    .nav-item.active .nav-icon {{
      color: var(--text);
    }}
    .content-shell {{
      min-width: 0;
      padding: 26px 42px 48px;
    }}
    .view-page {{
      margin: 0 auto;
      max-width: 980px;
      min-width: 0;
    }}
    .page-head {{
      align-items: flex-start;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin-bottom: 22px;
    }}
    .page-head h1 {{
      color: var(--text);
      font-size: 28px;
      font-family: var(--font-display);
      font-weight: 460;
      line-height: 1.15;
      margin: 0 0 6px;
    }}
    .page-head p {{
      color: var(--muted);
      margin: 0;
    }}
    .state {{
      color: var(--text);
      font-family: var(--font-display);
      font-size: 30px;
      font-weight: 460;
      line-height: 1.12;
      letter-spacing: 0;
      margin: 0 0 10px;
    }}
    .hero {{
      align-items: stretch;
      background: transparent;
      border: 0;
      border-radius: 0;
      display: grid;
      gap: 24px;
      grid-template-columns: minmax(0, 1fr) minmax(292px, 340px);
      margin-bottom: 18px;
      padding: 0;
    }}
    .hero-main {{
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}
    .hero-summary {{
      background: transparent;
      border: 0;
      border-bottom: 1px solid var(--border);
      border-radius: 0;
      border-top: 1px solid var(--border);
      display: grid;
      gap: 0;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      overflow: hidden;
    }}
    .message, .note, .hint-line {{
      color: var(--muted-strong);
      line-height: 1.6;
      margin: 0;
      max-width: 620px;
    }}
    .hint-line {{
      color: var(--muted);
      font-size: 14px;
      margin-top: 14px;
    }}
    .note {{ font-size: 14px; }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: auto;
      padding-top: 22px;
    }}
    button {{
      align-items: center;
      background: var(--button-bg);
      border: 1px solid var(--button-bg);
      border-radius: 7px;
      color: var(--button-text);
      cursor: pointer;
      display: inline-flex;
      font-size: 14px;
      font-weight: 460;
      justify-content: center;
      line-height: 1.2;
      min-height: 35px;
      padding: 8px 13px;
      transition: background .16s ease, border-color .16s ease, color .16s ease, opacity .16s ease, transform .16s ease;
    }}
    button:hover:not(:disabled) {{
      background: var(--button-hover);
      border-color: var(--button-hover);
      transform: translateY(-1px);
    }}
    button.secondary, .provider-card-actions .provider-edit, .provider-card-actions .provider-check, #cancelProvider, #saveSpeed {{
      background: var(--control-bg);
      border-color: var(--border);
      color: var(--text);
    }}
    button.secondary:hover:not(:disabled),
    .provider-card-actions .provider-edit:hover:not(:disabled),
    .provider-card-actions .provider-check:hover:not(:disabled),
      #cancelProvider:hover:not(:disabled),
      #saveSpeed:hover:not(:disabled) {{
      background: var(--control-hover);
      border-color: var(--text);
      color: var(--text);
    }}
    button.warn {{
      background: var(--red);
      border-color: var(--red);
      color: #ffffff;
    }}
    button.warn:hover:not(:disabled) {{ background: var(--red-hover); border-color: var(--red-hover); }}
    button:disabled {{
      cursor: not-allowed;
      opacity: .58;
    }}
    button[aria-busy="true"] {{ cursor: wait; }}
    button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible {{
      outline: 2px solid var(--green);
      outline-offset: 2px;
    }}
    .danger-zone {{
      align-items: stretch;
      background: color-mix(in srgb, var(--red-soft) 78%, var(--surface));
      border: 1px solid var(--danger-border);
      border-radius: 10px;
      display: grid;
      gap: 18px;
      grid-template-columns: minmax(0, 1fr) 180px;
      margin-top: 18px;
      overflow: hidden;
      padding: 0;
    }}
    .danger-copy {{
      padding: 18px 18px 17px;
    }}
    .danger-eyebrow {{
      color: var(--danger-text);
      display: block;
      font-size: 14px;
      font-weight: 460;
      margin-bottom: 7px;
    }}
    .danger-copy > strong {{
      color: var(--text);
      display: block;
      font-family: var(--font-display);
      font-size: 20px;
      font-weight: 460;
      line-height: 1.25;
      margin-bottom: 8px;
    }}
    .danger-zone p {{
      color: var(--danger-text);
      line-height: 1.6;
      margin: 0;
      max-width: 680px;
    }}
    .danger-route {{
      border-top: 1px solid color-mix(in srgb, var(--danger-border) 72%, transparent);
      display: grid;
      gap: 1px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 15px;
      max-width: 620px;
    }}
    .danger-route > div {{
      display: grid;
      gap: 3px;
      padding: 12px 12px 10px 0;
    }}
    .danger-route > div + div {{
      border-left: 1px solid color-mix(in srgb, var(--danger-border) 72%, transparent);
      padding-left: 14px;
    }}
    .danger-route span {{
      color: var(--muted);
      font-size: 14px;
    }}
    .danger-route strong {{
      color: var(--text);
      font-size: 14px;
      font-weight: 500;
      line-height: 1.45;
    }}
    .danger-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      margin-top: 14px;
    }}
    .danger-art {{
      align-items: center;
      background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 58%, transparent), transparent);
      border-left: 1px solid color-mix(in srgb, var(--danger-border) 72%, transparent);
      display: flex;
      justify-content: center;
      min-height: 190px;
      padding: 16px;
    }}
    .danger-art svg {{
      display: block;
      height: auto;
      max-width: 170px;
      width: 100%;
    }}
    .art-panel {{
      fill: color-mix(in srgb, var(--surface) 82%, var(--red-soft));
      stroke: var(--danger-border);
      stroke-width: 1.2;
    }}
    .art-panel.muted {{
      fill: color-mix(in srgb, var(--surface-soft) 74%, var(--red-soft));
    }}
    .art-line, .art-bridge, .art-key {{
      fill: none;
      stroke: var(--red);
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-width: 3;
    }}
    .art-line {{
      opacity: .55;
      stroke-width: 2.2;
    }}
    .art-bridge {{
      opacity: .28;
      stroke-width: 2.4;
    }}
    .art-node {{
      fill: var(--red);
      opacity: .62;
    }}
    .overview-section {{
      padding-top: 0;
    }}
    .detail-panel {{
      background: transparent;
      border: 0;
      border-top: 1px solid var(--border);
      margin-bottom: 24px;
      min-width: 0;
      overflow: visible;
    }}
    .detail-panel-head {{
      align-items: flex-start;
      background: transparent;
      border-bottom: 0;
      display: flex;
      gap: 14px;
      justify-content: space-between;
      padding: 17px 0 14px;
    }}
    .detail-panel-head h2 {{
      color: var(--text);
      font-size: 18px;
      font-family: var(--font-display);
      font-weight: 460;
      line-height: 1.25;
      margin: 3px 0 4px;
      overflow-wrap: anywhere;
    }}
    .detail-panel-head p {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .detail-panel-body {{
      padding: 0;
    }}
    .panel-actions {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }}
    .inline-feedback {{
      color: var(--muted-strong);
      font-size: 14px;
      line-height: 1.55;
      margin: 0;
      min-height: 0;
    }}
    .inline-confirm {{
      align-items: center;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin-bottom: 16px;
      padding: 15px;
    }}
    .inline-confirm strong {{
      color: var(--text);
      display: block;
      font-size: 15px;
      font-weight: 500;
      margin-bottom: 4px;
    }}
    .inline-confirm p {{
      color: var(--muted-strong);
      font-size: 14px;
      line-height: 1.5;
      margin: 0;
    }}
    .inline-confirm p + p {{
      color: var(--muted);
      margin-top: 4px;
    }}
    .inline-confirm-actions {{
      display: flex;
      flex: 0 0 auto;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }}
    .detail-note {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
      margin: -6px 0 16px;
    }}
    .provider-note {{
      margin: 0;
      padding: 11px 18px 13px;
    }}
    .provider-workspace {{
      padding: 0;
    }}
    .provider-workspace.detail-panel {{
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
    }}
    .provider-workspace .detail-panel-head {{
      padding: 15px 18px;
    }}
    .provider-panel-header {{
      align-items: flex-start;
      display: flex;
      gap: 14px;
      justify-content: space-between;
      margin-bottom: 12px;
    }}
    .provider-panel-header h3 {{
      color: var(--text);
      font-size: 15px;
      font-weight: 500;
      margin: 0;
    }}
    .provider-split {{
      border-top: 1px solid var(--border);
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      min-height: auto;
    }}
    .provider-split.editing {{
      grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
      min-height: 420px;
    }}
    .provider-list-pane {{
      min-width: 0;
      padding: 16px 18px;
    }}
    .provider-list {{
      display: grid;
    }}
    .provider-card {{
      align-items: center;
      background: transparent;
      border-top: 1px solid var(--border);
      display: flex;
      gap: 14px;
      justify-content: space-between;
      padding: 13px 0;
    }}
    .provider-card:last-child {{
      padding-bottom: 0;
    }}
    .provider-card:hover {{
      background: transparent;
    }}
    .provider-card.current {{
      background: color-mix(in srgb, var(--blue-soft) 44%, transparent);
      border-radius: 10px;
      border-top-color: transparent;
      margin: 6px -10px;
      padding: 12px 10px;
    }}
    .provider-card.current .provider-avatar {{
      background: var(--surface);
      border-color: color-mix(in srgb, var(--blue) 24%, var(--border));
      color: var(--blue);
    }}
    .provider-card.pending {{
      background: color-mix(in srgb, var(--amber-soft) 34%, transparent);
      border-radius: 10px;
      border-top-color: transparent;
      margin: 6px -10px;
      padding: 12px 10px;
    }}
    .provider-main {{
      display: flex;
      gap: 12px;
      min-width: 0;
    }}
    .provider-avatar {{
      align-items: center;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 7px;
      color: var(--muted-strong);
      display: inline-flex;
      flex: 0 0 auto;
      font-size: 14px;
      font-weight: 460;
      height: 30px;
      justify-content: center;
      width: 30px;
    }}
    .provider-info {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .provider-info strong {{
      font-size: 15px;
      font-weight: 500;
    }}
    .provider-url, .provider-auth-state {{
      color: var(--muted);
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .provider-row-feedback {{
      color: var(--muted-strong);
      display: grid;
      font-size: 14px;
      gap: 2px;
      line-height: 1.45;
      margin-top: 2px;
      max-width: 540px;
      overflow-wrap: anywhere;
    }}
    .provider-row-feedback[hidden] {{
      display: none;
    }}
    .provider-row-feedback strong {{
      font-weight: 500;
    }}
    .provider-row-feedback span {{
      color: var(--muted);
    }}
    .provider-row-feedback.checking strong {{
      color: var(--blue);
    }}
    .provider-row-feedback.ok strong {{
      color: var(--green-text);
    }}
    .provider-row-feedback.warn strong {{
      color: var(--red);
    }}
    .provider-card-actions {{
      align-items: center;
      display: flex;
      flex: 0 0 auto;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: flex-end;
    }}
    .provider-card-actions button {{
      min-height: 32px;
      padding: 6px 10px;
    }}
    .provider-card-actions .provider-delete {{
      background: var(--surface);
      border-color: var(--border-strong);
      color: var(--red);
    }}
    .provider-card-actions .provider-delete.confirming {{
      background: var(--red-soft);
      border-color: var(--red);
      color: var(--red);
    }}
    .provider-card-actions .provider-delete:hover:not(:disabled) {{
      background: var(--red-soft);
      border-color: var(--red);
      color: var(--red);
    }}
    .provider-editor {{
      border-left: 1px solid var(--border);
      margin-top: 0;
      padding: 16px 18px;
    }}
    .provider-editor-title {{
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
      margin-bottom: 14px;
    }}
    .provider-editor-title h3 {{
      font-size: 18px;
      font-family: var(--font-display);
      font-weight: 460;
      margin: 0;
    }}
    .provider-form-feedback {{
      color: var(--red);
      margin-top: 1px;
    }}
    .readonly-config {{
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      display: grid;
      gap: 1px;
      grid-template-columns: 140px minmax(0, 1fr);
      overflow: hidden;
    }}
    .readonly-config span,
    .readonly-config strong {{
      background: var(--surface);
      min-width: 0;
      padding: 12px 14px;
    }}
    .readonly-config span {{
      color: var(--muted);
      font-size: 14px;
      font-weight: 460;
    }}
    .readonly-config strong {{
      color: var(--text);
      font-size: 14px;
      font-family: var(--font-display);
      font-weight: 500;
      overflow-wrap: anywhere;
    }}
    .readonly-note {{
      color: var(--muted-strong);
      line-height: 1.6;
      margin: 12px 0 0;
    }}
    .secret-input-row {{
      align-items: center;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      position: relative;
    }}
    .secret-input-row input {{
      min-width: 0;
      padding-right: 42px;
    }}
    .icon-button {{
      background: transparent;
      border-color: transparent;
      border-radius: 6px;
      color: var(--muted-strong);
      font-size: 15px;
      min-height: 30px;
      padding: 0;
      position: absolute;
      right: 6px;
      top: 6px;
      width: 30px;
    }}
    .icon-button:hover:not(:disabled) {{
      background: var(--surface-hover);
      border-color: transparent;
      color: var(--text);
    }}
    .eye-icon {{
      display: block;
      fill: none;
      height: 20px;
      margin: 0 auto;
      stroke: currentColor;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-width: 1.9;
      width: 20px;
    }}
    .eye-icon[hidden] {{
      display: none;
    }}
    .muted {{
      color: var(--muted);
      font-size: 14px;
    }}
    .status-pill {{
      border: 1px solid var(--border);
      border-radius: 7px;
      display: inline-flex;
      font-size: 14px;
      font-weight: 460;
      padding: 4px 8px;
      white-space: nowrap;
    }}
    .status-pill.ok {{
      background: color-mix(in srgb, var(--green-soft) 70%, transparent);
      border-color: color-mix(in srgb, var(--green) 25%, var(--border));
      color: var(--green-text);
    }}
    .status-pill.warn {{
      background: color-mix(in srgb, var(--amber-soft) 72%, transparent);
      border-color: color-mix(in srgb, var(--amber) 24%, var(--border));
      color: var(--amber);
    }}
    .status-pill.idle {{
      background: var(--surface-soft);
      border-color: var(--border);
      color: var(--muted-strong);
    }}
    .status-metric {{
      background: transparent;
      border-bottom: 1px solid var(--border);
      display: grid;
      gap: 6px;
      min-width: 0;
      padding: 13px 14px;
    }}
    .status-metric:nth-child(odd) {{ border-right: 1px solid var(--border); }}
    .status-metric:nth-child(n + 3) {{ border-bottom: 0; }}
    .status-metric span {{
      color: var(--muted);
      font-size: 14px;
    }}
    .status-metric strong {{
      color: var(--text);
      font-family: var(--font-display);
      font-size: 16px;
      font-weight: 500;
      overflow-wrap: anywhere;
    }}
    .status-metric.ok strong {{ color: var(--green-text); }}
    .status-metric.warn strong {{ color: var(--red); }}
    .status-metric.idle strong {{ color: var(--muted-strong); }}
    .overview-preference {{
      align-items: center;
      border-bottom: 1px solid var(--border);
      border-top: 1px solid var(--border);
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin: -2px 0 18px;
      min-width: 0;
      padding: 13px 0;
    }}
    .preference-copy {{
      display: grid;
      gap: 3px;
      min-width: 0;
    }}
    .preference-copy span {{
      color: var(--muted);
      font-size: 14px;
    }}
    .preference-copy strong {{
      font-family: var(--font-display);
      font-size: 16px;
      font-weight: 500;
    }}
    .speed-hint {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
      margin: 0;
    }}
    .speed-preference-form {{
      align-items: center;
      display: flex;
      flex: 0 0 auto;
      gap: 8px;
    }}
    .speed-preference-form button {{
      min-height: 32px;
      padding: 6px 10px;
    }}
    form {{
      display: grid;
      gap: 11px;
      margin-top: 0;
    }}
    form button {{
      justify-self: start;
    }}
    label {{
      color: var(--muted-strong);
      display: grid;
      font-size: 14px;
      gap: 7px;
    }}
    input, select {{
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius);
      color: var(--text);
      font-size: 14px;
      min-height: 38px;
      padding: 8px 11px;
    }}
    input[type="radio"] {{
      accent-color: var(--green);
      min-height: auto;
    }}
    fieldset {{
      border: 0;
      margin: 0;
      padding: 0;
    }}
    legend {{
      color: var(--muted-strong);
      font-size: 14px;
      margin-bottom: 6px;
    }}
    .actions.compact {{ margin-top: 4px; }}
    .segments {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .segments label {{
      align-items: center;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius);
      cursor: pointer;
      display: flex;
      flex: 1 1 140px;
      gap: 9px;
      min-height: 38px;
      padding: 9px 11px;
    }}
    .segments label:has(input:checked) {{
      background: var(--green-soft);
      border-color: rgba(16, 163, 127, .36);
      color: var(--green-text);
    }}
    .segments input {{
      margin: 0;
      padding: 0;
    }}
    .segments.compact-segments {{
      gap: 6px;
    }}
    .segments.compact-segments label {{
      flex: 1 1 76px;
      font-size: 14px;
      min-height: 34px;
      padding: 7px 9px;
    }}
    .subsection-title {{
      border-top: 1px solid var(--border);
      font-size: 15px;
      margin: 18px 0 10px;
      padding-top: 16px;
    }}
    .empty-state {{
      background: transparent;
      border: 0;
      border-radius: 0;
      color: var(--muted);
      line-height: 1.6;
      margin: 0;
      padding: 3px 0;
    }}
    .request-table-wrap {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow-x: hidden;
    }}
    .request-table {{
      border-collapse: collapse;
      font-size: 14px;
      table-layout: fixed;
      width: 100%;
    }}
    .request-table th,
    .request-table td {{
      border-bottom: 1px solid var(--surface-soft);
      padding: 9px 7px;
      text-align: left;
      vertical-align: middle;
      white-space: nowrap;
    }}
    .request-table th {{
      background: var(--surface-soft);
      color: var(--muted);
      font-weight: 500;
    }}
    .metric-term {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 3px;
    }}
    .request-table tr:last-child td {{
      border-bottom: 0;
    }}
    .request-table th:nth-child(1), .request-table td:nth-child(1) {{ width: 148px; }}
    .request-table th:nth-child(2), .request-table td:nth-child(2) {{ width: 144px; }}
    .request-table th:nth-child(3), .request-table td:nth-child(3) {{ width: 100px; }}
    .request-table th:nth-child(4), .request-table td:nth-child(4),
    .request-table th:nth-child(5), .request-table td:nth-child(5),
    .request-table th:nth-child(6), .request-table td:nth-child(6) {{ width: 82px; }}
    .request-table th:nth-child(7), .request-table td:nth-child(7) {{ width: 76px; }}
    .request-route {{
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .mobile-cell-label {{
      display: none;
    }}
    .cell-value {{
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .number-cell {{
      color: var(--text);
      font-family: var(--font-display);
      font-variant-numeric: tabular-nums;
    }}
    .local-time {{
      color: var(--muted-strong);
      white-space: nowrap;
    }}
    .signal-grid {{
      display: grid;
      gap: 20px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .signal-card {{
      border: 0;
      border-radius: 0;
      background: transparent;
      min-width: 0;
      padding: 0;
    }}
    .signal-head {{
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
      margin-bottom: 12px;
    }}
    .signal-head > span {{
      color: var(--text);
      font-size: 15px;
      font-weight: 500;
    }}
    .signal-metrics {{
      display: grid;
      gap: 1px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--border);
    }}
    .signal-metric {{
      background: var(--surface);
      display: grid;
      gap: 5px;
      min-width: 0;
      padding: 10px;
    }}
    .signal-metric span,
    .signal-note {{
      color: var(--muted);
      font-size: 14px;
    }}
    .signal-metric strong {{
      color: var(--text);
      font-family: var(--font-display);
      font-size: 15px;
      font-weight: 500;
      overflow-wrap: anywhere;
    }}
    .signal-note {{
      line-height: 1.55;
      margin: 11px 0 0;
    }}
    .metadata-table {{
      border-collapse: collapse;
      font-size: 14px;
      table-layout: fixed;
      width: 100%;
    }}
    .metadata-table th,
    .metadata-table td {{
      border-bottom: 1px solid var(--surface-soft);
      padding: 9px 6px;
      text-align: left;
      vertical-align: middle;
      white-space: nowrap;
    }}
    .metadata-table th {{
      color: var(--muted);
      font-weight: 500;
    }}
    .metadata-table tr:last-child td {{
      border-bottom: 0;
    }}
    .metadata-table th:nth-child(1), .metadata-table td:nth-child(1) {{ width: 118px; }}
    .metadata-table th:nth-child(2), .metadata-table td:nth-child(2) {{ width: 96px; }}
    .metadata-table th:nth-child(3), .metadata-table td:nth-child(3) {{ width: 66px; }}
    .metadata-table th:nth-child(4), .metadata-table td:nth-child(4) {{ width: 56px; }}
    .advanced-workbench .detail-panel-head {{
      align-items: center;
    }}
    .diagnostic-actions {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }}
    .diagnostic-actions button {{
      min-height: 34px;
      padding: 7px 11px;
    }}
    .diagnostic-feedback {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
      margin: 0;
      min-height: 20px;
    }}
    .diagnostic-layout {{
      display: grid;
      gap: 22px;
    }}
    .diagnostic-section {{
      min-width: 0;
    }}
    .diagnostic-section-head {{
      align-items: flex-end;
      display: flex;
      gap: 14px;
      justify-content: space-between;
      margin-bottom: 12px;
    }}
    .diagnostic-section-head h3 {{
      color: var(--text);
      font-size: 16px;
      font-family: var(--font-display);
      font-weight: 460;
      margin: 0 0 3px;
    }}
    .diagnostic-section-head p {{
      color: var(--muted);
      line-height: 1.55;
      margin: 0;
    }}
    .diagnostic-grid {{
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      display: grid;
      gap: 1px;
      overflow: hidden;
    }}
    .diagnostic-row {{
      align-items: center;
      background: var(--surface);
      display: grid;
      gap: 14px;
      grid-template-columns: minmax(0, 1fr) auto;
      min-width: 0;
      padding: 13px 14px;
    }}
    .diagnostic-row > div {{
      min-width: 0;
    }}
    .diagnostic-row span {{
      color: var(--muted);
      display: block;
      font-size: 14px;
      font-weight: 500;
      margin-bottom: 4px;
    }}
    .diagnostic-row p {{
      color: var(--text);
      line-height: 1.55;
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .diagnostic-row strong {{
      align-self: center;
      justify-self: end;
    }}
    .diagnostic-paths {{
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
    }}
    .diagnostic-path {{
      align-items: center;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      display: grid;
      gap: 12px;
      grid-template-columns: 116px minmax(0, 1fr);
      padding: 12px 14px;
    }}
    .diagnostic-path:last-child {{
      border-bottom: 0;
    }}
    .diagnostic-path span {{
      color: var(--muted);
      font-size: 14px;
      font-weight: 500;
    }}
    .diagnostic-path code {{
      background: transparent;
      color: var(--text);
      font-family: var(--font-mono);
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .doctor-list {{
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
    }}
    .doctor-row {{
      align-items: flex-start;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      display: grid;
      gap: 12px;
      grid-template-columns: minmax(132px, .4fr) minmax(0, 1fr) auto;
      padding: 11px 14px;
    }}
    .doctor-row:last-child {{
      border-bottom: 0;
    }}
    .doctor-row strong {{
      color: var(--text);
      font-size: 14px;
      font-weight: 500;
    }}
    .doctor-detail {{
      color: var(--muted-strong);
      font-size: 14px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }}
    .diagnostic-safe-note {{
      color: var(--muted);
      line-height: 1.6;
      margin: 0;
    }}
    .settings-list {{
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
    }}
    .settings-row {{
      align-items: center;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      display: grid;
      gap: 12px;
      grid-template-columns: minmax(150px, .45fr) minmax(180px, .55fr);
      padding: 12px 14px;
    }}
    .settings-row:last-child {{
      border-bottom: 0;
    }}
    .settings-row span {{
      color: var(--muted-strong);
      font-size: 14px;
      font-weight: 500;
    }}
    .segmented-control {{
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 8px;
      display: grid;
      gap: 2px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      justify-self: end;
      min-width: min(360px, 100%);
      padding: 2px;
    }}
    .segmented-control label {{
      cursor: pointer;
      display: block;
      font-size: 14px;
      min-width: 0;
      position: relative;
    }}
    .segmented-control input {{
      cursor: pointer;
      height: 100%;
      inset: 0;
      margin: 0;
      opacity: 0;
      padding: 0;
      position: absolute;
      width: 100%;
    }}
    .segmented-control label > span {{
      align-items: center;
      border: 1px solid transparent;
      border-radius: 6px;
      color: var(--muted-strong);
      display: flex;
      font-size: 14px;
      font-weight: 460;
      justify-content: center;
      min-height: 32px;
      padding: 6px 10px;
      text-align: center;
      transition: background .16s ease, border-color .16s ease, color .16s ease;
      white-space: nowrap;
    }}
    .segmented-control input:checked + span {{
      background: var(--surface);
      border-color: var(--border-strong);
      color: var(--text);
    }}
    .segmented-control input:focus-visible + span {{
      outline: 2px solid var(--green);
      outline-offset: 2px;
    }}
    .software-update {{
      align-items: center;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1fr) auto;
      padding: 14px;
    }}
    .software-update strong {{
      color: var(--text);
      display: block;
      font-family: var(--font-display);
      font-size: 16px;
      font-weight: 460;
      margin-bottom: 4px;
    }}
    .software-update button {{
      min-width: 112px;
    }}
    .settings-note {{
      margin: 10px 0 0;
    }}
    details {{
      border-top: 1px solid var(--border);
      margin: 0;
      padding: 18px;
    }}
    details summary {{
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      list-style: none;
    }}
    details summary::-webkit-details-marker {{
      display: none;
    }}
    pre {{
      background: var(--code-bg);
      border-radius: var(--radius);
      color: var(--code-text);
      font-size: 13px;
      line-height: 1.5;
      overflow: auto;
      padding: 16px;
    }}
    @media (prefers-reduced-motion: no-preference) {{
      .view-page.active {{
        animation: view-enter .22s ease both;
      }}
      .detail-panel,
      .danger-zone,
      .provider-card,
      .status-metric,
      .diagnostic-row {{
        transition: background .18s ease, border-color .18s ease, transform .18s ease;
      }}
      .diagnostic-row:hover,
      .status-metric:hover {{
        transform: translateY(-1px);
      }}
    }}
    @keyframes view-enter {{
      from {{ opacity: .72; transform: translateY(5px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    @media (min-width: 861px) and (max-width: 1080px) {{
      .content-shell {{ padding: 24px 32px 42px; }}
      .hero {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 860px) {{
      .app-shell {{ grid-template-columns: 1fr; }}
      .sidebar {{
        border-bottom: 1px solid var(--border);
        border-right: 0;
        gap: 14px;
        height: auto;
        overflow: visible;
        padding: 16px;
        position: static;
      }}
      .sidebar-nav {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        overflow: visible;
      }}
      .nav-item {{
        flex: 0 1 auto;
        gap: 6px;
        justify-content: center;
        min-width: 0;
        padding-left: 7px;
        padding-right: 7px;
        width: auto;
      }}
      .nav-item span:not(.nav-icon) {{
        min-width: max-content;
        overflow: visible;
        text-overflow: clip;
        white-space: nowrap;
      }}
      .content-shell {{ padding: 22px 16px 34px; }}
      .state {{ font-size: 28px; }}
      .hero {{ grid-template-columns: 1fr; }}
      .danger-zone {{ grid-template-columns: 1fr; }}
      .danger-art {{ border-left: 0; border-top: 1px solid color-mix(in srgb, var(--danger-border) 72%, transparent); min-height: 128px; }}
      .danger-route {{ grid-template-columns: 1fr; }}
      .danger-route > div + div {{ border-left: 0; border-top: 1px solid color-mix(in srgb, var(--danger-border) 72%, transparent); padding-left: 0; }}
      .provider-split {{ grid-template-columns: 1fr; }}
      .provider-split.editing {{ grid-template-columns: 1fr; min-height: auto; }}
      .inline-confirm {{ align-items: stretch; flex-direction: column; }}
      .inline-confirm-actions {{ justify-content: flex-start; }}
      .provider-editor {{
        border-left: 0;
        border-top: 1px solid var(--border);
      }}
      .overview-preference, .speed-preference-form, .provider-card {{ align-items: stretch; flex-direction: column; }}
      .provider-panel-header {{ align-items: stretch; flex-direction: column; }}
      .provider-card-actions {{ justify-content: flex-start; }}
      .actions button {{ width: 100%; }}
      .provider-card-actions button, #newProvider, #cancelProvider, #updatePrimary {{ width: auto; }}
      .signal-grid {{ grid-template-columns: 1fr; }}
      .advanced-workbench .detail-panel-head,
      .diagnostic-section-head {{
        align-items: stretch;
        flex-direction: column;
      }}
      .diagnostic-actions {{
        justify-content: flex-start;
      }}
      .diagnostic-row,
      .diagnostic-path,
      .doctor-row,
      .settings-row {{
        align-items: flex-start;
        grid-template-columns: 1fr;
      }}
      .segmented-control {{
        justify-self: stretch;
        min-width: 0;
        width: 100%;
      }}
      .software-update {{
        align-items: stretch;
        grid-template-columns: 1fr;
      }}
      .software-update button {{
        justify-self: start;
      }}
      .diagnostic-row strong {{
        justify-self: start;
      }}
    }}
    @media (max-width: 640px) {{
      .request-table-wrap {{
        background: transparent;
        border: 0;
        border-radius: 0;
        overflow: visible;
      }}
      .request-table,
      .request-table tbody,
      .request-table tr,
      .request-table td {{
        display: block;
        width: 100%;
      }}
      .request-table thead {{
        display: none;
      }}
      .request-table tr {{
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        margin-bottom: 10px;
        overflow: hidden;
      }}
      .request-table tr:last-child {{
        margin-bottom: 0;
      }}
      .request-table td {{
        border-bottom: 1px solid var(--surface-soft);
        display: grid;
        gap: 10px;
        grid-template-columns: 88px minmax(0, 1fr);
        padding: 9px 11px;
        white-space: normal;
      }}
      .request-table td:last-child {{
        border-bottom: 0;
      }}
      .request-table th:nth-child(1), .request-table td:nth-child(1),
      .request-table th:nth-child(2), .request-table td:nth-child(2),
      .request-table th:nth-child(3), .request-table td:nth-child(3),
      .request-table th:nth-child(4), .request-table td:nth-child(4),
      .request-table th:nth-child(5), .request-table td:nth-child(5),
      .request-table th:nth-child(6), .request-table td:nth-child(6),
      .request-table th:nth-child(7), .request-table td:nth-child(7) {{
        width: auto;
      }}
      .mobile-cell-label {{
        color: var(--muted);
        display: block;
        font-size: 14px;
        font-weight: 460;
      }}
      .request-route {{
        overflow: visible;
        text-overflow: clip;
      }}
    }}
  </style>
</head>
<body>
  <main class="app-shell">
    <aside class="sidebar" aria-label="控制台导航">
      <div class="brand">
        <strong data-i18n="brand.name">Codex Model Gateway</strong>
        <span data-i18n="brand.subtitle">控制台</span>
      </div>
      <nav class="sidebar-nav">
        {sidebar_nav}
      </nav>
      {settings_nav}
    </aside>
    <section class="content-shell">
        <section class="view-page active" data-page="overview">
          <div class="hero">
            <div class="hero-main">
              <p id="state" class="state">{html.escape(title)}</p>
            <p id="message" class="message">{html.escape(message)}</p>
            {login_hint}
            <div class="actions">
              {button}
              {action_buttons}
            </div>
          </div>
          {render_top_summary(snapshot)}
          </div>
          {render_overview_speed_panel(snapshot)}
          {danger_zone}
      </section>
      <section class="view-page" data-page="providers" hidden>
        <div class="page-head">
          <div>
            <h1 data-i18n="providers.title">供应商</h1>
            <p data-i18n="{provider_page_note_key}">{provider_page_note}</p>
          </div>
        </div>
        {provider_page_body}
      </section>
      <section class="view-page" data-page="requests" hidden>
        <div class="page-head">
          <div>
            <h1 data-i18n="requests.title">请求记录</h1>
            <p data-i18n="requests.description">查看最近请求、Provider 检查和性能基准。</p>
          </div>
        </div>
        <section class="detail-panel">
          <div class="detail-panel-head">
            <div>
              <span class="muted" data-i18n="requests.section">请求</span>
              <h2 data-i18n="requests.recent">最近请求</h2>
              <p data-i18n="requests.recentDescription">使用首响应、首文本和完整耗时三个口径。</p>
            </div>
          </div>
          <div class="detail-panel-body">
            {render_recent_events(snapshot)}
          </div>
        </section>
        <section class="detail-panel">
          <div class="detail-panel-head">
            <div>
              <span class="muted" data-i18n="requests.ops">运行细节</span>
              <h2 data-i18n="requests.opsTitle">Provider 检查与性能基准</h2>
              <p data-i18n="requests.opsDescription">这些记录来自本地代理日志，不包含密钥。</p>
            </div>
            {benchmark_action}
          </div>
          <div class="detail-panel-body">
            <div id="benchmarkConfirm" class="inline-confirm" hidden>
              <div>
                <strong data-i18n="requests.benchmarkConfirmTitle">选择基准测试强度</strong>
                <p data-i18n="requests.benchmarkConfirmText">快速测试运行 3 对请求，适合低成本观察；严格测试运行 12 对请求，使用平衡随机顺序和配对统计检验。</p>
                <p data-i18n="requests.benchmarkCost">两种模式都会消耗真实额度；严格测试成本更高，但更适合判断本轮是否存在统计意义的加速迹象。</p>
              </div>
              <div class="inline-confirm-actions">
                <button id="confirmBenchmark" type="button" data-benchmark-kind="quick" data-i18n="button.confirmBenchmark">运行快速测试</button>
                <button id="confirmStrictBenchmark" class="secondary" type="button" data-benchmark-kind="strict" data-i18n="button.confirmStrictBenchmark">运行严格测试</button>
                <button id="cancelBenchmark" class="secondary" type="button" data-i18n="button.cancel">取消</button>
              </div>
            </div>
            {render_operational_signals(snapshot)}
          </div>
        </section>
      </section>
      <section class="view-page" data-page="advanced" hidden>
        <div class="page-head">
          <div>
            <h1 data-i18n="advanced.title">高级</h1>
            <p data-i18n="advanced.description">用于排查的原始状态和诊断信息。</p>
          </div>
        </div>
        <section class="detail-panel advanced-workbench">
          <div class="detail-panel-head">
            <div>
              <span class="muted" data-i18n="advanced.diagnostics">诊断</span>
              <h2 data-i18n="advanced.diagnosticsTitle">高级诊断</h2>
              <p data-i18n="advanced.warning">这里汇总运行时、配置、登录、启动钩子和日志路径；诊断导出不包含密钥。</p>
            </div>
            <div class="diagnostic-actions" aria-label="诊断操作">
              <button id="runDoctor" class="secondary" type="button" data-i18n="advanced.runDoctor">运行自检</button>
              <button id="copyDiagnostics" class="secondary" type="button" data-i18n="advanced.copy">复制诊断</button>
              <button id="downloadDiagnostics" class="secondary" type="button" data-i18n="advanced.download">导出文件</button>
              <button id="refreshDiagnostics" class="secondary" type="button" data-i18n="advanced.refresh">刷新状态</button>
            </div>
          </div>
          <div class="detail-panel-body diagnostic-layout">
            <p id="diagnosticsFeedback" class="diagnostic-feedback" role="status" aria-live="polite"></p>
            <section class="diagnostic-section" aria-label="状态摘要">
              <div class="diagnostic-section-head">
                <div>
                  <h3 data-i18n="advanced.summary">状态摘要</h3>
                  <p data-i18n="advanced.summaryDescription">优先看这里判断下一步，不需要先读原始状态。</p>
                </div>
              </div>
              <div class="diagnostic-grid">
                {render_diagnostic_summary(snapshot)}
              </div>
            </section>
            <section class="diagnostic-section" aria-label="日志路径">
              <div class="diagnostic-section-head">
                <div>
                  <h3 data-i18n="advanced.logPaths">日志路径</h3>
                  <p data-i18n="advanced.logPathsDescription">这些路径便于排查代理进程、控制面板和请求记录。</p>
                </div>
              </div>
              <div class="diagnostic-paths">
                {render_diagnostic_paths(snapshot)}
              </div>
            </section>
            <section class="diagnostic-section" aria-label="自检结果">
              <div class="diagnostic-section-head">
                <div>
                  <h3 data-i18n="advanced.checks">自检结果</h3>
                  <p data-i18n="advanced.safeNote">诊断信息已做状态化展示；请不要在聊天里粘贴密钥、auth.json、完整请求体或提示词。</p>
                </div>
              </div>
              <div id="doctorResult">
                <p class="empty-state" data-i18n="advanced.doctorIdle">还没有运行自检。</p>
              </div>
            </section>
          </div>
          <details id="diagnosticsPanel" class="diagnostics-panel">
            <summary data-i18n="advanced.viewDiagnostics">查看诊断</summary>
            <pre id="diagnostics">{snapshot_json}</pre>
          </details>
        </section>
      </section>
      <section class="view-page" data-page="settings" hidden>
        <div class="page-head">
          <div>
            <h1 data-i18n="settings.title">设置</h1>
            <p data-i18n="settings.description">控制面板偏好和版本更新。</p>
          </div>
        </div>
        <section class="detail-panel settings-panel">
          <div class="detail-panel-head">
            <div>
              <span class="muted" data-i18n="settings.preferences">偏好</span>
              <h2 data-i18n="settings.preferences">偏好</h2>
              <p data-i18n="settings.preferencesDescription">语言和外观只影响这个本地控制面板。</p>
            </div>
          </div>
          <div class="detail-panel-body">
            <div class="settings-list">
              <div class="settings-row">
                <span data-i18n="toolbar.language">语言</span>
                <div class="segmented-control" role="radiogroup" aria-label="语言" data-i18n-aria-label="toolbar.language">
                  <label>
                    <input type="radio" name="languageChoice" value="zh">
                    <span>中文</span>
                  </label>
                  <label>
                    <input type="radio" name="languageChoice" value="en">
                    <span>English</span>
                  </label>
                  <label>
                    <input type="radio" name="languageChoice" value="ja">
                    <span>日本語</span>
                  </label>
                </div>
              </div>
              <div class="settings-row">
                <span data-i18n="toolbar.theme">外观</span>
                <div class="segmented-control" role="radiogroup" aria-label="外观" data-i18n-aria-label="toolbar.theme">
                  <label>
                    <input type="radio" name="themeChoice" value="system">
                    <span data-i18n="theme.system">跟随系统</span>
                  </label>
                  <label>
                    <input type="radio" name="themeChoice" value="light">
                    <span data-i18n="theme.light">浅色</span>
                  </label>
                  <label>
                    <input type="radio" name="themeChoice" value="dark">
                    <span data-i18n="theme.dark">深色</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </section>
        <section class="detail-panel settings-panel">
          <div class="detail-panel-head">
            <div>
              <span class="muted" data-i18n="settings.updates">版本更新</span>
              <h2 data-i18n="settings.updates">版本更新</h2>
              <p data-i18n="settings.updatesDescription">先检查远端状态，再决定是否更新本地代理。</p>
            </div>
          </div>
          <div class="detail-panel-body">
            <div class="software-update">
              <div>
                <strong id="settingsUpdateTitle" data-i18n="settings.updateTitleIdle">软件更新</strong>
                <p id="settingsUpdateFeedback" class="inline-feedback" role="status" aria-live="polite" data-i18n="settings.updateIdle">还没有检查更新。</p>
              </div>
              <button id="updatePrimary" class="secondary" type="button" data-update-action="check-update" data-i18n="button.checkUpdate">检查更新</button>
            </div>
            <p class="detail-note settings-note" data-i18n="settings.updateNote">检查更新是只读操作；更新会拉取代码并刷新本地运行时。</p>
          </div>
        </section>
      </section>
    </section>
  </main>
  <script>
    const token = {token_json};
    const headerName = {json.dumps(CONTROL_TOKEN_HEADER)};
    const $ = (id) => document.getElementById(id);
    const initialSnapshot = {initial_snapshot_json};
    const translations = {translations_json};
    const stateTranslations = {state_translations_json};
    const localeStorageKey = 'codex-fast-proxy.locale';
    const themeStorageKey = 'codex-fast-proxy.theme';
    const viewStorageKey = 'codex-fast-proxy.view';
    const supportedLocales = ['zh', 'en', 'ja'];
    const supportedThemes = ['system', 'light', 'dark'];
    const localeLang = {{ zh: 'zh-CN', en: 'en', ja: 'ja' }};
    const storedLocale = window.localStorage.getItem(localeStorageKey);
    const storedTheme = window.localStorage.getItem(themeStorageKey);
    let currentLocale = supportedLocales.includes(storedLocale) ? storedLocale : 'zh';
    let currentTheme = supportedThemes.includes(storedTheme) ? storedTheme : 'system';
    let currentSnapshot = initialSnapshot;
    let providerCheckResults = {{}};
    let pendingProviderDelete = {{ provider: '', timer: 0 }};
    const labels = {labels_json};
    const actionProgress = {{
      enable: [
        {{ delay: 0, label: '正在准备环境...', labelKey: 'action.enable.prepare.label', message: '正在读取当前 Provider 并准备环境。', messageKey: 'action.enable.prepare.message' }},
        {{ delay: 6000, label: '正在验证模型服务...', labelKey: 'action.enable.verify.label', message: '正在连接当前模型服务，首次启用可能需要几十秒。', messageKey: 'action.enable.verify.message' }},
        {{ delay: 18000, label: '模型服务响应较慢...', labelKey: 'action.enable.slow.label', message: '仍在等待模型服务响应，完成后页面会自动更新。', messageKey: 'action.enable.slow.message' }}
      ],
      update: [
        {{ delay: 0, label: '正在更新...', labelKey: 'action.update.start.label', message: '正在拉取更新并刷新本地代理，页面会在完成后自动恢复。', messageKey: 'action.update.start.message' }},
        {{ delay: 8000, label: '正在刷新运行时...', labelKey: 'action.update.runtime.label', message: '正在重新安装并刷新代理进程，这一步可能需要十几秒。', messageKey: 'action.update.runtime.message' }},
        {{ delay: 20000, label: '更新仍在继续...', labelKey: 'action.update.slow.label', message: '仍在等待本地更新完成，请保持控制面板打开。', messageKey: 'action.update.slow.message' }},
        {{ delay: 30000, label: '正在等待新版界面...', labelKey: 'action.update.waitUi.label', message: '更新已完成后会自动切换到新版控制面板，请不要手动刷新。', messageKey: 'action.update.waitUi.message' }}
      ],
      'check-update': [
        {{ delay: 0, label: '正在检查...', labelKey: 'action.checkUpdate.start.label', message: '正在读取远端分支和本地工作区状态。', messageKey: 'action.checkUpdate.start.message' }}
      ],
      'save-provider': [
        {{ delay: 0, label: '正在保存并验证...', labelKey: 'action.saveProvider.start.label', message: '正在保存，并验证模型服务是否可用。', messageKey: 'action.saveProvider.start.message' }},
        {{ delay: 6000, label: '正在验证模型服务...', labelKey: 'action.enable.verify.label', message: '正在发起一次真实响应接口流式检查，完成后会自动更新页面。', messageKey: 'action.saveProvider.verify.message' }},
        {{ delay: 18000, label: '模型服务响应较慢...', labelKey: 'action.enable.slow.label', message: '仍在等待模型服务响应；如果验证失败，当前设置会保持不变。', messageKey: 'action.saveProvider.slow.message' }}
      ],
      'verify-provider': [
        {{ delay: 0, label: '正在检查...', labelKey: 'action.verifyProvider.start.label', message: '正在发起一次真实 Responses 流式检查。', messageKey: 'action.verifyProvider.start.message' }},
        {{ delay: 12000, label: '检查仍在继续...', labelKey: 'action.verifyProvider.slow.label', message: '模型服务响应较慢，请保持页面打开。', messageKey: 'action.verifyProvider.slow.message' }}
      ],
      'switch-provider': [
        {{ delay: 0, label: '正在切换...', labelKey: 'action.switchProvider.start.label', message: '正在切换，并验证新的模型服务。', messageKey: 'action.switchProvider.start.message' }},
        {{ delay: 6000, label: '正在验证模型服务...', labelKey: 'action.enable.verify.label', message: '正在发起一次真实响应接口流式检查，完成后会自动更新页面。', messageKey: 'action.saveProvider.verify.message' }},
        {{ delay: 18000, label: '模型服务响应较慢...', labelKey: 'action.enable.slow.label', message: '仍在等待模型服务响应；如果验证失败，当前设置会保持不变。', messageKey: 'action.saveProvider.slow.message' }}
      ],
      'delete-provider': [
        {{ delay: 0, label: '正在删除...', labelKey: 'action.deleteProvider.start.label', message: '正在删除保存项，当前模型服务不会受影响。', messageKey: 'action.deleteProvider.start.message' }}
      ],
      'set-speed-mode': [
        {{ delay: 0, label: '正在保存...', labelKey: 'action.speed.start.label', message: '正在保存当前选择。', messageKey: 'action.speed.start.message' }},
        {{ delay: 6000, label: '正在验证模型服务...', labelKey: 'action.enable.verify.label', message: '正在确认当前模型服务仍可正常响应。', messageKey: 'action.saveProvider.verify.message' }},
        {{ delay: 18000, label: '模型服务响应较慢...', labelKey: 'action.enable.slow.label', message: '仍在等待模型服务响应；如果验证失败，当前设置会保持不变。', messageKey: 'action.saveProvider.slow.message' }}
      ],
      'run-benchmark': [
        {{ delay: 0, label: '正在运行...', labelKey: 'action.benchmark.start.label', message: '正在发起标准和优先请求。', messageKey: 'action.benchmark.start.message' }},
        {{ delay: 30000, label: '基准测试仍在继续...', labelKey: 'action.benchmark.slow.label', message: '这一步取决于模型服务响应速度，完成后会刷新结果。', messageKey: 'action.benchmark.slow.message' }}
      ],
      uninstall: [
        {{ delay: 0, label: '正在恢复直连...', labelKey: 'action.uninstall.start.label', message: '正在恢复 Codex 原模型服务，并准备清理本地代理。', messageKey: 'action.uninstall.start.message' }},
        {{ delay: 1200, label: '正在清理...', labelKey: 'action.uninstall.cleanup.label', message: '正在移除本地状态、安装文件和 skill 链接，控制面板会最后关闭。', messageKey: 'action.uninstall.cleanup.message' }}
      ],
      default: [
        {{ delay: 0, label: '处理中...', labelKey: 'action.default.label', message: null }}
      ]
    }};
    let providerRecords = {json.dumps(providers, ensure_ascii=False)};
    let loadedApiKey = '';
    let loadedApiKeyProvider = '';
    let latestDoctorReport = null;
    let pendingRefreshTimer = null;
    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, (char) => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }}[char]));
    }}
    function t(key, fallback = '') {{
      if (!key) return fallback;
      const localePack = translations[currentLocale] || translations.zh || {{}};
      const zhPack = translations.zh || {{}};
      return localePack[key] || zhPack[key] || fallback || key;
    }}
    function translatedState(userState) {{
      const state = userState || {{}};
      const code = state.code || '';
      const localeStates = stateTranslations[currentLocale] || {{}};
      const zhStates = stateTranslations.zh || {{}};
      const stateText = localeStates[code] || zhStates[code] || {{}};
      return {{
        title: stateText.title || state.title || t('advanced.title', '需要处理'),
        message: stateText.message || state.message || t('advanced.description', '请打开高级诊断，或让 Codex 根据诊断结果修复。')
      }};
    }}
    function syncPreferenceControls() {{
      const languageInput = document.querySelector(`input[name="languageChoice"][value="${{currentLocale}}"]`);
      if (languageInput) languageInput.checked = true;
      const themeInput = document.querySelector(`input[name="themeChoice"][value="${{currentTheme}}"]`);
      if (themeInput) themeInput.checked = true;
    }}
    function applyTheme() {{
      const systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      const resolved = currentTheme === 'system' ? (systemDark ? 'dark' : 'light') : currentTheme;
      document.documentElement.dataset.theme = resolved;
      syncPreferenceControls();
    }}
    function buttonLabel(id, fallback = '') {{
      const keys = {{
        update: 'button.update',
        checkUpdate: 'button.checkUpdate',
        uninstall: 'button.uninstall',
        confirmUninstall: 'button.confirmUninstall',
        cancelUninstall: 'button.cancelUninstall',
        finishCleanup: 'button.finishCleanup',
        saveProvider: 'button.saveProvider',
        saveSpeed: 'button.saveSpeed',
        runBenchmark: 'button.runBenchmark',
        confirmBenchmark: 'button.confirmBenchmark'
      }};
      return t(keys[id], fallback);
    }}
    function primaryButtonLabel(userState) {{
      const action = userState && userState.primary_action ? userState.primary_action : 'diagnostics';
      if (action === 'enable' && userState && userState.code === 'cleanup_pending') return t('button.reenable', userState.primary_label || '重新启用');
      if (action === 'enable') return t('button.enable', userState ? userState.primary_label : '启用');
      if (action === 'refresh') return t('button.refresh', userState ? userState.primary_label : '刷新状态');
      if (action === 'uninstall') return t('button.uninstall', userState ? userState.primary_label : '停用并恢复');
      return t('button.diagnostics', userState ? userState.primary_label : '打开高级诊断');
    }}
    function updateStaticTranslations() {{
      document.documentElement.lang = localeLang[currentLocale] || 'zh-CN';
      document.title = t('page.title', 'Codex 控制面板');
      document.querySelectorAll('[data-i18n]').forEach((node) => {{
        const key = node.getAttribute('data-i18n');
        node.textContent = t(key, node.textContent);
      }});
      document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {{
        const key = node.getAttribute('data-i18n-placeholder');
        node.setAttribute('placeholder', t(key, node.getAttribute('placeholder') || ''));
      }});
      document.querySelectorAll('[data-i18n-title]').forEach((node) => {{
        const key = node.getAttribute('data-i18n-title');
        node.setAttribute('title', t(key, node.getAttribute('title') || ''));
      }});
      document.querySelectorAll('[data-i18n-aria-label]').forEach((node) => {{
        const key = node.getAttribute('data-i18n-aria-label');
        node.setAttribute('aria-label', t(key, node.getAttribute('aria-label') || ''));
      }});
      syncPreferenceControls();
    }}
    function updateStateText(snapshot) {{
      const userState = snapshot.user_state || {{}};
      const text = translatedState(userState);
      $('state').textContent = text.title;
      $('message').textContent = text.message;
      const button = $('primary');
      if (button) button.textContent = primaryButtonLabel(userState);
    }}
    function applyLocale(snapshot = currentSnapshot) {{
      updateStaticTranslations();
      updateStateText(snapshot);
      resetControls(snapshot.user_state || {{}}, snapshot);
      renderProviderList(snapshot);
      resetSummary(snapshot);
      updateDiagnosticsWorkspace(snapshot);
      updateSettingsWorkspace(snapshot);
      const editorTitle = $('providerEditorTitle');
      if (editorTitle && editorTitle.dataset.editorMode) {{
        editorTitle.textContent = t(editorTitle.dataset.editorMode, editorTitle.textContent);
      }}
      const saveProvider = $('saveProvider');
      const providerEditor = $('providerEditor');
      if (saveProvider && providerEditor && !providerEditor.hidden) {{
        saveProvider.textContent = providerEditorActionLabel(saveProvider.dataset.providerMode || 'save');
      }}
      syncRevealButton($('apiKey') && $('apiKey').type === 'text');
    }}
    function currentProviderName(snapshot) {{
      const records = Array.isArray(providerRecords) ? providerRecords : [];
      if (snapshot && typeof snapshot.runtime_upstream_provider === 'string' && snapshot.runtime_upstream_provider) return snapshot.runtime_upstream_provider;
      if (snapshot && typeof snapshot.current_provider === 'string' && snapshot.current_provider) return snapshot.current_provider;
      if (snapshot && typeof snapshot.proxy_upstream_provider === 'string' && snapshot.proxy_upstream_provider) return snapshot.proxy_upstream_provider;
      if (snapshot && typeof snapshot.provider === 'string' && snapshot.provider) return snapshot.provider;
      const current = records.find((item) => item && item.current && item.name);
      if (current && current.name) return current.name;
      return records[0] && records[0].name ? records[0].name : '';
    }}
    function renderProviderCard(record, currentName) {{
      const name = record && record.name ? String(record.name) : t('provider.unnamed', '未命名');
      const baseUrl = record && record.base_url ? String(record.base_url) : t('provider.noService', '未设置模型服务');
      const isCurrent = Boolean(record && record.current) || name === currentName;
      const isPending = Boolean(record && record.pending);
      const statusPill = [
        isCurrent ? `<span class="status-pill ok">${{escapeHtml(t('value.inUse', '使用中'))}}</span>` : '',
        isPending ? `<span class="status-pill warn">${{escapeHtml(t('value.pending', '待应用'))}}</span>` : ''
      ].join('');
      const checkButton = `<button class="provider-check" type="button" data-provider-action="verify" data-provider="${{escapeHtml(name)}}">${{escapeHtml(t('button.checkProvider', '检查'))}}</button>`;
      const enableButton = isCurrent || isPending ? '' : `<button class="provider-enable" type="button" data-provider-action="switch" data-provider="${{escapeHtml(name)}}">${{escapeHtml(t('button.switch', '启用'))}}</button>`;
      const deleteButton = record && record.deletable ? `<button class="provider-delete" type="button" data-provider-action="delete" data-provider="${{escapeHtml(name)}}">${{escapeHtml(t('button.delete', '删除'))}}</button>` : '';
      const avatar = name.trim().charAt(0) || '?';
      return `
            <article class="provider-card${{isCurrent ? ' current' : ''}}${{isPending ? ' pending' : ''}}" data-provider-name="${{escapeHtml(name)}}">
              <div class="provider-main">
                <span class="provider-avatar">${{escapeHtml(avatar)}}</span>
                <div class="provider-info">
                  <strong>${{escapeHtml(name)}}</strong>
                  <span class="provider-url">${{escapeHtml(baseUrl)}}</span>
                  <span class="provider-auth-state">${{escapeHtml(t('provider.keyPrefix', '密钥：'))}}${{escapeHtml(keyLabel(record ? record.api_key : null))}}</span>
                  <span class="provider-row-feedback" data-provider-check-feedback role="status" aria-live="polite" hidden></span>
                </div>
              </div>
              <div class="provider-card-actions">
                ${{statusPill}}
                ${{checkButton}}
                ${{enableButton}}
                <button class="provider-edit" type="button" data-provider-action="edit" data-provider="${{escapeHtml(name)}}">${{escapeHtml(t('button.edit', '编辑'))}}</button>
                ${{deleteButton}}
              </div>
            </article>
`;
    }}
    function providerCheckRow(provider) {{
      return Array.from(document.querySelectorAll('.provider-card'))
        .find((item) => item.dataset.providerName === provider);
    }}
    function updateProviderCheckRow(provider) {{
      const card = providerCheckRow(provider);
      if (!card) return;
      const target = card.querySelector('[data-provider-check-feedback]');
      if (!target) return;
      const result = providerCheckResults[provider];
      if (!result) {{
        target.hidden = true;
        target.className = 'provider-row-feedback';
        target.textContent = '';
        target.removeAttribute('title');
        target.removeAttribute('aria-label');
        return;
      }}
      target.hidden = false;
      target.className = `provider-row-feedback ${{result.tone || 'checking'}}`;
      target.title = result.message || '';
      target.setAttribute('aria-label', `${{result.title || ''}}：${{result.message || ''}}`);
      target.innerHTML = `<strong>${{escapeHtml(result.title || '')}}</strong><span>${{escapeHtml(result.message || '')}}</span>`;
    }}
    function setProviderCheckResult(provider, result) {{
      if (!provider) return;
      providerCheckResults = {{ ...providerCheckResults, [provider]: result }};
      updateProviderCheckRow(provider);
    }}
    function resetPendingProviderDelete() {{
      if (pendingProviderDelete.timer) window.clearTimeout(pendingProviderDelete.timer);
      document.querySelectorAll('.provider-delete.confirming').forEach((button) => {{
        button.classList.remove('confirming');
        button.dataset.confirming = 'false';
        button.textContent = t('button.delete', '删除');
      }});
      pendingProviderDelete = {{ provider: '', timer: 0 }};
    }}
    function requestProviderDeleteConfirmation(provider, button) {{
      resetPendingProviderDelete();
      pendingProviderDelete.provider = provider;
      button.dataset.confirming = 'true';
      button.classList.add('confirming');
      button.textContent = t('button.confirmDelete', '确认删除');
      pendingProviderDelete.timer = window.setTimeout(resetPendingProviderDelete, 3500);
    }}
    function renderProviderList(snapshot) {{
      providerRecords = Array.isArray(snapshot.providers) ? snapshot.providers : providerRecords;
      const list = $('providerList');
      if (list) {{
        resetPendingProviderDelete();
        const currentName = currentProviderName(snapshot);
        list.innerHTML = providerRecords.map((item) => renderProviderCard(item, currentName)).join('');
        Object.keys(providerCheckResults).forEach((provider) => updateProviderCheckRow(provider));
      }}
    }}
    function resetControls(userState, snapshot) {{
      Object.entries(labels).forEach(([id, label]) => {{
        const item = $(id);
        if (item) {{
          item.disabled = false;
          item.textContent = buttonLabel(id, label);
        }}
      }});
      const primary = $('primary');
      if (primary) {{
        primary.disabled = false;
        primary.textContent = primaryButtonLabel(userState);
      }}
      const dangerZone = $('dangerZone');
      if (dangerZone) dangerZone.hidden = userState.code !== 'confirmation_required';
      const uninstall = $('uninstall');
      if (uninstall) uninstall.hidden = userState.code === 'confirmation_required';
      const saveSpeed = $('saveSpeed');
      if (saveSpeed) saveSpeed.disabled = !snapshot.base_url;
    }}
    function keyLabel(value) {{
      if (value === 'saved') return t('value.saved', '已保存');
      if (typeof value === 'string' && value.includes(':')) {{
        const parts = value.split(':');
        if (parts[0] === 'auth_json') return `${{t('provider.keyCodexSaved', 'Codex 已保存')}} ${{parts[1]}}`;
        return `${{t('provider.keyEnv', '环境变量')}} ${{parts[1]}}`;
      }}
      return t('value.missing', '未保存');
    }}
    function maskSecret(record) {{
      if (!record || record.api_key !== 'saved') return '';
      const length = Number(record.api_key_length);
      return '•'.repeat(Number.isInteger(length) && length > 0 ? length : 16);
    }}
    function syncRevealButton(revealed) {{
      const reveal = $('revealApiKey');
      if (!reveal) return;
      reveal.setAttribute('aria-pressed', revealed ? 'true' : 'false');
      const label = revealed ? t('provider.hideKey', '隐藏接口密钥') : t('provider.showKey', '显示接口密钥');
      reveal.title = label;
      reveal.setAttribute('aria-label', label);
      const open = reveal.querySelector('[data-eye-open]');
      const off = reveal.querySelector('[data-eye-off]');
      if (open) open.toggleAttribute('hidden', revealed);
      if (off) off.toggleAttribute('hidden', !revealed);
    }}
    function providerEditorActionLabel(mode) {{
      return mode === 'update' ? t('button.updateProvider', '更新') : t('button.saveProvider', labels.saveProvider || '保存');
    }}
    function openProviderEditor(record, titleKey) {{
      loadedApiKey = '';
      loadedApiKeyProvider = '';
      setProviderFormFeedback('');
      const editor = $('providerEditor');
      if (editor) editor.hidden = false;
      const split = editor ? editor.closest('.provider-split') : null;
      if (split) split.classList.add('editing');
      const editorTitle = $('providerEditorTitle');
      if (editorTitle) {{
        editorTitle.dataset.editorMode = titleKey || (record ? 'provider.editor.edit' : 'provider.editor.add');
        editorTitle.textContent = t(editorTitle.dataset.editorMode, editorTitle.textContent);
      }}
      fillProviderForm(record);
      updateRevealButtonState();
      const saveProvider = $('saveProvider');
      if (saveProvider) {{
        saveProvider.dataset.providerMode = record ? 'update' : 'save';
        saveProvider.textContent = providerEditorActionLabel(saveProvider.dataset.providerMode);
      }}
      const nameInput = $('providerNameInput');
      if (nameInput) nameInput.focus();
    }}
    function closeProviderEditor() {{
      setProviderFormFeedback('');
      const editor = $('providerEditor');
      if (editor) editor.hidden = true;
      const split = editor ? editor.closest('.provider-split') : null;
      if (split) split.classList.remove('editing');
      const editorTitle = $('providerEditorTitle');
      if (editorTitle) {{
        editorTitle.dataset.editorMode = 'provider.editor.edit';
        editorTitle.textContent = t('provider.editor.edit', '编辑');
      }}
      const saveProvider = $('saveProvider');
      if (saveProvider) {{
        saveProvider.dataset.providerMode = 'save';
        saveProvider.textContent = providerEditorActionLabel('save');
      }}
    }}
    function providerByName(name) {{
      return providerRecords.find((item) => item.name === name) || null;
    }}
    function fillProviderForm(record) {{
      const nameInput = $('providerNameInput');
      if (nameInput) nameInput.value = record ? record.name || '' : '';
      const upstreamBase = $('upstreamBase');
      if (upstreamBase) upstreamBase.value = record ? record.base_url || '' : '';
      const apiKey = $('apiKey');
      if (apiKey) {{
        apiKey.type = 'password';
        apiKey.value = maskSecret(record);
        apiKey.dataset.masked = record && record.api_key === 'saved' ? 'true' : 'false';
        apiKey.dataset.maskValue = apiKey.value;
        apiKey.dataset.original = '';
      }}
      syncRevealButton(false);
      updateRevealButtonState();
    }}
    function updateRevealButtonState() {{
      const apiKey = $('apiKey');
      const reveal = $('revealApiKey');
      if (!apiKey || !reveal) return;
      reveal.disabled = !apiKey.value.trim();
    }}
    function setProviderFormFeedback(message) {{
      const feedback = $('providerFormFeedback');
      if (feedback) feedback.textContent = message || '';
    }}
    function providerFormValidationError() {{
      const provider = $('providerNameInput') ? $('providerNameInput').value.trim() : '';
      const upstreamBase = $('upstreamBase') ? $('upstreamBase').value.trim() : '';
      if (!provider) return t('provider.form.invalidName', '先填写供应商名称。');
      try {{
        const url = new URL(upstreamBase);
        if (!['http:', 'https:'].includes(url.protocol)) throw new Error('unsupported protocol');
      }} catch (_error) {{
        return t('provider.form.invalidUrl', '模型服务地址需要是 http 或 https URL。');
      }}
      return '';
    }}
    async function fetchProviderKey(provider) {{
      const response = await fetch('/api/provider-key?provider=' + encodeURIComponent(provider), {{
        headers: {{ [headerName]: token }},
        cache: 'no-store'
      }});
      const data = await response.json();
      if (data.status !== 'ok') throw new Error(data.error || '没有读取到已保存的接口密钥。');
      return data.api_key || '';
    }}
    async function revealProviderKey() {{
      const apiKey = $('apiKey');
      if (!apiKey) return;
      if (apiKey.type === 'text') {{
        apiKey.type = 'password';
        syncRevealButton(false);
        return;
      }}
      if (apiKey.dataset.masked === 'true') {{
        const provider = $('providerNameInput').value.trim();
        if (!provider) return;
        const secret = await fetchProviderKey(provider);
        apiKey.value = secret;
        apiKey.dataset.masked = 'false';
        apiKey.dataset.original = secret;
        loadedApiKey = secret;
        loadedApiKeyProvider = provider;
      }}
      apiKey.type = 'text';
      syncRevealButton(true);
    }}
    function apiKeyFormValue() {{
      const apiKey = $('apiKey');
      if (!apiKey) return null;
      const value = apiKey.value.trim();
      if (!value || apiKey.dataset.masked === 'true') return null;
      const provider = $('providerNameInput').value.trim();
      if (provider === loadedApiKeyProvider && value === loadedApiKey) return null;
      return value;
    }}
    function resetProviderForm(snapshot) {{
      renderProviderList(snapshot);
      closeProviderEditor();
      fillProviderForm(providerByName(currentProviderName(snapshot)));
    }}
    function resetSpeedForm(snapshot) {{
      const speedMode = snapshot.service_tier_policy === 'preserve' ? 'standard' : 'fast';
      const speedInput = document.querySelector(`input[name="speedMode"][value="${{speedMode}}"]`);
      if (speedInput) speedInput.checked = true;
    }}
    function hasProviderCandidate(snapshot) {{
      return (Array.isArray(snapshot.providers) && snapshot.providers.length > 0) ||
        Boolean(snapshot.provider || snapshot.upstream_base || snapshot.config_base_url || snapshot.base_url);
    }}
    function speedControlsAvailable(snapshot) {{
      const state = snapshot.user_state || {{}};
      const terminalState = ['cleanup_pending', 'uninstalled_deferred', 'uninstalled'].includes(state.code);
      const apiKeyLogin = Boolean(snapshot.api_key_auth || snapshot.login_mode === 'api_key');
      return hasProviderCandidate(snapshot) && Boolean(snapshot.base_url) && apiKeyLogin && !snapshot.chatgpt_auth && !terminalState;
    }}
    function displayValue(value, fallback) {{
      return typeof value === 'string' && value ? value : fallback;
    }}
    function speedLabel(snapshot) {{
      return snapshot.service_tier_policy === 'preserve' ? t('value.standard', '标准') : t('value.fast', '快速');
    }}
    function providerStatus(snapshot) {{
      if (snapshot.config_matches && snapshot.healthy && !snapshot.needs_restart) return [t('value.running', '运行中'), 'ok'];
      if (snapshot.config_matches && snapshot.needs_restart) return [t('value.restartPending', '待重启'), 'warn'];
      if (snapshot.config_matches) return [t('value.needsAttention', '需处理'), 'warn'];
      if (snapshot.base_url) return [t('value.restored', '已恢复'), 'idle'];
      return [t('value.notEnabled', '未启用'), 'idle'];
    }}
    function shortLoginLabel(snapshot) {{
      if (snapshot.chatgpt_auth) return 'ChatGPT';
      if (snapshot.api_key_auth) return t('value.key', '密钥');
      return t('value.unknown', '未知');
    }}
    function shortProxyLabel(snapshot) {{
      if (snapshot.config_matches && snapshot.healthy && !snapshot.needs_restart) return t('value.managed', '已接管');
      if (snapshot.config_matches && snapshot.needs_restart) return t('value.restartPending', '待重启');
      if (snapshot.base_url) return t('value.notManaged', '未接管');
      return t('value.notEnabled', '未启用');
    }}
    function speedLabelForBehavior(behavior) {{
      if (behavior === 'app_controlled') return t('value.appControlled', 'App 控制');
      if (['inject_missing', 'global_priority', 'auto_global_priority'].includes(behavior)) return t('value.fast', '快速');
      if (['preserve', 'preserve_only', 'unknown_conservative'].includes(behavior)) return t('value.standard', '标准');
      return t('value.notEnabled', '未启用');
    }}
    function shortSpeedLabel(snapshot) {{
      const currentBehavior = snapshot.settings_pending ? snapshot.runtime_fast_behavior : snapshot.fast_behavior;
      const current = speedLabelForBehavior(currentBehavior);
      if (snapshot.settings_pending) {{
        const pending = speedLabelForBehavior(snapshot.fast_behavior);
        return pending !== current ? `${{current}} · ${{t('value.pending', '待应用')}}${{pending}}` : `${{current}} · ${{t('value.pending', '待应用')}}`;
      }}
      return current;
    }}
    function proxySummaryTone(snapshot) {{
      if (snapshot.config_matches && snapshot.healthy && !snapshot.needs_restart) return 'ok';
      if (snapshot.config_matches) return 'warn';
      return 'idle';
    }}
    function loginSummaryTone(snapshot) {{
      return snapshot.chatgpt_auth || snapshot.api_key_auth ? 'ok' : 'idle';
    }}
    function speedSummaryTone(snapshot) {{
      return shortSpeedLabel(snapshot) === t('value.notEnabled', '未启用') ? 'idle' : 'ok';
    }}
    function recentRequestSummary(snapshot) {{
      const events = Array.isArray(snapshot.recent_response_events) ? snapshot.recent_response_events : [];
      const event = events.length ? events[events.length - 1] : null;
      if (!event) return [t('value.noRequests', '暂无'), 'idle'];
      const status = Number(event.status);
      if (!Number.isFinite(status) || status >= 400) return [t('value.abnormal', '异常'), 'warn'];
      return [t('value.normal', '正常'), 'ok'];
    }}
    function compactUrl(value, fallback) {{
      if (typeof value !== 'string' || !value) return fallback;
      return value.replace('https://', '').replace('http://', '');
    }}
    function providerRouteChain(snapshot) {{
      const codexProvider = displayValue(snapshot.codex_model_provider || snapshot.active_provider || snapshot.config_provider, '');
      const localProxy = compactUrl(snapshot.base_url, '');
      const configBase = compactUrl(snapshot.config_base_url, '');
      const upstreamProvider = displayValue(snapshot.runtime_upstream_provider || snapshot.proxy_upstream_provider || snapshot.managed_upstream_provider || snapshot.provider, '');
      const upstream = compactUrl(snapshot.runtime_upstream_base || snapshot.upstream_base, '');
      if (!(localProxy && snapshot.config_matches)) return [codexProvider, configBase || upstream].filter(Boolean).join(' -> ');
      const route = [codexProvider, localProxy, upstreamProvider, upstream].filter(Boolean).join(' -> ');
      const pendingProvider = displayValue(snapshot.pending_upstream_provider, '');
      const pendingUpstream = compactUrl(snapshot.upstream_base, '');
      const pendingRoute = [pendingProvider, pendingUpstream].filter(Boolean).join(' -> ');
      return pendingRoute ? `${{route}} · ${{t('value.pending', '待应用')}} ${{pendingRoute}}` : route;
    }}
    function withCount(key, fallback, count) {{
      const value = t(key, fallback);
      return value.split('{{{{count}}}}').join(String(count)).split('{{count}}').join(String(count));
    }}
    function runtimeSource(snapshot) {{
      const runtime = snapshot && snapshot.runtime && typeof snapshot.runtime === 'object' ? snapshot.runtime : {{}};
      const manager = runtime.manager && typeof runtime.manager === 'object' ? runtime.manager : {{}};
      const source = manager.source_root || manager.module_file || '';
      return [manager.source_layout, source].filter(Boolean).join(' · ') || t('value.unknown', '未知');
    }}
    function diagnosticRuntimeInfo(snapshot) {{
      if (snapshot.config_matches && snapshot.healthy && !snapshot.needs_restart) {{
        return [t('value.running', '运行中'), 'ok', compactUrl(snapshot.base_url, t('value.notEnabled', '未启用'))];
      }}
      if (snapshot.base_url) {{
        const [label, tone] = providerStatus(snapshot);
        return [label, tone, runtimeSource(snapshot)];
      }}
      return [t('value.notEnabled', '未启用'), 'idle', t('advanced.noProxySettings', '代理尚未启用，因此没有本地代理设置。')];
    }}
    function diagnosticConfigInfo(snapshot) {{
      const provider = snapshot.codex_model_provider || snapshot.config_provider || '';
      const baseUrl = snapshot.config_base_url || snapshot.upstream_base || '';
      if (provider && baseUrl) {{
        return [t('advanced.providerReady', '已检测到 provider'), 'ok', providerRouteChain(snapshot)];
      }}
      return [t('advanced.noProvider', '未检测到 provider'), 'warn', t('advanced.noProviderDetail', '请先在 Codex config.toml 配置可接管的第三方模型服务。')];
    }}
    function diagnosticAuthInfo(snapshot) {{
      if (snapshot.chatgpt_auth) {{
        let detail = t('auth.chatgpt', 'ChatGPT 账户登录');
        if (snapshot.chatgpt_login_compatible === true) detail = `${{detail}} · provider-auth`;
        else if (snapshot.chatgpt_login_compatible === false && snapshot.base_url) detail = `${{detail}} · provider-auth needed`;
        return ['ChatGPT', 'ok', detail];
      }}
      if (snapshot.api_key_auth) return [t('value.key', '密钥'), 'ok', t('auth.key', '接口密钥 / 第三方登录')];
      return [t('value.unknown', '未知'), 'idle', t('value.notConfigured', '未配置')];
    }}
    function diagnosticHookInfo(snapshot) {{
      const trust = snapshot.startup_hook_trust && typeof snapshot.startup_hook_trust === 'object' ? snapshot.startup_hook_trust : {{}};
      const hooks = Array.isArray(trust.hooks) ? trust.hooks : [];
      if (snapshot.startup_hook) return [t('value.normal', '正常'), 'ok', withCount('advanced.hooksTrusted', '已信任 {{count}} 条', hooks.length)];
      if (snapshot.base_url) return [t('value.needsAttention', '需处理'), 'warn', t('value.notConfigured', '未配置')];
      return [t('value.notEnabled', '未启用'), 'idle', t('advanced.noProxySettings', '代理尚未启用，因此没有本地代理设置。')];
    }}
    function diagnosticTelemetryInfo(snapshot) {{
      const responses = Array.isArray(snapshot.recent_response_events) ? snapshot.recent_response_events.length : 0;
      const metadata = Array.isArray(snapshot.recent_provider_metadata_events) ? snapshot.recent_provider_metadata_events.length : 0;
      const benchmark = snapshot.benchmark_result && typeof snapshot.benchmark_result === 'object';
      if (responses || metadata || benchmark) {{
        const benchmarkLabel = benchmark ? t('advanced.benchmarkReady', '已有性能基准') : t('advanced.benchmarkMissing', '未运行性能基准');
        return [
          t('advanced.logsReady', '日志路径已准备'),
          'ok',
          `${{withCount('advanced.requestsCount', '请求 {{count}} 条', responses)}} · ${{withCount('advanced.metadataCount', '检查 {{count}} 条', metadata)}} · ${{benchmarkLabel}}`
        ];
      }}
      return [t('value.noRequests', '暂无'), 'idle', t('advanced.logsReady', '日志路径已准备')];
    }}
    function diagnosticNextInfo(snapshot) {{
      const state = snapshot.user_state || {{}};
      const text = translatedState(state);
      let tone = state.code === 'working' ? 'ok' : 'warn';
      if (['cleanup_pending', 'ready_to_enable'].includes(state.code)) tone = 'idle';
      return [text.title, tone, text.message];
    }}
    function updateDiagnosticRow(id, info) {{
      const value = $('diagnostic-' + id + '-value');
      const detail = $('diagnostic-' + id + '-detail');
      if (value) {{
        value.textContent = info[0];
        value.className = `status-pill ${{info[1] || 'idle'}}`;
        value.removeAttribute('data-i18n');
      }}
      if (detail) detail.textContent = info[2] || '';
    }}
    function updateDiagnosticsWorkspace(snapshot) {{
      const diagnostics = $('diagnostics');
      if (diagnostics) diagnostics.textContent = JSON.stringify(snapshot, null, 2);
      updateDiagnosticRow('runtime', diagnosticRuntimeInfo(snapshot));
      updateDiagnosticRow('config', diagnosticConfigInfo(snapshot));
      updateDiagnosticRow('auth', diagnosticAuthInfo(snapshot));
      updateDiagnosticRow('hook', diagnosticHookInfo(snapshot));
      updateDiagnosticRow('telemetry', diagnosticTelemetryInfo(snapshot));
      updateDiagnosticRow('next', diagnosticNextInfo(snapshot));
      if (latestDoctorReport) renderDoctorReport(latestDoctorReport);
    }}
    function updateSettingsWorkspace(snapshot) {{
      const feedback = $('settingsUpdateFeedback');
      const title = $('settingsUpdateTitle');
      const action = $('updatePrimary');
      if (!feedback || !title || !action) return;
      const state = snapshot.user_state || {{}};
      const updateCodes = ['update_checked_dirty', 'update_available', 'already_current', 'update_blocked', 'updated'];
      if (updateCodes.includes(state.code)) {{
        const text = translatedState(state);
        title.textContent = text.title || t('settings.updateTitleIdle', '软件更新');
        title.removeAttribute('data-i18n');
        feedback.textContent = text.message || text.title;
        feedback.removeAttribute('data-i18n');
      }} else {{
        title.dataset.i18n = 'settings.updateTitleIdle';
        title.textContent = t('settings.updateTitleIdle', '软件更新');
        feedback.dataset.i18n = 'settings.updateIdle';
        feedback.textContent = t('settings.updateIdle', '还没有检查更新。');
      }}
      const canUpdate = state.code === 'update_available';
      const checked = ['already_current', 'updated', 'update_checked_dirty', 'update_blocked'].includes(state.code);
      action.dataset.updateAction = canUpdate ? 'update' : 'check-update';
      action.dataset.i18n = canUpdate ? 'button.updateNow' : (checked ? 'button.recheckUpdate' : 'button.checkUpdate');
      action.textContent = t(action.dataset.i18n, canUpdate ? '立即更新' : '检查更新');
      action.classList.toggle('secondary', !canUpdate);
    }}
    function diagnosticExportText() {{
      const payload = {{
        generated_at: new Date().toISOString(),
        snapshot: currentSnapshot
      }};
      if (latestDoctorReport) payload.doctor = latestDoctorReport;
      return JSON.stringify(payload, null, 2);
    }}
    function setDiagnosticFeedback(key, fallback) {{
      const node = $('diagnosticsFeedback');
      if (node) node.textContent = t(key, fallback);
    }}
    function fallbackCopyText(text) {{
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      const copied = document.execCommand('copy');
      textarea.remove();
      return copied;
    }}
    async function copyDiagnostics() {{
      const text = diagnosticExportText();
      try {{
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
        else if (!fallbackCopyText(text)) throw new Error('copy blocked');
        setDiagnosticFeedback('advanced.copyDone', '诊断已复制。');
      }} catch (_error) {{
        setDiagnosticFeedback('advanced.copyFailed', '浏览器没有允许复制，请改用导出文件。');
      }}
    }}
    function downloadDiagnostics() {{
      const blob = new Blob([diagnosticExportText()], {{ type: 'application/json;charset=utf-8' }});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `codex-model-gateway-diagnostics-${{new Date().toISOString().replace(/[:.]/g, '-')}}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setDiagnosticFeedback('advanced.exportDone', '诊断文件已生成。');
    }}
    function doctorCheckLabel(name) {{
      return t('advanced.check.' + name, String(name || '').replace(/_/g, ' '));
    }}
    function doctorBoolean(value) {{
      return value ? t('value.normal', '正常') : t('value.abnormal', '异常');
    }}
    function doctorObjectSummary(detail) {{
      if (detail.configured || detail.effective || detail.fast_behavior) {{
        return [detail.configured, detail.effective, detail.fast_behavior].filter(Boolean).join(' -> ');
      }}
      if (detail.upstream_auth || detail.upstream_api_key_source) {{
        const source = detail.upstream_api_key_source || detail.upstream_auth;
        const state = detail.upstream_api_key_available === false ? t('value.missing', '未保存') : t('value.saved', '已保存');
        return [source, state].filter(Boolean).join(' · ');
      }}
      if (Array.isArray(detail.loose)) {{
        return detail.loose.length ? `${{detail.loose.length}} loose path(s)` : `${{detail.checked || 0}} checked`;
      }}
      if (detail.ok !== undefined || detail.pid || detail.upstream_base) {{
        return [
          detail.pid ? `pid ${{detail.pid}}` : '',
          compactUrl(detail.upstream_base, ''),
          detail.upstream_api_key_source || ''
        ].filter(Boolean).join(' · ') || doctorBoolean(Boolean(detail.ok));
      }}
      if (detail.manager || detail.proxy) {{
        const manager = detail.manager && typeof detail.manager === 'object' ? detail.manager.source_layout : '';
        const proxy = detail.proxy && typeof detail.proxy === 'object' ? detail.proxy.source_layout : '';
        return [
          manager ? `manager ${{manager}}` : '',
          proxy ? `proxy ${{proxy}}` : '',
        ].filter(Boolean).join(' · ') || t('value.unknown', '未知');
      }}
      if (detail.installed !== undefined || detail.trusted !== undefined || detail.ready !== undefined) {{
        return [
          detail.installed ? 'installed' : '',
          detail.trusted ? 'trusted' : '',
          detail.ready ? 'ready' : '',
        ].filter(Boolean).join(' · ') || doctorBoolean(false);
      }}
      if (detail.hooks !== undefined || detail.codex_hooks !== undefined) {{
        const parts = [`hooks ${{detail.hooks ? 'on' : 'off'}}`];
        if (detail.codex_hooks !== undefined) parts.push(`legacy ${{detail.codex_hooks ? 'on' : 'off'}}`);
        return parts.join(' · ');
      }}
      const parts = Object.entries(detail)
        .filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value))
        .slice(0, 3)
        .map(([key, value]) => `${{key}}: ${{String(value)}}`);
      return parts.join(' · ') || t('value.unknown', '未知');
    }}
    function doctorDetailText(detail) {{
      if (detail === null || detail === undefined || detail === '') return '-';
      if (typeof detail === 'string') return detail;
      if (typeof detail === 'number' || typeof detail === 'boolean') return String(detail);
      if (typeof detail === 'object') return doctorObjectSummary(detail);
      try {{
        return JSON.stringify(detail, null, 2);
      }} catch (_error) {{
        return String(detail);
      }}
    }}
    function renderDoctorReport(report) {{
      const target = $('doctorResult');
      if (!target) return;
      const checks = report && Array.isArray(report.checks) ? report.checks : [];
      if (!checks.length) {{
        target.innerHTML = `<p class="empty-state">${{escapeHtml(t('advanced.doctorIdle', '还没有运行自检。'))}}</p>`;
        return;
      }}
      target.innerHTML = `<div class="doctor-list">${{checks.map((check) => {{
        const ok = Boolean(check && check.ok);
        const warning = !ok && check && check.severity === 'warning';
        const tone = ok ? 'ok' : 'warn';
        const status = ok ? t('value.normal', '正常') : (warning ? t('value.needsAttention', '需处理') : t('value.abnormal', '异常'));
        return `<div class="doctor-row">
          <strong>${{escapeHtml(doctorCheckLabel(check.name))}}</strong>
          <span class="doctor-detail">${{escapeHtml(doctorDetailText(check.detail))}}</span>
          <span class="status-pill ${{tone}}">${{escapeHtml(status)}}</span>
        </div>`;
      }}).join('')}}</div>`;
    }}
    async function runDoctor() {{
      const button = $('runDoctor');
      const oldText = button ? button.textContent : '';
      if (button) {{
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        button.textContent = t('advanced.doctorRunning', '正在运行自检...');
      }}
      setDiagnosticFeedback('advanced.doctorRunning', '正在运行自检...');
      try {{
        const response = await fetch('/api/doctor', {{
          headers: {{ [headerName]: token }},
          cache: 'no-store'
        }});
        const data = await response.json();
        if (!response.ok || data.status !== 'ok') throw new Error(data.error || 'doctor failed');
        latestDoctorReport = data.doctor || null;
        try {{
          await refreshSnapshot();
        }} catch (_refreshError) {{}}
        renderDoctorReport(latestDoctorReport);
        const hasWarnings = latestDoctorReport && Array.isArray(latestDoctorReport.warnings) && latestDoctorReport.warnings.length > 0;
        if (latestDoctorReport && latestDoctorReport.ok && hasWarnings) {{
          setDiagnosticFeedback('advanced.doctorWarnings', '功能链路正常，有权限安全建议。');
        }} else {{
          setDiagnosticFeedback(latestDoctorReport && latestDoctorReport.ok ? 'advanced.doctorPassed' : 'advanced.doctorFailed',
            latestDoctorReport && latestDoctorReport.ok ? '自检通过。' : '自检发现需要处理的项目。');
        }}
      }} catch (error) {{
        const message = (error && error.message) ? error.message : String(error);
        const target = $('doctorResult');
        if (target) target.innerHTML = `<p class="empty-state">${{escapeHtml(message)}}</p>`;
        setDiagnosticFeedback('advanced.doctorFailed', '自检发现需要处理的项目。');
      }} finally {{
        if (button) {{
          button.disabled = false;
          button.removeAttribute('aria-busy');
          button.textContent = oldText || t('advanced.runDoctor', '运行自检');
        }}
      }}
    }}
    function metricToneClass(node, tone) {{
      if (!node) return;
      node.className = `status-metric ${{tone || 'idle'}}`;
    }}
    function formatLocalTime(date) {{
      const pad = (value) => String(value).padStart(2, '0');
      return [
        date.getFullYear(),
        '-',
        pad(date.getMonth() + 1),
        '-',
        pad(date.getDate()),
        ' ',
        pad(date.getHours()),
        ':',
        pad(date.getMinutes()),
        ':',
        pad(date.getSeconds())
      ].join('');
    }}
    function renderLocalTimes() {{
      document.querySelectorAll('time.local-time[datetime]').forEach((node) => {{
        const value = node.getAttribute('datetime');
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return;
        node.textContent = formatLocalTime(date);
        node.title = `UTC ${{value}}`;
      }});
    }}
    function showView(view) {{
      const target = view || 'overview';
      if (!document.querySelector(`.view-page[data-page="${{target}}"]`)) return;
      document.querySelectorAll('.view-page[data-page]').forEach((page) => {{
        const active = page.dataset.page === target;
        page.hidden = !active;
        page.classList.toggle('active', active);
      }});
      document.querySelectorAll('.nav-item[data-view]').forEach((item) => {{
        item.classList.toggle('active', item.dataset.view === target);
      }});
      window.sessionStorage.setItem(viewStorageKey, target);
    }}
    function currentActiveView() {{
      const active = document.querySelector('.view-page.active[data-page]');
      return active ? active.dataset.page || 'overview' : 'overview';
    }}
    function showBenchmarkConfirm(show) {{
      const panel = $('benchmarkConfirm');
      if (panel) panel.hidden = !show;
    }}
    function resetSummary(snapshot) {{
      const providerSpeed = $('providerSpeed');
      if (providerSpeed) providerSpeed.textContent = speedLabel(snapshot);
      const [label, className] = providerStatus(snapshot);
      const status = $('providerStatus');
      if (status) {{
        status.textContent = label;
        status.className = `status-pill ${{className}}`;
      }}
      const summaryName = $('providerSummaryName');
      if (summaryName) summaryName.textContent = currentProviderName(snapshot) || t('value.notSelected', '未选择');
      const summaryUrl = $('providerSummaryUrl');
      if (summaryUrl) summaryUrl.textContent = displayValue((providerByName(currentProviderName(snapshot)) || {{}}).base_url, t('provider.noService', '未设置模型服务'));
      const summaryMetrics = document.querySelectorAll('.hero-summary .status-metric');
      if (summaryMetrics.length >= 4) {{
        summaryMetrics[0].querySelector('strong').textContent = shortProxyLabel(snapshot);
        metricToneClass(summaryMetrics[0], proxySummaryTone(snapshot));
        summaryMetrics[1].querySelector('strong').textContent = shortLoginLabel(snapshot);
        metricToneClass(summaryMetrics[1], loginSummaryTone(snapshot));
        summaryMetrics[2].querySelector('strong').textContent = shortSpeedLabel(snapshot);
        metricToneClass(summaryMetrics[2], speedSummaryTone(snapshot));
        const [requestLabel, requestTone] = recentRequestSummary(snapshot);
        summaryMetrics[3].querySelector('strong').textContent = requestLabel;
        metricToneClass(summaryMetrics[3], requestTone);
      }}
    }}
    function selectedSpeedMode() {{
      const selected = document.querySelector('input[name="speedMode"]:checked');
      return selected ? selected.value : 'fast';
    }}
    function shouldReloadForSnapshot(snapshot) {{
      const userState = snapshot.user_state || {{}};
      const terminalState = ['cleanup_pending', 'uninstalled_deferred', 'uninstalled'].includes(userState.code);
      const hasRuntimeControls = Boolean($('dangerZone') || $('uninstall'));
      const shouldShowRuntimeControls = Boolean(snapshot.base_url) && !terminalState;
      const hasProviderPanel = Boolean($('providerPanel'));
      const hasCodexConfigPanel = Boolean($('codexConfigPanel'));
      const providerAvailable = Array.isArray(snapshot.providers) && snapshot.providers.length > 0;
      const proxyEnabled = Boolean(snapshot.base_url) && !terminalState;
      const shouldShowProviderPanel = providerAvailable && proxyEnabled;
      const shouldShowCodexConfigPanel = providerAvailable && !proxyEnabled && !terminalState;
      const hasSpeedForm = Boolean($('speedForm'));
      const shouldShowSpeedForm = speedControlsAvailable(snapshot);
      return hasRuntimeControls !== shouldShowRuntimeControls ||
        hasCodexConfigPanel !== shouldShowCodexConfigPanel ||
        hasProviderPanel !== shouldShowProviderPanel ||
        hasSpeedForm !== shouldShowSpeedForm;
    }}
    function hasActiveTraffic(snapshot) {{
      const activity = snapshot && snapshot.proxy_activity && typeof snapshot.proxy_activity === 'object' ? snapshot.proxy_activity : {{}};
      return Number(activity.active_requests || 0) > 0 || Number(activity.active_streams || 0) > 0;
    }}
    function schedulePendingRefresh(snapshot) {{
      if (pendingRefreshTimer) {{
        window.clearTimeout(pendingRefreshTimer);
        pendingRefreshTimer = null;
      }}
      const userState = snapshot && snapshot.user_state ? snapshot.user_state : {{}};
      const waiting = userState.code === 'restart_deferred_active' || (snapshot && snapshot.needs_restart && hasActiveTraffic(snapshot));
      if (!waiting) return;
      pendingRefreshTimer = window.setTimeout(async () => {{
        pendingRefreshTimer = null;
        try {{
          await refreshSnapshot();
        }} catch (_error) {{
          schedulePendingRefresh(currentSnapshot);
        }}
      }}, 2000);
    }}
    function render(snapshot) {{
      currentSnapshot = snapshot || {{}};
      if (shouldReloadForSnapshot(snapshot)) {{
        window.location.reload();
        return;
      }}
      const userState = snapshot.user_state || {{}};
      updateDiagnosticsWorkspace(snapshot);
      updateSettingsWorkspace(snapshot);
      renderLocalTimes();
      const button = $('primary');
      button.dataset.action = userState.primary_action || 'diagnostics';
      resetControls(userState, snapshot);
      resetProviderForm(snapshot);
      resetSummary(snapshot);
      resetSpeedForm(snapshot);
      updateStateText(snapshot);
      applyLocale(snapshot);
      schedulePendingRefresh(snapshot);
    }}
    applyTheme();
    applyLocale(currentSnapshot);
    renderLocalTimes();
    schedulePendingRefresh(currentSnapshot);
    const savedView = window.sessionStorage.getItem(viewStorageKey);
    if (savedView) showView(savedView);
    document.querySelectorAll('.nav-item[data-view]').forEach((item) => {{
      item.addEventListener('click', () => showView(item.dataset.view));
    }});
    if ($('runDoctor')) $('runDoctor').addEventListener('click', () => runDoctor());
    if ($('copyDiagnostics')) $('copyDiagnostics').addEventListener('click', () => copyDiagnostics());
    if ($('downloadDiagnostics')) $('downloadDiagnostics').addEventListener('click', () => downloadDiagnostics());
    if ($('refreshDiagnostics')) $('refreshDiagnostics').addEventListener('click', () => window.location.reload());
    document.querySelectorAll('input[name="languageChoice"]').forEach((input) => input.addEventListener('change', (event) => {{
      if (!event.currentTarget.checked) return;
      const value = event.currentTarget.value;
      currentLocale = supportedLocales.includes(value) ? value : 'zh';
      window.localStorage.setItem(localeStorageKey, currentLocale);
      applyLocale(currentSnapshot);
    }}));
    document.querySelectorAll('input[name="themeChoice"]').forEach((input) => input.addEventListener('change', (event) => {{
      if (!event.currentTarget.checked) return;
      const value = event.currentTarget.value;
      currentTheme = supportedThemes.includes(value) ? value : 'system';
      window.localStorage.setItem(themeStorageKey, currentTheme);
      applyTheme();
    }}));
    if (window.matchMedia) {{
      const themeQuery = window.matchMedia('(prefers-color-scheme: dark)');
      const onSystemThemeChange = () => {{
        if (currentTheme === 'system') applyTheme();
      }};
      if (themeQuery.addEventListener) themeQuery.addEventListener('change', onSystemThemeChange);
      else if (themeQuery.addListener) themeQuery.addListener(onSystemThemeChange);
    }}
    async function requestAction(action, body, options = {{}}) {{
      const response = await fetch('/api/actions/' + action, {{
        method: 'POST',
        cache: 'no-store',
        headers: {{ [headerName]: token, 'Content-Type': 'application/json' }},
        body: body ? JSON.stringify(body) : undefined
      }});
      const data = await response.json();
      if (data.status !== 'ok') {{
        const shouldRenderErrorSnapshot = data.snapshot && options.renderErrorSnapshot !== false;
        if (shouldRenderErrorSnapshot) render(data.snapshot);
        const error = new Error(data.error || '操作没有完成。');
        error.renderedSnapshot = Boolean(shouldRenderErrorSnapshot);
        throw error;
      }}
      if (data.action && data.action.control_ui && data.action.control_ui.url) {{
        await reloadWhenControlUiReady(data.action.control_ui);
        return;
      }}
      if (data.action && data.action.reload_required) {{
        window.sessionStorage.setItem(viewStorageKey, currentActiveView());
        window.location.reload();
        return;
      }}
      if (options.onSuccessData) options.onSuccessData(data);
      if (options.renderSuccessSnapshot === false) {{
        data.renderedSnapshot = false;
        return data;
      }}
      render(data.snapshot);
      data.renderedSnapshot = true;
      return data;
    }}
    async function refreshSnapshot() {{
      const response = await fetch('/api/status', {{
        headers: {{ [headerName]: token }},
        cache: 'no-store'
      }});
      const data = await response.json();
      if (!response.ok || data.status !== 'ok') throw new Error(data.error || 'refresh failed');
      if (data.snapshot) render(data.snapshot);
      return data.snapshot || null;
    }}
    async function reloadWhenControlUiReady(controlUi) {{
      const url = controlUi.url;
      const delay = controlUi.reload_after_ms ?? 120;
      const timeout = controlUi.reload_timeout_ms ?? 8000;
      const waitForDisconnect = Boolean(controlUi.wait_for_disconnect);
      const replacementPid = Number(controlUi.pid);
      await new Promise((resolve) => window.setTimeout(resolve, delay));
      const deadline = Date.now() + timeout;
      let disconnected = !waitForDisconnect;
      while (Date.now() < deadline) {{
        try {{
          const response = await fetch(new URL('/api/ping', url), {{ cache: 'no-store' }});
          const ping = response.ok ? await response.json() : {{}};
          const replacementReady = Number.isFinite(replacementPid) && ping.pid === replacementPid;
          if (response.ok && (disconnected || replacementReady)) {{
            window.location.href = url;
            return;
          }}
        }} catch (error) {{
          disconnected = true;
        }}
        await new Promise((resolve) => window.setTimeout(resolve, 120));
      }}
      window.location.href = url;
    }}
    function startActionProgress(button, action, options = {{}}) {{
      const timers = [];
      const steps = actionProgress[action] || actionProgress.default;
      const applyStep = (step) => {{
        button.textContent = t(step.labelKey, step.label);
        if (step.message && !options.suppressGlobalProgress) $('message').textContent = t(step.messageKey, step.message);
      }};
      steps.forEach((step) => {{
        if (step.delay > 0) timers.push(window.setTimeout(() => applyStep(step), step.delay));
        else applyStep(step);
      }});
      return () => timers.forEach((timer) => window.clearTimeout(timer));
    }}
    async function runButton(button, action, body, options = {{}}) {{
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      const oldText = button.textContent;
      const stopProgress = startActionProgress(button, action, options);
      let renderedSnapshot = false;
      let ok = false;
      let caughtError = null;
      let responseData = null;
      try {{
        const data = await requestAction(action, body, options);
        responseData = data || null;
        renderedSnapshot = Boolean(data && data.renderedSnapshot);
        ok = true;
      }} catch (error) {{
        caughtError = error;
        renderedSnapshot = Boolean(error && error.renderedSnapshot);
        if (!renderedSnapshot && !options.suppressGlobalError) {{
          $('state').textContent = t('value.needsAttention', '需要处理');
          $('message').textContent = (error && error.message) ? error.message : String(error);
        }}
        if (options.feedbackElement) {{
          options.feedbackElement.textContent = (error && error.message) ? error.message : String(error);
        }}
      }} finally {{
        stopProgress();
        button.disabled = false;
        button.removeAttribute('aria-busy');
        if (!renderedSnapshot) button.textContent = oldText;
      }}
      return {{ ok, error: caughtError, renderedSnapshot, data: responseData }};
    }}
    $('primary').addEventListener('click', async (event) => {{
      const action = event.currentTarget.dataset.action;
      if (action === 'enable') await runButton(event.currentTarget, 'enable', {{ provider: currentProviderName() || null }});
      else if (action === 'refresh') window.location.reload();
      else if (action === 'uninstall') await runButton(event.currentTarget, 'uninstall');
      else {{
        showView('advanced');
        const panel = $('diagnosticsPanel');
        if (panel) panel.open = true;
      }}
    }});
    if ($('updatePrimary')) $('updatePrimary').addEventListener('click', (event) => runButton(event.currentTarget, event.currentTarget.dataset.updateAction || 'check-update'));
    if ($('uninstall')) $('uninstall').addEventListener('click', (event) => runButton(event.currentTarget, 'uninstall'));
    if ($('finishCleanup')) $('finishCleanup').addEventListener('click', (event) => runButton(event.currentTarget, 'uninstall'));
    if ($('confirmUninstall')) $('confirmUninstall').addEventListener('click', (event) => runButton(event.currentTarget, 'uninstall', {{ confirm: true }}));
    if ($('cancelUninstall')) $('cancelUninstall').addEventListener('click', () => {{
      const dangerZone = $('dangerZone');
      if (dangerZone) dangerZone.hidden = true;
      const uninstall = $('uninstall');
      if (uninstall) uninstall.hidden = false;
    }});
    if ($('newProvider')) $('newProvider').addEventListener('click', () => {{
      openProviderEditor(null, 'provider.editor.add');
    }});
    if ($('cancelProvider')) $('cancelProvider').addEventListener('click', () => closeProviderEditor());
    if ($('revealApiKey')) $('revealApiKey').addEventListener('click', async () => {{
      try {{
        await revealProviderKey();
      }} catch (error) {{
        $('message').textContent = (error && error.message) ? error.message : String(error);
      }}
    }});
    if ($('apiKey')) $('apiKey').addEventListener('input', (event) => {{
      const input = event.currentTarget;
      if (input.dataset.masked === 'true' && input.value !== (input.dataset.maskValue || '')) {{
        input.dataset.masked = 'false';
        input.dataset.maskValue = '';
        input.dataset.original = '';
        loadedApiKey = '';
        loadedApiKeyProvider = '';
      }}
      updateRevealButtonState();
    }});
    if ($('providerList')) $('providerList').addEventListener('click', async (event) => {{
      const button = event.target.closest('button[data-provider-action]');
      if (!button) return;
      const provider = button.dataset.provider || '';
      if (button.dataset.providerAction === 'edit') {{
        openProviderEditor(providerByName(provider), 'provider.editor.edit');
        return;
      }}
      if (button.dataset.providerAction === 'switch') {{
        await runButton(button, 'switch-provider', {{ provider }});
      }}
      if (button.dataset.providerAction === 'verify') {{
        setProviderCheckResult(provider, {{
          tone: 'checking',
          title: t('provider.check.checking', '检查中'),
          message: t('provider.check.checkingMessage', '正在验证这个模型服务。')
        }});
        const result = await runButton(button, 'verify-provider', {{ provider }}, {{
          renderErrorSnapshot: false,
          renderSuccessSnapshot: false,
          suppressGlobalProgress: true,
          suppressGlobalError: true,
          onSuccessData: (data) => {{
            const action = data.action || {{}};
            const state = (data.snapshot && data.snapshot.user_state) || action.user_state || {{}};
            const text = translatedState(state);
            setProviderCheckResult(provider, {{
              tone: 'ok',
              title: t('provider.check.ok', '正常'),
              message: text.message || t('provider.check.ok', '正常')
            }});
          }}
        }});
        if (!result.ok) {{
          const message = result.error && result.error.message ? result.error.message : t('provider.check.warn', '异常');
          setProviderCheckResult(provider, {{
            tone: 'warn',
            title: t('provider.check.warn', '异常'),
            message
          }});
        }} else if (result.data && result.data.snapshot) {{
          render(result.data.snapshot);
        }}
      }}
      if (button.dataset.providerAction === 'delete') {{
        if (pendingProviderDelete.provider !== provider || button.dataset.confirming !== 'true') {{
          requestProviderDeleteConfirmation(provider, button);
          return;
        }}
        resetPendingProviderDelete();
        await runButton(button, 'delete-provider', {{ provider }});
      }}
    }});
    if ($('runBenchmark')) $('runBenchmark').addEventListener('click', () => showBenchmarkConfirm(true));
    if ($('cancelBenchmark')) $('cancelBenchmark').addEventListener('click', () => showBenchmarkConfirm(false));
    async function confirmBenchmark(event) {{
      showBenchmarkConfirm(false);
      await runButton(event.currentTarget, 'run-benchmark', {{
        confirm: true,
        benchmark_kind: event.currentTarget.dataset.benchmarkKind || 'quick'
      }});
    }}
    if ($('confirmBenchmark')) $('confirmBenchmark').addEventListener('click', confirmBenchmark);
    if ($('confirmStrictBenchmark')) $('confirmStrictBenchmark').addEventListener('click', confirmBenchmark);
    if ($('providerForm')) $('providerForm').addEventListener('submit', async (event) => {{
      event.preventDefault();
      const validationError = providerFormValidationError();
      if (validationError) {{
        setProviderFormFeedback(validationError);
        return;
      }}
      setProviderFormFeedback('');
      const result = await runButton($('saveProvider'), 'save-provider', {{
        provider: $('providerNameInput').value.trim() || null,
        upstream_base: $('upstreamBase').value.trim() || null,
        api_key: apiKeyFormValue()
      }}, {{
        feedbackElement: $('providerFormFeedback'),
        renderErrorSnapshot: false
      }});
      if (result.ok && $('apiKey')) $('apiKey').value = '';
    }});
    if ($('speedForm')) $('speedForm').addEventListener('submit', async (event) => {{
      event.preventDefault();
      await runButton($('saveSpeed'), 'set-speed-mode', {{ speed_mode: selectedSpeedMode() }});
    }});
  </script>
</body>
</html>"""
