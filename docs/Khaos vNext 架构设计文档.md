# Khaos vNext 架构设计文档

**状态：Draft / Architecture Constitution**  
**文档性质：规范性设计草案；“必须”描述目标约束，不代表当前已经实现。**  
**当前实现状态：** Seed 已有 macOS Seatbelt 能力探针、独立 Kernel Worker 与 Runner、受限 workspace snapshot、Kernel-mediated `fs.read` / `fs.list` / `fs.write`、`process.exec` 和经校验的 `workspace.commit` 路径。Runner 的 `process.exec` 请求只携带有界 `argv`；Kernel 校验参数，并固定 timeout、cwd、环境、workspace/read scope、资源限制与 OS sandbox。命令只修改 private snapshot，Kernel 将其整体 diff 视为不可信输入后再验证写回。Seatbelt 在 snapshot 写入规则之后拒绝移动未授权 baseline 项，并保护 read-scope 目录祖先不被移出；空 read scope 也拒绝 snapshot 项移动。Kernel 使用同一 trusted `workspace_write_scope` 限制 Runner SDK `fs.write` 与提交的全部新增、修改、删除路径；命令仍可在 private snapshot 内写入任意路径，但只要完整 changeset 含 scope 外路径，Kernel 就在任何 live mutation 前拒绝整次 commit。

**2026-10-04 Snapshot Broker signal scope：**Broker Seatbelt 现默认拒绝进程 signal，仅允许同一 sandbox 内的进程信号。现有签名产品 headless XPC 探针由 OS 拒绝 `kill(host_pid, 0)`，并通过生产 ToolRunner 取消、回收同 sandbox 子进程；真实 APFS snapshot 路径仍通过。该策略仍以 `(allow default)` 为基础，不代表 Broker 完整隔离。

当前 `process.exec` 是 trusted workspace session 隐式启用的能力。Kernel 已对该 session 的提交执行精确 per-path write scope，但尚没有 Plugin identity-bound capability grant、Manifest admission、Candidate digest/approval 或用户批准；因此它还不是生产授权模型。XPC `workspace.run` 只携带 Runner source、timeout 与 workspace scopes，不接受命令 `argv`；Runner 随后通过已认证 IPC 请求执行。现有真实 macOS 攻击测试覆盖进程隔离、workspace/scope 越权拒绝、sandboxed 命令、changeset 恶意输出拒绝及同一 workspace 的 Kernel 写回。保证范围以当前主机与各项可执行测试覆盖的接口为限；产品 Picker 的用户观察和可复现的自动化验收仍分别记录，不互相代替。项目还没有受保护的 Kernel 安装或排他的 live-workspace 写入权。

**2026-10-04 签名产品的执行边界：**本机签名 App Sandbox helper 的真实 OS 测试确认，沙箱内对子进程再应用 Seatbelt 返回 `sandbox_apply: Operation not permitted`；这使原先 App-Sandboxed `KernelProduction.xpc` 无法建立 Runner 所需的 OS 隔离。当前产品构建把这个固定可信 XPC service 移出 App Sandbox，仍以代码签名要求认证 Launcher，且由它给不可信 Runner 应用独立 Seatbelt；该服务属于 TCB，不属于可进化层。APFS Snapshot Broker 继续使用独立的进程级 Seatbelt，其固定存储根现位于用户 OS 临时目录下的私有子树。canonical `python3 -m unittest discover -s tests -v` 通过 250 项（484.088 秒），包含签名产品的 headless Broker、XPC 身份与真实 Seatbelt 攻击。修复 test-only driver 在取消后的新请求漏传 Broker endpoint 后，另一次用户选择的交互产品 XPC 攻击通过 1 项（116.146 秒）：测试父进程验证 read/list scope、Runner 直接访问 live workspace 的 OS 拒绝、Kernel 写回及越权 changeset 拒绝、取消后代清理与恢复、workspace 内容和深度签名。此证据限于本机签名临时产品副本及其 test-only driver，不证明 Plugin admission、Candidate activation、安装不可篡改或跨版本等价。此实现调整不放宽 Normative 的 OS enforcement 和 fail-closed 约束。

**2026-10-02 Runner-selected command ABI：**Runner IPC 升至 v6，`process.exec` 仅接受有界 `argv`；Kernel 仍固定 timeout、snapshot cwd、环境、read scope、资源限制及 Seatbelt policy。Workspace XPC 操作帧升至 v8，并从外层请求移除 `argv`；XPC service response ABI 仍为 v7。真实 macOS suite 通过全部 235 项（436.097 秒），包含拒绝附加 `workspace` 的 Runner IPC 攻击与签名产品包的 headless XPC 检查。该 suite 不打开 Picker。用户另行确认最近一次 Picker 交互已选择目录并关闭结果弹窗，但没有可关联的进程输出、workspace digest 或 app identity；这保留为 UI 观察，不算所选 workspace 写回验收证据。该 ABI 仍隐式开放给当前 trusted workspace session，不满足最终 Plugin 身份绑定授权要求。

**2026-10-02 完整 changeset 写入 scope：**Kernel 将 trusted `workspace_write_scope` 同时用于 Runner SDK `fs.write` 与完整提交 changeset 的新增、修改、删除 filesystem entry；命令可在 private snapshot 内生成任意内容，但任何未逐路径列入 scope 的改动都会在 live mutation 前使整次提交失败。独立真实 Seatbelt 攻击分别确认 scope 外新增、修改和删除都被拒绝，且 live workspace 无部分写入。精确 scope 仍只是 trusted workspace session 参数，不是用户批准或 Plugin-bound capability。签名产品 XPC、真实 Seatbelt 正向写回与越权写回拒绝均通过；canonical `python3 -m unittest discover -s tests -v` 通过 240 项（481.131 秒），headless 且未打开 Picker。此处保留的用户回执只确认选择目录并关闭结果弹窗，未独立确认显示结果、workspace digest 或签名。

**2026-10-02 `process.exec` read-scope rename 绕过修复：**真实 Seatbelt 攻击发现，命令不能直接读取 scope 外 canary，却能通过 `os.replace` 将它移动到获准文件名后读出；修复前测试以攻击 sentinel `48` 失败。现在命令 profile 在 snapshot 写入规则之后拒绝移动 scope 外 baseline 文件/子树，并保护精确文件 scope 的父目录；空 scope 则拒绝整个 snapshot 的 unlink/move。真实 macOS 回归覆盖 APFS `RENAME_SWAP`、父目录移出后再尝试把 canary 放入 scope、以及本机 volume 实际解析的大小写和 Unicode 规范化别名。focused profile test 检查规则顺序、scope 祖先保护和 deny-all 规则；focused launcher read-scope、empty-scope、rename 和别名攻击通过。生成规则超出现有 Seatbelt 数量或字节上限时 fail closed。上游调查发现 Anthropic `sandbox-runtime` 有同类 `file-write-unlink` 保护；它是 Apache-2.0 beta research preview 并要求 Node.js 22.12+，因此只借鉴窄 OS policy 思路，没有加入通用运行时依赖。canonical `python3 -m unittest discover -s tests -v` 通过 237 项（472.947 秒），没有打开交互 Picker。

**2026-10-02 App Sandbox APFS mount probe：**签名 App Sandbox helper 的真实 OS 回归通过，确认 `hdiutil create/attach`、`diskutil image attach` 和对部分附着 APFS 设备执行的 `diskutil mount` 均返回非零；其中 `diskutil image attach` 可留下未挂载的 OS-visible 设备，因此测试宿主会卸载并验证清理。未沙箱对照可用两种 attach 命令挂载同一 APFS sparsebundle。focused test 通过（1 项，9.785 秒），canonical `python3 -m unittest discover -s tests -v` 通过全部 235 项（438.586 秒）。该回归只证明这些精确 App Sandbox 路径在当前 macOS 主机上的结果，不证明生产 XPC entitlement 组合或 Broker 已受进程级 confinement。

**2026-10-02 Snapshot Broker 进程级 Seatbelt：**`KernelSnapshotBroker.xpc` 在任何 XPC listener resume 前，使用系统 `libsandbox` 将固定 SBPL 应用到 Broker 进程；策略初始化失败时服务退出，不开放 endpoint。策略拒绝网络访问、整个 `/Users` 树（含 `/Users/Shared` 及 APFS Data-volume firmlink alias）中固定 Broker storage subtree 以外的文件数据、xattr 与写入，以及常见系统临时目录、`/Volumes` 和从 `/Users` 执行程序。为进入 storage subtree，策略保留其目录祖先所需的有限枚举/元数据访问；文件节点本身仍受拒绝规则保护。Broker 为固定 `hdiutil` / `diskutil` 子进程设置 `TMPDIR` 到该 private storage root；Kernel peer 身份、canonical root 与 lease 校验仍保留。真实签名产品包测试确认 snapshot 创建、挂载、释放与卸载仍成功；同一策略的 test-only Broker XPC 探针尝试读取及 `lstat` `/Users/Shared` canary、经 Data-volume alias 读取同一文件、在共享目录建文件及改目录 mode、写入系统临时目录及其 `/tmp`、`/var/tmp` alias、打开 Kernel 可执行文件写入、执行 `/Users/Shared` 中的程序及连接 loopback，均由 OS 返回 `EPERM` 或 `EACCES`，且每项宿主正向对照成功。test-only malformed-policy 产品副本也确认 `sandbox_init(3)` 拒绝无效 profile 后真实 Broker 在 listener resume 前退出，Launcher 收不到 endpoint。探针退出后 canary、目录 mode、Kernel 摘要、deep code signature 与挂载清单均通过检查；更新后的聚焦产品 XPC 测试通过 1 项（29.192 秒），canonical `python3 -m unittest discover -s tests -v` 通过全部 237 项（471.837 秒），均不打开 Picker。Broker 接收固定容器 URL 后不再调用 `startAccessingSecurityScopedResource()`；该私有目录只在 authenticated Kernel 调用和活跃 Seatbelt policy 下处理。

**2026-10-04 Snapshot Broker 临时目录元数据拒绝：**Seatbelt 现对标准临时根下 storage subtree 及其祖先以外的路径同时拒绝文件数据、metadata、existence 检查、xattr 和写入。真实签名产品 Broker XPC 探针先在宿主确认 `/var/tmp` 与临时写入 canary 可用，再要求 Broker `lstat /var/tmp` 和 `access(F_OK)`；两项均收到 `EPERM` 或 `EACCES`。同一 headless 产品用例仍成功创建、挂载并释放 APFS snapshot，1 项通过（27.928 秒），未打开 Picker。这只收紧了所测标准临时根的 metadata/existence 访问；Broker 仍使用 `(allow default)`，不能称为完整 confinement。

**2026-10-04 Snapshot Broker Homebrew Data-volume alias：**Broker 的 package-manager 写入和执行拒绝现在同时覆盖 `/opt/homebrew`、`/usr/local` 及其 `/System/Volumes/Data` firmlink 拼写。签名产品 XPC 探针在宿主确认 Data-volume 路径与 `/opt/homebrew` 指向同一目录，并先成功通过该拼写执行 canary、创建文件；采用生产策略 helper 的同签名身份 test-only Broker 两项均收到 `EPERM` 或 `EACCES`。生产 Broker 的 APFS snapshot 路径保持可用；headless 聚焦用例通过 1 项（28.856 秒），未打开 Picker。当前 Apple Silicon 主机实际覆盖 `/opt/homebrew` alias；不证明 `/usr/local`、其他 macOS 版本或所有系统资源。策略仍使用 `(allow default)`，不是完整 confinement。

**2026-10-04 Snapshot Broker 临时目录 Data-volume alias：**临时目录拒绝规则现也覆盖 `/System/Volumes/Data/private/var/folders`、`/System/Volumes/Data/private/tmp` 和 `/System/Volumes/Data/private/var/tmp`；固定 storage subtree 的 Data-volume 拼写也保留在例外范围内。签名产品 XPC 探针先确认 `/System/Volumes/Data/private/tmp` 与 `/tmp` 是同一目录且宿主可写，再确认 Broker 经该 alias 创建文件被 OS 拒绝；APFS snapshot 路径保持可用，headless 聚焦用例通过 1 项（28.858 秒），未打开 Picker。当前主机的直接攻击证据覆盖 `private/tmp` alias；策略仍使用 `(allow default)`，不证明完整 containment。

**2026-10-04 Snapshot Broker 临时目录执行拒绝：**Broker 现通过同一 Seatbelt 路径规则拒绝从常见临时根及其 Data-volume aliases 执行程序。签名产品 XPC 探针先在 `/System/Volumes/Data/private/tmp` 放置并由宿主成功执行 `/usr/bin/true` 副本，再确认 Broker 的 `posix_spawn` 被 OS 拒绝；同一运行中真实 APFS snapshot create/attach/release/detach 仍成功。headless 聚焦用例通过 1 项（29.283 秒），未打开 Picker。直接执行攻击覆盖 `private/tmp` alias；其他临时根的执行拒绝来自同一策略生成逻辑，Broker 仍以 `(allow default)` 为基础。

此策略仍是有界但非最小权限的过渡实现：它使用 `(allow default)` 加 deny 规则，没有 App Sandbox entitlement，并且系统 `sandbox_init(3)` 当前标记为 deprecated；`/Users`、常见临时区、挂载点和网络以外的系统路径仍可能保有默认 authority。当前证据只覆盖本机 macOS 上列出的真实操作，不证明所有文件/IPC/设备/进程资源均被拒绝、所有系统版本等价、安装包不可由其他同 UID 进程修改，或插件准入/Activation 已实现。完整 deny-by-default Broker containment 仍是目标差距。此实现状态不改变本文 Normative 约束。

**2026-10-01 Snapshot Broker 实现状态（当时）：**locally signed Seed 已将 `KernelProduction.xpc` 置于 App Sandbox，并将 APFS sparsebundle 的创建、挂载和卸载交给独立 `KernelSnapshotBroker.xpc`。Launcher 通过签名身份受限的 named XPC bootstrap 获取匿名 operation endpoint；Kernel 再校验 Broker 身份，并把 Kernel container 内固定私有目录 URL 传给 Broker。Broker 对每次租约串行处理、验证 storage root 和 lease 路径，并在完成清理后释放文件访问 scope。真实签名产品包的 headless 测试会通过该 endpoint 创建并挂载 APFS snapshot、验证 Kernel 对端身份、释放租约并检查卷已卸载。真实 App Sandbox 探针拒绝本 backend 所需的 `hdiutil create/attach` 与 `diskutil mount`；`diskutil image attach` 虽返回非零，却会留下未挂载设备，不能作为可用挂载后端。该时点 Broker 未启用 App Sandbox，且尚未有进程级 confinement；此残余风险由 2026-10-02 的新证据更新。该测试不打开 Picker；当前交互 Picker 的选目录、read/list、Kernel 写回和运行后签名检查仍需逐次以新建测试 workspace 验证。此实现状态不改变本文 Normative 约束。

**2026-10-03 Snapshot Broker package-manager 写入拒绝：**Broker Seatbelt policy 现也由 OS 拒绝向 `/opt/homebrew` 和 `/usr/local` 子树写入，同时保留读取系统工具和原有执行拒绝。真实签名产品 XPC 探针先证明宿主可在 `/opt/homebrew/var/homebrew/tmp` 创建并删除 canary，再要求同一测试 Broker 创建该文件；Broker 收到 `EPERM` 或 `EACCES`，canary 保持不存在。真实生产 Broker 的 APFS snapshot 创建、挂载、释放和卸载仍通过；聚焦产品测试通过（1 项，30.237 秒），canonical suite 通过 244 项（470.812 秒），均未打开 Picker。该证据仅覆盖当前 Apple Silicon 主机的可写 `/opt/homebrew` 路径；不证明 `/usr/local`、其他 macOS 版本或其他系统资源。策略仍以 `(allow default)` 为基础，不能标记为 deny-by-default 或完整 containment。

**2026-10-03 Product XPC 缺少 Snapshot Broker 时 fail closed：**真实签名 `KernelProduction.xpc` 收到一条 source digest 匹配、内容试图用 `/usr/bin/touch` 写入宿主可写 `/Users/Shared` canary 的请求，但未附带同连接的 Snapshot Broker endpoint。XPC 必须在 Runner 执行前返回 `snapshot_broker_not_configured`；canary 保持不存在。宿主正向控制先证明该 canary 路径可写。聚焦产品测试通过 1 项（27.918 秒），canonical suite 通过 244 项（471.613 秒），未打开 Picker。它证明本产品路径对此缺失 endpoint 请求明确拒绝，不外推到所有 sandbox/backend 故障，也不证明用户选择、Runner admission 或完整 Broker containment。

**2026-09-30 Native Workspace XPC scope admission：**原生 Swift parser 现于读取 bookmark 前验证 read/write scope 路径结构、最多 64 个路径组件、重复项及既有数量和字节上限；Python Worker 仍独立校验。真实签名 `KernelProduction.xpc` 的无 bookmark、有效 source-digest 攻击覆盖 traversal、absolute、空路径、NUL、空组件、`.`/`..`、过深路径、重复路径、超量路径和超限字节，并要求每项返回 `invalid_request`、服务随后仍可响应。扩展后的 focused 测试通过（1 项，14.303 秒）；对应的 canonical suite 通过全部 212 项（426.185 秒）。此前另一项 full-suite run 曾有一个无关 commit-child 竞态 ERROR，单测重跑通过且后续两次全量运行均未复现。此项证明测试签名服务在该主机上的早期准入拒绝，不授予 workspace scope，也不证明用户授权或产品 writeback。

2026-09-28 新增固定 XPC service entrypoint `KernelWorkspaceServiceMain.swift`，将 shared bootstrap 绑定到固定 Python executor。build-mode XPC 测试先将其编译并签入临时 bundle，随后一次无 picker 的 headless 检查实际启动该服务，经 bootstrap 获取 anonymous endpoint，并由正确的测试签名身份收到随机 idle-cancel 请求的 `process_not_active` 响应（76.380 秒）。这验证固定入口的启动及两段 XPC 响应，不运行 workspace executor，也不证明选择授权。后续 headless 攻击通过同一固定入口提交由 sandboxed 测试 app 在自身 Application Support 创建的 plain bookmark（`options: []`）；`KernelProduction.xpc` 返回 `workspace_rejected`，输入保持不变且没有 output/bypass 文件（最近 build-mode 测试 76.572 秒通过）。该拒绝仅适用于此固定入口和 app-container 夹具，不是外部 workspace 授权正向证据，也不代表其他 XPC service 行为。另一次同日攻击让同一测试 app 内的 sandboxed `UntrustedHost.xpc` 直接请求 Kernel named bootstrap；OS 使其连接失效，同时该 sibling 对外部 workspace canary 的写入也被拒绝。此项验证同 bundle 中独立 XPC peer 未继承 Launcher caller requirement，只覆盖临时测试签名。另一次直接启动未配置 bundle 的二进制以 `kernel-bootstrap=unavailable` 退出，未启动 listener。交互式授权、生产签名身份和安装保护仍未验证。

**XPC 授权实现状态：**目录选择、XPC 准入、bookmark-root、outbound client、Trusted Launcher 入口和固定 executor 逻辑已有共享源码，包括 `TrustedWorkspacePicker.swift`、`TrustedWorkspaceLauncherMain.swift`、`KernelWorkspaceService.swift`、`KernelWorkspaceBootstrap.swift`、`KernelWorkspaceClient.swift`、`KernelWorkspaceRoot.swift` 与 `KernelWorkspacePythonExecutor.swift`。`tools/build_macos_seed.py` 现在可生成本机架构、稳定签名身份签署的本地 `KhaosSeed.app`，并嵌入固定 Kernel XPC service。产品 bundle 的 headless 测试确认了两段 Peer identity 与错误 signer 拒绝。所选 workspace 的完整执行端到端攻击证据包括 ad-hoc XPC 测试 bundle 和 2026-09-29 临时产品 bundle 副本中的 test-only driver；2026-09-28 新鲜 `NSOpenPanel` 选择授权后，真实 XPC 测试经过共享 Python bridge 调用现有 Kernel Worker、Seatbelt Runner 和 validated changeset commit：获授权输入读取成功，直接 live-workspace 写入被拒绝，预期输出安全提交，symlink/FIFO changeset 被拒绝；hardlink 在 OS 创建阶段被拒绝或在 Kernel commit 阶段被拒绝，两种结果均要求候选路径未写入且外部 canary 与既有输出未改变。最终交互重跑在 334.921 秒通过。2026-09-28 用户在本机签名产品 app 中通过 `NSOpenPanel` 选择外部临时 workspace，较早的 bundle 显示 PASS，但仍携带 `com.apple.security.files.bookmarks.app-scope`。之后新构建的 reduced-entitlement bundle 也显示 PASS，用户确认后 workspace fixture 的 SHA-256 与预期一致；该 smoke 只证明固定 `/usr/bin/true` → Kernel XPC → Runner → 精确零变更结果路径。运行后的 `codesign --verify --deep --strict` 发现签名 Python.framework 中新增 `__pycache__` 文件。固定 executor 的独立 Python 子进程现显式传入 `-B`；干净环境仍设置 `PYTHONDONTWRITEBYTECODE=1` 供非隔离后代使用，产品包测试增加嵌套 Python imports 后无缓存新增且签名仍有效的断言；用户随后确认修复后的 reduced-entitlement app 显示 PASS；fixture SHA-256 为 c00d07fbc2916475914e8ccf2fbbb10c255a41ebc775898bb4ca2294df614659，运行前后未变；运行后 codesign --verify --deep --strict 通过，签名 Python.framework 中无 __pycache__。这仅验证固定零变更路径。当前产品 package test 还检查签名 entitlements：app 启用 App Sandbox 与 user-selected read/write、未声明 app-scope，Kernel service 未启用 App Sandbox。用户于2026-09-29确认本机签名产品 app 在所选 workspace 显示 PASS；该目录保留原 fixture，并出现五个内容、0600 权限和单链接均符合固定 smoke 预期的 marker。Launcher 现在还要求 macOS 在释放 Picker scope 后拒绝对已提交 marker 的直接写打开，才显示 PASS；产品路径已有固定一文件 changeset 与直接写拒绝的实际证据，但不证明一般 Plugin 执行。2026-09-29 产品交互验收已在 Launcher 释放 Picker scope 后，实际对 Kernel 已提交 marker 执行 `open(O_WRONLY | O_NOFOLLOW)`，并由 macOS 返回 `EPERM` 或 `EACCES`；此证据仅适用于当前产品构建和本机。Kernel XPC service 仍未开启 App Sandbox，且产品 bundle 未安装、notarize 或经过发行身份验证。Candidate admission、持久授权和安装完整性也未实现。

**2026-09-29 source digest 绑定：**Native Workspace XPC ABI 升至 v5，`workspace.run` 新增 `runner_source_sha256`。Swift Kernel parser 在读取 bookmark 前校验它等于 `runner_source` 的 UTF-8 SHA-256；独立 Python bridge 在启动 Worker 前再次校验。真实产品 `KernelProduction.xpc` headless 攻击用不匹配摘要得到 `invalid_request`，交互式产品 XPC 攻击则用匹配摘要通过真实 bridge/Worker/Runner 和安全提交（303.470 秒）。它证明 source 内容摘要在该请求路径上保持一致，不代表用户 approval、Manifest/capability admission 或 Candidate activation；XPC 攻击使用临时 bundle 副本中的 test-only driver。随后用 v5 代码运行正常 Product Launcher 写回验收，Picker 300 秒内未收到用户选择，308.598 秒后测试超时并清理 fixture；因此当前正常 Launcher 的外部 workspace 正向运行仍未验证，之前版本的用户 PASS 不能替代此证据。canonical `python3 -m unittest discover -s tests -v` 全部 188 项通过（365.615 秒）；默认 suite 不打开 Picker，也未解决上述 v5 Launcher 交互缺口。

**2026-09-29 当前树验证：**产品包的 focused headless peer-authentication test 通过（1 项，7.651 秒）。之后 opt-in 交互验收在临时 self-signed app 中由用户选择测试专属的新 workspace 并通过（1 项，153.683 秒）：Kernel 恰好提交一个预期 marker，原 fixture 未变；测试核对 marker 内容、0600 权限、单链接、深度签名和 signed Python.framework 中无 `__pycache__`。`--picker-start-directory` 只设置系统 Picker 的初始导航位置，实际 scope 仍来自用户在 `NSOpenPanel` 中的选择；产品当前只运行固定 Runner source，不加载任意 Plugin。测试启动时仍观察到 `sandbox_extension_issue_file_to_process` warning；验收通过，但 warning 来源和原因未确定。修改后的 canonical `python3 -m unittest discover -s tests -v` 随后通过全部 186 项，耗时 365.245 秒；默认套件没有打开 Picker。之后 Launcher 增加了对 Kernel 已提交 marker 的真实 `open(O_WRONLY | O_NOFOLLOW)` 检查，只接受 `EPERM` 或 `EACCES` 才显示 PASS；focused headless package test 通过（1 项，7.772 秒）；新的交互式产品验证也通过（1 项，30.270 秒），测试断言 path-free diagnostic 为 `direct-write=denied`，并核对 Kernel marker 和 fixture。产品 Launcher 在当前签名及主机上的直接写拒绝已获实际执行证据；改动后的 canonical suite 通过全部 186 项，耗时 384.191 秒。经产品 XPC 的 test-only unsafe-changeset/cancellation 攻击已由下面的新鲜交互测试通过；不可信 Plugin source 经正式产品 Launcher 准入、Candidate admission 仍未证明。

**2026-09-29 Workspace XPC 唯一 JSON 编码：**Kernel 现在要求 Workspace XPC v5 请求体逐字节等于 Foundation sortedKeys 对解析对象的序列化结果，避免重复字段被字典静默折叠，并拒绝其他非规范编码；请求深度上限仍在 Foundation 解析前执行。默认 signed-product 测试把 `workspace_read_scope` 的精确重复与解码后同名的 escaped-key 重复请求发送到真实 KernelProduction.xpc，无 bookmark 时均要求 invalid_request，随后确认服务仍能响应 idle cancellation；超深请求攻击也使用同一编码器生成，确保其由深度限制拒绝。最终聚焦产品包测试通过 1 项（10.277 秒），canonical suite 通过 193 项（373.618 秒）。这只证明该 XPC 请求解析边界，不构成 Candidate admission 或用户授权证据。

2026-09-28 当前树上的 canonical `python3 -m unittest discover -s tests -v` 通过全部 185 项，耗时 384.048 秒，包含真实 Seatbelt/APFS 攻击和 headless XPC 检查。针对当前直接 Picker scope 撤销探针的交互重跑到达 `WorkspaceGrant` 系统 Picker，但 300 秒内没有收到目录选择，测试于 419.214 秒超时并清理 fixture；因此当前 probe 的 OS 写拒绝及其 `KernelProduction` changeset/cancellation 断言仍未执行。该超时不改变产品 app 零变更 smoke 的证据，也不构成攻击断言失败。

**2026-09-28 最新验证补充：**test-only `WorkspaceGrant` 现在将 `NSOpenPanel` 原始 root bookmark 传给 `KernelProduction`，fixture 与 sibling canary 也位于所选 root；focused headless build-mode test 通过（109.470 秒），canonical suite 在改动前通过 185 项（383.060 秒），加入 `-B` 后再次通过 185 项（361.049 秒）。较新的 reduced-entitlement 本地签名 `KhaosSeed.app` 经用户选择外部 workspace 后显示 `PASS`，fixture 的 SHA-256 保持 `e15de7f2e6c2cfe2e8b4f4aafe7f79ada1b50b1b50a90695d207a22e12b13d1e`。运行后 `codesign --verify --deep --strict` 报告签名的 `Python.framework` 新增 `__pycache__`；固定 executor 对每个隔离 Python 子进程传入 `-B`，并为非隔离后代设置 `PYTHONDONTWRITEBYTECODE=1`；产品包测试现嵌套启动 Python 并检查无缓存新增及签名仍有效。针对该修复的 focused package test 已通过（7.743 秒），Launcher 24 项、Seatbelt 37 项、Broker 27 项也均串行通过，用户随后确认修复后的 reduced-entitlement app 显示 PASS；fixture SHA-256 为 c00d07fbc2916475914e8ccf2fbbb10c255a41ebc775898bb4ca2294df614659，运行前后未变；运行后深度签名验证通过且签名 Python.framework 无 __pycache__。这仅验证固定零变更路径。新版 `WorkspaceGrant` helper 后续打开 Picker，但 300 秒内未收到选择，408.852 秒后超时并清理夹具，因此 direct-write-denial、非空 changeset、unsafe changeset、cancellation 仍未交互验证。


2026-09-28 的 canonical suite 随后通过全部 182 项测试（322.529 秒）。该套件不替代交互式选择证据；当前授权与 shared-executor 端到端证据来自上面的真实 `NSOpenPanel` / XPC 测试。之后按用户要求重新打开 Picker，前台 `WorkspaceGrant` 在 300 秒内未收到选择或取消，focused test 总计 376.117 秒后以 `subprocess.TimeoutExpired` 失败并清理 helper 和临时目录；该次重试没有产生新的授权或 writeback 证据，不改变此前成功运行的历史记录。

2026-09-28 随后收紧 Picker 的真实 workspace 写权限：共享选择器同时返回 Kernel 的读写 bookmark 和验证用只读 bookmark；Picker 在运行 workspace 请求前平衡 `NSOpenPanel` 隐式开始的读写 scope，再解析只读 bookmark，并由真实 `open(O_WRONLY)` 攻击要求 OS 拒绝 Picker 写入。test harness 在 helper 退出后校验 Kernel 输出。canonical suite 通过 182 项（322.896 秒），发生在保存原始 panel URL 的最后一项 Swift 变更之前；该变更后的 XPC build-mode 测试通过（75.966 秒）。交互 Picker 在 300 秒内未收到选择，focused test 在 376.136 秒后超时清理。之后按用户选择再次重开 Picker，`WorkspaceGrant` 再次前台等待 300 秒仍未收到选择，focused test 总计 387.031 秒后超时清理；CUA inventory 可见临时 app，但窗口附着调用超时。当前代码下的 Picker 写权限撤销与 Kernel 写回断言仍未执行，不以此前 picker 版本证据替代。

2026-09-28 对上述 Picker 写权限撤销探针进行交互复核时，首次选择了预期的临时 `user-selected-workspace`，但 helper 无法在撤销 panel scope 后重新开始显式只读 scope，OS 返回 `EPERM`。修正后，测试以 `.withSecurityScope` 解析显式只读 bookmark，并在临时 sandboxed `WorkspaceGrant.app` 上声明 `com.apple.security.files.bookmarks.app-scope`；这是测试探针配置，未加入 Kernel。Apple 文档要求显式 security-scoped bookmark 的解析包含该选项，并说明 sandboxed app 的 scoped bookmark entitlement。缺少 entitlement 时的一次已选择重跑仍以 `EPERM` 退出。加入 entitlement 后的 headless build-mode XPC 测试通过（1 项，110.747 秒），canonical suite 通过全部 184 项（387.453 秒）；随后交互面板在前台等待 300 秒但没有选择，focused test 在 409.603 秒后清理 helper 与 fixture。因而当前代码下的 Picker 写权限撤销、Kernel 写回及 unsafe changeset 拒绝尚无新的交互证据，之前成功的 Picker 运行不能替代这些断言。

随后一次用户已选择预期 workspace 的重跑，在 `.withSecurityScope` 解析及 test-app entitlement 均已加入后仍由 OS 返回 `EPERM`。因此 picker 改为直接从 `NSOpenPanel` 返回的原始 `selectedURL` 创建只读 bookmark；规范化 URL 仍用于选中根身份比较，Kernel bookmark 路径不变。该变化后的 build-mode XPC 测试通过（1 项，109.623 秒），canonical suite 随后通过全部 184 项（387.692 秒）。最新交互面板确认处于前台，但 300 秒内没有选择，focused test 在 408.758 秒后清理。当前只读 scope 重新开始、Picker 写拒绝和 Kernel 安全写回仍未验证；原始 URL 变更目前只有编译与 headless 证据。

2026-09-28 为 `KernelProduction.xpc` 增加了真实 XPC 取消攻击夹具：验证其他连接不能取消活动请求、原连接取消后命令后代退出、snapshot 输出未写回，并由后续无变更请求确认服务恢复。headless XPC build-mode 编译该夹具并通过既有跨进程攻击（74.228 秒）；当时完整 181 项测试通过（328.892 秒）。随后两次按用户要求打开交互 picker，第一次 300 秒、第二次延长至 1800 秒仍未收到目录选择；第二次运行期间确认 `NSOpenPanel` 位于前台可见。测试总计 1874.365 秒后以 `subprocess.TimeoutExpired` 退出并清理 helper 与 fixture。因此新增的共享 executor 取消断言尚未执行，不能视为取消安全属性的端到端证据。

2026-09-28 的独立真实 App Sandbox 攻击中，非 picker 测试父进程为 workspace 路径创建 scope bookmark；仅带 `com.apple.security.app-sandbox` entitlement 的已签名 helper 无法启动该 scope，并得到 `EPERM`/`EACCES` 打开 canary。该测试拒绝的是无用户选择的路径 bookmark，不证明 Kernel XPC 或生产授权流程。

2026-09-28 的 headless build-mode XPC 测试（1 项，77.793 秒）扩展了真实 App Sandbox 的 Kernel 文件写入攻击：sandboxed Host 的容器内写入正向对照成功，但对临时签名 bundle 中 `KernelExecution` 和固定 `KernelProduction` 可执行文件、Python bridge、changeset 模块及 Python interpreter 的 `open(O_WRONLY)` 均被拒绝；目标摘要未变，deep code-signature verification 通过。这仅证明当前测试 bundle/主机上的这些路径受该 Host sandbox 限制，不证明生产安装不可篡改。随后按用户要求再次打开 Picker；`WorkspaceGrant` 前台等待 300 秒仍无选择或取消，测试清理 helper 与临时目录，未新增授权或 writeback 证据。之后当前树上的完整 canonical suite 通过 182 项（322.741 秒）；未打开 Picker，因此不构成新用户授权或固定 executor active-cancellation/writeback 证据。

一次较早的同目标重跑在 picker 启动前因 APFS image identity 歧义退出；后续重跑未改代码即通过该 APFS preflight。歧义产生原因尚未查明，保持 fail-closed 行为。

2026-09-28 使用当前 Picker 代码的新鲜选择重跑，在返回测试证据前以
`NSPOSIXErrorDomain` code 1 退出；当时可见 XPC/Worker 子进程，但未收集到
提交或拒绝断言。测试探针随后给 Kernel bookmark 创建和只读 bookmark 解析增加了
错误阶段上下文，headless build-mode 测试通过。下一次诊断重跑在 300 秒内未收到
选择并清理 fixture。当前 Picker 写权限撤销与外部 workspace 写回仍未验证；此前
旧测试状态的成功结果不替代当前代码的证据。之后 Kernel 传输 bookmark 的来源也从
规范化 URL 改为原始 `NSOpenPanel` URL，并保留 `options: []`，以传递系统授予的
implicit scope；Apple 文档将该形式用于 XPC 文件访问传递。修正后的 build-mode
测试通过（119.557 秒），交互重跑在 300 秒内未收到选择并于 408.694 秒后清理，
因此当前 bookmark 来源的正向外部 workspace 证据仍待取得。

2026-09-27 将仅供可信 UI 调用的目录选择与 bookmark 创建提取到共享
`TrustedWorkspacePicker.swift` 后，交互式 XPC 集成测试在 100.706 秒通过。它再次验证所选 bookmark 到达 Kernel、路径-only sibling XPC 写入被 OS 拒绝、安全 changeset 成功提交、不安全 changeset 被拒绝且 workspace 路径差分精确。共享选择器不持久化 grant；生产 Launcher、executor composition、Kernel packaging 与安装保护仍未实现。

2026-09-28 将 named bootstrap 和匿名 endpoint 的 outbound XPC 连接流程提取到
`KernelWorkspaceClient.swift`。同一函数在两类连接上都从调用者 bundle 读取签名
requirement 并在 `resume()` 前设置；缺失时不启动连接。测试的错误身份攻击也复用
该连接准备逻辑，并由真实 macOS XPC 返回签名要求失败。headless focused XPC 测试通过
（1 项，109.901 秒）；上一次 canonical suite 的 184 项通过发生在此次提取之前，未
重跑。没有打开 Picker，因此不增加 workspace grant 或 writeback 证据。该次提取本身
只提供共享 XPC 客户端；随后首次可构建的本地 Launcher/Kernel 组合见下，尚非发行或
安装后的服务。

2026-09-28 新增 `TrustedWorkspaceLauncherMain.swift` 与
`tools/build_macos_seed.py`，首次产生可本机运行的签名 `.app` 组合：sandboxed
Launcher 通过 shared picker 获取 bookmark，并请求空 read scope 的固定 smoke operation；
XPC Kernel 绑定既有 Python bridge/executor。独立 headless
测试用稳定 designated requirement 签署两个 bundle，启动真实 named service、获取并
连接 anonymous endpoint，再以同 bundle ID / 错误 signer 的真实 XPC client 验证 OS
拒绝；1 项通过，7.395 秒。一次较早的集成尝试在 `security find-identity -v` 排除
自签测试证书时失败，随后将 package test 分离并修正身份预检；未改为放宽 cdhash
检查。没有打开 Picker，因此 app 中的外部 workspace grant/commit 路径仍待用户选择
后验证。Kernel service 目前没有 App Sandbox entitlement；bundle 也不是发行、安装或
notarized 产物。此项没有改变 Normative 约束，最近 184 项 canonical suite 早于本次
改动且没有重跑。

当前 Launcher 的固定 smoke 已改为在 private snapshot 中创建唯一命名的测试文件，并只在
`process.exec` 返回成功后请求 `workspace.commit`；Launcher 要求 Kernel 精确报告新增一项、
无修改和删除，成功弹窗显示文件名。Picker 明示会写入测试文件。此前用户报告的 PASS 来自
零变更 bundle；2026-09-28 用户再次报告 PASS，但所选目录内只有原夹具、没有当前源码应创建的
标记文件，无法确认那次运行使用了新构建。当前产品 app 的非空写回仍待以新构建做交互验证。
当前源代码已新构建为本机签名 bundle；产品包/XPC 测试通过，深度签名检查通过，
只读 bootstrap 输出 `kernel-xpc-peer-authentication=verified`。启动时另输出
`sandbox_extension_issue_file_to_process` 警告；它未导致 bootstrap 失败，但尚未完成归因。
本次没有打开 Picker，非空产品写回仍待验证。

2026-10-04 的 Seed Launcher 增加一次性 `--command` 入口：用户选择 workspace 后，
Launcher 展示完整命令、精确读写 scope 和包含 bookmark、Runner source、scope 的本次请求摘要，
收到确认后释放自身 Picker scope，再通过原有 XPC/Kernel/Runner 路径执行。Runner 仅在命令
返回零时请求可信 changeset commit；非零退出或 Runner 失败不会写回。该入口不提供
Candidate admission、Plugin activation 或模型能力。Swift 类型检查、签名产品 headless
构建与 XPC 身份检查、现有真实 Seatbelt 的授权提交和越权输出拒绝用例通过；新命令入口
尚未经过选中 workspace 后的交互式端到端验收，因此不能据此宣称产品命令模式已获
完整执行证据。
命令 Seatbelt profile 仅对 trusted write scope 中 baseline 不存在的精确路径开放
`file-read-metadata`，供普通工具检查自己新建的输出；它不开放内容读取，也不给未授权
baseline 项元数据读取。真实 Seatbelt 检查确认 `cat input.txt > result.txt` 可写回唯一
scope 内输出，命令读取 scope 外兄弟文件及新输出内容仍被 OS 拒绝；原有元数据写入拒绝
和 scope 外 changeset 拒绝也通过。`/bin/cp` 因试图复制 xattr 仍可能非零退出，
Launcher 命令模式在非零退出时不请求提交。
对新增元数据规则的真实 OS 攻击还验证了未授权 baseline hardlink、指向外部文件的
新建 symlink、以及 baseline symlink 祖先均不能取得目标元数据。

2026-10-04 Seed 新增手动一次性 Plugin 装载入口：可信 Launcher 通过系统 Picker 获取
package 文件夹，使用 `O_NOFOLLOW` 打开的 descriptor 读取有界 `manifest.json` 与
`plugin.py`，校验精确 Manifest schema、ABI、scope 和内容摘要。用户另选 workspace，
在可信弹窗中审阅 Plugin/Manifest digest、请求的读写范围、process 权限及本次
workspace invocation digest 后，才将捕获的源码送入隔离 Runner。单次操作完成后
Runner 退出，不建立持久 active slot。Manifest 仍只提出请求，不能自行授予能力；
这一路径不等于 Candidate 安装、激活、Trusted Promoter 或 rollback。示例 Plugin
在真实 Seatbelt 下通过 Kernel 写回，签名产品构建、深度签名和 headless XPC bootstrap
通过；截至 2026-10-04，双 Picker 的产品调用尚无交互式执行证据。
本次无 Picker 的 canonical suite 通过全部 250 项（485.373 秒），包含新 Plugin
示例的授权写回/空 scope 拒绝及元数据 alias 攻击；它不替代产品 UI 或模型对话验收。

**2026-10-05 signed two-Picker Plugin writeback：**用户在本机签名产品中选择
`examples/seed-writer` 与新建 workspace，并批准一次性运行。产品提示 Kernel 完成
1 个新增文件；随后 workspace 中的 `seed-plugin-output.txt` 内容为
`Khaos Seed plugin ran\n`，SHA-256 为
`92d9641b3613c290f07aa781c193a955b4b38386da79f74d5889710059d7effc`；产品运行进程
退出，`codesign --verify --deep --strict` 通过。这是一次实际的产品 UI → 已签名
Kernel XPC → Runner → changeset 校验与 Kernel 写回证据，不代表 Candidate admission、
持久激活或 Plugin 身份绑定授权。该运行的 Bash `stderr` 报告 `getcwd` 无法访问父目录；
Kernel 提交仍成功。之后源码为沙箱命令环境加入指向 private snapshot root 的可信 `PWD`，
并以一个真实 Seatbelt 回归验证 Bash 的逻辑 `pwd` 和 scope 拒绝保持正常；该源码修正
随后已重新打包为本机签名产品 `Khaos Seed vNext Agent 2026-10-05 current.app`，并复用
已固定摘要的 Qwen2.5-1.5B 模型。新包的深度签名和无 Picker XPC bootstrap 检查通过，包内
Kernel Python 源码包含该 `PWD` 设置；同一包的 `--agent` 经 launchd XPC 完成了一轮纯文本
响应并正常退出；简单算术请求返回 `Khaos: 2`。当前源码下的 focused 真实 Seatbelt
回归也通过（1 项）。
这次没有用新包重跑 Picker；此前截图只证明旧包的一次 Kernel 操作提交 1 个新增文件，仍带有
`getcwd` stderr，不能作为新包已消除交互告警的证据。

`workspace.commit` 现在由一次性可信子进程执行。它关闭从 Worker 继承的其他文件描述符，在完整 staging 和 live baseline 校验后固定 changeset 与随机临时项名称，再于写入前应用 Seatbelt。workspace 不再获得递归读写权限：读取权限只覆盖变化源文件、预生成的同目录临时项以及提交所需的目录路径；Seatbelt 的目录数据权限仍允许枚举这些直接目录中的名称，但未列入 scope 的兄弟文件内容和元数据不可读。新安装文件和普通文件临时项只在各自精确路径上获得写权限；已有项、待删除项、目录项及其直接父目录只获得精确路径上的 create/unlink 权限。读写 scope 合计超过 8192 条规则或生成文本超过 1 MiB 时，提交在首次 live mutation 前 fail closed。私有 staging 根仍由提交子进程完整读写以便校验和清理，结果管道只返回变化计数。真实端到端 Seatbelt 测试确认嵌套目录中的新增、修改、删除文件、空目录和 symlink 仍可提交，并拒绝读取未变化兄弟文件的内容和元数据、经待删除 symlink 读取 workspace 外 canary、写入未变化兄弟项、直接写入被替换文件及修改父目录权限；外部 canary 保持原值。另一项真实攻击测试在提交子进程打开并验证嵌套父目录后，由独立同 UID 写者将该目录移出 workspace，再让提交子进程通过旧目录描述符执行 APFS swap。Seatbelt 拒绝了该越界 swap，移出目录中的目标文件保持原内容；已准备的临时替换项不能在移出目录清理，因此 Broker 返回 `commit_outcome_uncertain`。这些结果只证明所测读写集合和目录移出窗口受 OS 限制，不提供对其他同 UID 写者的全局仲裁，也不把多文件写回变成事务。
**开发 ABI v4 的读取 scope：**可信 Launcher 可为 Kernel-mediated `fs.read` / `fs.list`
提供有界 workspace-relative scope；默认 deny-all，目录祖先枚举会过滤未授权条目。该 scope
同时限制固定 `process.exec` 命令的 OS 文件读取规则。Kernel 只对 baseline 中的普通文件
和目录生成精确或 subtree 规则；缺失路径、symlink 及 symlink / 非目录祖先不获得命令读取权。
真实 macOS 集成攻击确认：空 scope 下 Runner 和固定命令都不能读取 snapshot canary；授权文件与目录
可读，未授权兄弟文件、scope 内指向未授权内容的 symlink，以及被替换为 symlink 的授权文件均被
Seatbelt 拒绝。测试还尝试把未授权 canary hardlink 到授权目录；OS 拒绝建立链接时通过，若链接可建，
则要求别名读取仍被拒绝。该 scope 仍不构成 Plugin identity-bound approval。

命令可以写 private snapshot，因此读权限还需抵御路径移动：Seatbelt 在 snapshot write allow
之后拒绝 `file-write-unlink` 对未授权 baseline 文件/子树的匹配，并保护精确文件 scope 的目录祖先
不被移动；空 scope 拒绝 snapshot 内全部 baseline 项的 unlink/move。创建和文件数据写仍只作用于
private snapshot。真实攻击尝试 `os.replace`、APFS `RENAME_SWAP`、移动父目录后再把 canary 放进
scope，以及本机 APFS 会解析的大小写和 Unicode 规范化别名。规则数量或文本字节超限时命令 sandbox
fail closed。该测试只证明这些当前主机上的 Seatbelt 路径；不代表任意 OS 或文件系统的语义相同。

**macOS Worker 的进程附加防护：**Worker 在接受 IPC 前调用 `PT_DENY_ATTACH`，若 OS
拒绝该设置则不启动。真实 Seatbelt Runner 攻击测试确认：对 Worker 发起 `PT_ATTACHEXC`
会使攻击 Runner 收到 `SIGSEGV`，Worker 返回 `runner_failed`，snapshot 输出未写回；尝试
`task_for_pid`、`task_read_for_pid` 和 `task_inspect_for_pid` 均未取得 Worker task port，
Runner 随后仍可完成受限命令与提交。此证据只覆盖当前 macOS 主机和所测进程附加路径，
不证明 Kernel 安装不可篡改，也不替代 Runner 的 Seatbelt 限制。

**项目定位：Local-first / Single-user / Self-Evolving Agent**  
**核心架构：Immutable Security Microkernel + Evolvable Plugin Harness**

---

# 1. 项目定义

Khaos 是一个运行在**不可变本地安全微内核**之上的**可自进化 Agent Harness**。

Khaos 不追求成为一个大型 Agent 平台，也不承担云端、多租户、远程调度、企业审计、分布式执行等基础设施职责。

Khaos 的核心目标只有两个：

1. 让 Agent 可以自由地改进自己的能力。
2. 无论 Agent 如何进化，都不能绕过固定的安全边界。

一句话定义：

> **Khaos is an evolvable local agent harness running above an immutable security microkernel.**

中文：

> **Khaos 是运行在不可变安全微内核之上的自进化本地 Agent Harness。**

Khaos 的核心设计原则是：

> **Intelligence may evolve. Authority may not.**

即：

> **智能可以进化，权力不能自我扩张。**

本文件同时包含三类内容，后续实现时必须区分：

```text
Normative     必须满足的安全不变量和接口约束
Milestone     当前阶段的实现范围和验收标准
Vision        未来可能实现的自进化能力
```

Vision 中描述的能力不能被当作当前已有能力，也不能反过来放宽 Normative 约束。

---

# 2. 为什么重新开发

旧版 Khaos 最初以“本地安全机制对标成熟 Coding Agent”为目标，但随着开发逐渐加入：

- TaskManager
- Scheduler
- Runtime Authority
- Verification Pipeline
- Completion Gate
- Recovery Control Plane
- Durable Ledger
- Supply-chain Attestation
- Gateway
- RPC
- Browser Runtime
- Subagent
- 多模型 Routing
- Memory Framework
- 多平台 Production Trust

最终 Khaos 从一个本地 Agent 演变成了一个复杂的 Agent Runtime Platform。

这与新的产品目标已经不一致。

Khaos vNext 不从旧项目直接重构。

旧 Khaos 作为：

> **Reference Implementation / Engineering Knowledge Base**

保留在 GitHub。

新 Khaos 从空仓库重新开始。

迁移原则：

> **Do not migrate architecture. Migrate knowledge.**

不要迁移旧架构。

只迁移经过验证的工程经验、安全不变量和真正有价值的实现。

---

# 3. 产品假设

Khaos vNext 的运行环境非常明确：

```text
一个用户
一台本地电脑
一个本地 Agent
用户主动启动
用户拥有机器
用户可信
```

因此 Khaos 不为以下场景设计：

```text
多租户
SaaS
远程执行平台
跨组织权限
企业 RBAC
服务端大规模部署
分布式 Scheduler
云端 Control Plane
跨用户隔离
长期驻留服务器
复杂合规审计
```

如果未来确实需要这些能力，应当通过独立项目或插件实现，而不能污染 Khaos Core。

---

# 4. Threat Model

Khaos 的信任模型非常简单。

## 4.1 可信

默认可信：

```text
用户
Khaos Security Microkernel
Khaos trusted launcher / promoter
操作系统本身
```

## 4.2 不完全可信

以下全部视为潜在不可信代码：

```text
LLM
Agent Harness
Plugin
Memory Plugin
Tool Plugin
Planner Plugin
Context Plugin
Verifier Plugin
Evolver Plugin
Agent 自动生成的代码
第三方插件
项目仓库代码
项目中的 README / AGENTS.md / Prompt Injection
npm / pip / cargo 等依赖脚本
```

即使插件来自 Khaos 官方，也按照同样的安全模型处理。

## 4.3 Threat model 的边界

Single-user 不等于 Agent trusted。用户拥有机器，只说明用户可以最终授权；不说明
LLM、Host、Plugin 或由它们生成的代码可以直接获得宿主机权限。

如果使用远程模型，模型提供商和模型 API 也属于外部数据接收方。发送到模型的内容
必须经过独立的数据边界控制，不能因为“模型适配器是 Host 的一部分”就自动获得
workspace、secret 或 Plugin storage 的读取权。

以下能力不属于第一版的默认保证范围：

```text
防御操作系统内核、固件或已获得同等宿主权限的恶意用户
防止用户在 Full Access 下主动批准的操作
把远程模型提供商当作可信存储
仅靠提示词、命令黑名单或 Python 模块边界实现隔离
```

## 4.4 主要威胁

Khaos 只重点解决以下问题：

### Agent 误操作

例如：

```bash
rm -rf ..
git reset --hard
git push --force
```

### Prompt Injection

项目中的内容可能诱导 Agent：

```text
读取 ~/.ssh
读取 ~/.aws
读取 .env
上传用户文件
关闭安全限制
```

### 恶意仓库代码

Agent 执行：

```bash
npm install
pip install .
pytest
make
cargo test
```

时，项目代码本身可能执行恶意行为。

### 恶意或错误 Plugin

Plugin 可能：

```text
访问不属于自己的文件
偷偷联网
读取凭据
启动异常进程
无限占用资源
试图修改 Security Kernel
```

---

# 5. 核心架构

Khaos vNext 只存在两个主要世界：

```text
                     Evolvable World

                ┌─────────────────┐
                │       LLM       │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │  Agent Harness  │
                └────────┬────────┘
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
       ▼                 ▼                 ▼
    Memory            Context           Planner
    Plugin            Plugin            Plugin
       │                 │                 │
       ├─────────┬───────┴───────┬─────────┤
       ▼         ▼               ▼         ▼
     Tools     Skills         Verifier   Evolver

────────────────────────────────────────────────
                 Security Boundary
────────────────────────────────────────────────

                ┌─────────────────┐
                │ Security Kernel │
                │    IMMUTABLE    │
                └────────┬────────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
       Filesystem     Process       Network
                         │
                         ▼
                         OS
```

上层：

> 可以替换，可以删除，可以重写，可以进化。

下层：

> 固定、可信、简单、确定性。

## 5.1 真实安全边界

上图中的分层不是安全边界本身。Khaos vNext 采用以下强制拓扑：

```text
Untrusted LLM / Agent Host
            │  versioned IPC only
            ▼
Trusted Kernel Broker + Trusted Promoter
            │
            ▼
OS-enforced sandboxed process / filesystem / network
```

具体规则：

1. `Kernel` 必须运行在与不可信 Host、Plugin 不同的 OS 进程中。Kernel 的实现不能
   作为一个可被不可信代码直接导入和修改的普通 Python 模块提供。
2. Plugin 必须运行在独立的 Runner 进程中。Plugin SDK 中的对象只是 IPC 客户端
   facade，不是安全边界。
3. 所有文件、进程、网络和 secret 副作用必须由 Kernel Broker 代为执行；Host 或
   Plugin 不能因为拿到了对象引用、模块路径或环境变量而绕过 Broker。
4. Kernel 按 Plugin 实例发放最小 capability handle。不存在对所有资源都有效的
   `kernel` 万能对象；Manifest 只能申请权限，不能授予权限。
5. Kernel 的安装文件、Trusted Promoter 和审批记录必须位于 workspace、Candidate
   和普通 Plugin storage 之外。更新 Kernel 必须由用户或独立的 trusted launcher
   显式执行。
6. IPC 通道必须使用 OS peer identity、一次性 nonce 或等价的不可伪造绑定；Kernel
   不能只相信消息体里的 `plugin_instance_id` 或 `capability handle` 字符串。

---

# 6. Khaos 的三个基础组件

整个系统只需要三个核心概念：

```text
khaos-kernel
khaos-host
khaos-plugins
```

---

# 7. Khaos Kernel

`khaos-kernel` 是整个系统的 Trusted Computing Base，并以独立的 Kernel Broker
进程运行。它不是由不可信 Host 直接 import 的普通库。

Kernel 不负责智能。

Kernel 不知道：

```text
Memory
Planner
Prompt
Context
Task
Subagent
Verification
Evolution strategy
```

Kernel 只负责：

> **限制 Agent 拥有什么能力。**

为了执行这个职责，Kernel 可以知道以下安全元数据，但不能理解其中的智能语义：

```text
Plugin / process identity
capability grant
resource scope
user approval record
operation quota
```

Kernel 必须保持：

```text
deterministic
small
auditable
boring
stable
non-self-modifying
```

安全层越“聪明”，风险越大。

---

# 8. Kernel 职责

第一版 Kernel 只负责六件事情。

## 8.1 Filesystem Boundary

默认：

```text
workspace:
    read/write

outside workspace:
    deny
```

Plugin 不能直接拥有宿主文件系统权限。

所有文件操作必须经过 Kernel API。

例如：

```text
kernel.fs.read()
kernel.fs.write()
kernel.fs.list()
kernel.fs.stat()
```

Kernel 必须处理：

```text
path traversal
symlink escape
TOCTOU
unsafe rename
atomic write
workspace escape
```

这些不是“路径检查通过即可”的功能要求，而是必须由 OS 文件描述符、受控目录
句柄或等价机制实现的安全契约。实现至少需要明确：symlink、hardlink、mount、
特殊文件、大小写不敏感文件系统、Unicode 规范化、rename race 和 TOCTOU 的策略。
如果某个平台无法提供同等保证，Kernel 必须拒绝启动对应能力。

当前开发 ABI 提供相对 snapshot root 的 `fs.read(path)`、`fs.list(path)` 和
精确路径 `fs.write(path, bytes)`。Kernel 使用 directory descriptor-relative lookup 和 no-follow open；
`fs.read` 只返回单链接 regular file，禁止绝对路径、`.`、`..` 和 symlink 路径分量。
`fs.list` 不跟随 symlink，只返回其 `symlink` 类型，不返回 target。单次读取上限为
32 KiB；单次目录列表最多 128 项、文件名 UTF-8 编码总量最多 4 KiB；一次 Runner
执行在 `process.exec` 前最多请求 128 次文件系统操作。不能编码为严格 UTF-8 的目录项
会在扫描时被拒绝，不通过替换字符或转义别名暴露。输出受 IPC frame 上限约束并视为
不可信输入。它们只适用于 trusted launcher 绑定的 workspace snapshot；这不是任意
文件系统访问，也不等于向远程模型发送数据已获授权。

读取 scope 按路径分量的原始 Unicode 拼写精确匹配，不做 NFC/NFD 规范化或大小写折叠。
调用方应使用 `fs.list` 返回的文件名；任何不同拼写即使在底层文件系统上解析为同一项，
也必须在文件查找前被 scope 检查拒绝，不能因此扩大读取权限。

开发 ABI 的 `fs.write` scope 是独立的精确文件路径集合，默认 deny-all，不允许目录
或其后代。Kernel 只在 private snapshot 中通过 descriptor-relative、no-follow 路径写入，
拒绝 symlink、hardlink、特殊文件和超出 32 KiB 的数据；成功写入仍须经过后续完整
changeset 验证，才能由可信 commit 路径应用到所选 workspace。这是当前开发路径，不是
产品 Launcher 的用户授权流程，也不授予 Runner 对 live workspace 的直接 OS 写权限。

旧 Khaos `SafeWorkspaceFS` 中验证过的安全思想可以迁移。

但应重新实现，而不是复制旧架构。

---

## 8.2 Process Boundary

所有 shell/process 执行必须通过：

```text
kernel.exec()
```

负责：

```text
spawn
timeout
cancel
kill process tree
cwd boundary
environment filtering
resource limits
output limits
```

Plugin 不允许直接：

```python
subprocess.Popen(...)
os.system(...)
```

---

## 8.3 OS Sandbox

Kernel 根据平台执行真实 OS 隔离。

目标：

```text
macOS
    Seatbelt / sandbox-exec compatible backend

Linux
    bubblewrap / namespace based backend

Windows
    后续提供 native sandbox backend
```

上述名称只是 backend category，不是实现承诺。每个受支持平台必须记录具体的
profile、entitlement、namespace 或其他 OS 约束，以及它们覆盖的资源范围；没有
对应证据的 backend 不能被标记为 production-ready。

Sandbox 是安全边界。

Command blacklist 不是安全边界。

即：

```text
OS enforcement > command filtering
```

“支持某种 backend”不等于“已经完成隔离”。每个平台必须有可执行的启动自检和
攻击性测试，证明进程确实受到文件、进程、网络和资源策略约束。Sandbox backend
不可用、检测失败或能力不完整时，必须 fail closed；不得退化为 Host 执行。

---

## 8.4 Network Boundary

第一版只需要非常简单的网络策略：

```text
deny
allow
allow-list
```

默认建议：

```text
network = deny
```

Plugin 如果需要网络：

```text
Plugin Manifest
    ↓
declare NETWORK capability
    ↓
Kernel
    ↓
用户允许
```

Network grant 必须绑定到具体 Plugin 实例和具体范围，而不是一个全局的
`NETWORK = true` 开关。范围至少要定义 protocol、host/IP、port、DNS、IPv4/IPv6、
redirect、proxy、localhost 和 Unix socket 的处理方式。默认网络拒绝也必须覆盖
子进程和通过代理、DNS rebinding 等方式产生的间接连接。

---

## 8.5 Secret Boundary

Plugin 默认看不到完整 Host 环境。

Kernel 必须避免自动继承：

```text
AWS credentials
SSH keys
GitHub tokens
API keys
Cloud credentials
敏感 environment variables
```

只有显式授权后才能提供给 Plugin。

Secret 不得通过环境变量、argv、继承的文件描述符、日志、错误信息或子进程继承
链路隐式泄漏。Secret grant 必须是一次性的、带范围的，并且不能自动转化为网络
权限。远程模型也不应默认获得 Secret；如果确实需要，必须单独显示数据范围和
用户批准。

---

## 8.6 Approval / Escape Hatch

安全模式保持极少。

建议只有：

```text
Workspace
Full Access
```

可选增加：

```text
Read Only
```

即：

```text
ReadOnly
Workspace
FullAccess
```

Approval 只需要：

```text
Deny
AllowOnce
AllowSession
```

不要重新设计复杂 Permission Framework。

但“简单”不等于无记录。每一次会改变权限或激活 Plugin 的批准至少需要持久化：

```text
target plugin id
proposal digest or candidate / manifest digest
requested capability set
resource scope
approval kind and expiry
session or operation binding
```

Kernel 或 Trusted Promoter 必须重新验证这些字段。LLM、Host 或 Plugin 传入的
`approved: true` 不能作为用户批准的证据。

批准界面或 CLI 必须显示目标、digest、权限范围、数据范围、有效期和回滚影响。
模型生成的文本不能伪装成批准界面，也不能通过普通 Event Bus 注入批准结果；如果
TUI 本身不在 TCB，最终批准仍必须由 Trusted launcher / Broker 验证。

---

# 9. Security Kernel 永远不能做什么

Kernel 永远不能：

```text
调用 LLM
读取 Prompt 并做推理
决定 Planning Strategy
实现 Memory
实现 Skill
实现 Context Compression
选择模型
运行 Reflection
自行修改代码
自动提升自己的权限
```

Kernel 是“权力管理器”，不是 Agent。

---

# 10. Khaos Host

Host 是非常薄的一层。

它负责：

```text
Agent Loop
Model Adapter
Session
Event Bus
Plugin Host
Plugin Registry
Plugin Lifecycle
Plugin Promotion
```

Host 不应该拥有复杂业务能力。

Host 是编排层，不是可信授权层。`Plugin Registry` 只能保存发现、版本和 proposal
信息；`Plugin Promotion` 只能向 Trusted Promoter 提交请求，不能直接替换 active
slot、发放 capability 或解释用户批准。

Host 本身应该尽可能接近：

```text
Model
  ↓
AgentLoop
  ↓
Plugin
  ↓
Kernel
```

---

# 11. Agent Loop

AgentLoop 必须保持小。

目标：

```text
几百行
```

而不是几千行。

伪代码：

```python
while session.running:

    context = plugins.context.build(session)

    response = model.generate(context)

    if response.is_text:
        session.append(response)

    if response.has_tool_calls:
        for call in response.tool_calls:
            request = host.validate_tool_call(call)
            decision = trusted_broker.authorize(request, session.policy)
            if decision.denied:
                session.append(decision.reason)
                continue
            result = plugins.tools.execute(request, decision.grant)
            session.append(result)

    if response.finished:
        break
```

AgentLoop 不应该知道：

```text
Memory 实现
Planner 实现
Sandbox backend
Verification pipeline
Subagent runtime
Database schema
Plugin 内部状态
```

AgentLoop 也不能把模型输出当作授权。模型只能提出 Tool request；请求必须经过
工具 schema 校验、session policy、用户批准和 Kernel capability 检查。任何一个
环节失败都应拒绝该调用，而不是尝试 Host fallback。

## 11.1 Data Flow Boundary

Capability 不仅限制副作用，也必须限制数据读取和数据转发。Event Bus、Session
和 Config 不能默认对所有 Plugin 广播。

第一版至少区分：

```text
control data     Plugin identity、状态、审批和错误
workspace data   文件内容、命令输出和测试结果
memory data      CanonicalMemory 记录
secret data      凭据、token、私钥和敏感环境变量
model data       将要发送给本地或远程模型的内容
```

规则：

1. Event topic 必须显式声明读者和字段范围；未声明的订阅默认拒绝。
   如果 Event Bus 由不可信 Host 实现，过滤必须在 Kernel/Trusted IPC 边界再次执行，
   不能只依赖 Host 的路由代码。
2. Secret 不得进入普通 session、Memory、日志或 Shadow Evaluation 输入。
3. Model Adapter 只能发送经过 data-scope 检查的内容；远程模型是外部接收方，
   不能自动读取完整 workspace。
4. 一个有网络能力的 Plugin 不得通过 Event Bus 间接读取另一个 Plugin 的私有
   storage。跨 Plugin 数据交换必须由 Host/Kernel 按 schema 和范围授权。
5. Tool output、错误信息和 benchmark 必须支持脱敏，避免把权限边界变成数据
   外传通道。

---

# 12. Harness = Plugin Graph

Khaos Harness 不再是一套固定能力。

Harness 本质定义为：

> **Plugin Graph + Configuration**

例如：

```yaml
harness:
  version: 17

plugins:

  memory:
    semantic-memory: 3.1

  context:
    adaptive-context: 2.0

  planner:
    react-planner: 1.2

  tools:
    filesystem: 1.0
    shell: 1.0

  verifier:
    test-verifier: 1.4

  evolver:
    default-evolver: 2.1
```

因此不同插件组合就是不同 Harness。

---

# 13. Plugin 类型

Khaos 不应该对 Plugin 类型做太强限制。

第一版可以约定：

```text
tool
memory
context
planner
verifier
model
strategy
skill
evolver
```

这些只是 capability category。

未来允许新增类别，而不修改 Kernel。

---

# 14. Plugin ABI

Plugin ABI 是整个 Khaos 架构中第二重要的稳定边界。

最小接口可以类似：

```python
class Plugin:

    def manifest(self) -> Manifest:
        ...

    async def start(self, ctx: PluginContext):
        ...

    async def stop(self):
        ...
```

`manifest()` 只是 SDK 便利接口，不能作为启动时的权限来源。Trusted admission
runtime 必须在启动 Plugin 代码前读取并锁定包内 Manifest 和 content digest；运行中
Plugin 返回的 Manifest 与已批准版本不一致时，必须拒绝启动或立即停用。

PluginContext 只暴露经过范围限制的 SDK facade：

```text
scoped_capabilities
topic_scoped_events
read_only_session_view
non_secret_config
virtual_plugin_storage
```

不要暴露 Host 内部对象、原始 session、原始 config、任意文件描述符或万能
`kernel` 对象。每一个 facade 调用最终都必须转换成带 Plugin identity 和
capability grant 的 Kernel IPC request。

## 14.1 Wire ABI 和 Plugin Runner

上面的 Python 接口只是 SDK 的编程体验，不是跨信任边界的 ABI。真正的 ABI 必须
是有版本、有长度限制、有超时和有结构化错误的序列化消息协议。

第一版至少需要定义：

```text
request id / plugin instance id
operation name and schema version
capability handle
resource scope
deadline and cancellation
bounded input/output
structured error
```

Plugin Runner 必须与 Host、Kernel 分进程运行。Runner 崩溃只能使该 Plugin
失败，不能使 Kernel 或其他 Plugin 取得它的文件描述符、secret 或状态。

当前开发 ABI v6 的精确请求顺序、字段、错误码和字节上限记录在
`docs/KERNEL_ABI.md`。该契约不包含尚未实现的 Plugin identity、capability handle、
用户 approval 或 Plugin admission。开发 launcher 可为 Kernel 的 `fs.read` / `fs.list` 设置默认 deny-all 的相对路径
read scope，并为 `fs.write` 设置独立的默认 deny-all 精确文件路径 scope；Runner
不能更改这些 scope。`fs.write` 只写入 private snapshot，不直接修改 live workspace；
产品 Launcher 的固定 smoke source 现已使用它。用户报告重新打开 Picker、选择
`khaos-seed-app-3mfj1nf_` workspace 并看到 `PASS`；该弹窗只在 scoped read/list、scope
释放后的 OS 拒绝、Runner write allow/deny、Kernel 写回和 Launcher 直写拒绝后出现。
临时 app/workspace 与测试父进程结果已不可用，因此这次报告不能独立绑定到 bundle digest，
也不能证明该次的 post-alert deep-signature assertion。它不是用户 approval 或 Plugin-bound grant。目录 scope
由命令的 Seatbelt profile 限制到 snapshot 中对应的子树，symlink 和缺失路径不获得读取规则。
`workspace_write_scope` 是 trusted launcher 保留的 workspace-relative 精确路径集合。它限制
Runner SDK `fs.write`，也约束 Kernel commit 的完整 changeset：每个新增、修改或删除的文件、
目录或其他允许类型路径都必须精确列入 scope，不能用目录项授权后代；空 scope 拒绝任何非空
changeset。命令仍可在 private snapshot 内生成任意内容，但有任一路径未获授权时，Kernel 在
开始任何 live mutation 前拒绝整个 changeset。创建目录树时必须显式列出每一个新增目录和文件，
删除目录树时必须显式列出每个被删除项。

Seatbelt 还拒绝移动 read scope 外的 baseline 文件/子树及精确文件 scope 的父目录；命令因此不能
删除/重命名这些项，也不能借路径替换扩大读取权限。Runner 与命令均不能直接写 live workspace 或
snapshot 之外的路径；Kernel 将整个 snapshot diff 当作不可信输入重新验证，并只在所选 root 中提交。
`process.exec` 请求包含 Runner 选出的有界 `argv`；Kernel 重新验证 argv，并固定 timeout、
private snapshot cwd、净化环境、workspace read scope 与 Seatbelt policy。该操作由当前
trusted workspace session 隐式启用，尚无 Plugin identity-bound grant 或生产授权模型。

ABI v6 的开发 Runner 在完成 Kernel peer 验证后接收一个不超过 10 KiB 的 `plugin.start`
source frame，并在自身 Seatbelt 进程中执行其 `run()` entrypoint。Python `exec` 仅负责
加载代码，不能作为隔离边界；此路径尚无 Candidate content/Manifest digest 锁定、用户
activation approval 或按 Plugin scope 发放 capability。

---

# 15. Plugin Manifest

每个 Plugin 都必须声明 Manifest。

例如：

```yaml
id: semantic-memory
version: 2.1.0
api_version: 1

kind: memory

permissions:

  filesystem:
    read:
      - plugin-data/**
    write:
      - plugin-data/**

  process: false
  network: false
  secrets: []

capabilities:
  - memory.store
  - memory.recall
```

Manifest 只是声明。

真正权限由 Kernel 决定。

Plugin 不能通过 Manifest 自己获得权限。

Manifest 必须经过严格解析：未知字段、模糊的路径模式、未声明的 entrypoint、
不受支持的 ABI 版本和超出平台能力的权限都应拒绝。权限判断必须绑定到安装包
内容 digest，而不能只相信 `id` 和 `version`。

Manifest 中的 `filesystem`、`process`、`network` 和 `secrets` 均是请求，不是
授权结果。授权结果由 Kernel 根据默认策略、用户批准、平台能力和本次操作的
resource scope 计算。

---

# 16. Plugin 不能直接访问 OS

这是 Khaos 最重要的不变量之一。

禁止：

```text
Plugin
  ↓
OS
```

必须：

```text
Plugin
  ↓
Kernel ABI
  ↓
OS
```

即使 Memory Plugin 只是读一个 JSON：

```text
memory plugin
      ↓
kernel.fs
      ↓
filesystem
```

即使 Tool Plugin 要执行 git：

```text
git plugin
      ↓
kernel.exec
      ↓
sandbox
      ↓
git
```

这使得：

> **可进化代码永远不等于可信代码。**

---

# 17. Plugin State

Core 不应该拥有插件数据库 schema。

原则：

> **Plugin owns its state.**

例如：

```text
~/.khaos/plugins/
    semantic-memory/
        data/
        config.json

    adaptive-context/
        data/
```

Kernel 只负责限制 Plugin 能访问自己的 storage。

Plugin storage 不是任意的 `~/.khaos` 路径。它必须由 Kernel 分配为一个不可逃逸的
virtual root；Plugin 不能通过相对路径、symlink、hardlink 或 rename 访问其他
Plugin、Candidate、Kernel 安装目录或用户 home 的其他内容。

Core 不拥有 Plugin 的业务数据 schema，但必须拥有极小的、不可绕过的激活元数据：

```text
plugin id / content digest / manifest digest
installed version and ABI version
active slot / previous slot
approval binding / activation timestamp
crash and rollback marker
```

这些元数据需要 crash-safe、原子更新和单实例锁；它们不是 Plugin 业务数据库，
而是安全边界的一部分。

不要再出现：

```text
Core migration:
0037_memory_x
0038_planner_y
0039_verifier_z
```

插件升级自行处理数据迁移，但迁移不能自动获得额外 filesystem、process、network
或 secret 权限。迁移失败时，系统必须保留旧数据和旧版本，并把状态标记为不可
激活，而不是只切换一个 active 字段后继续运行。

---

# 18. Plugin Lifecycle

生命周期保持极简：

```text
installed
enabled
disabled
failed
```

上述是用户可见的主状态，不代表内部可以省略安全状态。安装和激活至少要能
区分以下不可混淆的角色：

```text
candidate     已生成但未激活
shadow        只读评估中的版本
active        当前接收生产请求的版本
previous      可回滚的旧版本
pending       等待用户批准或等待测试
incompatible  ABI、平台或数据迁移不兼容
```

这些角色应由 Core 激活元数据表达，而不是让不可信 Plugin 自己修改。所有状态
转换必须有明确的前置条件、持久化顺序和崩溃恢复行为。

不要重新出现：

```text
DISCOVERED
VALIDATED
AVAILABLE
DEGRADED
DRAINING
QUARANTINED
...
```

除非未来真实需求证明有必要。

---

# 19. Plugin Swap

插件替换是 Khaos 自进化的核心机制。

例如当前：

```text
memory-v1
```

Agent 发现：

```text
retrieval quality poor
token consumption high
important memories often missed
```

Agent 不修改 Core。

而是提出：

```text
replace memory-v1 with memory-v2
```

流程：

```text
Current Plugin
      │
      ▼
Observation
      │
      ▼
Proposal
      │
      ▼
User Approval
      │
      ▼
Generate Candidate
      │
      ▼
Sandbox Build/Test
      │
      ▼
Evaluation
      │
      ▼
Activation Approval
      │
      ▼
Switch Plugin
      │
      ▼
Keep Old Version
      │
      ▼
Rollback Possible
```

---

# 20. 自进化的定义

Khaos 的“自进化”不是：

> Agent 无限修改自己的源代码。

Khaos 的自进化定义为：

> **Agent 根据自身运行经验发现能力缺陷，通过生成、修改、评估和替换 Plugin，使 Harness 逐渐发生变化。**

进化单位：

> **Plugin**

而不是：

> source file。

---

# 21. Evolution Loop

Khaos 的 evolution 不需要复杂 framework。

核心只有：

```text
Observe
Reflect
Propose
Build
Evaluate
Adopt
```

即：

```text
执行任务
   ↓
观察问题
   ↓
分析原因
   ↓
提出插件改进
   ↓
生成 candidate
   ↓
测试
   ↓
评估
   ↓
用户批准
   ↓
替换
```

---

# 22. Evolution 必须由真实证据触发

Agent 不应该频繁随意重写插件。

建议要求至少满足以下一种：

```text
重复失败
用户明确反馈
可测量性能问题
插件异常
明显 token 浪费
检索质量问题
工作流重复低效
已有 benchmark 显示退化
```

例如：

```text
Observation:
memory plugin frequently returns irrelevant results.

Evidence:
8 of the last 12 recall operations were unused.

Proposal:
Build a recency-aware memory plugin.
```

Evidence 必须来自 Host/Kernel 记录的可追溯事件，而不能只由待评估 Plugin 自报。
至少要保存样本范围、基线版本、指标定义、失败样本和统计阈值；涉及 workspace
或 Memory 内容时，应保存脱敏后的引用或摘要，而不是把原始敏感数据复制到
Evolution 日志。

---

# 23. 用户必须拥有最终决定权

Khaos 可以：

```text
发现问题
提出方案
编写插件
运行测试
生成 benchmark
推荐替换
```

但不能在没有用户授权的情况下自动：

```text
安装高权限插件
扩大 capability
替换安全相关组件
修改 Security Kernel
启用新的网络权限
读取新的敏感目录
```

开发批准发生在 Candidate 生成之前，因此绑定 proposal digest、生成范围、资源
预算和允许申请的 capability 上限；它不能直接授权激活。激活批准必须绑定到不可变
的 Candidate 内容 digest、完整 Manifest digest、目标 Plugin slot 和具体 capability
scope。Candidate 在批准后发生任何内容或权限变化，都必须重新批准。批准不能由
LLM、Host 或 Plugin 通过一个布尔值伪造。

---

# 24. 两阶段授权

对于 Agent 自己生成的新插件，必须有两次用户确认。

第一次：

> 是否允许开发这个 Candidate？

第二次：

> 是否允许激活这个 Candidate？

原因：

```text
写代码
```

和：

```text
让代码成为自己的一部分
```

是两个不同风险等级。

---

# 25. Candidate Area

Agent 生成的插件永远先进入：

```text
~/.khaos/candidates/
```

例如：

```text
~/.khaos/candidates/
    semantic-memory-v2/
```

Candidate 权限应比正式 Plugin 更低。

Candidate 不应该自动进入生产 Harness。

`~/.khaos/candidates/` 是 Kernel 管理的特殊根，不是对用户 home 的一般访问授权。
它必须通过 virtual root 暴露给 Candidate，并与以下区域隔离：

```text
workspace
active Plugin storage
other Candidate storage
Kernel installation
user home and secrets
```

Candidate 的构建、依赖安装和测试全部按不可信代码执行：默认无网络、无 secret、
无生产写入，并受独立的 CPU、内存、PID、磁盘、文件描述符和输出限制约束。

---

# 26. Shadow Evaluation

允许 Candidate 与当前 Plugin 并行评估，但 Candidate 不得接收生产写入。

例如：

```text
          Recorded Input / Read-only Snapshot
                         │
                  ┌──────┴──────┐
                  ▼             ▼
              memory-v1      memory-v2
               active         shadow
```

正常结果仍来自：

```text
memory-v1
```

但系统同时记录：

```text
v1 result
v2 result
latency
token usage
relevance
task outcome
```

第一版 Shadow Evaluation 应优先使用历史事件 replay 或只读快照。它必须有独立的
state、资源预算和固定的评估数据集；不得让 Candidate 修改 active 数据、产生
外部副作用或自行写入评估指标。评估结果应记录样本数、基线、置信度和回归阈值，
否则“更好”只是不可复现的主观判断。

当 v2 有足够证据更好时：

```text
propose activation
```

---

# 27. Rollback

任何 Plugin activation 都必须保留旧版本。

例如：

```text
memory-v1
    ↓
memory-v2
```

至少保留：

```text
active:
    memory-v2

previous:
    memory-v1
```

如果新插件：

```text
crash
性能退化
产生异常输出
破坏数据
```

可以：

```text
rollback → memory-v1
```

Rollback 首先保证的是后续请求重新路由到旧版本，不自动声称能够撤销已经发生的
外部副作用或修复已损坏的数据。要支持数据级回滚，必须同时保留兼容的 canonical
snapshot 或可验证的 migration backup。激活过程必须在 session 边界执行，并通过
原子 slot 切换、旧版本保留和启动恢复来处理崩溃；第一版不支持运行中热替换。

---

# 28. Memory Plugin

Memory 是第一个最适合用于验证 Khaos 自进化思想的 Plugin。

第一版不要重新实现复杂 Memory Framework。

只做：

```text
memory-simple
```

例如：

```text
memory.md
```

或者：

```text
SQLite key/value
```

接口：

```python
remember(item)

recall(query)

forget(id)

export()

import(data)
```

---

# 29. Canonical Data Format

插件可以替换，所以数据不能永久绑定插件。

例如 Memory 应定义：

```text
CanonicalMemory
```

Memory Plugin 至少支持：

```text
export canonical format
import canonical format
```

Canonical format 不能只是一个未定义的 JSON 或 key/value 集合。它至少要定义：

```text
format version and compatibility rule
stable item id and timestamps
provenance / source task
data classification and secret handling
deletion / forget semantics
deterministic serialization
size and nesting limits
```

Export 和 import 都是数据边界操作。Candidate 默认只能读取经过脱敏和范围限制的
canonical snapshot，不能借此取得全部历史记录、secret 或其他 Plugin 的私有状态。

这样：

```text
memory-v1
   ↓ export
canonical memory
   ↓ import
memory-v2
```

避免 Plugin lock-in。

---

# 30. 自进化层级

Khaos 可以逐渐支持四个层级。

## Level 1 — Memory Evolution

Agent 学习：

```text
项目命令
项目约定
用户偏好
失败经验
```

## Level 2 — Skill Evolution

Agent 形成：

```text
debug workflow
parser modification workflow
test workflow
release workflow
```

## Level 3 — Tool Evolution

Agent 自动创建：

```text
dependency graph tool
custom search tool
benchmark helper
project-specific command
```

## Level 4 — Harness Evolution

Agent 替换：

```text
context plugin
planner plugin
memory plugin
verification plugin
agent strategy
```

Security Kernel 始终不参与 evolution。

---

# 31. Evolution 本身也是 Plugin

重要原则：

> **Evolver 不应该成为不可替换 Core。**

例如：

```text
evolver-v1
```

未来可以被：

```text
evolver-v2
```

替换。

这意味着：

> Khaos 甚至可以改进“自己如何进化”。

真正不可变的只有：

```text
Security Kernel
Plugin ABI
极薄的可信 IPC / admission runtime
Trusted Promoter
```

普通 Agent Loop、Model Adapter、Event Bus 和 Plugin Registry 不自动属于 TCB。
只有负责验证身份、解析 ABI、转发受限请求和执行安全状态转换的最小代码才进入
TCB；其余 Host 代码即使位于同一仓库，也按不可信代码处理。

---

# 32. Trusted Promoter

Plugin 自己不能直接替换正在运行的自己。

应存在非常小的 Trusted Promoter。

流程：

```text
Harness
   ↓
Candidate B is better
   ↓
Evaluation result
   ↓
Trusted Promoter
   ↓
Switch A → B
```

Promoter 可以：

```text
activate
deactivate
rollback
```

但不负责判断 Plugin 是否聪明。

它只执行经过批准的状态转换，并必须独立验证：

```text
candidate content digest
manifest digest
ABI / platform compatibility
requested capability scope
user approval binding and expiry
current active slot
```

Harness 只能提交 proposal 和 evaluation result，不能提交一个未经验证的路径、
版本号或布尔值要求 Promoter 激活。Promoter 的激活、停用和 rollback 必须是
crash-safe 的原子状态转换。

---

# 33. Trusted Computing Base

Khaos TCB 应尽量小。

理想情况下只有：

```text
Security Kernel
Sandbox backend
Trusted IPC / Plugin admission runtime
Trusted Promoter
Plugin ABI validation
```

所有其它东西：

```text
Memory
Planner
Context
Tools
Skills
Verifier
Evolver
Model Routing
Subagent
Browser
```

都不属于 TCB。

---

# 34. 新项目不应该包含的东西

初期明确禁止加入：

```text
TaskManager
复杂 Task lifecycle
Scheduler
Cron
Subagent
Browser
Web UI Server
Go Gateway
RPC Server
multi-tenant identity
principal delegation
authorityd
signed execution receipts
WORM audit
Supply-chain attestation
CompletionGate
Recovery Control Plane
复杂 Verification Framework
复杂 Memory Framework
复杂 Model Router
企业权限系统
```

这些能力未来必须通过真实需求重新证明存在价值。

这里禁止的是面向网络或远程调度的 RPC Server，不是 Kernel Broker、Plugin Runner
和 Host 之间所必需的本地、版本化、受限 IPC。IPC 必须保持单机、不可被任意外部
客户端连接，并继续受到 Kernel 的身份和 capability 校验。

---

# 35. Tool System

第一版 Tool 越少越好。

建议只提供：

```text
read
write/edit
search
list
exec
```

甚至：

```text
read
write
edit
bash
```

即可。

以下不要专门实现 Tool：

```text
git
pytest
cargo
npm
markdown
todo
history
```

因为 Agent 可以通过 shell 完成。

`bash` 只是被 Kernel sandbox 包裹的一个不可信输入面，不是权限模型。所有执行
请求仍应先转换为结构化的 `argv / cwd / env allowlist / stdin / limits`，由 Kernel
决定是否允许；Shell 不得继承 Host 的完整环境、文件描述符、网络能力或 secret。
需要高风险操作时，不能用“命令不是黑名单”作为免审批理由。

只有当长期使用证明专用 Tool 明显优于 shell，才增加 Plugin。

---

# 36. 不再追求“所有东西结构化”

旧 Khaos 一个重要复杂度来源是：

> 每个行为都需要正式 domain object、repository、ledger、gate、state machine。

Khaos vNext 不这样做。

默认：

> Simple first.

只有真实 bug 或需求证明简单方案不够时，再增加结构。

该原则不适用于安全边界本身。Capability grant、用户批准、激活 slot、digest、
锁和崩溃恢复虽然是结构化状态，但它们是为了让安全约束可验证，而不是为了提前
建设业务框架。

---

# 37. Architecture Rule

每增加一个 abstraction，都必须回答：

```text
现在有几个真实使用者？
是否已有第二个实现？
没有这个 abstraction 会发生什么？
它解决的是现实问题还是未来想象？
```

如果答案只是：

> 以后可能方便。

不能加入 Core。

---

# 38. Complexity Budget

Khaos vNext 应主动设置复杂度预算。

理想目标：

```text
AgentLoop:
    < 500 LOC

Plugin Host:
    < 1000 LOC

Plugin SDK:
    < 1000 LOC

Kernel API:
    小而稳定

核心系统:
    一个人半天可以读懂
```

这不是绝对数字。

真正指标是：

> 一个开发者可以预测一次改动会影响哪里。

---

# 39. 新增 Tool 的理想体验

未来新增 Tool：

```text
plugins/my-tool/
    manifest.yaml
    plugin.py
```

然后：

```text
khaos plugin install ./plugins/my-tool
```

结束。

`plugin install` 必须先把输入目录复制为受控、content-addressed 的 Candidate，
解析并锁定 Manifest，完成无网络构建/测试和能力审查后才能进入 installed 状态。
不能在 Host 进程中直接 import `plugin.py`，也不能因为路径来自本地就信任其中的
安装脚本或依赖。

不应该修改：

```text
AgentLoop
RuntimeFactory
Scheduler
Database
PermissionEngine
TUI
```

---

# 40. 新增 Memory Plugin 的理想体验

```text
plugins/memory-vector/
    manifest.yaml
    memory.py
    tests/
```

实现统一 Memory ABI。

然后：

```text
khaos plugin install memory-vector
khaos plugin activate memory-vector
```

AgentLoop 不应该感知发生了变化。

---

# 41. 建议目录结构

第一版建议：

```text
khaos/
│
├── kernel/
│   ├── broker/
│   ├── fs/
│   ├── process/
│   ├── sandbox/
│   ├── network/
│   ├── secrets/
│   ├── capability/
│   └── approval/
│
├── host/
│   ├── agent/
│   ├── model/
│   ├── session/
│   ├── events/
│   ├── plugins/
│   └── ipc/
│
├── runner/
│   └── plugin/
│
├── trusted/
│   └── promoter/
│
├── sdk/
│   ├── plugin/
│   ├── manifest/
│   └── conformance/
│
├── plugins/
│   ├── filesystem/
│   ├── shell/
│   └── memory-simple/
│
├── tui/
│
├── tests/
│   ├── kernel/
│   ├── host/
│   ├── plugins/
│   └── security/
│
├── ARCHITECTURE.md
├── SECURITY.md
├── PLUGIN_ABI.md
├── EVOLUTION.md
└── README.md
```

目录可以以后调整，但边界不能改变。

其中 `host/agent`、Model Adapter、普通 Plugin Registry 和 `runner/plugin` 按不可信
代码处理；负责启动和验证 Runner 的 trusted admission runtime、`kernel/broker` 和
`trusted/promoter` 必须有明确的进程边界及最小 IPC 接口。目录分层本身不能替代
OS 隔离。

---

# 42. 依赖规则

必须严格执行：

```text
kernel
    imports nothing from host/plugins

host
    imports sdk + IPC client only

runner
    imports sdk + IPC client only

sdk
    must remain lightweight

plugins
    import sdk
    access OS only through scoped IPC capability facade
```

最重要的不变量：

> **Kernel never imports Harness.**

依赖图还必须区分信任级别：`host/agent`、Model Adapter、普通 Plugin Registry
按不可信代码处理；只有 Kernel Broker、Plugin admission runtime 和 Trusted
Promoter 属于 TCB。静态 import 检查不能替代进程隔离，但应作为额外的构建检查。

---

# 43. Security Invariants

必须长期保持以下规则。

## Invariant 1

```text
Plugin cannot bypass Kernel for side effects.
```

## Invariant 2

```text
Plugin cannot modify Security Kernel, including when Full Access is enabled.
```

## Invariant 3

```text
Plugin cannot grant itself additional capability.
```

## Invariant 4

```text
Workspace escape is denied unless user explicitly enables Full Access.
```

## Invariant 5

```text
Candidate plugin cannot activate itself.
```

## Invariant 6

```text
Harness failure must not imply Kernel failure.
```

## Invariant 7

```text
No silent Host fallback.
```

如果 Sandbox 不可用：

```text
fail
```

不要：

```text
run on host anyway
```

## Invariant 8

```text
Plugin data access and Event Bus subscriptions are scope-limited by default.
```

## Invariant 9

```text
Remote model input is an explicit data flow and cannot include secrets by default.
```

## Invariant 10

```text
Activation approval is bound to the exact Candidate digest and capability scope.
```

---

# 44. Full Access

Full Access 是显式逃生口。

用户主动启用：

```text
Full Access
```

等于声明：

```text
Agent may request broader user-scoped capabilities through the Kernel.
```

必须明确显示。

不能偷偷升级。

但必须是：

```text
explicit
visible
revocable
```

Full Access 不是 silent Host fallback，也不是把 Kernel、Trusted Promoter、其他
Plugin storage 或系统级 secret 目录直接交给 Agent。它仍然必须经过 Kernel Broker，
并显示具体的 workspace、network、process 和 secret 范围、有效期及撤销方式。
第一版 Khaos Seed 不实现 Full Access；Seed 只验证默认拒绝路径。

---

# 45. Khaos Seed

第一个 milestone 不做自进化。

名称：

> **Khaos Seed**

完成标准：

```text
模型可以对话
有 read/edit/bash
bash 经过真实 sandbox
workspace 外默认不可写
Plugin 可以加载
Plugin 可以卸载
Plugin 无法绕过 Kernel
支持简单 Session
支持 TUI/CLI
```

Seed 必须先选择一个明确的平台和 Sandbox backend；未支持的平台不得声称兼容，
而应在启动时 fail closed。第一版建议只选择一个平台，待安全契约和攻击测试
稳定后再增加其他平台。

当前原型选择 macOS Seatbelt 作为真实 OS enforcement 的研究起点。系统自带的
`sandbox-exec` 已被 Apple 标记为 deprecated，因此此选择只支持本地实验，不代表
长期平台承诺。每次开发路径启动前都会运行真实能力探针；探针验证 disposable snapshot
内的受限数据写入及路径/网络拒绝，其 disposable fixture 不会修改用户 workspace。

### Seed 的执行模型与 TCB 预算

上层只需要理解这条执行链：

```text
Launcher
    ↓
Kernel
    ↓
Runner
```

Launcher 取得用户选择的 workspace，并把明确的调用范围交给 Kernel。Kernel 负责
认证 IPC 对端、绑定 workspace descriptor、执行 OS sandbox、隔离 Runner、检查完整
changeset 并控制写回。Runner 与其中运行的 Plugin 代码都不可信。

`KernelProduction.xpc` 是 Kernel 的 XPC 入口。Python Bridge、one-shot Worker、commit
child、IPC operation handler，以及 Swift Bootstrap、Service、Client、Executor 都是
Kernel 的内部实现，不是新的上层架构节点。它们只有在实际承担上述 Kernel enforcement
时才属于 TCB；名称、模块或类边界本身不构成安全边界。

`KernelSnapshotBroker.xpc` 保持为独立可信进程，因为 APFS image 工具需要与工作区
Kernel 不同的受限 Seatbelt policy。它只创建、验证和释放 Kernel 绑定的私有 APFS lease，
属于 Kernel 的 macOS 平台实现，不向 Launcher、Agent 或 Plugin 增加新的产品层级。Agent
Host 与 Runner SDK/启动代码是受 OS 限制的不可信输入处理面，不属于 Kernel TCB。

签名 Seed 产品只打包当前执行链所需的 Python 模块。源码树里的直接 APFS image
创建/挂载/恢复后端仅供开发与测试使用，不进入 `KernelProduction.xpc`；产品缺少已认证的
Snapshot Broker lease 时必须失败，不能切换到该直接挂载后端。

每次新增 trusted 代码、进程、IPC operation、持久状态或依赖，都必须说明它保护的
invariant、不能放在 untrusted 层的原因、不能复用现有 trusted primitive 的原因，以及
是否存在更小的实现。威胁模型之外的任意同 UID 宿主进程不作为扩充 TCB 的理由；变更此
边界必须先修改威胁模型。

独立的 App Sandbox/XPC 探针现已能够从服务包内启动当前 Python 版本和仓库的
`khaos.runner`。在一个无 workspace bookmark 的 XPC 调用中，测试 Kernel peer 使用
ABI v4 的 OS peer-PID 握手与有界匿名管道，验证 `ping`、`plugin.start` 及一个合成的
Kernel-mediated `fs.read`；Plugin 直接读写 Host workspace/sibling/outside canary 和
连接 loopback 均被 OS 拒绝。该探针的 Kernel 是同一 XPC sandbox 内的测试 shim，读取数据
是固定内存 fixture；它没有接入真实 snapshot、`process.exec`、`workspace.commit` 或生产
Kernel，也不替代下述 Seatbelt 本地执行路径和写回验证。

原生 Kernel.xpc 的 scope 模式保留 App Sandbox，验证 bookmark 的 OS 授权差异：未解析
bookmark 前仅凭 Host app-container fixture 路径打开 input.txt 会被拒绝；Host 传入 bookmark 后，
Kernel 按固定相对路径、O_NOFOLLOW、regular-file、单链接和 4 KiB 上限读取同一 fixture。伪造签名
身份的 XPC 服务不能连接其 anonymous endpoint。该 listener 要求嵌入式 HostClient.xpc 的签名标识及当前
可执行文件全部架构的 cdhash；测试中的 Spoof 使用相同签名标识但不同代码，OS 拒绝它的连接。外层 Host
通过 named bootstrap 获取 endpoint，再通过真实 XPC 转给 HostClient.xpc；HostClient 创建并向 Kernel
发送 app-container bookmark。
该读取来自一次性 Host app-container fixture，不是
外部用户 workspace，也没有接入 Runner SDK 的 fs.read、process.exec 或 workspace.commit。本机探针
曾报告 bookmark stale，尽管 fixture 读取成功；现在探针会在原 scoped access 仍打开时重建 bookmark，
要求新 bookmark 可解析且不再 stale，并比较刷新前后的 workspace 根目录 device/inode 后才使用新 URL。
真实 XPC 测试覆盖成功刷新路径；超限、无效或身份变化的刷新会拒绝。本策略仅用于单次测试调用，没有
持久化 grant 更新或生产级用户重新授权流程。

真实执行链现在由另一个 KernelExecution.xpc 测试服务承载。它没有
com.apple.security.app-sandbox entitlement，且只导出 workspace.run 方法；Host 仍在 App Sandbox 中，
Kernel endpoint 仍核对 HostClient.xpc 的代码签名标识和当前构建各架构 cdhash。早期主机探针观察到
App-Sandboxed helper 的 `hdiutil create` 和 `diskutil image attach` 返回非零。仓库现由
[`test_app_sandbox_cannot_create_or_mount_kernel_apfs_images`](../tests/test_macos_xpc_sandbox.py)
维护真实签名 App-Sandboxed helper 的回归：helper 可写其 temporary directory，但 `hdiutil create`
和生产后端使用的精确 `hdiutil attach -plist -nobrowse -mountpoint …` 均返回非零；未沙箱对照可挂载
同一 APFS sparsebundle。新回归进一步验证 `diskutil image attach --plist --nobrowse --mountPoint …`
也返回非零，但系统镜像清单会短暂出现未挂载的 APFS 设备；helper 再以该设备调用 `diskutil mount`
仍返回非零，测试宿主卸载并确认无残留挂载。因此，命令状态非零不等于没有任何 DiskImages 副作用，
当前证据只证明这些 App-Sandboxed 调用路径没有挂载工作卷。此 helper 没有使用生产
KernelProduction.xpc 的完整 entitlement 组合或 XPC 执行路径；KernelExecution.xpc 仍留在 TCB，完整
生产挂载路径尚未验证。
[Apple XPC service guidance](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingXPCServices.html)
支持按 service 配置不同 sandbox 能力；此测试服务是 ad-hoc 签名的可信 TCB 探针，不是生产 IPC、用户授权机制或可供不可信 Host 任意调用的 Kernel API。

KernelExecution.xpc 解析 disposable app-container bookmark，并立即打开 no-follow workspace 根 descriptor。
stale bookmark 刷新前后保持旧 scoped access，并要求新旧 descriptor 的 device/inode 一致；探针在原位移动目录
再移回后验证此路径。该 descriptor 通过 posix_spawn 文件动作映射给捆绑 CPython，并传入
`run_workspace_command()`；Launcher 再次核对授权路径仍指向该 descriptor，并把它传给 Kernel Worker，供
snapshot baseline 与 commit 延续使用。由于该服务没有 App Sandbox，子进程能经 ../、兄弟 symlink 和 hardlink
读取 sibling-secret；这些 descriptor 不是读权限边界。探针将受污染目录与干净执行目录分开：后者调用
真实 run_workspace_command()，创建并挂载 bounded APFS snapshot，通过 Seatbelt 能力探针，运行独立 Runner，
拒绝 Runner 对 live workspace 的直接写入，并由 trusted changeset commit 安装一个安全输出。伪造签名
相同签名标识但不同代码的 Spoof 对 workspace.run endpoint 的请求也被拒绝。Seatbelt runtime allowlist 现在只加入 bundled Python
Framework 的精确动态库文件，以支持受限 Runner 启动；不会开放整个 Python prefix。

这证明了当前主机上 Kernel Worker→APFS snapshot→Seatbelt Runner→trusted commit 的测试执行路径，并覆盖
XPC bookmark descriptor 到 Kernel Worker 的路径重定向检查；它不证明外部用户 workspace 的授权边界：bookmark
仍是 disposable Host container fixture。探针可在单次调用内刷新 stale bookmark，但生产 grant 的持久化、撤销
和重新授权策略尚未实现。KernelExecution.xpc 没有 OS 级 App Sandbox 文件范围，因此必须保持在可信 TCB 内，绝不能加载或执行
Host/Plugin 提供的代码。trusted Launcher 打开的 workspace_root_fd 贯穿 snapshot baseline、Runner 执行
期间和 commit 生命周期，但仅由 trusted Kernel Worker / committer 持有：snapshot 在其上下文生命周期内借用
该 descriptor，fork 的一次性 committer 保留并复制它；Runner 与命令子进程不得继承。
通过该 descriptor 扫描源树并执行 changeset。committer 仍会按路径重开 workspace 根目录以验证原授权路径
没有移走或替换，并重开 mountpoint 取得 advisory lock；这些是身份/互斥检查，不是新的根目录授权来源。
污染目录没有送入真实执行路径；snapshot copier 对 st_nlink != 1 的既有 fail-closed 回归仍是 hardlink 防线。
这条 FD 连续性只覆盖可信测试执行路径，不实现外部用户授权、生产级 stale bookmark 持久化/撤销策略，
也不解决同 UID 非协作写者仲裁。

当前 XPC 测试另建了 app container 外部的临时目录，并验证未获选择授权的 Host 仅凭路径无法读取它；随后用户在独立 sandboxed `WorkspaceGrant.app` 中选择该目录。UI app 通过 named bootstrap 获取 KernelExecution endpoint，并在应用内直接连接嵌入式 `KernelExecution.xpc` anonymous endpoint，传入所选子目录 bookmarks；当前实现不再经过 `WorkspaceGrantClient.xpc` 转发进程。KernelExecution 从已签名 service Info.plist 读取父 App 的 designated code-signing requirement，并在接受调用前由 OS 校验调用者。真实攻击客户端使用相同 service identifier、不同签名身份，尝试以空 bookmarks 调用 `workspace.run`；OS 使其连接失效，服务不接受请求。`HostClient.xpc` 仍在接受新连接时，从其已签名的 service Info.plist 读取父 App 的 designated code-signing requirement，并在 `resume()` 前调用 `NSXPCConnection.setCodeSigningRequirement`；缺少要求时拒绝连接。真实攻击进程使用与目标父 App 相同的签名标识、不同签名身份和代码；identifier-only 检查通过，完整 requirement 检查失败，OS 不让其调用 HostClient peer probe。嵌入式 helper 的 caller requirement 会被封入父 App 的资源签名；在这个包布局中用父 executable cdhash 自引用会随最终 bundle 重签变化，因此测试绑定稳定的 designated requirement（签名证书身份与 bundle identifier）；该测试用临时自签名证书保持父 App 的 requirement 跨 bundle 重签稳定。此前通过旧转发路径完成的 picker→Kernel→snapshot→Runner→commit 交互证据，不能证明移除 helper 后的当前直接成功路径。复核发现此前的 picker helper 在 Kernel 请求后曾直接把测试报告文件写入所选目录，因此那些成功运行也不能证明所有写回均由 Kernel 完成；现已改为将报告写到 stdout，并让交互测试检查目录差分只有 `kernel-workspace/output.txt` 和 Kernel descriptor 测试探针写入的 `kernel-descriptor-scope/descriptor-probe-started.txt`。2026-09-27 上一次当前直接路径选择器运行未收到选择并在 600 秒后超时；测试清理了临时目录和 helper。移除报告文件写入和 app-container 正向夹具后，build 模式在 46.068 秒通过并验证同标识异签名客户端被 OS 拒绝；本次重新打开的 picker 又在 600 秒后超时（总计 645.871 秒），测试清理了临时目录和 helper，外部用户选择及 Kernel 写回正向验证仍待完成。 2026-09-27 再次打开前台 picker 后，仍未收到目录选择；运行在 600 秒后以 `subprocess.TimeoutExpired` 结束（总计 645.855 秒），临时目录与 helper 已清理，外部 workspace grant 和 Kernel 写回正向验证仍未成立。2026-09-27 本次用户请求的重试中，`WorkspaceGrant` helper 在 `NSOpenPanel.runModal()` 中等待 600 秒后超时（总计 647.630 秒）并清理临时目录与 helper；UI 自动化因 Launch Services 返回 `kLSIncompatibleSystemVersionErr` 无法附着临时 app，故不能证明选择器是否显示在前台，外部 workspace grant 和 Kernel 写回仍未验证。2026-09-27 第二次干净重试未切换其他应用，`WorkspaceGrant` 仍在 600 秒内未收到目录选择（总计 647.153 秒）；测试清理临时目录与 helper，外部 workspace grant 和 Kernel 写回仍未验证。上述测试只证明当前主机上的测试签名身份校验，不代表发布证书身份或同签名者不同二进制的隔离，也不代表生产授权保存、撤销、重新授权、scope 策略或批准绑定。

2026-09-27 将 XPC peer requirement 配置提取到共享 Khaos 源码 `khaos/macos/XPCPeerIdentity.swift` 后，build 模式通过，用户在新 picker 中选择 workspace 后，交互式 sibling-service scope 攻击在 321.592 秒通过。测试验证 picker 自身能以 `O_WRONLY` 打开所选文件；仅获路径的独立 sandboxed `UntrustedHost.xpc` 能写入自身 container，但不能写入该 workspace；随后 KernelExecution 接收 scoped bookmarks 并完成受信任写回。该结果验证当前临时测试 bundle 编译并调用共享 helper，不构成生产可信 Launcher、XPC service、安装保护或 grant policy 的证据。

之后将 bounded Workspace XPC ABI v2 从 `tests/macos_xpc_probe/KernelWorkspaceXPC.swift` 移至共享 Khaos 源码 `khaos/macos/KernelWorkspaceXPC.swift`，并将测试协议命名为 `KernelWorkspaceEndpoint`。移动后的 build-mode XPC 测试于 2026-09-27 在 66.194 秒通过，编译该共享 ABI 并实测 OS peer-identity 拒绝；canonical 全量测试随后在 317.693 秒通过 181 项。321.592 秒的 picker scope 正向攻击发生在源码移动前；移动后尚未重跑 picker 正向路径。在随后提取操作服务之前，XPC service bundle 与 service 实现仍只存在于 ad-hoc 测试中。

后续 IPC 审计发现客户端在构造 bookmark frame 前只检查 `UInt32.max`，未遵循接收端 64 KiB 总上限，可能先复制远超协议预算的数据。共享 ABI 现让发送端和接收端复用同一个非空/总长验证，并在复制前拒绝超限输入。测试以调用计数器证明 helper 返回 `EMSGSIZE` 且没有调用 XPC endpoint；另以绕过 helper 的真实 XPC 攻击仅发送超限长度头，验证服务在 descriptor marker 前拒绝。修改后 build-mode XPC 测试在 54.080 秒通过，迁移后交互式 picker/sibling-scope 攻击在 69.477 秒通过，完整 181 项测试在 317.673 秒通过。生产 XPC service 与 Trusted Launcher 仍未打包。

随后按用户请求重开的交互测试重新创建了临时 fixture，并由原生 picker 返回匹配的 `user-selected-workspace`。当前 ABI 与 sender-side size bound 下，focused XPC 测试在 72.619 秒通过：picker 获得所选目录写权限；仅获路径的 sibling sandboxed XPC 可写自己的 container、但被 OS 拒绝写 workspace；Kernel 完成安全 changeset 写回并拒绝不安全 changeset；目录差分只含 Kernel 输出和 descriptor test marker。该重跑再次验证当前 test-only probe 的正向路径，不构成生产 Launcher、持久授权或安装保护证据。

为避免最小 XPC 准入/取消逻辑只在测试实现，已将单活动操作槽、bookmark stream 接收、连接绑定取消与清理提取到 `khaos/macos/KernelWorkspaceService.swift`。测试仍通过真实 XPC 调用该共享服务，并由测试 adapter 执行真实 Kernel→Seatbelt→snapshot→changeset 路径；peer-authenticating bootstrap、executor 的生产组合、Trusted Launcher 与正式服务 bundle 仍未建立。提取后 build-mode 攻击在 53.586 秒通过，交互 picker/sibling-scope 攻击在 130.694 秒通过，完整 181 项测试在 305.833 秒通过。此项只证明共享操作服务源码在当前 ad-hoc OS XPC 探针中可运行，不代表生产部署或完整认证边界。

之后一次交互重试发现 Swift 6.3.3 在 macOS 27.0 主机上的默认目标为 `arm64-apple-macosx28.0`；Launch Services 拒绝该 `.app` 并返回 `kLSIncompatibleSystemVersionErr`。将 `WorkspaceGrant` 的 Mach-O 目标设为本机架构与系统版本后，签名 `.app` 可由 Launch Services 启动并成为前台应用，但 600 秒内未收到目录选择；`open -W` 超时退出后留下孤儿应用，现已终止。交互测试改为直接管理已签名 helper 二进制，且将等待设为 300 秒；本次仍未收到选择（总计 352.736 秒），但超时正确终止了 helper 并清理临时目录。`NSWorkspace` 确认 app 曾为前台应用，UI 自动化仍无法附着读取面板；外部 workspace grant 和 Kernel 写回正向证据仍未成立。2026-09-27 用户再次要求打开选择器后，系统截图确认当前直接路径的面板位于前台并显示新建的 `user-selected-workspace`；UI 自动化附着仍返回 `timeoutReached`，300 秒内未收到选择，聚焦测试总计 363.448 秒后超时，测试进程已清理 helper 和临时目录。此次确认面板可见，但仍未建立外部 workspace grant 或 Kernel 写回正向证据。2026-09-27 新一轮用户请求重开选择器后，`WorkspaceGrant` 持续作为前台应用等待目录选择，测试 300 秒内未收到选择或取消并在总计 351.457 秒后超时；进程与临时目录检查确认 helper 和 fixture 已清理。本轮仍未建立外部 workspace grant 或 Kernel 写回正向证据。详细证据及 Apple 错误码依据见 [docs/SEED_BACKEND_RESEARCH.md](SEED_BACKEND_RESEARCH.md)。

同一签名 XPC 探针还让 App-Sandboxed Host 攻击嵌入的 KernelExecution helper、固定 KernelProduction executable、Python bridge、changeset 实现、Python runtime 和 XPC bundle：覆盖写打开、新建、chmod、hardlink、`renameatx_np(RENAME_SWAP)`、常规替换 rename、symlink 替换、unlink 以及同文件系统的 bundle 目录原子交换。Host 在自身 app container 的写入正向控制成功；每项受保护操作均被 OS 拒绝，目标 SHA-256 保持不变且 bundle 深度签名验证通过。2026-09-28 聚焦真实 XPC/App Sandbox 测试通过，耗时 89.037 秒。该结果只证明当前 macOS 主机上的临时 ad-hoc 测试 bundle 具有这些拒绝行为，不代表生产安装完整性、更新保护，也不抵御能够直接改写该 bundle 的非 sandbox 同 UID 进程。

本轮用户要求重开的 `WorkspaceGrant` 又在 `NSOpenPanel.runModal()` 中等待 300 秒，随后以 `subprocess.TimeoutExpired` 结束（测试总时长 352.557 秒）；临时 workspace 和 helper 已清理。UI 自动化附着超时，因此本轮不能证明选择器是否可见，也未建立外部 workspace grant 或 Kernel 写回正向证据。


本次用户要求重开的 picker 由 `System Events` 确认为前台 `WorkspaceGrant`，但 300 秒内
没有目录选择或取消。Focused test 总计 409.692 秒后以 `subprocess.TimeoutExpired` 结束，
并清理 helper 与临时 fixture；没有新增 user-selected grant 或 Kernel 写回证据。

2026-09-28 为 Workspace XPC 客户端补上 Kernel 对端身份检查。共享
`XPCPeerIdentity.requirePeerIdentity()` 在恢复连接前，将 signed Launcher `Info.plist`
中的 Kernel service designated requirement 应用于 named bootstrap 和返回的 anonymous
endpoint 连接；缺失要求时拒绝。headless 真实 XPC 攻击把可连接的 sandboxed
`UntrustedHost.xpc` 当作 Kernel 连接目标，OS 返回
`NSXPCConnectionCodeSigningRequirementFailure` 且没有方法回复；正确签名的
`KernelProduction.xpc` 仍成功返回 idle-cancel 响应。Focused build-mode 测试通过 2 项，
耗时 110.251 秒。此证据仅覆盖临时签名测试 bundle，不建立 production Launcher、
发布身份或安装保护；ABI 约束与 API 依据见 [KERNEL_ABI.md](KERNEL_ABI.md) 和
[SEED_BACKEND_RESEARCH.md](SEED_BACKEND_RESEARCH.md)。

随后 canonical suite `python3 -m unittest discover -s tests -v` 在 375.548 秒通过 184 项。
该默认套件没有打开交互 Picker；出站 XPC 错误身份攻击的可执行证据来自 focused
build-mode 测试，Picker 授权正向证据仍未新增。

之后按用户要求重开 Picker。`System Events` 确认 `WorkspaceGrant` 为前台进程，但
300 秒内未收到目录选择或取消；focused XPC test 在 409.627 秒后以
`subprocess.TimeoutExpired` 结束并清理 helper 与临时 fixture。该次运行没有新增外部
workspace 授权、Picker 写拒绝或 Kernel 写回证据。

随后当前树上的 canonical 命令 `python3 -m unittest discover -s tests -v` 通过全部
184 项测试，耗时 402.372 秒。默认测试没有打开交互 Picker，因此不增加外部用户授权
或当前 Picker 写权限撤销的证据。

2026-09-27 用户在新鲜的直接路径 picker 中选择了 `user-selected-workspace`。`workspace.run` 经 Kernel 完成输出，拒绝不安全 changeset，且未产生 bypass 或 picker report 文件；修正交互测试的路径差分后，测试在 72.161 秒通过，新增路径精确为 Kernel 输出 `kernel-workspace/output.txt` 和 descriptor test probe 标记 `kernel-descriptor-scope/descriptor-probe-started.txt`。本次首次运行也到达 Kernel 成功输出，但暴露了测试断言漏列该预期 marker 的问题。此证据只覆盖当前本机 test-only ad-hoc direct picker/XPC probe，不证明生产授权持久化、正式签名身份、Kernel 安装保护或抵御非 sandbox 同 UID 写者。

后续 2026-09-27 交互攻击在 picker app 持有所选目录授权时，先由 picker app 成功以 `O_WRONLY` 打开 `kernel-workspace/input.txt`；再让独立 sandboxed `UntrustedHost.xpc` 仅凭绝对路径打开同一文件。该 service 可写自己的 app container，但 OS 对 workspace 文件返回 `EPERM`/`EACCES`。它没有收到 bookmark；KernelExecution 单独收到两个 scoped bookmarks 并成功完成写回。交互 XPC 测试在 104.323 秒通过，目录差分仍只有 Kernel output 与 descriptor marker。这只证明当前临时 bundle 中这些分离进程的 scope 行为，不证明正式生产安装或签名身份。

针对 Invariant 6，真实 XPC 故障测试由已签名的 `HostClient.xpc` 发起长时间 `workspace.run`；descriptor probe 留下启动标记后，helper 对自身发送 `SIGKILL`。外层 Host 观察到 XPC interruption，新的 helper 随后通过同一个 Kernel 完成新的 workspace 请求；崩溃请求没有写回结果或 bypass 文件。该测试只证明当前 ad-hoc 探针中的调用方进程退出处理，不覆盖 Kernel worker 或操作系统崩溃。

匿名 listener 使用的 `NSXPCListener.setConnectionCodeSigningRequirement` 与 named XPC service 收到的连接上使用的 `NSXPCConnection.setCodeSigningRequirement` 是不同 API；后者必须在 listener delegate 中、连接 resume 前设置。Apple 的 [TN3127](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements) 说明 requirement 的身份语义，另见 [listener API](https://developer.apple.com/documentation/foundation/nsxpclistener/setconnectioncodesigningrequirement%28_%3A%29) 与 [connection API](https://developer.apple.com/documentation/foundation/nsxpcconnection/setcodesigningrequirement%28_%3A%29)。

2026-09-27 将 named bootstrap 与 anonymous workspace endpoint 的准入检查提取到共享 Khaos 源码 `khaos/macos/KernelWorkspaceBootstrap.swift`。已签名服务 bundle 必须分别提供非空白的 `KhaosBootstrapRequirement`（限制谁能从 named service 取得 endpoint）和 `KhaosWorkspaceCallerRequirement`（限制谁能调用 anonymous workspace endpoint）；缺失、非字符串、空或纯空白时 bootstrap 初始化失败。named connection 在 `resume()` 前由 OS 检查，anonymous listener 仍独立检查 `workspace.run` 调用者，因此转交 endpoint 不会扩展调用权限。`KernelWorkspaceBootstrapEndpoint` 位于共享 `khaos/macos/KernelWorkspaceXPC.swift`，Host、picker 和负向客户端编译同一协议；同 identifier、不同签名身份的真实 XPC 攻击被 OS 拒绝。共享 ABI 的交互式 picker/sibling-scope/Kernel-writeback 测试在 96.327 秒通过。随后 requirement 读取复用 `XPCPeerIdentity.codeSigningRequirement`；最终代码的 build-mode XPC 在 53.223 秒通过，完整 181 项测试在 313.424 秒通过。picker 正向测试发生在 parser 抽取前；parser 抽取后的 build-mode 与完整套件通过。所有证据仅覆盖当前 ad-hoc 测试 bundle 的签名身份与本机 OS 行为；生产签名身份、服务组合、安装保护、授权持久化及撤销仍未实现。

2026-09-27 将共享 workspace XPC framing 提升为 ABI v3：一次 `workspace.run` 只携带一个有界 bookmark blob，不再接受分别指定 execution/descriptor 的两个 caller roots。测试 adapter 对单一 resolved root 持有 descriptor，并用 `openat`、`O_DIRECTORY`、`O_NOFOLLOW` 打开隔离的 descriptor probe 与 clean execution 子目录。真实 XPC 对两个子目录分别注入指向授权根外部的 symlink；两次请求都在 probe 启动前失败，未出现 marker 或 output，外部 canary 保持不变。build-mode XPC 测试在 52.547 秒通过，全量 181 项测试在 305.044 秒通过。一次 ABI v3 picker 重试未收到目录选择；随后在新 fixture 中及时将 picker 激活到前台，用户选择目录后，交互 XPC 测试于 293.641 秒通过。它验证了 picker 的用户授权写入、仅获路径的 sibling sandboxed XPC 被 OS 拒绝写 workspace，以及 Kernel 成功写回 `kernel-workspace/output.txt`、拒绝不安全 changeset、保留 outside canary；目录差分仅含该 output 和 descriptor probe marker。该结果只证明当前主机上的 ad-hoc 测试 bundle 正向路径，不证明生产 Launcher、持久授权、正式安装保护或抵御非 sandbox 同 UID 写者。生产 Trusted Launcher 与 executor composition 仍未实现。

随后将 bookmark scope 与根目录 descriptor 处理从测试 `Kernel.swift` 提取至共享 TCB 源码 `khaos/macos/KernelWorkspaceRoot.swift`。该实现持有 scoped access 跨越 descriptor 操作，使用 ABI 的统一 bookmark 上限，stale refresh 仅在重新打开的 root 与原 root 具有相同 device/inode 时继续，并通过 `openat`、`O_DIRECTORY`、`O_NOFOLLOW` 打开固定子目录。XPC 测试 adapter 已改为调用共享实现，不再复制 bookmark resolver。提取后真实 XPC build-mode 测试通过（53.484 秒），全量 181 项测试通过（303.552 秒）。提取后交互 picker 重跑中，`WorkspaceGrant` 保持前台但 300 秒内未收到用户选择，测试清理 helper 与 fixture；因此该次没有重新建立外部用户授权正向证据。生产 executor composition、Trusted Launcher 与正式 Kernel service bundle 仍未建立。

随后将 Runner 的 scoped `fs.read` / `fs.list` 验证扩展到已认证 XPC 操作：只读 scope 内的 `input.txt` 成功，未授权文件从根目录列表隐藏，未授权读取/列举分别返回 scope 错误；新增的 `fs.read("../sibling-secret.txt")` 也在命令执行和 changeset commit 前返回 `path_not_readable`。focused build-mode XPC 测试在 69.088 秒通过。应用户请求重开的原生 picker 在本次返回匹配新鲜 fixture 的 bookmark，交互 XPC 测试于 137.345 秒通过：仅获路径的 sibling sandboxed XPC 无法写入所选 workspace，Kernel 成功写入经验证输出并拒绝不安全 changeset。以上证据只覆盖当前 ad-hoc 测试 bundle；生产 Trusted Launcher、executor composition、持久授权策略与正式服务打包仍未实现。

2026-09-27 将共享 Workspace XPC framing 提升为 ABI v4，使 `workspace.run` 在同一有界 stream 中携带 Runner IPC v4 envelope 与单个 scoped bookmark。服务在 bookmark 解析或 executor 调用前验证精确 schema、字段上限及内外 request ID 一致性；XPC 客户端提交的 argv、timeout、Runner source 和 read scope 由现有 `run_workspace_command()` 路径继续校验。真实 XPC 攻击覆盖 oversized request length、空 argv、request ID mismatch、oversized/stalled bookmark；build-mode XPC 于 68.982 秒通过，并执行 Runner scope 与 changeset 攻击。随后按用户要求重开的交互尝试在 300 秒内未收到目录选择或取消；临时 `WorkspaceGrant` 被置于前台，但没有建立 user-selected grant 或正向 Kernel 写回证据，helper 与临时 fixture 已清理。当前 Python executor adapter 仍是 test-only；本 ABI 不代表生产 executor composition、Trusted Launcher 或正式 Kernel packaging。

macOS 的 `NSOpenPanel` 会把用户选中的目录递归授权给弹出它的应用，security-scoped bookmark 再传给 XPC 时会把范围授给接收端，因此普通不可信 Host 不得弹出该授权面板。生产实现仍须由独立可信 Launcher 接受用户选择，再由它把 bookmark 直接交给 Kernel。可信 Picker/Launcher 在把授权交给 Kernel 后必须平衡 `NSOpenPanel` 自动开始的读写 scope；Picker 不得继续持有真实 workspace 写权限。需要在提交后检查结果时，只能重新取得受限只读 bookmark。交互攻击必须证明 Picker 读成功、直接 `open(O_WRONLY)` 被 App Sandbox 拒绝，而 Kernel 仍能通过读写 bookmark 安全提交；仅有 `stopAccessingSecurityScopedResource()` 调用或语言层 API 不能作为证明。该边界使用 [App Sandbox 文件访问文档](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)
及 [NSOpenPanel 文档](https://developer.apple.com/documentation/appkit/nsopenpanel) 作为 OS 行为依据。

ABI v4 更新后的 canonical 全量测试通过全部 181 项，耗时 320.241 秒。最近一次 ABI v4 交互 picker 尝试虽将 `WorkspaceGrant` 置于前台，但 300 秒内没有收到选择或取消，临时 helper 与 fixture 已清理；因此当前 ABI v4 尚无新的 user-selected grant 或正向 Kernel 写回证据。此前 ABI v3 代码状态的 picker 正向证据不能替代对 ABI v4 路径的验证。

Apple 对独立 XPC helper sandbox 能力的说明见 [sandbox 诊断指南](https://developer.apple.com/documentation/security/discovering-and-diagnosing-app-sandbox-violations)。
XPC/descriptor 实验证据见 [docs/SEED_BACKEND_RESEARCH.md](SEED_BACKEND_RESEARCH.md)；Seed 威胁范围、测试证据索引和未成立的安全属性见 [docs/SEED_THREAT_MODEL.md](SEED_THREAT_MODEL.md)。

2026-09-27 为 ABI v4 的 `workspace.run` stream 增加了进程身份绑定：Kernel 在解析前读取 AF_UNIX `LOCAL_PEERPID`，并要求它等于当前已认证 `NSXPCConnection.processIdentifier`。发送端半关闭写方向后保留 descriptor 到 XPC 回复，避免 macOS 在对端完全关闭后返回 `ENOTCONN`。Focused build-mode XPC 测试在 71.164 秒通过；其中一项真实 socketpair parser 攻击发送完整有效 frame，却提供不同的 expected peer PID，Kernel parser 在读取 frame 前拒绝；普通请求也通过真实 XPC service 的 caller-PID 检查。此 parser 攻击不等于跨进程 XPC relay 端到端测试。本次按用户要求重开的 picker 再次到达前台，但 300 秒内没有收到用户选择或取消；临时 helper 与 workspace 已清理，因此没有新增 user-selected grant 或 Kernel 写回证据。OS API 依据为 [NSXPCConnection.processIdentifier](https://developer.apple.com/documentation/foundation/nsxpcconnection/processidentifier) 与 [XNU `LOCAL_PEERPID`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/un.h)。

同日后续测试补上了真实跨进程 relay 攻击：sandboxed sibling `UntrustedHost.xpc` 创建包含有效 `workspace.run` 前缀、但不含 bookmark 的 socketpair，并将 reader descriptor 经已认证 app 转交给 Kernel。测试先以 `LOCAL_PEERPID` 验证 descriptor 确由 sibling XPC 创建；Kernel 返回 `invalid_request`，若跳过 peer 身份检查则会继续读入缺失的 bookmark 并得到不同错误。Headless build-mode 攻击在最终清理版本通过，耗时 71.439 秒；按用户要求重开的 picker 返回新鲜临时 workspace bookmark，交互式 XPC 测试随后通过，耗时 139.630 秒，并继续验证安全写回、unsafe changeset 拒绝和 sibling XPC 无 workspace 写权限。Canonical 全量测试通过 181 项，耗时 346.503 秒。Picker、executor 与签名 bundle 仍为测试用途，不代表生产 Trusted Launcher 或 Kernel service。

开发用 `run_workspace_command()` 现已接通一次性本地路径：trusted launcher 通过有界匿名
管道和 nonce 握手启动单独的 Kernel worker；worker 固定 workspace、cwd、环境和 snapshot，
拒绝与当前 Kernel 安装目录路径重叠的 workspace；随后 worker 以 Seatbelt 启动独立
Runner。Runner 只通过 IPC facade 请求 `fs.read` / `fs.list`、`process.exec` 和
`workspace.commit`，不提供 workspace、cwd、env 或命令 argv。Kernel 保留调用方验证后的
argv 和 timeout，Runner 只能以空 payload 请求执行该固定命令。Runner 的 cwd 位于私有
scratch；Seatbelt 拒绝它读取或写入 snapshot，
也拒绝它向 scratch 和其他路径写文件（`/dev/null` 除外），包括 profile 只读开放的 Kernel 模块路径；
真实 Seatbelt 攻击还验证 Runner 对一次性 live-workspace 文件和 user-home secret 的直接读取、
写入均被拒绝。
真实 Seatbelt 攻击还让 Plugin source 绕过 facade，直接发送带 `argv` 和 `workspace` 字段的
`process.exec` wire payload；Broker schema 测试断言其返回 `invalid_request`，真实攻击会话以
`runner_failed` 结束，所选 workspace 与伪造目标均未出现文件。该测试覆盖当前一次性 ABI
的命令和目标注入，不建立 Agent Host API 或 capability grant。
另一项真实攻击先让固定命令在 snapshot 写入待提交文件，再由 Runner 绕过 facade 发送带
伪造 changeset 和 alternate workspace 的 `workspace.commit` payload；Broker schema 测试断言
其返回 `invalid_request`，真实攻击会话失败，待提交文件没有进入真实 workspace，外部 canary
保持原值。
只放行到精确 peer-PID Unix socket 的连接。只有 Kernel 启动的独立 `process.exec` 子进程获得
snapshot 写权限。真实测试验证这些拒绝行为，
launcher 集成测试验证 Runner IPC 和命令写回仍可用。命令结果视为不可信，Kernel worker
校验 changeset 后才写回显式选择的 workspace。真实 macOS 集成测试验证命令直接写 workspace
外部文件、把 live workspace 的嵌套目录 rename 到外部路径都会被 OS 拒绝；普通 snapshot
输出仍可通过提交，新建 symlink 输出会被拒绝且外部目标不变。真实 launcher 测试使用
`/bin/bash` 在私有 snapshot 写文件，同时尝试直接写入以及通过 `../` 路径越界写 workspace 外文件，
并移动 live-workspace 目录；越界写收到 `EPERM`，受限命令不能完成目录移动，而有效 snapshot 输出仍经 Kernel commit。
另一项 Bash 攻击把安全文件与指向外部 canary 的新 symlink 一起写入 snapshot；Kernel 拒绝整个
changeset，安全文件未部分写入且 canary 未改变。端到端 Bash hardlink 攻击确认命令可在
snapshot 内创建并验证双链接文件，但 Kernel 拒绝包含 hardlink 的整个 changeset，live workspace
不变。另一项真实 Runner IPC 攻击让 Bash 在 snapshot 中创建并通过 `test -p` 验证 FIFO，旁边还放入
本可接受的普通文件；Kernel 将 special file 视为不可信 changeset 并整体拒绝，真实 workspace 中
两条路径都未出现。Runner 故障测试确认：sandbox 命令已修改 snapshot
而 Runner 在 commit 前退出时，Broker
遇到 pipe EOF 并拒绝写回，真实 workspace 仍保持原状。真实 outer-Runner probe 还尝试以 `O_WRONLY` 打开实际的
`macos_seatbelt.py` Kernel 模块，Seatbelt 拒绝该操作；这只证明当前 Runner profile 不能直接
写该模块，不证明安装对用户或 sandbox 外的同 UID 进程不可修改。这是一个开发/验证垂直路径，
不是加载 Candidate Plugin 的 Agent-facing Runner，也不是长期运行的生产 Broker。
真实 macOS 故障测试在 `process.exec` 活跃期间对调用 launcher 发送 `SIGKILL`；Kernel
从控制管道 EOF 检出调用方退出。命令先在 snapshot 写入文件，再启动的带唯一标记沙箱
后代进程随即消失；live workspace 中该文件未写回。这覆盖调用方突然退出，不覆盖
Kernel worker 自身崩溃或系统崩溃。
另一项真实 macOS 故障测试在 sandbox command 已启动后对 Kernel worker 发送 `SIGKILL`。
command 启动子进程在 `setsid` 后、执行 `sandbox-exec` 前，通过继承的私有匿名管道 writer
发送与 `workspace.run` request ID 绑定的 `process_started` 帧，然后关闭该 descriptor；因此
Runner 和 command 都拿不到它。launcher 取得 OS 确认的进程组 ID 后，Worker 即使在 `Popen`
返回前被杀，仍可终止该组。测试确认唯一标记的命令及后代消失、snapshot 中未提交的文件未进入
live workspace、该 Worker 的挂载卷和临时目录均已清除。Worker 所属进程组同时收纳 IPC Runner
及其辅助工具；launcher 清理时即使 Worker 收到 `SIGINT` 后迅速退出，也会继续终止整个组，因为
`SIGINT` 本身只发给 Worker，可能留下已 fork 的 committer。真实进程组测试让 Worker 对 `SIGINT`
执行快速退出，并让同组 helper 在 Worker 退出后尝试写入标记；launcher 清理终止该 helper，标记未出现。
这些路径只覆盖 launcher 存活时的 Worker 清理；不覆盖 launcher 同时退出、系统崩溃或清理工具本身失效。
profile 构造还会 fail closed：额外可写目录不能与运行时只读根或显式可读路径重叠，避免未来
调整 scratch 路径时意外把 Kernel/Runner 代码树纳入 Runner 的可写范围。
只读运行时范围按当前 Python 可执行文件、标准库、动态模块目录和必要 Framework 文件构造，
不再开放整个 `sys.prefix` / `sys.base_prefix`；profile 还显式拒绝 `site-packages` 和
`dist-packages`。真实 Seatbelt 测试验证 Runner 无法读取 Python 安装目录中的头文件或通过
标准库内的 `site-packages` 符号链接列目录，同时标准库导入仍可工作。

匿名管道 ping 验证有界启动握手。outer probe profile 默认拒绝 process-fork 和
process-exec，只精确放行启动探针所需的 Python 可执行文件及其 Framework runtime；
真实探针验证直接启动子进程和 `execve("/usr/bin/true", ...)` 都被系统拒绝。Broker 启动
命令时使用另一条 Seatbelt profile，仅允许在容量固定的独立 APFS snapshot 和其私有临时
目录中写入，拒绝网络，允许命令所需的 fork/exec，并拒绝 `mount`、`unmount`、`setsid` 和
`setpgid` 系统调用。真实 macOS 测试验证命令写入只到 snapshot、workspace 外写入和 IPv4
loopback 被拒绝、超时会终止同进程组的 fork 子进程、输出超过 8 KiB 时拒绝结果并终止进程，
且跨文件写入最终收到 `ENOSPC`、直接卸载 snapshot 卷收到 `EPERM`。Runner SDK 的
真实 macOS 差分攻击测试先由可信宿主把同一 snapshot 中的 APFS 镜像通过 `hdiutil attach` 和
`diskutil image attach` 分别挂载到 live workspace 目标并成功卸载；受限命令重放这两条命令时
均返回非零，目标未成为挂载点、仍与父目录处于同一卷，且镜像不在 `hdiutil` 系统清单中。
此证据覆盖当前主机的这两条镜像挂载路径，不代表覆盖所有系统服务委托或 macOS 版本。
`process_exec()` 可轮询取消条件，并在
同一管道提交一个指向当前 `process.exec` request ID 的 `process.cancel` 控制帧；目标不匹配
时拒绝取消，目标匹配时 Kernel 杀死命令进程组并回收 launcher 后才确认。真实 Seatbelt
Runner SDK 集成测试验证 fork 子进程不会在确认取消后写入幸存标记。Runner 只能提交有界
argv 和 timeout；command stdout/stderr 仍未可信，之后的 `workspace.commit` 独立校验变化集。
另一项真实 Seatbelt 测试覆盖命令 leader 正常返回、fork 子进程关闭 stdout/stderr 后仍等待
写 snapshot 的情况：Kernel 在返回命令结果前终止同进程组后代；测试随后释放子进程的写入门闩，
确认它不能在 commit 前追加文件，可信 changeset 只提交扫描到的 snapshot 输出。该证据针对
当前进程组与 macOS profile，不代表对沙箱外同 UID 写者的全局排他控制。另一项真实 Seatbelt
攻击测试执行 double-fork daemonization 序列：后代尝试 `setsid`，实测 OS 拒绝；leader 随后退出，
命令监督器清理进程组。测试再释放后代写入门闩，确认没有 late-write 文件进入
changeset。该测试证明当前 profile 和进程组监督阻止此 double-fork 写者脱离本次 command 生命周期。

另外，真实命令 sandbox 攻击测试验证 IPv4/IPv6 loopback、fork 子进程的 IPv4 连接、显式
HTTP proxy、发往本地受控 listener 的 UDP DNS 报文，以及到 macOS `mDNSResponder` Unix
socket 的连接均被 OS 拒绝；listener 未收到 DNS 报文。另一项真实 Seatbelt 测试通过
`getaddrinfo()` 请求唯一的 `.example.com` 名称，确认请求失败，并按该 sandbox 子进程 PID
检查 unified log，验证 macOS 拒绝了 `com.apple.system.opendirectoryd.libinfo` resolver
lookup（或对应 resolver socket / outbound network 操作）。这证明当前 macOS resolver 路径的
该次访问被拒绝，不代表所有 resolver 配置或 macOS 版本都已覆盖。另一项真实 Seatbelt
测试确认宿主环境中的 sentinel 和显式设为 inheritable 的匿名管道描述符都不会传入 command。
另一个真实攻击从受限 command profile 中启动 `/usr/bin/sandbox-exec`，尝试用
`(version 1)(allow default)` 给子进程放宽权限并在 workspace 外创建 canary；相同 profile
在 sandbox 外可成功启动 `/usr/bin/true`，作为语法控制。受限路径中的嵌套 `sandbox-exec`
收到 `sandbox_apply: Operation not permitted`，canary 未创建。当前 macOS `sandbox(7)` 手册
说明新进程继承父进程 sandbox；这项 live test 证明该 Khaos profile 在当前主机上的此条
重放攻击失败，不代表覆盖所有系统服务委托或 macOS 版本。配套攻击从未沙箱化的控制子进程
直接调用 `/usr/lib/libsandbox.dylib:sandbox_init` 并成功应用同一 permissive profile、写入控制
canary；从受限 command 调用时收到 `Operation not permitted`，workspace 外 canary 未创建。
同一 API 攻击在只读 IPC Runner profile 下也收到 `Operation not permitted`，Runner 外部 canary 未创建；
未沙箱化控制组证明 permissive profile 本身有效。这只验证当前主机上的两种 Khaos profile，
不覆盖所有 macOS 版本或系统服务委托。

`run_workspace_command()` 现在可接收调用方的取消条件，并在独立 launcher→Kernel 管道上发送
绑定当前 `workspace.run` request ID 的 `workspace.cancel` 帧。Kernel 在 Seatbelt 能力探针期间
以及私有 snapshot 构建期间检查取消；snapshot 每个条目和每个文件复制块都会轮询，APFS
文件系统查询、稀疏镜像创建/挂载和卷身份查询也检查同一取消条件。`hdiutil` / `diskutil`
运行在独立进程组中；取消先发送 `SIGTERM`，等待工具组退出，超时后才升级到 `SIGKILL` 并回收。
真实探针发现 DiskImages helper 可能在 `hdiutil attach` CLI 退出后继续挂载：系统清单先报告空
`system-entities`，稍后才出现设备和挂载点。Kernel 现在最多等待 5 秒让镜像清单和预期挂载点稳定，
卸载随后出现的设备，并在删除 backing directory 前同时确认镜像清单中无该镜像且挂载点未挂载；状态
持续不明确时 fail closed 并保留目录。真实 macOS attach-cancellation 测试在修复后连续 5 次通过，
确认测试操作没有遗留挂载卷。Runner 启动前的取消会清理私有 APFS volume。
Runner 启动前的取消会清理私有 APFS volume。macOS launcher→Kernel 真实端到端测试在私有 APFS
volume 中观察到 768 MiB 输入文件仅部分复制后，触发调用方取消并收到 `process_cancelled`；测试确认
原 workspace 文件逐字节不变，且没有遗留新的 snapshot volume。Kernel 还在 `process.exec`
期间把它接入现有进程组监督器；命令完成后，独立 commit 子进程在完成输出 staging、live baseline
校验并应用 Seatbelt 后发送 READY。Kernel 在准备阶段轮询调用方取消，并在 READY 时再次检查；
只有收到 ACCEPT 才开始任何 live-workspace 写入。Kernel 在发送 ACCEPT 前最后一次观察到的
取消状态是本操作的取消截止点；此后到达的取消信号可能被视为太晚，即使子进程尚未开始写入。
截止点前接受的取消会使子进程收到 ABORT、丢弃 snapshot 并返回 `process_cancelled`；通过截止点后，
changeset 可能正常完成，且不承诺回滚部分写入。真实 macOS Seatbelt 集成测试在 READY 门处触发取消，确认
Broker 拒绝提交且原文件保持不变。此接口只覆盖一次性开发 launcher，不是 Agent Host API、通用
operation dispatcher 或生产级 operation lifecycle；当前也没有 Agent Host 向 Runner 提供取消信号。
另一项真实 Seatbelt 故障测试在 commit 子进程已应用 sandbox 并发出 READY、Worker 尚未发送 ACCEPT
时对 Worker 发送 `SIGKILL`；决策管道 EOF 使子进程中止，staging 被清理，真实 workspace 文件保持不变。
该保证只覆盖 ACCEPT 前的 Worker 退出；通过截止点后，已授权的 commit 不会因调用方或 Worker 随后退出而撤销。
Runner 当前仍没有按命令聚合的内存配额。2026-09-26 在 macOS 27.0 arm64 上，CPython 3.13.4
与一个极小的动态链接 C 探针设置 `RLIMIT_AS` 到 8–256 GiB 均失败，512 GiB 才能设置；
XNU 会先核对当前进程地址空间。当前 launcher 路径因此不能据此提供有实际约束力的内存上限；
2026-09-27 对 macOS 26.5 公共 SDK 与当前 XNU 源码的核查未找到受支持的公开
`posix_spawnattr_t` 内存限额 setter；XNU 内部 active/inactive 字段由 launchd 按
`JetsamProperties` 传递并应用于各个进程，不能形成命令进程树的聚合配额。Khaos 不使用
私有 spawn API，kernel-applied aggregate spawn limit 仍未成立。磁盘使用由
私有 APFS sparse bundle 的固定容量限制，真实 Seatbelt 测试验证多文件写满该卷会得到
`ENOSPC`，并验证 Runner 无法卸载该卷。`RLIMIT_FSIZE` 仍是单文件上限，`RLIMIT_NPROC`
仍按 real UID 计数，不能代表命令级进程配额。即使逐进程 `RLIMIT_AS` 可用，也不能限制
整个 fork 命令树的聚合地址空间。实验来源与限制见 `docs/SEED_BACKEND_RESEARCH.md`。
2026-09-30 又对 Apple 公共 [`task_set_phys_footprint_limit`](https://developer.apple.com/documentation/kernel/1538131-task_set_phys_footprint_limit)
Mach API 做了当前主机探针：未提权 Python 调用自身 `mach_task_self_` 的 task port，内核返回
`KERN_NO_ACCESS`（Mach error 8）。该 API 即使在具备调用权限时也针对单个 task，而不是 fork
命令树的合计资源，因此既不能作为当前普通 Runner 可用的 enforcement，也不能满足 aggregate quota。
Apple Containerization 当前源码为 Linux guest 配置了 cgroup CPU 和内存限额，可能成为
命令树级配额的后续验证方向；它会把执行环境从 native macOS 改为 Linux VM，尚未集成或经过
Khaos 攻击测试，因此不是当前 Seed 能力。
新增的真实 Seatbelt 测试确认命令继承配置的 `RLIMIT_NPROC=1024`，在配置允许时可以
fork；将该限制降至 2 后，OS 返回 `EAGAIN` 并拒绝后续 fork。这证明当前 Darwin 内核
确实执行该 per-UID 限制，但没有证明 1024 个命令进程的专属上限，也不提供命令树级资源配额。
launcher→Kernel 与 Kernel→Runner 均通过一次性 AF_UNIX 凭据握手双向验证 OS peer PID；
握手不承载应用数据，有界帧仍走匿名管道。Runner 的 Seatbelt 只为 scratch 内的精确
socket 路径增加 network-outbound 例外；真实攻击测试确认同一 scratch 下另一个 AF_UNIX
listener 仍无法连接，IPv4 loopback 也保持拒绝。两条 IPC 链路仍没有用户 capability grant 或
approval 绑定。Kernel 源码安装仍可由同一用户修改；其他同 UID 进程也不受 Kernel 写入
仲裁，因此 Kernel 还没有排他的 live-workspace 写入权。Agent Host 和最小 Agent Loop 已经
作为独立 App-Sandboxed XPC 服务实现；Plugin 有隔离 Runner 和小型 IPC ABI，Launcher 也支持
手动、一次性加载。Plugin identity-bound capability、content-addressed Candidate admission、
Trusted Promoter、持久的 digest/scope/slot/expiry-bound activation approval 和完整 Seed 攻击矩阵
仍未实现。详细依据见 `docs/SEED_BACKEND_RESEARCH.md`。

**2026-10-05 Agent Host / local Agent Loop：**签名产品把 CPU-only llama.cpp 与 Qwen2.5-1.5B-
Instruct Q4_0 模型嵌入单独签名、App-Sandboxed 的 Agent Host；本地模型没有远端 provider。真实产品
`--agent` 运行经 launchd-managed XPC 完成一次用户文本输入到 `Khaos: READY.` 的模型往返。
聚焦签名产品测试通过 1 项（41.693 秒），实际检查 Host 子进程对父进程可读 canary 的直接读取和写入
都被 OS 拒绝，并确认原文件与产品深度签名未变。这证明当前签名产品和主机上的最小文本轮次及该
canary 的 App Sandbox 拒绝路径；没有证明模型对其他请求的质量、模型生成的 tool proposal 正确性、
Plugin 准入或用户批准流程已经完成。模型输出仍是不可信输入，工具请求仍由 Launcher 向用户征求
批准，并由 Kernel 在既有 Runner/Sandbox 路径中执行。

当前 changeset 原型对既有文件替换和条目删除使用 macOS
`renameatx_np(RENAME_SWAP)`，并核对被换出的 inode、内容、符号链接目标或目录身份；
检测到 pre-swap 竞争写入时会尝试原子换回并拒绝提交。需要该原语但当前平台或文件系统
不支持时会 fail closed。它仍不是多文件事务，也不能阻止不遵守 Kernel 写入路径的进程并发修改
workspace；因此 Kernel 独占 live-workspace 写入权仍是安全保证的前提。
Broker 的 `workspace.commit` 已将此写回过程移入一次性 Seatbelt 子进程。Kernel 在 sandbox 应用前固定 changeset 与临时项名称；读取仅允许变化源文件、临时项及目录遍历所需的精确路径，没有 workspace 子树的递归读权限。目录数据权限允许枚举直接使用目录中的名称，但不允许读取未列入 scope 的兄弟文件内容或元数据。新安装文件及普通文件临时项只获精确 `file-write*` 权限，已有项、目录项和直接父目录只获精确 `file-write-create` / `file-write-unlink` 权限，不再授予 workspace 子树的递归写权限。读写规则超过 8192 项或生成文本超过 1 MiB 时 fail closed。私有 staging 根仍需完整读写权限。真实 Seatbelt 端到端测试验证新增、修改、删除文件、空目录和 symlink 成功，同时拒绝读取未变化同目录文件的内容和元数据、经待删除 symlink 读取外部 canary、对未变化项写入、对被替换文件直接写入，以及修改父目录权限；canary 保持原值。真实同 UID 目录移出攻击还验证了旧父目录描述符上的 APFS swap 会被 Seatbelt 拒绝，Broker 随后拒绝提交；这些测试不阻止同 UID 进程在仍位于 workspace 内时修改数据，也不能替代 Kernel 对 live workspace 的全局读写仲裁。
`commit_snapshot()` 现在对已打开的源挂载点根目录持有非阻塞 `flock(LOCK_EX)`，让同一挂载点下走
该代码路径的 Khaos Kernel 写回进程互斥，包括嵌套 workspace 根路径；真实子进程测试验证嵌套
workspace 冲突提交在无写入时 fail closed，释放锁后同一 changeset 可提交。该锁是 advisory lock，
只约束遵守锁协议的进程；不能阻止非协作同 UID
进程写入，因此 Kernel 排他仲裁权仍未建立。
commit mutation 会重新打开 workspace 根路径及操作父目录，并对照仍持有的描述符身份；
snapshot baseline 也包含 workspace 根目录的完整 stat signature（含 device/inode），live tree 重扫会据此拒绝
快照后同一路径被替换成新目录的情况。
真实文件系统攻击在空 workspace 完成 snapshot 后移走原根目录并在原路径创建新空目录，Kernel 拒绝候选写入，
原目录与替换目录均保持为空。
trusted Launcher 现在在启动 Kernel Worker 前打开所选 workspace 根目录，并将该目录描述符显式继承给
Worker；snapshot 从该固定 inode 复制，并要求规范路径仍指向同一个 device/inode。真实端到端测试在 Launcher
打开目录后、Worker 启动前移走原目录并在原路径建新目录，Kernel 在执行命令前以 `workspace_rejected` 拒绝，
原目录和替换目录均未收到候选文件。这关闭了 Launcher 到 Worker 之间按路径重新解析导致的授权重定向窗口；
它不阻止其他同 UID 进程在后续时间修改 workspace，也不替代全局写入仲裁。
文件替换/删除在原子 swap 后再次检查父路径，检测到已测的根目录或父目录移出竞态时会拒绝提交，
替换/删除会尝试换回，新增文件/目录会清理本次创建的条目。macOS adversarial tests 真实执行
目录 rename、文件 link、mkdir 和 APFS swap，覆盖描述符打开后、swap 期间以及新增条目后这些窗口。
这些重查和恢复只覆盖具体检查点，不能排除非协作同 UID 写者在检查之间再次改名；Kernel 独占
workspace 写入权仍未建立。
新增的 APFS 跨进程竞态测试让独立同 UID 写者忽略 advisory lock，并在 `RENAME_SWAP` 前分别
替换目标 inode 或原位写入同长度内容；committer 检测到被换出的文件与 baseline 不符后恢复并拒绝提交。
这些测试证明两个真实跨进程窗口会被处理，不代表已排除所有非协作写者竞态。
另一项真实 Seatbelt Broker-path 测试在一次性 commit child 的 live-baseline 和 pre-swap 检查后，
由独立同 UID 写者在 `RENAME_SWAP` 前替换目标 inode。受限 committer 检测到 displaced entry 与 baseline
不符，换回竞争者文件并删除候选临时项，向 Broker 返回 `commit_outcome_uncertain`；目标保留竞争者的
inode 和内容，workspace 与 staging 中均无遗留 Khaos 临时项。该测试证明被测窗口在真实 Seatbelt
write scope 下不会把 Runner 候选覆盖到并发替换项；它不能阻止同 UID 写者在 workspace 内自行修改，
也不建立排他的 live-workspace 写入权。
替换既有普通文件时，committer 从可信源 inode 保留 uid/gid、ACL 和扩展属性，不接受 Runner
输出携带的 ACL 或扩展属性；使用 descriptor-based `fcopyfile` 只复制 ACL/xattrs，不复制数据。
写回前会枚举扩展属性名称并查询其值长度，单次 commit 的名称与值总量上限为 64 MiB、单个名称
列表上限为 1 MiB；不能随替换保留的文件 flags 和超限元数据会在应用 changeset 前拒绝写回。
新增文件和既有文件替换都在从暂存区复制时重新核对扫描阶段记录的大小与 SHA-256；失败注入测试
在 Kernel 扫描后改写新增文件暂存项，确认 Kernel 拒绝安装且真实目标不存在。这证明暂存字节漂移会被
发现，不代表 Kernel 已获得对任意同 UID 写者的独占控制。
新增文件只写入经过摘要核对的数据，并以 `0600` 创建；committer 不复制 Runner 输出中的 ACL 或
xattr。最终安装使用 Apple `fclonefileat` 从仍打开的已验证临时文件 descriptor 原子创建独立 inode，
不再按可被替换的临时路径名解析 clone 源；目标已存在或文件系统不支持该原语时 fail closed。
新建文件和目录仍遵循目标父目录的 OS ACL 继承规则：父目录中带 `file_inherit` 或
`directory_inherit` 的 ACE 会由 macOS/APFS 授予新条目。这些 ACE 属于用户选定工作区已有的
访问策略，不是 Runner changeset 元数据，Kernel 不应为追求 POSIX mode 外观而静默清除它们。
因此 `0600`/`0700` 描述 mode bits；若目标父目录配置了更宽的继承 ACL，新条目的有效访问权限也会更宽。
用户若要求新输出不继承共享权限，应先由用户调整目标目录 ACL。参见 Apple 的
[ACL permission inheritance](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/FileSystemDetails/FileSystemDetails.html)。
真实 APFS 跨进程攻击在安装前把临时路径替换成指向外部 canary 的 hardlink；Kernel 仍提交了
snapshot 中经扫描的 Runner 字节，目标文件保持单链接，外部 canary 内容和链接数不变。该测试关闭
临时源路径替换窗口，不建立对可独立写 live workspace 的任意同 UID 进程的全局仲裁。另一个真实
APFS 跨进程测试让攻击进程在 clone 窗口中把已记录的同一 xattr 改为等长新值，并在 clone 完成后
恢复临时源 inode 上的旧值；Kernel 比对源 descriptor stat 字段和 xattr 名称、长度及值摘要，并将
目标 inode 的属性指纹与 clone 前状态核对，检测变化后拒绝提交并清理新目标。源比较忽略 unlink 临时
路径造成的 link count 与 ctime 变化。它覆盖该 clone 窗口中的被测 xattr 变化，不建立对任意同 UID
写者的全局仲裁。
真实 macOS 文件系统测试在没有继承 ACL 的目标目录中，给新增 snapshot 文件附加 ACL 和 xattr，
确认 Runner metadata 不进入 live workspace，且新文件 mode 为 `0600`。
另一项真实文件系统测试给 snapshot 新目录设置 `0777`、ACL 和 xattr，确认写回目录固定为
`0700`，Runner 目录 ACL/xattr 被丢弃，目录中的新增文件仍为 `0600`。
另一个真实 APFS 测试给目标父目录设置继承 ACL，再让 snapshot 文件与目录携带不同的 Runner ACL；
Kernel 保留目标目录的 ACE，在新文件和目录上按 OS 规则继承，同时不复制 Runner ACE。
这证明 Kernel 区分目标工作区 ACL 策略与 untrusted changeset metadata；mode bits 不承诺覆盖继承 ACL 的授权。
真实 Seatbelt 端到端测试还让受限命令在 snapshot 中创建目录和文件；对目录执行 `chmod` 及原生
`setxattr` 均收到 `EPERM`/`EACCES`，随后 changeset 仍经 Kernel commit，workspace 中目录为
`0700`、新文件为 `0600` 且没有 Runner xattr。单独的 snapshot 元数据攻击测试继续验证即使输入携带
ACL/xattr，Kernel 也不会把它们带回 workspace。
Kernel 先在每个被替换文件的同目录准备随机临时文件并复制可信元数据，再开始 changeset 的目标项
修改。失败注入测试让第二次元数据复制报错，确认既有文件内容不变且临时项被清理；另一项真实
Seatbelt Broker 测试让元数据复制失败并拒绝删除已创建的临时项，确认既有文件内容不变、临时项留存且
Broker 返回 `commit_outcome_uncertain`。因此，只有确认没有 changeset 临时项或目标项残留时才返回
`commit_rejected`；写回或清理结果不确定时返回 `commit_outcome_uncertain`。其他后续 OS 写入故障
仍可能留下部分 changeset；这不是多文件事务。真实 Seatbelt 故障注入测试
在第二次 APFS swap 前失败，观察到第一个文件已替换、第二个文件仍为旧内容，Broker 返回
`commit_outcome_uncertain`。另一项真实 Seatbelt 故障测试在第一次 APFS swap 完成后对 committer
发送 `SIGKILL`，观察到同样的部分写入；目标旁的 `.khaos-*.tmp` 和私有 `khaos-changes-*` staging
目录也留存，Broker 仍报告 `commit_outcome_uncertain`。当前没有 crash-recovery 或自动清理协议，收到
该结果后应先检查 live workspace 和遗留临时项，再决定是否重试。新文件按 0600 创建，既有文件时间戳
随替换更新。该原型仍假设可信的单写者，尚未获得 Kernel 对 live workspace 的独占仲裁权，不能据此
声称已建立完整安全写回边界。
macOS snapshot 与 commit 通过已打开文件描述符读取 `ATTR_VOL_MOUNTPOINT`。源 workspace
及其每个目录/普通文件必须属于捕获的源挂载点；snapshot 及其每个目录/普通文件则必须属于
独立、固定容量 APFS 卷的挂载点。Kernel 分别保存并验证这两个挂载身份，changeset 只在源
挂载点内写回；跨挂载点条目或挂载身份变化都会 fail closed。APFS snapshot 按源卷的 APFS
大小写敏感属性创建；稀疏镜像后备文件放在所选 workspace 树和挂载后的 snapshot 卷之外，
但可能与 workspace 位于同一个宿主 APFS 挂载点，固定容量不代表预留宿主物理磁盘空间。
workspace 包含关系会按各自 mount root 规范化并验证 firmlink 别名，避免路径拼写漏检。
真实测试验证源卷与 snapshot
卷的挂载身份不同，实际命令跨多文件写入触及 APFS 容量后得到 `ENOSPC`，尝试卸载时被 Seatbelt
拒绝，随后剩余 changeset 仍通过可信扫描并只写回 disposable workspace。直接卸载测试增加了
同用户的未沙箱正向对照：该用户能卸载控制卷，但对 Kernel snapshot 调用同一 `unmount(2)` 被
Seatbelt 以 `EPERM` 或 `EACCES` 拒绝，命令之后仍能写入 snapshot。一次真实 macOS 实验
将临时 APFS 稀疏磁盘映像挂载到 workspace 子目录，snapshot 因 `st_dev` 不同而拒绝了该嵌套
卷。另一项真实 APFS 写回攻击在 snapshot 创建后向 live workspace 添加嵌套卷；Kernel 扫描源
workspace 时拒绝 commit，候选文件没有部分写回。上述真实嵌套卷因 `st_dev` 不同被拒绝；同设备、
不同挂载点的分支仍由 descriptor 测试验证。新增真实同卷探测在同一 disposable APFS 卷上建立
workspace 与外部 canary，snapshot 后由同 UID Host 尝试把该卷重复挂到 workspace 子目录；当前 macOS
27.0 返回 75（`Operation already in progress`），mount root 未改变，随后安全 candidate 仍由 Kernel 写回。
由于 OS 拒绝建立重复挂载，Kernel 对真实同设备、不同挂载点的拒绝分支仍未实测；测试已预置为若未来
OS 允许挂载，则必须读到 canary 并验证 Kernel 拒绝 changeset。不可信 command Runner
的 Seatbelt profile 拒绝 `mount` / `unmount` 系统调用，真实集成攻击也确认 `hdiutil` 与
`diskutil image attach` 在可信宿主控制中可挂载 workspace 镜像、在 Runner 中则失败。另一项直接 APFS
测试先由同 UID Host 通过 `/sbin/mount_apfs` 成功把镜像只读挂到 disposable workspace 目标；Runner
尝试启动同一 helper 时收到 `EPERM` 或 `EACCES`，目标仍未挂载。Runner 还直接调用 `libc.mount()`：
故意传入空 APFS 参数时，Host 控制返回 `EFAULT`，真实 Seatbelt Runner 则返回 `EPERM` 或 `EACCES`，
证明 `SYS_mount` 规则在参数验证前拒绝了系统调用；该原始调用没有使用有效的 APFS mount 参数结构。
这些差分证明了所测 Disk Arbitration、APFS helper 和原始 syscall 路径在当前主机上的拒绝。Apple 的
[`mount(2)` 文档](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/mount.2.html)
描述了 OS 权限本身可能返回 `EPERM` 的条件。特权宿主进程并发改变挂载状态仍未覆盖。

Seed 的完成不以“命令返回成功”为准，而以以下安全测试全部通过为准：

```text
filesystem: traversal / symlink / hardlink / rename race / TOCTOU
process: timeout / cancellation / descendant cleanup / daemonization / quotas
network: deny by default / localhost / DNS / IPv4 / IPv6 / proxy / child process
secret: environment / argv / inherited fd / log and error redaction
plugin: direct OS access / cross-plugin storage / capability escalation
promotion: digest binding / stale approval / crash during activation / rollback
failure: missing sandbox backend must not run on Host
```

每项测试都必须针对真实 OS enforcement，而不是只测试 Python facade 或命令黑名单。

明确不包含：

```text
Memory
Planner
Subagent
Browser
Scheduler
MCP
复杂 Verification
Evolution
```

---

# 46. Khaos Seed 的真正目的

不是“做出很多功能”。

而是验证：

> **这个架构真的足够小，同时安全边界真的成立。**

如果 Seed 已经变得很复杂，应立即停止新增功能。

---

# 47. 第二阶段：Plugin Harness

目标：

```text
Plugin Manifest
Plugin install
Plugin enable
Plugin disable
Plugin version
Plugin storage
Plugin capability
Plugin rollback
```

完成后 Harness 才真正具备：

> 可替换器官。

---

# 48. 第三阶段：Memory Evolution

加入：

```text
memory-simple
```

再加入：

```text
memory candidate generation
shadow evaluation
plugin swap
rollback
```

Memory 应成为第一个完整 self-evolution demo。

---

# 49. 第四阶段：Skill / Tool Evolution

允许 Agent 发现：

```text
某个工作流反复出现
```

然后生成：

```text
Skill
Script
Tool Plugin
```

候选能力依然必须经过：

```text
user approval
sandbox
tests
evaluation
activation approval
```

---

# 50. 第五阶段：Harness Evolution

允许 Agent 改进：

```text
Context Plugin
Planner
Verifier
Model Routing
Agent Strategy
```

这时才真正进入：

> Self-Evolving Harness。

---

# 51. 第六阶段：Meta Evolution

允许：

```text
Evolver Plugin
```

被替换。

最终：

```text
Agent
can improve
how the Agent improves.
```

但 Kernel 仍然固定。

---

# 52. 旧 Khaos 如何使用

旧 Khaos 不再是开发基础。

它是：

```text
security knowledge base
implementation reference
bug archive
test case source
```

使用方式：

当新项目需要：

```text
symlink-safe write
```

去旧项目研究。

需要：

```text
process tree termination
```

去旧项目研究。

需要：

```text
macOS sandbox
```

去旧项目研究。

但不要复制整个 subsystem。

原则：

> **Copy invariants, not architecture.**

---

# 53. 最值得从旧 Khaos 迁移的知识

重点保留：

```text
filesystem race lessons
symlink / hardlink escape lessons
sandbox fail-closed behavior
process cancellation lessons
process-tree cleanup
environment isolation
secret handling
network boundary
OS sandbox implementation experience
```

不要迁移：

```text
TaskManager
Scheduler
CompletionGate
Recovery
Authority receipt
principal hierarchy
RPC security architecture
enterprise audit architecture
```

---

# 54. 开发过程中最重要的问题

每次准备增加一个模块之前都问：

> 它属于 Intelligence，还是 Authority？

如果属于 Intelligence：

```text
Plugin
```

如果属于 Authority：

```text
Kernel
```

如果两者都不是：

> 很可能不需要。

---

# 55. 第二个判断问题

对于任何想放入 Kernel 的功能，问：

> 如果 Agent 可以替换它，会不会导致 Agent 获得更多系统权限？

如果答案：

```text
是
```

它可能属于 Kernel。

如果答案：

```text
否
```

大概率应该是 Plugin。

---

# 56. 第三个判断问题

对于任何 Core 功能：

> 删除以后，损失的是今天真实需要的能力，还是未来可能需要的扩展性？

如果只是：

```text
未来扩展性
```

删除。

---

# 57. 项目哲学

Khaos 不追求：

> 功能最多。

而追求：

> 核心最小，同时允许能力无限增长。

因此：

```text
Core remains small.
Capabilities grow outside.
```

---

# 58. Self-Evolution 的最终形态

最终希望 Khaos 能够出现这样的行为：

```text
Khaos:
“过去 20 次任务中，当前 Memory Plugin
有 38% 的检索结果最终没有被使用。

我认为当前 Memory 的检索策略不适合这个项目。

我想开发一个新的 memory-v2：

- 保留长期项目事实
- 增加 recency decay
- 根据 tool outcome 调整 importance
- 不增加网络权限

是否允许我开发 Candidate？”
```

用户：

```text
允许
```

然后：

```text
Khaos
  ↓
create candidate
  ↓
sandbox
  ↓
test
  ↓
shadow evaluation
  ↓
compare
```

之后：

```text
Khaos:
“memory-v2 在最近 15 次任务中：

relevant recall +24%
unused recall -31%
token consumption -18%

是否替换当前 memory-v1？”
```

用户：

```text
允许
```

然后：

```text
memory-v1 → standby
memory-v2 → active
```

整个过程中：

```text
Security Kernel
```

完全没有改变。

这就是 Khaos 的核心产品体验。

---

# 59. 最终架构哲学

Khaos 的智能层应该像一个生命体：

```text
不断尝试
不断学习
不断替换能力
不断淘汰低效组件
```

Security Kernel 则像物理定律：

```text
稳定
简单
不可谈判
不参与进化
```

所以最终：

```text
          EVOLUTION

   Prompt
   Context
   Memory
   Planner
   Skills
   Tools
   Verifier
   Evolver
      ↓
      ↓
      ↓

══════════════════════════
      SECURITY ABI
══════════════════════════

   Filesystem
   Process
   Network
   Secrets
   Capability
   Approval

══════════════════════════
          OS
══════════════════════════
```

---

# 60. Khaos Constitution

以下规则视为 Khaos vNext 的架构宪法。

**Rule 1**

Security Kernel 不允许自我修改。

**Rule 2**

Harness 所有智能能力原则上都应该可替换。

**Rule 3**

所有副作用必须穿过 Kernel。

**Rule 4**

Plugin 永远默认不可信。

**Rule 5**

Plugin 不允许提升自身权限。

**Rule 6**

Evolution 只能改变 Intelligence，不能改变 Authority。

**Rule 7**

所有 Evolution 必须可观察、可测试、可回滚。

**Rule 8**

高风险 Evolution 必须由用户批准。

**Rule 9**

安全边界失败必须 fail closed，不允许 silent fallback。

**Rule 10**

任何新增 Core complexity 都必须由当前真实需求证明，而不是为了未来可能存在的场景。

**Rule 11**

安全边界必须由独立进程、IPC 和 OS enforcement 实现，不能由语言对象或命令黑名单替代。

**Rule 12**

数据读取权限和副作用权限同等重要；Plugin、Event Bus 和 Model Adapter 都必须遵守
显式的数据范围。

---

# 61. 项目最终目标

Khaos 最终不是一个：

> “功能丰富的 Agent Runtime Platform”。

而是：

> **一个足够小，使 Agent 可以理解和重构自己的 Harness；又足够安全，使 Harness 可以大胆进化而无法突破宿主边界的本地 Agent。**

最终公式：

```text
Khaos
=
Immutable Security Microkernel
+
Minimal Untrusted Agent Host
+
Trusted Security ABI / Promoter
+
Evolvable Plugin Graph
+
LLM
```

其中：

```text
Kernel, Security ABI and Trusted Promoter stay.

Only the intelligence layer above them may evolve.
```

**2026-09-28 最新交互尝试：**用户确认产品 app 显示 PASS 后，重新运行当前 WorkspaceGrant XPC 攻击测试。新 helper 已被系统确认处于前台，临时 workspace 为 /var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-xpc-sandbox-xfgwfbv2/user-selected-workspace；300 秒内没有目录选择，focused test 在 379.907 秒后以 subprocess.TimeoutExpired 结束并清理 fixture。因此本次没有执行 Picker scope 写拒绝、非空 Kernel commit、恶意 changeset 或 cancellation 断言；这是缺少交互选择，不是攻击断言失败。

**2026-09-29 产品包 XPC 攻击预检：**新增的 test-only driver 被装入临时产品包后，仍满足 `KernelProduction.xpc` 中固定的 Launcher code-signing requirement；原 XPC service 未改动。headless 预检通过（1 项，10.766 秒），并收到真实 service 的 authenticated idle-cancellation 响应，但没有访问 workspace。交互模式曾在选中目录后暴露两个测试边界问题：产品 App Sandbox 在 Picker scope 释放后拒绝 driver 回读 committed file；后续一次原始 `EPERM` 与 driver 在沙箱内发现 cancellation child 的 `/bin/ps` 路径相符。文件核验已移到外部测试父进程，取消阶段现等待该父进程观察唯一随机 sleep child 后再发送信号，不增加产品 entitlement。一次历史交互运行等待 600 秒未获目录选择并清理 fixture。之后当前交互测试在 135.293 秒通过：父进程验证安全 changeset 提交、直接写拒绝、symlink/special-file 拒绝、hardlink 在 OS 创建或 Kernel commit 阶段拒绝、取消连接绑定、后代退出、无取消写回、服务恢复、canary 与 fixture 完整、深度签名有效且签名 Python.framework 无新增 `__pycache__`。此证据来自临时产品 bundle 副本中的 test-only driver，且不证明 Candidate admission 或生产 Launcher 执行任意 Plugin。

**2026-09-29 Picker UI 观察补充：**用户报告 Picker 显示 `PASS`，并确认当时打开的是 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-picker-b_oua14q/Workspace`；当次提示的新鲜目录为 `.../khaos-seed-picker-hsk30_5i/Workspace`。新包进程随后退出，临时 workspace 未变化，日志没有结果记录。用户在后续复核中再次确认弹窗显示 `PASS`，但没有残留进程、对应的新鲜 fixture 或 bundle 身份记录能将该弹窗与 ABI v5 自动化验收关联。该结果作为用户观察记录；它不能单独证明该自动化验收通过。

**2026-09-29 新增文件 post-clone 竞态修复：**真实 Broker/Seatbelt commit-child 攻击测试发现，APFS clone 创建新增目标后、Kernel 验证其字节前记录 inode，会让失败清理误删并发写者刚替换进去的同长度文件。当前实现仅在目标仍绑定到已打开 inode且大小、SHA-256、类型和链接数通过校验后，才允许按 inode 清理；真实独立进程在该窗口替换目标后，commit 返回 `commit_outcome_uncertain`，竞争文件的 inode 与内容保留。新的真实 Seatbelt 回归和五项 focused APFS 新文件测试通过。该修复只覆盖已同步验证的竞态窗口，未建立对任意同 UID 写者的全局仲裁或多文件事务。

改动后的 canonical `python3 -m unittest discover -s tests -v` 通过全部 189 项，耗时 366.991 秒；默认 suite 不打开交互式 Picker。

**2026-09-29 修改文件 prepared-temp cleanup 竞态修复：**真实 Broker/Seatbelt 测试在 Kernel 完成 modified-file preflight 后、首次校验前，用独立 same-UID 进程把竞争 inode 原子替换到 prepared 临时路径。旧失败清理会删除竞争文件并返回普通拒绝。现在清理通过单独 Seatbelt 精确授权的 sentinel 做原子交换，仅在 displaced inode 与创建时记录的 inode 一致时移除；不一致时恢复路径并报告 `commit_outcome_uncertain`。攻击测试确认原 workspace 文件保持 baseline，竞争文件的内容与 inode 保留。workspace changes、Seatbelt 和相关 Broker 测试共 81 项通过，耗时 113.807 秒；canonical suite 通过 190 项，耗时 368.974 秒，且不会打开交互式 Picker。该证据只覆盖同步测试的 preflight cleanup 窗口，不建立对任意 same-UID 写者的全局写入排他。

**2026-09-29 产品包 Picker 写回重试：**按仓库定义启动新签名 Seed bundle 和 fresh disposable workspace；300 秒内 Picker 写回流程未完成。最后一次 workspace 检查只有初始 fixture，测试结束后确认临时 bundle 目录和 KhaosSeed 进程均已清理。本次没有写回结果，也不能说明 Picker 未显示或选择失败的具体原因。此前超时分支会在读取 stderr 前中止；现改为先终止应用再读取诊断和 workspace 条目摘要，并增加了超时诊断回归。该回归单测通过，不构成产品写回证据。

**2026-09-29 Picker 精确路径提示重试：**产品 Launcher 现在会在 `--picker-start-directory` 验收模式的 system Picker message 中显示本次 fresh workspace 完整路径；该文本只是选择提示，Kernel 仍只使用用户在 Picker 中实际选择的 bookmark。签名包构建与 service 身份测试通过（1 项，8.807 秒）。交互测试打印并显示 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-ujujb7cq/user-selected-writeback-workspace`，但 300 秒内没有选择到达测试进程；fixture 仍是唯一条目（41 字节），marker 数量为 0，stderr 只有 `sandbox_extension_issue_file_to_process` warning。fixture 和 helper 已清理。本次不能证明 Picker 是否可见，也没有增加所选 workspace 或写回证据。

**2026-09-29 prepared-file cleanup stat 竞态补充：**真实 Broker/Seatbelt 测试在清理已准备文件的初始 inode 检查后、sentinel 原子交换前暂停 committer，由独立 same-UID 写者替换临时路径。committer 核对交换出的 device/inode 与准备阶段 descriptor 身份不符后恢复竞争项，并返回 `commit_outcome_uncertain`；baseline 文件不变，竞争 inode 与内容保留。清理也重新验证 parent-directory binding。如果 parent binding 已变化或 atomic swap 不可用，系统保留 prepared entry 并报告不确定结果，需要检查 workspace 后再重试。该测试仅证明同步覆盖的 pre-exchange 窗口，不能排除所有非协作 same-UID 写者，也不构成多文件事务。

该修复及保留临时项断言后的 canonical `python3 -m unittest discover -s tests -v` 通过 192 项，耗时 384.108 秒；suite 不打开交互式 Picker。

**2026-09-29 Picker acceptance guard 补充：**验收专用 Launcher 参数已从只设置初始目录的 `--picker-start-directory` 收敛为 `--acceptance-workspace`：它设置初始目录，并要求 Picker 返回的标准化、解析符号链接后的 URL 与请求路径相同，否则返回 `selected_workspace_mismatch`。该参数不授予 workspace 权限；Kernel 的授权仍来自用户选择的 bookmark。Launcher 新增不含路径的 `picker-requested` 和 `workspace-selected` 阶段诊断。签名包构建及 service authentication focused test 通过（1 项，7.707 秒）。其后的交互尝试超时，fresh workspace 检查只有 fixture、没有 marker；用户报告弹窗显示 `PASS`，但没有成功诊断或文件结果将该观察关联到本次 fixture 或 bundle。那次交互二进制早于阶段诊断。本轮源码已含精确路径检查与诊断，尚未在交互运行中验证两者。

**2026-09-29 当前源码 Picker 重试：**使用带 `--acceptance-workspace` 的当前源码构建签名产品包，测试进程收到 `workspace-kernel-smoke=picker-requested`，但 300 秒内没有目录选择或 `workspace-selected`，随后超时退出。最后检查仅含 41 字节 fixture（`entry_count=1`、`marker_count=0`）；日志另含 `sandbox_extension_issue_file_to_process ... Operation not permitted`，原因未确认。测试与 app 进程已退出，临时 bundle 已清理。此结果确认当前交互验收仍未完成，但不能确定 Picker 是否可见，也不能解释用户此前报告的 `PASS`。

**2026-09-29 产品 Picker 前台诊断：**测试直接执行签名 Launcher 以捕获 path-free stderr；此前 Finder 留在前台。AppKit `activate()` 请求没有切换前台。当前交互测试等待 `picker-requested` 后调用 `/usr/bin/open -a`（不带 `-n`），对 Launch Services `-600` 有界重试最多 20 次、间隔 250 ms。系统查询确认 `KhaosSeed` 成为 frontmost，测试观察到一个匹配进程。随后运行仍因 300 秒内未收到目录选择而超时：没有 `workspace-selected`、只有 41 字节 fixture 且 marker 数量为 0；`sandbox_extension_issue_file_to_process` warning 的原因未确认。进程与临时包已清理。此修复让当前测试构建在本机进入前台，但不证明系统 Picker 可见或真实 workspace 写回成功。

用户随后确认这次看到了 `PASS` 弹窗。自动化记录仍没有 `workspace-selected` 或成功诊断，fresh workspace 在清理前只有初始 fixture、没有 marker；因此记录为用户观察到的 UI 结果，不能据此认定当前源码的所选 workspace 写回验收通过。

**2026-09-29 changeset post-clone 竞争替换证据收紧：**真实 Broker/Seatbelt commit-child 回归现在让并发竞争文件与候选文件具有相同 owner、`0600` mode、单链接数和长度，只让内容不同，从而直接经过 Kernel 对扫描候选 SHA-256 的验证。攻击被拒绝，竞争者 inode 和字节保留；`commit_child` 组 8 项通过（13.301 秒），canonical suite 193 项通过（375.225 秒）。这证明该同步窗口内仅内容摘要不匹配也会被拒绝，不代表对任意同 UID 写者的全局互斥。

**2026-09-29 acceptance Picker 导航与选择前读取拒绝：**验收专用 Launcher 将系统 `NSOpenPanel` 的初始目录设为指定 workspace 的父目录，并要求用户选择准确的 workspace 子目录。显示路径之前，Launcher 对已知 fixture 执行真实 `open(O_RDONLY | O_NOFOLLOW)`，只接受 `EPERM` 或 `EACCES`。签名产品包与 Kernel service 身份 focused test 通过（1 项，7.795 秒）。交互重试记录 `preselection-read=denied` 与 `picker-requested`，CoreGraphics 确认 Picker 窗口可见；但 300 秒没有目录选择，focused test 307.703 秒失败，检查到 workspace 只有 41 字节 fixture、没有 marker。临时包与目录随测试清理。该运行证明当前主机上显示 Picker 前直接读取被拒绝，不证明 Picker 打开后的访问状态，也不构成本次写回成功。用户报告的 `PASS` 保留为独立 UI 观察，未能关联到本次 fixture 或 bundle。Apple 将 `directoryURL` 定义为面板显示的目录，并说明系统对用户选择的 URL 扩展 App Sandbox；此实现没有改变授权来源，Kernel 仍只接收 Picker 返回的 bookmark。随后将读、写两种 OS denial probe 合并为一个 Launcher helper；改后 focused package test 通过（7.967 秒），timeout 诊断回归通过，canonical suite 通过 193 项（367.608 秒），默认套件未打开 Picker。

**2026-09-29 默认 Seed suite 纳入产品 XPC 请求边界攻击：**产品包身份测试默认在临时签名 bundle 中用 test-only Launcher 向真实 `KernelProduction.xpc` 发送 source 与 SHA-256 不匹配且不带 bookmark 的 `workspace.run`，服务在 bookmark 处理前返回 `invalid_request`，fixture 与 sibling canary 未变。默认路径还发送超过 8 层结构深度的有界 JSON 请求；Swift parser 在 Foundation 解码前拒绝它，随后服务仍能回复新的 idle-cancellation 请求。当前 envelope 最深为 3 层，字符串中的括号不计深度。两项 UI 环境变量都未设置时，focused signed-product test 通过（1 项，10.429 秒），canonical `python3 -m unittest discover -s tests -v` 通过全部 193 项（394.905 秒）。默认 suite 不打开 Picker，也不新增所选 workspace 写回证据。内容摘要只证明 source 完整性，不代表 Candidate 授权；Manifest、scope approval 和生产 Candidate admission 仍未实现。

**2026-09-29 产品 Picker 写回验收确认：**用户选择了 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace` 并看到 `PASS`。与这次交互关联的签名 acceptance-bundle 测试通过（1 项，103.483 秒），按顺序验证 Picker 前读取被拒绝、选择后 scoped 读取成功、scope 释放后读取被拒绝、Kernel 写回及 direct-write denial；fixture 保持不变，并检查恰有一个 `0600` 单链接 Kernel marker 和成功的 strict deep signature。临时 bundle 和 workspace 已由测试清理。这证明该 acceptance bundle 在当前 macOS 主机上的选择与写回路径，不代表生产 app 身份、Candidate admission、approval binding 或一般 Plugin 执行。

**2026-09-29 当前工作树 Seed suite 复验：**按 `AGENTS.md` 运行 `python3 -m unittest discover -s tests -v`，199 项通过，耗时 382.671 秒，覆盖当前 macOS Seatbelt、APFS、IPC、XPC 和 changeset 测试。此次未设置交互式 Picker 环境变量；结果不证明 Picker 以外的生产授权、任意同 UID 写入排他或 Candidate admission。

**2026-09-29 打包 Runner 对 Kernel 代码的真实写入拒绝：**签名产品包 focused test 使用包内嵌的 Python、Kernel Worker 和 Runner，通过受信任的测试 launcher 调用真实 Seatbelt 路径。Runner source 针对实际 `KernelProduction.xpc/Contents/Resources/khaos/kernel/workspace_changes.py` 执行 `open(O_WRONLY)`；只有 OS 返回 `EPERM` 或 `EACCES` 才继续。随后同一运行由受限命令写入 snapshot，并经 Kernel 正常提交一个 `0600` 单链接文件；Kernel 源文件摘要不变，`codesign --verify --deep --strict` 通过。聚焦产品包测试通过（1 项，25.072 秒），修改后的 canonical `python3 -m unittest discover -s tests -v` 随后通过全部 199 项（402.379 秒）。此项验证产品包内实际代码路径的 Runner→Kernel 写隔离，不是 XPC 调用方授权、Picker scope、安装更新完整性或抵御包外非沙箱同 UID 进程的证明。

这就是 Khaos vNext。

**2026-09-30 normal product Launcher selected-workspace writeback：**按仓库定义的交互验收通过（1 项，95.427 秒，exit code 0）。用户在正常本机签名 `KhaosSeed.app` 的 Picker 中选择临时 workspace 后，同一次运行验证选择前读取拒绝、Picker scope 有效时读取成功、Launcher 释放 scope 后读取拒绝、Kernel 提交一个预期 marker，以及 Launcher 直接写打开该 marker 被 OS 拒绝。测试父进程在清理前核对 fixture digest/link count、精确 workspace 条目、marker 内容与 `0600`/单链接属性、deep code signature，以及签名 Python.framework 无 `__pycache__`。这证明当前主机上固定 Product smoke 的真实选择与写回路径；Launcher 仍运行固定 Runner source，不证明任意 Plugin 执行、Candidate/Manifest admission、activation approval、安装保护或发行签名。

**2026-09-30 Product Launcher read/list 集成尝试：**固定 Runner source 增加验收专用精确 fixture scope：要求通过 Kernel IPC 读取 `seed-picker-fixture.txt`，根目录列表只返回该 fixture，并在 `process.exec` / commit 前验证现存 sibling 的读取与直接目录枚举分别被拒绝。普通无参数启动仍发送空 read scope，并在固定 source 中验证默认拒绝。签名产品包及 headless service/authentication focused test 通过（1 项，14.968 秒）。新版交互验收等待 300 秒未收到目录选择，诊断仅到 `preselection-read=denied` 和 `picker-requested`；fresh workspace 保留两个初始 fixture，没有 marker，因此本次未执行 Runner read/list、Kernel commit 或 Picker 后的签名断言。用户此前报告的 PASS 来自不同临时 workspace，不能归属于本次构建。故 Kernel 现有精确 scope 仍有 Product XPC test-only Runner 的真实证据，但普通 Launcher 中这段新增集成尚未获得运行时证明；不得声称已验证。

**2026-09-30 fixed Launcher read/list Picker retry：**用户报告的 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace` 对应先前 acceptance-bundle PASS，不是新增 Runner read/list 的证据。为当前源码另建签名 app 和 workspace `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-107zf9i5/user-selected-writeback-workspace`。系统查询确认 `KhaosSeed` 位于前台，但 300 秒内未收到选择或取消；focused test 322.357 秒后失败，workspace 仍只有两个 fixture、无 marker，日志止于 `preselection-read=denied` 和 `picker-requested`。本次没有执行 Runner read/list、Kernel writeback 或 Picker 后签名检查，故新版普通 Launcher 集成仍未验证。

**2026-09-30 Seatbelt Runner inherited-FD denial：**新增真实 macOS Seatbelt 端到端攻击：宿主进程打开并标记可继承的敏感 pipe FD；恶意 Runner 与其固定命令分别用 `fstat` 尝试确认该 FD 存在，只有二者都观察到 `EBADF` 才继续。测试还由宿主在执行后读回原始 secret，确认没有被消费；Runner 经 Kernel 正常结束，changeset 为空。focused test 通过（1 项，3.506 秒）；既有宿主环境隔离和 Seatbelt pipe-FD 测试通过（各 1 项）；完整 `test_launcher.py` 模块通过 28 项（106.587 秒）。canonical 全量 suite 未在添加本测试后重跑。该证据覆盖本机测试 backend 的 Runner/命令 descriptor closure，不证明 XPC 的 Candidate admission 或其它任意 descriptor 组合。

**2026-09-30 fixed Launcher read/list Picker 再验收：**用户再次报告先前路径 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace` 显示 `PASS`；该路径属于已清理的旧 acceptance bundle。本轮为当前固定 Runner read/list 源码重新构建签名产品包，workspace 为 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-m3629ih1/user-selected-writeback-workspace`。测试在 300 秒内未收到选择或取消，311.971 秒失败并清理临时包与 workspace；实际日志仅有 `preselection-read=denied` 和 `picker-requested`，workspace 仍是两个原始 fixture、无 Kernel marker。故本轮没有执行 Runner scoped read/list、scope 释放后的 OS 拒绝、Kernel 写回或选择后的签名检查。旧 `3mfj1nf_` PASS 仍只证明旧 acceptance bundle 的读写链路，不能证明当前固定 Launcher read/list 集成。

**2026-09-30 Picker 结果确认与 Unix socket changeset 拒绝：**用户再次确认重新打开 Picker 后，选择 `.../khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace` 并看到 `PASS`。接受为用户观察到的 Launcher 成功结果；当前 Launcher 源码仅在 scoped read/list、scope 释放后的 OS 拒绝、Kernel 写回和 direct-write 拒绝都通过后显示 PASS。该临时路径和进程随后已清理，且没有该轮 bundle/source digest 或测试父进程输出，因此不能独立验证该次的 deep-signature 断言，也不将结果归给另一条 `m3629ih1` 超时运行。仓库仍保留同一路径对应的 103.483 秒 acceptance-bundle 成功记录。changeset 侧新增真实 AF_UNIX socket 输出攻击：直接在 APFS snapshot 中构造 socket 后，Kernel 在扫描阶段拒绝 changeset，搭配的普通新增文件与既有文件替换没有部分写入（1 项，1.608 秒）。另一个真实 Seatbelt Runner 测试通过标准 `process.exec` 尝试 `AF_UNIX bind`；当前主机由 Seatbelt 返回 `EPERM`，Runner 不产生 socket 或安全伴随文件，并正常提交空 changeset（1 项，3.569 秒）。完整 `test_launcher.py` 模块通过 29 项（109.945 秒）。OS 拒绝与 Kernel scanner 拒绝是两项不同证据；本机实跑到的是前者，若未来 sandbox 允许创建，该 changeset 仍会被后者拒绝。

该改动后的 canonical `python3 -m unittest discover -s tests -v` 通过全部 212 项（427.651 秒）；产品 XPC 检查为 headless，没有打开 Picker，也没有把 `m3629ih1` 的超时改写为成功证据。

**2026-09-30 当前 Product Launcher 全链路验收重试：**按 `AGENTS.md` 设置 `KHAOS_RUN_PRODUCT_WRITEBACK_UI=1` 启动当前签名产品包；测试打印新目录 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-ebiza556/user-selected-writeback-workspace`，300 秒内未收到用户选择，312.038 秒后失败并清理临时 bundle/workspace。诊断仅包含 `preselection-read=denied` 和 `picker-requested`；workspace 有两份原始 fixture、无 marker，因此没有执行 Runner scoped read/list/write、Kernel commit 或 post-run signature check。用户报告的 `3mfj1nf_` PASS 是不同的旧临时目录，不能证明这次失败的自动化运行已完成。当前 normal Launcher 的最新验收仍未验证；其下层真实 Seatbelt 与 test-only Product XPC 证据不受此 Picker timeout 影响。

**2026-09-30 Picker 导航提示与当前 Launcher 重试：**交互测试现在明确打印 ⌘⇧G 导航步骤与 fresh workspace 完整路径，并在 timeout 回归中断言提示包含该快捷键和对应路径；回归通过（1 项，0.002 秒）。再次按 `AGENTS.md` 启动当前签名 Product Launcher，fresh workspace 为 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-rx5bn0nu/user-selected-writeback-workspace`。运行约 3 分钟时系统前台应用为 `KhaosSeed`，但日志仍只有 `preselection-read=denied` 与 `picker-requested`；300 秒内未收到选择，测试在 312.321 秒失败并清理。workspace 只有两个 fixture（41 与 27 字节）、无 marker。故本轮未执行 scoped Runner read/list/write、Kernel commit、scope 释放后拒绝或 post-run signature check。用户报告的 `3mfj1nf_` PASS 保持为单独观察，不能归给这次 timeout。

**2026-10-01 canonical suite 复验：**当前工作树运行 `python3 -m unittest discover -s tests -v`，212 项全部通过，耗时 437.331 秒。涵盖现有 Broker/IPC/真实 macOS Seatbelt、XPC peer identity、changeset 竞态和 prompt timeout regression。产品 XPC 检查为 headless；该套件不打开 Picker，不会为 selected-workspace Launcher 路径增加交互证据。后续用户报告的 PASS 单独记录如下。

**2026-10-01 Product Launcher Picker 结果：**用户重新打开 Picker，选择报告路径 `.../khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace` 并看到 `PASS`。当前 Launcher 只有在 scoped Runner read/list allow/deny、Picker scope 释放后的真实 OS 读取拒绝、Runner `fs.write` allow/deny、Kernel commit 和 Launcher direct-write denial 均通过后才显示该弹窗；因此记录为这些执行门槛的用户观察证据。进程与临时 app/workspace 已清理，未保留本轮测试父进程退出状态或 bundle/source digest，故不能将该观察扩写为本轮 deep-signature 成功。它与早先 103.483 秒 acceptance-bundle 签名检查记录、以及 `rx5bn0nu` 的未选择超时分别保留，不互相替代。

**2026-10-01 macOS workspace ACL 继承：**真实 APFS changeset 测试在目标 workspace root 配置 `file_inherit`/`directory_inherit` ACE，并在 snapshot 输出中放入不同的 Runner ACL。Kernel 写回后 root 的 ACL 不变，新建目录和文件继承 root 对应 ACE，Runner ACL 未进入 live workspace；mode bits 仍为 `0700`/`0600`。ACL 相关 focused tests 通过 4 项（6.599 秒），随后 canonical `python3 -m unittest discover -s tests -v` 通过全部 213 项（423.624 秒）。这是所选目录的 OS 权限策略，不是 Runner 获得的权限；有效 ACL 可比 mode bits 更宽，因此实现保留继承规则且不把 `0600`/`0700` 表述为有效访问控制的上限。

**2026-10-01 workspace root FD 隔离：**新增真实 macOS Seatbelt 测试将 Launcher 传给 Kernel Worker 的 live-workspace 根目录 descriptor 固定为 FD 200。Runner source 尝试对该 descriptor 执行 `fstat`、`openat` 读取 fixture 与创建 live 文件；固定命令尝试从该 descriptor 通过 `..` 创建 workspace 外文件。两端都必须收到 `EBADF`，随后 Kernel 成功提交空 changeset，live fixture 与外部 canary 均不变。focused test 通过（1 项，3.743 秒）。这证明当前测试 launcher → Kernel Worker → Runner / command 的实际 FD 关闭路径，不覆盖 unconfined 同 UID 进程的写入仲裁。

**2026-10-01 Kernel commit 后 Runner 写入拒绝：**真实 Seatbelt 集成测试覆盖 Worker 先返回 commit 结果、再关闭 IPC 并等待 Runner 退出的尾部窗口。Runner 在成功 commit 后仍存活时，直接写刚提交的 live 文件必须得到 `EPERM` / `EACCES`，迟到的 `fs.write` 必须因 Kernel IPC pipe 已关闭而失败；workspace 保留 Kernel 验证后的内容。Worker 在有界等待后会终止仍运行的 Runner，且该清理超时不能把已确认的 commit 降级为 `runner_failed`：恶意 Runner 永久循环的真实 Seatbelt 测试确认 Worker 返回成功结果，提交文件内容正确（1 项，8.698 秒）。post-commit 写入拒绝回归在 Worker 修复后通过（1 项，3.728 秒）。修复后的 `test_launcher.py` 真实 macOS 模块测试通过 31 项（125.383 秒），`test_worker.py` 通过 7 项（0.007 秒）；之后 canonical `python3 -m unittest discover -s tests -v` 通过 215 项（438.268 秒），不打开 Picker。这些是当前 Worker / Runner 路径的 OS 写拒绝与 IPC 生命周期证据，不代表产品 bundle 专项复验，也不排除 unconfined 同 UID 进程。

**2026-10-01 final-unlink symlink 目标隔离：**保留的真实 Broker/Seatbelt 攻击在 commit child 完成 sentinel inode 校验、即将对 workspace 内恢复路径执行 `unlink` 时暂停；独立同 UID 进程把该目录项原子替换为指向 workspace 外 canary 的 symlink。commit child 随后完成经过验证的文件替换，只删除 symlink 本身，outside canary 字节保持不变。focused test 通过（1 项，11.996 秒）。该结果证明最终 pathname unlink 不跟随被竞态替换的 symlink 目标；它不消除 check-to-unlink 竞态，普通竞争文件仍可能在授权 workspace 内被删除，也不建立全局同 UID 写仲裁。

**2026-10-01 symlink 竞态后的完整验证：**`tests/test_broker.py` 通过 39 项（73.577 秒）；canonical `python3 -m unittest discover -s tests -v` 通过全部 216 项（441.428 秒）。真实 macOS suite 未打开 Picker；本次新证据只收紧 final `unlink` 遇到外部 symlink 时的路径范围结论，不覆盖 arbitrary same-UID 写仲裁。

**2026-10-01 当前 Product Launcher read/list 复验：**canonical `python3 -m unittest discover -s tests -v` 通过 217 项（452.195 秒），但默认 suite 不打开 Picker。随后按 `AGENTS.md` 启动当前源码构建的签名 Product Launcher 验收，fresh workspace 为 `/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-od7g0_lr/user-selected-writeback-workspace`；300 秒内没有 selection 到达测试。测试于 311.939 秒失败并清理临时 bundle/workspace，日志仅有 `preselection-read=denied` 与 `picker-requested`，目录保留两份 fixture、没有 marker。因此本轮没有执行 scoped Runner read/list/write、Kernel commit、scope 释放后的 OS 拒绝或父进程签名验证。用户报告的 `3mfj1nf_` PASS 是独立的旧临时 bundle 观察，不归属于本次构建。当前普通 Product Launcher read/list 集成仍缺同一轮自动化验收证据；这次超时是缺少 Picker 选择，不是 enforcement assertion 失败。

**2026-10-01 Product XPC caller-asserted authority 拒绝：**test-only `WorkspaceGrant` driver 在真实签名 `KernelProduction.xpc` 上新增两个 headless 攻击：带匹配 Runner source digest、无 bookmark 的 `workspace.run` 分别附加 `approval: true` 和 caller-supplied `capabilities`。当前 exact-schema parser 必须在 bookmark 处理前返回 `invalid_request`，随后服务仍需响应 idle cancellation。聚焦 signed-product test 通过（1 项，14.375 秒）。首次 canonical suite 发现取消超时单测仍使用旧 bootstrap 输出 fixture；同步新诊断行并单独通过该回归后，canonical `python3 -m unittest discover -s tests -v` 通过全部 217 项（455.010 秒）。这只证明当前 XPC schema 拒绝未认证 authority 字段，不实现或证明 Candidate admission、用户 approval 或 capability grant。

**2026-10-01 打包 Runner 直接 Workspace 写入拒绝：**本地签名 Seed package focused test 使用产品包内嵌 Python 和实际 Kernel Worker 启动 Seatbelt Runner。宿主正向对照能以 `O_WRONLY` 打开 live fixture；不可信 Runner 以同一绝对路径尝试写入，只接受 OS 返回 `EPERM`/`EACCES`，并同时确认 Runner 不能写打包的 Kernel changeset 模块。随后固定 command 只在 private snapshot 写入，Kernel 验证并提交一个新文件；fixture 与 Kernel 源摘要保持不变，deep code signature 仍有效。聚焦测试通过（1 项，16.507 秒）；canonical `python3 -m unittest discover -s tests -v` 随后通过全部 217 项（440.864 秒）。此测试直接调用打包 Python 中的开发 launcher，不经过 `KernelProduction.xpc`；它证明打包 Worker→Seatbelt Runner→snapshot→trusted commit 的实际 OS 写隔离，不替代 Product XPC transport/Picker 集成或 Candidate admission 证据。

**2026-10-01 打包 Runner 对 live Workspace 与 test HOME 的直接读取/写入拒绝：**签名产品包测试增加位于选中 Workspace 之外的 test-owned `HOME` canary；宿主先验证 canary 可读、live fixture 可写。包内 Seatbelt Runner 对 live fixture 的 `O_RDONLY`/`O_WRONLY`、对 canary 的 `O_RDONLY` 和对打包 Kernel changeset 模块的 `O_WRONLY` 都必须由 OS 返回 `EPERM`/`EACCES`。固定 command 仍只在 private snapshot 写入，Kernel 提交一个新文件；父进程确认 fixture 与 canary 未变、Kernel digest 未变，并通过 `codesign --verify --deep --strict`。聚焦签名产品包测试通过（1 项，14.011 秒）；完整 canonical suite 通过 217 项（450.812 秒）。此证据针对测试专用 canary，不代表读取真实用户 HOME 或 secrets；路径是打包 Python launcher/Worker→Seatbelt Runner→trusted commit，不经过 `KernelProduction.xpc`，不证明 Candidate admission、Manifest approval 或任意 Plugin 执行。

**2026-10-01 Product XPC Picker 未选择与阶段诊断：**重新构建的签名产品包执行 `KHAOS_RUN_PRODUCT_XPC_ATTACK_UI=1`，但 Picker 在 600 秒内没有收到用户选择；测试于 614.180 秒失败，输出只有 driver PID，workspace 保持两个原始 fixture，临时目录随测试清理。因此本次没有进入选中 workspace 的 Runner、scope、unsafe changeset、取消、Kernel 写回或父进程签名断言。这是缺少用户选择，不是 enforcement 失败。复核发现旧诊断把 Picker 等待误报成取消子进程未到位；test-only Swift driver 现记录 path-free `picker-requested` / `selection=complete` 标记，Python 测试按阶段分类超时，并打印 Command-Shift-G 导航提示。超时回归通过（1 项，0.004 秒），签名产品包 headless 测试通过（1 项，14.134 秒），canonical `python3 -m unittest discover -s tests -v` 通过 217 项（439.790 秒）。默认套件不打开 Picker，未补充 XPC 选择后的执行证据。

**2026-10-01 Product XPC 直接读取拒绝探针：**test-only 签名产品 XPC driver 增加 Picker scope 内 fixture 可读、释放 scope 后 OS 拒绝直接读取和写入、Runner 直接读取 live Workspace 被 OS 拒绝三项检查，并保留 Kernel scope/commit、unsafe changeset 和 cancellation 攻击。更新后的 Swift probe 通过 signed-product headless 测试；canonical suite 通过 217 项（440.185 秒）。随后新的 `KHAOS_RUN_PRODUCT_XPC_ATTACK_UI=1` 交互运行仍未收到目录选择，于 614.303 秒超时；日志只到 `production-xpc-picker-requested`，没有执行上述新断言或所选目录 writeback/signature 校验。用户报告的 PASS 对应普通 Product Launcher writeback workspace，不能作为此 XPC 交互路径的证据。当前仅增加了可执行检查，所选 workspace 的 XPC 直接读取拒绝仍未得到运行证据。

**2026-10-03 Product XPC sandbox readiness 阶段诊断：**Kernel 将固定、path-free 的探测阶段编码为有限错误码（child、readiness、snapshot、verification），不向 IPC 返回异常文本、OS 错误或本地路径；签名 Product Launcher 仍把这些内部码折叠为通用 `sandbox_unavailable`，fail-closed 行为不变。两次此前完成 Picker 选择的 Product XPC 运行都在取消握手前收到通用 `sandbox_unavailable`，Runner、scope 释放拒绝、Kernel 写回与签名检查未执行。新诊断版本的一次交互运行在 600 秒内未收到选择；用户随后报告已选择 `/Users/huangruibang/Applications/khaos-seed-app-l2fgx4wq/user-selected-product-xpc-workspace` 并关闭结果弹窗，但该临时目录、进程和可关联的测试日志均已不存在，所以该 UI 观察不能揭示阶段码或证明写回。path-free 阶段映射的单测、签名 headless XPC 检查及 canonical `python3 -m unittest discover -s tests -v` 全部 247 项（459.405 秒）通过；默认套件不打开 Picker。选中 Workspace 后的 Product XPC 执行和安全断言仍未获得可关联的端到端证据。

**2026-10-03 Product XPC 祖先目录拒绝与诊断修正：**一次与测试父进程关联的 Picker 选择使真实签名 `KernelProduction.xpc` 返回 `sandbox_unavailable_probe_snapshot`。macOS 日志显示 App Sandbox 拒绝读取 `/Users`；签名沙箱 helper 的真实 OS 测试进一步证明它不能以目录描述符逐级打开 `/Users`（`EPERM`），但能够直接打开自己的临时 source 与 APFS 挂载目录，并在已打开描述符上取得 `ATTR_VOL_MOUNTPOINT` 和 `ATTR_DIR_MOUNTSTATUS`。快照目录 opener 现在只在 macOS 祖先目录权限拒绝时直接打开已解析的目标目录，并要求内核 `F_GETPATH` 与期望路径严格相同；其余 descriptor、inode 和挂载身份验证保持不变，验证失败继续 fail closed。单元回归覆盖祖先拒绝及路径不匹配拒绝。新的签名产品包选中目录复验仍返回同一阶段码，但 OS 日志显示 Seatbelt 探针子进程已运行。代码复核发现 `_seatbelt_probe_snapshot` 还把探针主体内的 `WorkspaceCommitError` 等错误误标为快照建立失败；现在仅映射 context entry，主体错误保持原类型，并有单元回归。`/Users` 拒绝是已证实的 OS 行为，但现有运行不能证明它是 Product XPC 失败原因。Runner 和 Kernel 写回仍无本轮完整通过证据。
