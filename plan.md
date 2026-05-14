# Control UI 重构计划

## 已冻结结论

### 1. 普通用户首次闭环

- 普通用户主路径固定为：自然语言安装 -> Codex 返回中文 Control UI 链接 -> 用户用外部浏览器打开 -> 点击「启用」-> 自动完成启用和 ChatGPT 登录准备 -> 提示重启 Codex -> 重启后显示「运行正常」。
- 默认 Control UI 使用中文。
- 「启用」是普通用户主路径里的唯一主按钮。按钮背后可以做多件事，但界面只表达一个动作：准备好当前模型服务路径，同时准备好用户之后切换到 ChatGPT 账户登录所需的兼容性。
- 用户不切换 ChatGPT 登录时，继续按当前 provider/API 方式使用；用户想切换 ChatGPT 登录时，启用流程已经提前准备好必要兼容性。
- 普通用户主路径不暴露 `proxy`、`base_url`、`auth.json`、`provider-auth.json`、`hooks.json`、`service_tier_policy`、`upstream_api_key_env`、`config.toml` 等内部概念。
- 普通用户只需要看到三个结论态：`准备启用`、`已准备好，请重启 Codex`、`运行正常`。
- 异常统一显示 `需要处理`，并提供「打开诊断」或「让 Codex 修复」。

### 2. Control UI 打开策略

- 自然语言安装完成后，不默认尝试浏览器自动化或自动打开外部浏览器；安装命令只启动 Control UI 并返回本地链接。
- 安装完成后用中文文本提示用户把链接放到外部浏览器打开，例如：`请在外部浏览器中打开：http://127.0.0.1:<control-port>/`。
- 如果页面是在 Codex 内置浏览器中打开，页面必须提示：重启 Codex 前请用外部浏览器打开此页面，否则重启后页面会关闭。
- `--open-browser` 只作为高级可选项，不进入普通用户安装路径；打开失败不能影响安装成功，也不能阻断用户通过复制链接继续操作。

### 3. 分层边界与清债原则

- 这次不是给现有 main 套一层 Control UI，而是借 Control UI 重构，把 main 里历史膨胀的业务堆拆开。
- `manager.py` 不能继续作为 3000 行大杂烩。后续只保留 CLI 入口和向后兼容薄包装。
- 历史业务逻辑必须拆到可复用层：
  - `core`：纯规则和纯函数，例如 URL 规范化、redaction、Fast policy、diagnosis。
  - `state/status`：只读本机状态聚合，例如 config、settings、manifest、hook、auth、runtime、logs。
  - `actions`：真实用例和事务，例如 enable、prepare ChatGPT login、set upstream、start、safe disable、finish uninstall。
  - `control API`：localhost JSON API，只做 token、安全校验、preview/run 调度。
  - `UI`：中文界面，只展示、确认、刷新状态。
- 每拆一块，都要让 CLI 和 UI 共用它；不允许为了 UI 复制一套业务逻辑。
- 能删的历史页面、胶水代码、重复判断要删；保留必须有明确入口或测试覆盖。
- `dashboard.py` 不再作为主 UI 演进。短期降级为 diagnostics；Control UI 成熟后优先删除或极限瘦身。
- 数据代理热路径 `proxy.py` 第一阶段尽量不动，除非是为了移除 dashboard 耦合；Responses 转发、SSE、service_tier patch 不跟 Control UI 重构混在一起。

### 4. 第一阶段范围与验收

- 第一阶段不是做漂亮 UI，而是做一条普通用户能走通的中文启用闭环，并用这条闭环倒逼 `manager.py` 拆层和清债。
- 第一阶段完成后必须能模拟真实用户验证：自然语言安装 -> 文本返回中文 Control UI 链接 -> 用户用外部浏览器打开 -> 点击「启用」-> 按提示重启 Codex -> 重启后确认「运行正常」。
- 第一阶段必须把启用闭环涉及的屎山代码清理干净：相关状态判断、诊断、启用事务、ChatGPT 登录准备、恢复基线不能继续散落在一个 3000 行 `manager.py` 里。
- 第一阶段可以只做启用闭环，不急着做完整配置中心、benchmark UI、update UI、多 provider 管理、托盘/原生 App、快捷方式、force stop、强制卸载、手动编辑 `auth.json` 等高级功能。
- 第一阶段必须保留 CLI/Skill 兜底能力，但 CLI/Skill 应逐步调用拆出来的状态和 action 层，不再复制业务判断。
- 第一阶段不改数据代理核心转发逻辑：Responses 转发、SSE 透传、service_tier patch 不和 Control UI 重构混在一起。
- `dashboard.py` 第一阶段只作为 diagnostics 保留，不作为普通用户入口继续建设；普通用户入口是独立 Control UI。
- 验收标准以真实用户路径为准：用户不需要知道后台配置文件、端口、proxy/auth/hook 概念，也能完成启用并知道何时重启 Codex。

## 待继续讨论

- 后续实现顺序和验收命令。
