# 真实外部会话与官方桌面接续：执行清单

状态：**PREPARED / NOT_RUN**。固定候选 **`76307345d8f036c548128de96c5f230099cc65d8`**。
P1 和两项 P2 保持关闭；离线／合成验收通过（1004 tests）。本包准备不等于真实验收或额度授权。
沿用 [接口契约](EXISTING_SESSIONS_API.md) 与 [验收矩阵 E10](VALIDATION_MATRIX.md)，不改产品范围。

## 1. 开始前填好样本与授权

两家各至少一个**在 RepoBridge 外创建、有历史、可用于测试**的原生会话；旧 RepoBridge 自建样本不算。
优先用不含私人会话的专用测试项目；两家可共用项目，但串行验收，前一家释放写入者后再做后一家。

| 必填项 | Claude Code | Codex |
|---|---|---|
| 项目绝对路径／实际 cwd | 待用户指定 | 待用户指定 |
| 原生 session/thread ID（非 RepoBridge ses_ ID） | 待用户提供 | 待用户提供 |
| 创建来源、日期及证据 | CLI／官方桌面／其他；待填 | CLI／官方桌面／其他；待填 |
| 官方原生界面可辨认的历史锚点 | 无敏感内容的已有消息／时间，待填 | 无敏感内容的已有消息／时间，待填 |
| 当前写入者、如何结束它 | 所在终端／窗口；活动／已结束／未知 | 所在终端／窗口；活动／已结束／未知 |
| 原生存储环境 | 默认，或用户指定配置根路径（仅路径） | 默认，或用户指定 CODEX_HOME 路径（仅路径） |
| CLI 路径／版本、官方桌面路径／版本 | 执行前只读核对 | 执行前只读核对 |
| 本次选择的模型／强度／权限 | 用户确认；记录实际回报值 | 用户确认；记录实际回报值 |

另需确认两项：①允许上述**指定项目范围的发现元数据**及指定 ID 的历史读取；②新的发送次数预算。
现有发现接口按项目枚举元数据，不能声称只读取某一个 ID。若项目内还有未授权私人会话，先停止，
改由用户指定专用项目／合适样本；不全局搜索、不移动原生记录、不扩大目录范围。
只预览和继续表内 ID，发现了其他候选也不打开。来源证据和接口 `source` 分别记录；`unknown` 不猜成 CLI／desktop。

**最小新预算：已有合格样本时 Claude 3 次 + Codex 3 次 = 6 次显式发送尝试。**
每家分别用于下表 L1、L3、L5。没有自动重试／返修；发送结果不明也占用该次尝试，停止而不重复发送。
若没有现成样本，在原生工具外建样本至少另需每缺一家 1 次创建消息；两家都缺时最低总数是 8，须另行授权。
桌面来源与 CLI 来源是不同覆盖项：每家只测一种来源，不声称另一种也通过。桌面创建、其他本地来源、
云端／远程、未索引／归档会话及其他存储环境，未提供样本者单列 NOT_RUN／不支持，不扩大扫描。

计数单位是用户发起的模型轮次，**不是底层 API 请求／计费次数的硬上限**。候选没有统一本轮数或墙钟硬限制；
建议每次等待上限 120 秒，超时由操作者停止该测试轮并核对退出，不追加发送；六次累计模型等待最多 720 秒。
鉴权、配额、额外付费或权限提升请求、模型被替换、未知退出：立即停止。旧 W6–W8 额度已耗尽，本轮未续用。

## 2. 固定源码、独立状态与启动／停止

下面命令留给**获得样本读取许可后的执行轮次**。在用户手动打开的普通 Terminal 中执行；不从 Codex／Claude
代理终端启动真实 harness，不清除 nested/cloud 标记来绕过拒绝。本轮准备只核对命令，不启动这个真实实例。
使用现有 Python 环境，不安装、不升级依赖，不运行打包／安装命令。

先在该 Terminal 准备目录（每次新验收只执行一次）：

```sh
RB_CANDIDATE=76307345d8f036c548128de96c5f230099cc65d8
RB_REPO=/Users/chan/Downloads/repobridge-integration
RB_PY=/Users/chan/Downloads/harness-bridge/.claude/worktrees/repobridge-product-direction-8e26f9/.venv/bin/python
umask 077
RB_ACCEPT_ROOT=$(mktemp -d /private/tmp/repobridge-live-7630734.XXXXXX)
export RB_CANDIDATE RB_PY RB_ACCEPT_ROOT
export RB_SOURCE="$RB_ACCEPT_ROOT/source" RB_STATE="$RB_ACCEPT_ROOT/state"
test "$(git -C "$RB_REPO" rev-parse "$RB_CANDIDATE^{commit}")" = "$RB_CANDIDATE" &&
mkdir "$RB_SOURCE" "$RB_ACCEPT_ROOT/evidence" &&
git -C "$RB_REPO" archive --format=tar --output="$RB_ACCEPT_ROOT/candidate.tar" "$RB_CANDIDATE" &&
tar -xf "$RB_ACCEPT_ROOT/candidate.tar" -C "$RB_SOURCE" &&
printf '%s\n' "$RB_CANDIDATE" > "$RB_ACCEPT_ROOT/candidate.sha"
```

上段任何错误即停。不切换原 worktree；后续文档提交、PR #3 的新提交都不改变导出的候选。
启动前设置绝对源码路径；检查导出完整性、模块来源及全新状态目录。候选用独立浏览器页，便于以端口区别现用窗口：

```sh
export PYTHONPATH="$RB_SOURCE/src" PYTHONDONTWRITEBYTECODE=1
"$RB_PY" - <<'PY'
import json, os, subprocess, tarfile
from pathlib import Path
from harness_bridge.workbench import app, service
from harness_bridge.workbench.harness import environment_refusal, stripped_billing_env
root = Path(os.environ['RB_ACCEPT_ROOT']).resolve()
source, state = Path(os.environ['RB_SOURCE']).resolve(), Path(os.environ['RB_STATE']).resolve()
sha = '76307345d8f036c548128de96c5f230099cc65d8'
assert root.parent == Path('/private/tmp') and root.name.startswith('repobridge-live-7630734.')
assert source == root / 'source' and state == root / 'state' and not state.exists()
assert (root / 'candidate.sha').read_text().strip() == sha
assert Path(app.__file__).resolve() == source / 'src/harness_bridge/workbench/app.py'
assert Path(service.__file__).resolve() == source / 'src/harness_bridge/workbench/service.py'
with tarfile.open(root / 'candidate.tar') as archive:
    assert archive.pax_headers.get('comment') == sha
    for member in archive.getmembers():
        if member.isfile():
            data = archive.extractfile(member).read()
            assert (source / member.name).read_bytes() == data, member.name
reason = environment_refusal(os.environ)
if reason:
    raise SystemExit(reason)
if stripped_billing_env(os.environ):
    raise SystemExit('检测到 API/provider 环境变量；停止，核对订阅来源。不要打印变量值。')
os.chdir(source)
birth = subprocess.check_output(['ps', '-p', str(os.getpid()), '-o', 'lstart='], text=True).strip()
record = {'sha': sha, 'source': str(source), 'state': str(state), 'pid': os.getpid(), 'process_birth': birth}
(root / 'launch.json').write_text(json.dumps(record, indent=2) + '\n')
(root / 'candidate.pid').write_text(str(os.getpid()) + '\n')
print(json.dumps(record, indent=2), flush=True)
raise SystemExit(app.main(['--state-dir', str(state), '--port', '0', '--browser']))
PY
```

预期：打印的源码位于新目录，状态为 `<新目录>/state`；浏览器打开独立 `127.0.0.1:<端口>`，
首次项目列表为空。记录端口和 `launch.json`，页面加载后核对两家 CLI 路径／版本及官方应用版本。
启动只探测 CLI 版本／本地能力，不发送消息；未添加项目时不发现历史。若来源不符、出现旧项目、目录非空，立即停止。
浏览器是本包的候选控制界面；原生 RepoBridge 窗口的 IME／剪贴板／VoiceOver 另交 Opus，不算本包已验。
不使用 `--no-open`，不抄录 `/auth?token=…`、Cookie 或完整 HAR。

只隔离 **RepoBridge 状态**，不伪造 HOME 或复制登录／原生历史。之后获准的原生 CLI 会使用用户指定的原生环境，
L1/L3/L5 会在同一个真实原生会话追加消息。候选单写入锁只覆盖自身状态，不能代表其他实例已经释放写入者。
现用 RepoBridge 不添加测试会话，不打开／迁移它的数据库；原生会话的外部占用仍需用户明确确认。

**正常停止：** 等测试轮结束，先在候选会话菜单断开原生连接（`POST …/stop`，不是仅停止这一轮），
确认该 run 的 `exit_confirmed`。再在启动候选的 Terminal 按 Ctrl-C，等待命令返回。关闭浏览器标签本身不会停服务。
`app.main` 的退出清理仅结束该候选托管的 CLI；不会负责关闭外部桌面写入者。
若 Terminal 已不可用，另开普通 Terminal，将 `RB_ACCEPT_ROOT` 指向记录中的**准确新目录**，执行：

```sh
RB_PID=$(cat "$RB_ACCEPT_ROOT/candidate.pid")
lsof -a -p "$RB_PID" -d cwd
lsof -a -p "$RB_PID" -iTCP -sTCP:LISTEN
ps -p "$RB_PID" -o pid=,lstart=,command=
# 仅在 PID/进程启动时间/监听端口与本次 launch.json 和终端记录一致后，才执行下一条停止命令。
```

```sh
kill -TERM "$RB_PID"
```

确认候选进程已退出、记录端口不再监听；未确认退出就停止验收，不重启、不强杀、不使用 pkill/killall。
保留状态和证据目录，不执行清理删除。重新启动必须另行核对保留的状态及未决运行，不重跑“全新目录”前置断言。
不要退出或结束其他工作中的官方客户端；若指定测试线程无法单独释放写入者，记录阻断，先协调其结束方式。

## 3. 逐步执行（Claude、Codex 各一遍）

每步记录 `harness / project_id / local_session_id / native_id / run_id / 时间 / 结果`；N0–N3 不发 prompt，
不 `start/resume`，允许为查询启动无 turn 的原生 RPC 进程。N 阶段通过不消耗上述 6 次续聊预算。

| 步骤 | 操作 | 预期／最小证据 | 发送预算 | 失败停止条件 |
|---|---|---|---|---|
| N0 原生基线 | 用户在指定原生工具确认原 ID、项目、已有消息锚点；记录创建来源和当前写入者。候选仅添加该项目 | 原生 ID、来源证据；候选项目路径完全相同；没有新建会话 | 0 | ID／cwd／来源证据不明；未指定的私人内容会被纳入发现 |
| N1 发现 | 项目菜单“添加已有会话”，选 harness；按标题搜索，必要时翻页 | 记录 candidate_id/native_session_id/cwd/source/completeness；目标 ID 精确匹配；partial 与空／失败分别记录 | 0 | 目标缺失、跨项目结果、错误被当空；不做全局搜索或手工注入 ID |
| N2 预览 | 只打开目标，核对既有首尾锚点；有更早页则翻页 | 原 ID 的可见历史、稳定消息 ID／时间／计数；截图仅测试内容 | 0 | 错会话、历史不一致、部分可见隐藏关键锚点；没有更早页则记未覆盖，不填“通过” |
| N3 关联与去重 | 添加关联；再从发现入口添加同候选；刷新历史 | `native_binding=linked`；native ID 不变；第二次同 ses_ ID、created=false；runs 仍为 []、turns_observed=0；原生端锚点／用户消息数无新增 | 0 | 出现新原生 ID、重复本地关联、历史重放、任何新消息／运行；本地只读缓存不等于复制出新原生会话 |
| L0 释放外部 | 用户结束指定终端／桌面写入者，记录证据；明确确认“外部已结束” | `/desktop/return` 只记确认、清保护、失效缓存；运行数与消息数不增；确认不等于自动检测进程退出 | 0 | 写入者仍活动或未知；不可点确认来试探抢锁 |
| L1 RepoBridge 接续 | 明确用原生恢复，核对 native ID，再发第 1 条唯一标记 prompt | kind=resume；同 ID；完成一轮、原生历史仅一份标记；Codex receipt=sent；Claude 用原生回显／历史证明 | 1 | 锁拒绝、ID 变化、新建／fork、unknown、权限／登录／配额问题、未完成或超时；不重发 |
| L2 移交官方桌面 | 待本轮空闲后“在官方客户端继续”，按真实需要确认释放 | RepoBridge 运行 exit_confirmed；external hold 生效。Claude 官方确认含原 ID；Codex 打开该 ID 的 deep link。官方列表／页面历史匹配 | 0 | 未确认退出、仍有本地写入者、打开错会话、只有启动命令而无界面核对；不将打开应用视为通过 |
| L3 官方桌面接续 | 在已核对的同一会话发第 2 条标记 prompt，等完成 | 官方页面／列表，同原 ID，新增且只有一次标记；RepoBridge 保持 hold。不要用“试发”测试保护 | 1 | 新建了桌面会话、复制导入、ID／项目不符、并发写入；模型异常立即停 |
| L4 返回与刷新 | 用户结束该桌面写入者，确认“回到 RepoBridge 继续”；只刷新历史 | 审计 `source=user_confirmation,process_exit_observed=false`；读到 L3 标记，无重复；原生 ID 不变；没有新 run／发送 | 0 | 外部占用未结束、只确认未读取到新增内容、wrong ID、重复消息；不以强行恢复代替历史核对 |
| L5 RepoBridge 再接续 | 明确恢复同 ID，发第 3 条标记 prompt，等完成 | 新 run.kind=resume，同 native ID；三条标记各一次；两个 RepoBridge 发送与一个官方发送均可对照；单写入者证据连续 | 1 | 锁拒绝／unknown／重复／分叉／额外发送；已用次数不重置 |
| L6 收尾 | 结束候选托管写入者，停止候选服务；只读核对指定原生会话仍存在 | 最终原 ID、三条标记、run 状态／退出码；候选进程／端口已退出；未触及现用状态库 | 0 | 退出不明、后台仍写入；保留现场而不清理／强占 |

标记例：`RB763-<日期>-<C或X>-1/2/3`，每次不同。
最小 prompt：`这是接续验收。请只原样回复“<本次标记>”，不要读写文件、运行命令或调用工具。`
样本选无须工具、无敏感内容的会话；若原生配置要求工具或其他动作，停下记录，不扩大权限。不要自动批准权限卡片。
每条标记必须在**原生来源的同 ID 历史**核对；助手自述“同一会话”不算身份或单写入证据。

## 4. 证据、结论与保留限制

每个步骤用一行：`时间 | 步骤 | harness | native_id | local_id/run_id | writer前→后 | 预算累计 | PASS/FAIL/NOT_RUN | 证据文件`。
在私有 `<RB_ACCEPT_ROOT>/evidence/` 留样本表、版本记录、关键 UI 截图及必要响应字段（native ID、kind、
exit_confirmed、receipt、external）。不导出整库、凭据、启动令牌、全部私人历史／原始 HAR；提交 PR 只用脱敏摘要。
运行失败保留真实状态／退出码／诊断，消息 sent 不使运行变成成功；unknown 时只读核对，不恢复重发。

两家 N/L 闭环及身份／写入者证据齐全才把 E10 对应样本标为真实通过；未覆盖的来源、分页、真实异常路径单列。
任何一步失败只记该步／该 harness 阻断和已用预算；不重开已通过的离线结论，不把部分闭环称为整体通过。

- **Opus 后续范围：** 原生 RepoBridge 的 IME、系统剪贴板、VoiceOver；本包未执行，也不计入 6 次。
- Claude 无对应持久投递回执，原生回显前退出的证据范围有限。
- 整页刷新丢失普通未发草稿；历史刷新保留草稿、已接收消息回执恢复是不同能力。
- 历史持久化失败摘要未迁移；新运行摘要的事实修复保留。
- PR #3/#4 继续草稿及既有依赖；候选固定，不合并默认分支、不发布、不替换现用版本。
