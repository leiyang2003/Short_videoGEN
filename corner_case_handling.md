# Corner Case Handling Log

> Last updated: 2026-05-05 00:10:25 CST

这个文档记录小说转视频链路中实际遇到的 corner cases，包括问题现象、根因判断、试过但无效或不充分的方案、当前有效方案，以及未来可以系统化改进的方向。

后续每次新增内容时，建议保留时间戳，避免把一次局部修补误认为通用规则。

## 2026-05-05 00:10:25 CST - 长段落同一 source line 可承载多个镜头 beat

### Case 167: EP10 source selection QA 因同一长行内多 beat overlap 中断批处理

**现象**

- `ginza_night` EP10 从头到尾批处理时，`source_parsing` 成功，`source_selection.rules.response.json` 已生成。
- `source_selection_qa_report.json` 报 high findings：SH13 与 SH10/SH11/SH12 都 overlap 在 `source_range=[198, 200]`。
- 实际原文第 198 行是一个很长的 dialogue/action 段，包含电话响起、石川来电、樱子追问、健一安抚、美咲带樱子离开、门关上等多个连续可拍 beat；LLM selection plan 将其拆给 SH10-SH13，语义上可解释。
- 因未传 `--allow-selection-fallback`，`novel2video_plan.py` 在 selection QA high finding 处抛异常；随后 `run_novel_episode_batch.py --allow-plan-qa-fail` 仍继续查找未生成的执行目录，触发 `FileNotFoundError: execution dir not found`。

**根因**

- selection QA 目前按 line-level `source_range` 判断 overlap。对小说 markdown 中“单行长段落包含多动作/对白 beat”的情况，行号 overlap 不一定代表镜头语义重复。
- `--allow-plan-qa-fail` 只影响 planning QA 之后是否继续，不等同于允许 source selection QA high finding；批处理对“plan 子进程失败但 bundle 目录已部分存在”的状态也没有优雅跳过。

**有效方案**

- 对这类长段落多 beat 的 LLM selection plan，若人工确认每个 shot summary 指向不同动作/对白，可 rerun 时同时传 `--allow-selection-fallback` 和 `--allow-plan-qa-fail`，让 selection QA finding 保留为审计证据但不中断后续 records/keyframes/video。
- 保留 `source_selection_qa_report.json`，后续检查 records 时重点审查 SH10-SH13 的 `selection_plan.summary`、`source_excerpt`、可见人物/对白是否各自对应不同 beat。

**系统化改进建议**

- source parsing 可在长小说段落内按句号/引号对白/动作转折拆分更细的 source units，避免把多个镜头 beat 压在同一个 line-level unit。
- selection QA 的 overlap 检查应区分“完全重复同一语义 beat”和“同一长 source unit 内的连续 beat 分镜”；可结合 `source_unit_ids`、summary/action target/dialogue evidence 做 soft warning。
- batch runner 在 plan 子进程失败后，若 bundle 只是部分生成，应记录该 episode failed 并继续下一集，而不是继续寻找执行目录导致二次崩溃。

## 2026-05-04 21:52:16 CST - WebUI backend 必须加载仓库 .env

### Case 166: Adjust & Redo 起草 prompt 报 OPENAI_API_KEY 缺失

**现象**

- WebUI 中点击 Adjust & Redo 后生成 adjusted prompt，接口返回 `OPENAI_API_KEY is required to draft an adjusted redo prompt`。
- 同一仓库 `.env` 文件里已有 `OPENAI_API_KEY`，但当前 WebUI backend 进程没有读到该环境变量。

**根因**

- `webui/backend/main.py` 直接读取 `os.getenv("OPENAI_API_KEY")`，但没有像 `run_seedance_test.py`、`generate_keyframes_atlas_i2i.py` 等脚本一样在启动时加载仓库根目录 `.env`。
- 因此从未导出环境变量的 shell 启动 WebUI backend 时，prompt 调整接口会在调用 LLM 前直接失败。

**有效方案**

- WebUI backend 启动时加载 `REPO_ROOT/.env`，且不覆盖已经存在的真实环境变量。
- 修改 backend 代码后，需要重启 Uvicorn 或使用 `--reload` 让当前进程加载新代码。

**系统化改进建议**

- 所有 WebUI 后端调用 OpenAI/Seedance/API provider 的路径应共享同一套 env 初始化逻辑。
- `/api/health` 后续可暴露关键 provider env 是否已配置，但不得泄露具体 key。

## 2026-05-04 21:39:06 CST - 画外死亡信息不能变成可见听者死亡约束

### Case 165: EP02 SH11 keyframe prompt 把“彩花的尸体”误套到美咲身上

**现象**

- EP02 SH11 record 是佐藤美咲在银座高级酒店门外靠墙偷听，石川刑警只作为 offscreen voice 说“彩花的尸体上有丝巾勒痕。”
- `generate_keyframes_atlas_i2i.py` 生成的 keyframe prompt 错误加入“画面主体以可见五官和闭合眼睑状态为准”和“死亡约束：双眼完全闭合……”。
- 实际生成图未明显受污染，美咲仍睁眼靠墙持手袋，但该 prompt 文件不能再作为 Seedance prompt 继承来源。

**根因**

- keyframe prompt renderer / safety rewrite 从对白里的“尸体”触发死亡视觉约束，却没有区分死亡对象是画外被提及的彩花，还是首帧可见角色美咲。

**有效方案**

- 对该次 SH11 clip 生成，显式使用 `--prompt-final-map` 指向已审过的正确 `prompt.final.txt`，避免 Seedance 继承污染的 keyframe prompt。
- keyframe 结果可肉眼审查后保留；但 keyframe prompt/payload 必须标记为有语义污染风险。

**系统化改进建议**

- keyframe death/closed-eye safety rewrite 必须绑定到 visible character 或 prop target；仅出现在 offscreen dialogue/subtitle 的死亡词，不能改变画面内听者的眼睛、动作或生命状态。
- QA 应检查 keyframe prompt 中“死亡约束 / 闭合眼睑”等词是否与 `first_frame_contract.visible_characters` 对应。

## 2026-05-04 21:39:06 CST - offscreen police voice 不是 phone voice

### Case 164: EP02 SH11 auto phone audio repair 把偷听警方对话改成接电话

**现象**

- EP02 SH11 的原始 Seedance `output.mp4` 抽帧显示美咲靠酒店门外墙边持手袋倾听，没有手机。
- 同次脚本自动触发 `phone_audio_repair`，生成的 `output.phone_fixed.mp4` 中段/尾帧让美咲拿起手机接听。
- record 的 `i2v_contract.phone_contract={}`，语义是现场门外偷听 offscreen police voice，不是电话远端说话。

**根因**

- phone/remote-listener repair 逻辑把 `lip_sync_policy=remote_voice_listener_silent` 或画外声音风险泛化成 phone listener candidate，没有区分 offscreen 现场声音与 phone voice。
- repair prompt 的“无声听者” rerun 反而给模型打开了手机动作联想。

**有效方案**

- 本次 SH11 选择原始 `output.mp4` 作为可用 clip，不使用 `output.phone_fixed.mp4`。
- 对非电话场景，即使有 offscreen voice，也不要自动套用 phone audio repair；如需修嘴型，应使用“offscreen voice listener silent”专用修复，不允许新增手机。

**系统化改进建议**

- 自动 phone repair 的触发条件必须要求 record 明确存在 `phone_contract` 或电话/手机听者契约。
- 对 `phone_contract={}` 且场景是现场偷听/门外听见声音的 shot，repair prompt 必须添加“no phone, no handset, no calling gesture”或直接跳过 phone repair。

## 2026-05-04 21:07:22 CST - 正确 keyframe 不能掩盖错误 Seedance prompt

### Case 163: EP02 SH10 首帧图正确但 WebUI clip 中段跳成警视厅审问

**现象**

- GinzaNight EP02 SH10 的 WebUI latest keyframe 指向 `test/ginzanight_ep02_regen_keyframes_time_guard_20260503/SH10/start/start.jpeg`。
- 5/4 WebUI Seedance clip 的 `image_used.txt` 与该 latest keyframe 字节完全一致，视频第 0 帧也是美咲在俱乐部后台拿手袋，左侧一只玻璃酒杯可见。
- 同一个 clip 的 `record.snapshot.json`、`prompt.final.txt`、`request_payload.preview.json` 却写成“警视厅调查室 / 石川悠一 / 龙崎 / 监控屏幕”。
- 视频中段和尾帧实际跳成警视厅审问画面，偏离 EP02 SH10 record 的“俱乐部ルミナ后台 / 佐藤美咲 / 手袋 / 一只玻璃酒杯”。

**根因**

- Seedance 作业使用了正确的 latest keyframe 作为首帧图，但使用了不属于当前 SH10 record 的 prompt/record snapshot。
- I2V 首帧锚定只能保证起始图像相似，不能抵消错误文本 prompt 对后续画面、人物和场景的强控制。

**有效方案**

- 判断 clip 是否正确时不能只看 `image_used` 或第 0 帧，还必须同时审计 `record.snapshot.json`、`prompt.final.txt`、`payload.preview.json` 是否与 record source of truth 一致。
- 对 EP02 SH10，应以 rerun record 为准重新渲染 Seedance prompt：俱乐部ルミナ后台、佐藤美咲单人、手袋、从第一帧开始固定可见一只玻璃酒杯、固定机位/静态场景。

**系统化改进建议**

- WebUI Seedance job 创建前增加一致性检查：`record.snapshot.json` 的 episode/shot、location、visible characters、first-frame props 必须与 latest keyframe 的源 record 对齐。
- 如果 prompt/rendered record 与 latest keyframe source record 不一致，阻止提交并提示重新选择 record 或刷新项目 index。

## 2026-05-04 20:41:04 CST - WebUI backend 修改后必须重启或使用 reload

### Case 162: 修复已写入 main.py 但 Refresh 仍把 SH01 clip 清掉

**现象**

- `webui/backend/main.py` 已修复 `prune_artifact_candidates_to_latest()`，直接用当前文件代码执行 `sync_project_index(1)` 可以恢复 EP02 SH01 的 `clip_for_latest_keyframe`。
- WebUI 中点击 Refresh 后，`matching_clip_candidates` 又变成空，`clip_for_latest_keyframe=null`。
- `ps` 显示 backend 进程已运行数小时，启动命令没有 `--reload`。

**根因**

- 正在运行的 Uvicorn backend 仍加载旧 Python 代码。
- WebUI Refresh 调用旧内存逻辑执行 index rebuild，因此会把磁盘上已经修好的 JSON 再次写坏。

**有效方案**

- 停止旧 backend 进程，使用 `uvicorn webui.backend.main:app --reload --host 127.0.0.1 --port 8000` 重启。
- 重启后用 `/api/projects/1/shot-board?episode_id=EP02&refresh=1` 验证，SH01 的 `clip_for_latest_keyframe` 保持指向新 clip。

**系统化改进建议**

- 开发时默认使用 `--reload` 启动 backend。
- 后续可在 `/api/health` 暴露 backend start time 与 source mtime，当前端发现代码比进程更新时提示需要重启。

## 2026-05-04 19:58:12 CST - 旧 selected clip 不能挤掉同 shot 最新候选

### Case 161: EP02 SH01 新 WebUI clip 已生成但 Shot Board 仍显示 No clip

**现象**

- WebUI 生成 EP02 SH01 新 clip 成功，`test/webui_ginza_night_ep02_seedance_20260504_195224/SH01/output.mp4` 已存在。
- Shot Board 中 SH01 的 `latest_keyframe` 是 2026-05-03 的重生 keyframe。
- `/shot-board` 返回 `clip_for_latest_keyframe=null`、`matching_clip_candidates=[]`，点击 SH01 看不到新 clip。
- DB 中仍保留 2026-05-02 旧 `artifact_selections` clip；该旧 clip 的 `source_keyframe_path` 指向旧 keyframe。

**根因**

- `prune_artifact_candidates_to_latest()` 先保留 selected candidate，并把它的 `(episode, shot, media_type, source_kind)` 标记为已见。
- 当 selected clip 是旧的 `output_file` 时，同 shot/source_kind 下更新的 clip candidate 会在 prune 阶段被删除。
- 后续 `clip_for_latest_keyframe` 只能在剩余候选中匹配最新 keyframe，因此找不到刚生成的新 clip。

**有效方案**

- prune 时仍保留 selected candidate，但 selected candidate 不应占用 latest slot。
- 第二轮仍按 `(episode, shot, media_type, source_kind)` 保留最新 candidate。
- 这样旧 selected clip 可留作历史/用户选择，新生成的 matching clip 也能进入 `matching_clip_candidates` 并被 `clip_for_latest_keyframe` 选中。

**系统化改进建议**

- WebUI artifact pruning 应区分“保留用户选择用于历史/显式选择”和“每个 source_kind 的最新候选用于自动匹配”。
- 对 clip readiness，旧 selected clip 不能阻止最新 matching clip candidate 进入 index。

## 2026-05-04 17:50:52 CST - 双人首帧单说话人必须显式选择构图模板

### Case 160: SH05 record 要两人可见但 keyframe 生成成单人彩花

**现象**

- EP02 SH05 的 record 中 `visible_characters` 包含佐藤彩花和田中健一，且只有彩花说话。
- 实际 latest keyframe 只生成了彩花单人画面，没有田中健一。

**根因**

- keyframe prompt 反复强调 active speaker 彩花的脸和嘴必须清楚、占主视觉，并写了“如果双方脸部可见性冲突，优先保证说话人”。
- `character_positions` 只给彩花写了位置，没有给沉默听者田中健一完整位置。
- 人物锁定/构图语义把“单 active speaker”误强化成“单 visible character”。

**有效方案**

- 新增 `composition.md`，记录两人首帧、一人说话时的构图模板。
- `novel2video_plan.py` 的 LLM prompt 增加 `[COMPOSITION_RULES]`，把 `composition.md` 一起提供给 LLM。
- record schema / template / LLM 输出 schema 增加 `first_frame_contract.composition_method`。
- 如果首帧两人可见且只有一名 active speaker，必须选择构图模板并写入 record；每个 visible character 都必须有 position、face visibility、speaking/silent state。
- `keyframe_static_anchor` 生成时读取 `composition_method`，把构图方法、主动说话人、沉默听者和人物位置写入 keyframe 静态 prompt。

**系统化改进建议**

- 后续 keyframe prompt renderer 与 QA 都应检查 `composition_method`、`visible_characters`、`character_positions` 三者一致，避免沉默听者被 “no extra characters” 误删。

## 2026-05-04 17:36:15 CST - Shot Board 默认必须轻量读取 JSON index

### Case 159: 点击 keyframe 后右侧 clip 显示慢

**现象**

- WebUI 中点击 Shot Browser 的 keyframe/shot 后，右侧 clip 看起来需要较长时间才显示。
- 实测 `/api/file?...output.mp4` 首字节和下载很快，约毫秒到几十毫秒；慢的是 `/api/projects/{id}` 与 `/api/projects/{id}/shot-board`，曾分别约 3-6 秒。

**根因**

- `shot-board` 与 project dashboard API 每次请求都触发 `sync_project_index(project_id)`，会扫描 `test/`、重建 artifact DB、重写 `shot_asset_index.json`。
- 前端每 4 秒同时轮询 dashboard 和 shot-board，导致后端几乎持续处于重扫状态；点击 shot 虽是本地 state 切换，但视频请求和 React 更新会被长请求影响。

**有效方案**

- `/api/projects/{id}` 与 `/api/projects/{id}/shot-board` 默认只读现有 DB/`shot_asset_index.json`，不重扫。
- 增加显式 `refresh=1` 参数；只有手动 Refresh、job 完成、Codex 手动生成产物后的同步等明确时机才执行 `sync_project_index(project_id)`。
- 前端 4 秒轮询只刷新 dashboard/job 状态，不再轮询 shot-board 重扫；点击 shot/keyframe 只切换本地 selected shot。
- 选择 Current/New clip 后，后端 selection API 已重写 project-level JSON，前端只需轻量重读 shot-board。

**系统化改进建议**

- 后续若需要实时产物发现，使用 job completion 或显式 refresh 触发，不要让普通浏览/点击路径隐式扫描 `test/`。

## 2026-05-04 17:31:12 CST - selected-shot assembly 不能回退到旧 default clip

### Case 158: EP02 SH01 latest keyframe 已更新但旧 selected/default clip 仍让 assembly-check 误判 ready

**现象**

- EP02 SH01 的 latest keyframe 是 2026-05-03 重生图。
- 旧 clip 绑定的是 2026-05-02 keyframe，`clip_for_latest_keyframe` 正确为 `null`。
- WebUI assembly-check 若回退到 `selected_clip` 或 `default_video`，会把这个旧 clip 当成可拼，导致 SH01 没有显示为 missing clip。

**根因**

- `selected_clip` / `default_video` 是 shot-level 候选或历史选择，不一定匹配当前 latest keyframe。
- selected-shot assembly 的当前 clip 必须来自 shot asset index 的 `clip_for_latest_keyframe`，该字段已经内置“用户选择的 matching clip 优先，否则最新 matching clip”的规则。

**有效方案**

- assembly-check 只认 `clip_for_latest_keyframe` / `linked_clip_for_latest_keyframe`。
- 不再为 assembly readiness 回退到 `selected_clip` 或 `default_video`。

**系统化改进建议**

- “当前可用于生产的 clip”和“shot 下存在的 clip candidate”必须在 API 字段层保持分离；assembly、QA、右侧 preview 都应使用前者。

## 2026-05-04 17:22:10 CST - WebUI no_cover_page 必须显式传给 assembly 脚本

### Case 157: 只是不传 cover-page-dir 不能关闭自动封面

**现象**

- WebUI 创建 selected-shot assembly job 时传了 `params.no_cover_page=true`。
- 后端仅跳过 `--cover-page-dir`，但 `assemble_episode.py` 在未收到 `--no-cover-page` 时会继续自动发现项目封面目录并插入封面。

**根因**

- assembly 脚本的默认行为是自动搜索 cover page；缺少显式 `--no-cover-page` 不等于禁用封面。

**有效方案**

- WebUI 后端收到 `no_cover_page` 参数时必须向 `scripts/assemble_episode.py` 追加 `--no-cover-page`。
- 只有未禁用封面时，才传 `--cover-page-dir` 或允许脚本自动发现封面。

**系统化改进建议**

- WebUI job params 中的布尔开关应优先转成脚本显式开关；不要依赖省略某个辅助参数来表达禁用。

## 2026-05-04 17:17:43 CST - WebUI 勾选拼接必须按 episode shot 顺序而不是点击顺序

### Case 156: selected-shot assembly 若按 checkbox 勾选顺序写 concat 会打乱剧情

**现象**

- WebUI 新增按勾选 shots 拼接时，用户可能先点 SH02 再点 SH01。
- 如果后端直接按请求中的勾选顺序写 concat，输出视频会变成 SH02 -> SH01，违反镜头脚本顺序。

**根因**

- checkbox selection 是 UI 操作状态，不是剧情/镜头顺序。
- assembly 的 source of truth 应该是 shot board / episode record 的 shot sequence；selection 只表示包含哪些 shots。

**有效方案**

- assembly-check 保留 `requested_shots` 用于审计用户勾选集合。
- 实际 `ordered_shots` 和 concat 写入必须按 shot board 中的 episode 顺序排序。
- 缺失媒体列表也按 episode 顺序展示，避免 Complete 与后续 assembly 的顺序语义不一致。

**系统化改进建议**

- 所有 partial episode 操作都应显式区分 selection set 与 execution order；涉及输出时默认使用 episode order。

## 2026-05-04 16:34:13 CST - WebUI 每个项目维护 shot asset index

### Case 155: Shot Browser keyframe 与右侧 clip 必须通过项目级 index 统一

**现象**

- GinzaNight EP01/EP02 中，Shot Browser 可以显示最新 keyframe，但右侧 clip 曾出现 `No clip`、旧 clip 或与当前 keyframe 不一致的 clip。
- 用户 redo clip 后，可能选择保留 current clip 或切换到 new clip；这个选择需要被稳定保存，不能被下一次扫描自动覆盖。

**根因**

- 过去 shot-board 每次临时从 artifact candidates / selections 推导展示状态，且 clip selection 曾自动推进到最新 shot-level clip。
- 这会把“shot 有某个 clip”误当作“当前 latest keyframe 有对应 clip”，也会破坏用户对 current/new redo clip 的明确选择。

**有效方案**

- 每个 project 维护 `webui/.state/projects/<project_id>-<project_slug>/shot_asset_index.json`。
- 该 index 是从 records/artifacts/metadata 派生的缓存，不是手工源头真相；重建时必须保留仍然有效的用户选择。
- 每个 shot 先确定唯一 `latest_keyframe`，再收集 `source_keyframe_path == latest_keyframe.path` 的 `matching_clip_candidates`。
- `clip_for_latest_keyframe` 解析规则为：用户选择的 matching clip 优先；否则使用最新 matching clip；否则为 `null`。
- clip 缺失可靠 `source_keyframe_path` 时不可匹配；Shot Browser 的 `C` 只表示 latest keyframe 有 matching clip。
- clip selection 不再被同步流程自动推进到最新 clip，避免覆盖用户选择的 current/new redo 结果。

**系统化改进建议**

- 后续 redo job 成功后应先把新 clip 注册进 candidates，再让用户选择 current/new；选择 API 成功后同步写回 project-level shot asset index。
- 如果 index 与实际 artifacts 不一致，应重建 index，不应手工修改其中的派生字段。

## 2026-05-03 18:03:23 JST - WebUI 只索引 Seedance 命名目录，重跑后必须同步 selection

### Case 154: GinzaNight EP02 SH03 新 clip 已生成但 WebUI 仍显示旧 clip

**现象**

- EP02 SH03 使用简单版 `prompt.final.txt` 成功生成了新 `output.mp4`。
- WebUI 中 SH03 仍显示旧 clip；直接 `sync_project_index()` 后，最初的新目录没有进入 `artifact_candidates`。

**根因**

- WebUI artifact scanner 只扫描 `test/*seedance*/SH*/output.mp4`。
- 本次临时实验目录命名为 `ginzanight_ep02_sh03_simple_clip_20260503`，不含 `seedance`，因此 WebUI 索引不会发现它。
- 即使 clip 生成成功，如果没有写入 `artifact_selections`，shot board 也不会稳定切到新 clip。
- 后续又发现：如果旧 `artifact_selections` 被当作最高优先级保留，它会挡住同一 shot 的更新 clip，例如 EP01 SH12 已有 `..._v2/output.mp4` 但 current 仍停在旧 run。
- WebUI 前端还曾只用 `linked_clip_for_latest_keyframe` 判断 shot 是否有 clip，并要求 `selected_clip.source_keyframe_path == latest_keyframe.path`；当新 clip 缺少 `source_keyframe_path` metadata 时，正确的 selected clip 会被误显示成 `No clip` 或回退到旧 linked clip。
- 2026-05-04 复盘确认：Shot Browser 的 keyframe 必须是右侧 clip 的唯一主轴；`selected_clip` / `default_video` / 任意 shot-level 旧 clip 不能作为右侧 current clip 的回退来源，否则点击最新 keyframe 仍可能显示老 clip。

**有效方案**

- Seedance / I2V 重跑实验目录名必须包含 `seedance`，例如 `..._seedance_YYYYMMDD`。
- 生成成功后固定执行 WebUI 同步收尾：刷新 project artifact index，确认新 clip 出现在 `artifact_candidates`，再用稳定 `candidate_path` 写入 `artifact_selections`。
- 最后用 shot-board 构建逻辑验证目标 shot 的 `selected_clip.path` 和 `selected_source=user`。
- 对不断增长的 `test/` 目录，WebUI artifact index 应先按配置的扫描起点过滤，再按 `episode + shot + media_type + source_kind` 只保留每个 shot 的最新版本。
- 同一 shot/media 出现比旧 selection 更新的候选时，WebUI 同步应自动推进 selection 到最新候选；旧 selection 不能永久压住最新版本。
- 前端展示 current clip 时不得直接使用 `selected_clip` / `default_video` 回退；必须使用后端严格计算出的 `clip_for_latest_keyframe`。
- 最新规则改为更严格：后端输出 `clip_for_latest_keyframe`，且只有 `clip.source_keyframe_path == latest_keyframe.path` 才显示为 current clip；缺失 `source_keyframe_path` 的 clip 不可匹配，只能显示 `No clip` + Create。
- Scanner 可从可靠来源补全 `source_keyframe_path`：WebUI 生成时写入的 `image_input_map.source_keyframe.json`、普通 `image_input_map[SHxx].image` 本地路径、或 `run_manifest.default_image_url` 本地路径。

**系统化改进建议**

- WebUI redo/job 成功后应自动把新 clip 注册为候选并切换 selection，避免人工重跑脚本后页面仍指向旧产物。
- Scanner 可放宽为识别所有含 `run_manifest.json + SHxx/output.mp4` 的 I2V 目录，而不只依赖目录名包含 `seedance`；同时保留可配置 cutoff，避免反复扫描所有历史 `test/` 产物。

## 2026-05-03 17:52:51 JST - 擦肩/经过/离开镜头需要“擦肩后首帧拍法”

### Case 153: 首帧必须看见两人时，不能再把移动人物写成从画外入场

**现象**

- 对“美咲从房间走出与健一擦肩”这类动作，若 record 同时要求首帧两人都可见且露脸，keyframe 会先把两人都画进首帧。
- 后续 I2V prompt 若继续写“从房间走出 / 从左侧进入画面”，模型容易生成同一角色第二次入场，看起来像复制人物或又出现一个同名角色。

**根因**

- 首帧状态与动作时间线没有统一：首帧已经包含移动人物，但 action 仍描述为画外到画内的入场动作。
- 对擦肩动作来说，“动作开始前”的首帧不一定是最稳定选择；如果两人都必须可见，应该选择擦肩已经发生到一半或刚发生后的瞬间。

**有效方案**

- 建立通用“擦肩后首帧拍法”：首帧选在擦肩已经发生到一半或刚发生后的连续瞬间；移动人物位于画面侧边或侧后方，身体朝远处或出口方向，只露出三分之一侧脸或三分之二侧脸，不正对观众。
- 后续视频动作只能写“从首帧位置继续远离/离开”，不能再写“从画外进入 / 从房间走出 / 入画”。
- keyframe prompt 与 Seedance prompt 都追加同一拍法契约，保证首帧生成和视频运动解释一致。

**系统化改进建议**

- planning prompt 应把这种拍法作为擦肩/经过/离开类镜头的默认构图方法。
- renderer 层继续保留兜底改写，兼容已经生成的旧 record。

## 2026-05-03 17:37:29 JST - 首帧已可见人物不能再被视频 prompt 写成画外入场

### Case 152: GinzaNight EP01 SH12 首帧已有美咲，但 prompt 写“美咲从左侧进入/从房间走出”导致疑似第二个美咲

**现象**

- EP01 SH12 的 keyframe 首帧中田中健一和佐藤美咲都已经可见。
- 原 `prompt.final.txt` 同时写“美咲从左侧进入画面 / 从房间走出”，Seedance 会把它理解成首帧以外又有一个美咲入场，后段看起来像“又走出来一个美咲”。

**根因**

- Record 中 `first_frame_contract.visible_characters` 和 `prompt_render.shot_positive_core` 混用了首帧状态与动态动作。
- 对 keyframe 生成来说，“从左侧进入画面”可被理解为人物位于画面左边缘；对 I2V 来说，它更容易被理解为从画外新增入场。
- 这是 prompt rendering / model execution 层矛盾，不是 keyframe 本身多人物，也不是 record 真正要求两个美咲。

**有效方案**

- I2V prompt 渲染时，如果人物已经在 `first_frame_contract.visible_characters` 里，首帧段不能再写成“从左侧进入画面”，应改为“已在画面左侧边缘可见”。
- 动作段中的“从房间走出 / 进入 / 入画”应改写成“首帧已可见的人物从房门方向移动/擦肩经过”。
- 自动追加首帧人物连续性契约：首帧已可见人物就是后续动作中的同一批人物；不得新增同名或同身份人物，不得复制、分身或让同一角色再次从画外进入。

**系统化改进建议**

- Plan record 后续最好显式拆分 `first_frame_state` 与 `action_over_time`，不要把动态入场词直接塞进首帧字段。
- QA 应检查 `visible_characters` 与 `进入/走出/入画` 是否同时出现；若出现，必须确认是“已可见人物连续移动”而非新增人物。

## 2026-05-03 17:28:01 JST - 模板 prompt 不能硬编码场景地点或压掉英文状态词空格

### Case 151: GinzaNight EP01 SH12 走廊镜头 prompt.final.txt 被写成酒店套房连续性，英文状态词粘连

**现象**

- EP01 SH12 record 明确地点为 `酒店走廊至门外`，prepare-only 生成的新 `prompt.final.txt` 却出现“酒店套房、关键道具、服装和时代感保持一致”。
- 同一 prompt 中 `thoughtful eyes` / `three-quarter face` 被压成 `thoughtfuleyes` / `three-quarterface`。

**根因**

- `run_seedance_test.py` 的 template renderer 在 continuity summary 中硬编码了“酒店套房”，没有使用 record 的 scene/location。
- `strip_embedded_prompt_contracts()` 清理嵌入契约时把所有空白替换为空字符串，导致英文短语粘连。

**有效方案**

- continuity summary 应使用 `scene_name` 或 `first_frame_contract.location`，不能写死某个场景。
- 清理嵌入契约时把连续空白规范为单个空格，而不是全部删除。
- Seedance 生成前必须跑 prepare-only 审计 `prompt.final.txt`，检查地点、人物、动作与 record 是否一致。

**系统化改进建议**

- prompt renderer QA 可增加 `record location` 与 `prompt.final.txt` 地点词一致性检查。
- 对含英文视觉状态词的中文 prompt，增加空格粘连检查，避免模型误读。

## 2026-05-03 17:26:38 JST - WebUI artifact index rebuild must not leak partial candidates

### Case 150: EP01 SH01 `Use New Redo` 看起来无变化或短暂显示错误 current/new 状态

**现象**

- EP01 SH01 redo job 成功生成 `output.mp4` 后，shot board 有时短暂只返回新 redo clip，或点击 `Use New Redo` 后页面看起来没有立刻切换。
- 后端 `artifact_selections` 仍可保存旧 current clip path；再次稳定刷新后，新旧 clip 候选又都能出现。
- 本地探查期间，WebUI artifact DB 曾在并发 shot-board 同步和直接查询之间出现 `database is locked`，说明索引刷新与读取重叠。
- 当前 clip 若短暂变成最新 redo，前端把“第一个不同于 current 的 clip”错误标成 `New Redo`，导致右侧按钮可能反而选择旧 clip。

**根因**

- `sync_project_index()` 会删除并重建 `artifact_candidates` / `artifact_runs`，多个 shot-board 或 dashboard 请求并发进入时，读取方可能看到重建中的候选集合。
- 前端 selection refresh 可能被已有 4 秒轮询请求挡住，导致点击 `Use New Redo` 后没有立即强制读取最新 shot board。
- 前端 redo comparison 缺少“必须比 current 更新”的判断，只用 `path !== currentClip.path` 区分 current/new。
- 这是 WebUI artifact indexing / selection refresh 层问题，不是 record、prompt rendering、Seedance execution 或 assembly 问题。

**有效方案**

- 后端用进程内 `RLock` 串行化项目索引刷新，并在 shot-board 构建时持锁完成 `sync_project_index()` 和候选快照读取，避免 partial candidate list 泄露给 UI。
- 前端 `Keep Current` / `Use New Redo` 在 selection API 成功后等待强制 shot-board refresh，并显示 `Selecting...` 状态。
- 前端 `New Redo` 候选必须与当前 keyframe 匹配、path 不同、且 `mtime` 晚于 current clip，避免把旧 clip 标成新 redo。
- 对用户已经明确点击 `Use New Redo` 的 EP01 SH01，可用稳定 `candidate_path` 直接写入 artifact selection，避免依赖瞬时 candidate id。

**系统化改进建议**

- 长期可把 artifact scanning 改成临时表完整构建后原子替换，或增加 scan generation/version，保证所有 UI 响应来自同一代索引快照。

## 2026-05-03 17:18:22 JST - 死亡约束必须清理眼神冲突词与旁观者入画歧义

### Case 149: GinzaNight EP01 SH02 闭眼尸体重跑时，半开眼参考图与“服务员视角”造成二次偏移

**现象**

- 在 Seedance prompt 已追加“死亡约束”后，若继续使用眼睛半阖的粉色丝巾 keyframe，输出视频仍会继承半开眼状态，前几帧看起来像眼睛微动。
- 重生闭眼 keyframe 后，Seedance 曾把“服务员视角凝视”误解成服务员本人入画，白衬衫人物进入前景遮挡尸体。

**根因**

- I2V 首帧是强约束；如果首帧眼睛不是完全闭合，视频 prompt 很难可靠修正眼部状态。
- 原 prompt 中“眼神可辨认 / 无神半阖”等脸部可读性词与死亡约束冲突，会把模型拉回半睁眼。
- “服务员视角”属于摄影视角，不等于服务员可见；不显式禁止时，模型可能生成前景旁观者。

**有效方案**

- 对死亡 record，renderer 自动把“眼神可辨认 / 可见五官和眼神 / 无神半阖”等冲突词改为“闭合眼睑状态可辨认 / 双眼完全闭合”。
- 若 I2V 首帧已经半开眼，先重生 keyframe，再跑视频；不能只靠视频 prompt 修正。
- 对主观视角或旁观者视角镜头，若旁观者不应入画，用 execution overlay 明确“视角只表示观察方向，本人不入画；只允许指定尸体一名可见人物；禁止第二个人遮挡尸体”。

**系统化改进建议**

- 死亡状态 QA 除了检查视频 prompt，还要检查输入 keyframe 本身是否已经满足“双眼完全闭合”。
- 后续可把“视角人物是否入画”拆成显式字段，避免 `服务员视角 / 警察视角 / 旁观者视角` 被模型误解成可见人物。

## 2026-05-03 17:16:48 JST - WebUI artifact candidate id 会随索引刷新变化

### Case 148: EP01 SH01 Redo Clip 点击时报 `artifact candidate not found for this shot`

**现象**

- WebUI 中 EP01 SH01 当前 clip 和 keyframe 可正常显示，但点击 `Redo Clip` 后，前端报错 `{"detail":"artifact candidate not found for this shot"}`。
- 后端日志显示失败发生在 `PUT /api/projects/1/artifact-selection`，还没进入 Seedance job 创建。
- 实时 shot board 重新查询时，同一个 clip path 仍存在，但 `candidate_id` 已变成新的数据库 id。

**根因**

- WebUI artifact index 会删除并重建 `artifact_candidates`，导致 `candidate_id` 是短生命周期索引 id。
- 前端只提交 `candidate_id`，当用户页面持有旧 id 而后台刷新过索引时，后端按 id 查不到候选项。
- 这是 WebUI artifact selection / job creation 层问题，不是 record、prompt rendering 或 model execution 问题。

**有效方案**

- 前端选择 clip 时同时提交 `candidate_id` 和稳定的 `candidate_path`。
- 后端 artifact-selection 先按 id 查找，失败后按 `project_id + episode_id + shot_id + media_type + path` 回退查找。
- Redo job 创建时同样提交 `source_clip_path`，让 prompt-final map 在 `source_clip_candidate_id` 过期时仍能通过 path 找回当前 clip。

**系统化改进建议**

- WebUI API 对用户可见 artifact 操作应优先使用稳定路径或稳定 artifact uuid；数据库自增 id 只适合作为一次响应内的临时 UI key。

## 2026-05-03 17:11:48 JST - WebUI 重跑必须检查实际 clip 输出而不是只信脚本退出码

### Case 147: WebUI Seedance redo 中单镜头失败可能写 error.txt 但 job 仍显示 completed

**现象**

- WebUI 通过 `run_seedance_test.py` 重跑单个 clip 时，目标目录可能只生成 `error.txt`、`prompt.final.txt`、`payload.preview.json` 等审计文件，没有 `output.mp4` / `final_status.json`。
- `run_seedance_test.py` 对单镜头异常会捕获并继续，最终进程仍可能返回 `0`，导致 WebUI job 只按退出码显示 `completed`。
- 用户会误以为 redo 仍在后台或已经成功，但实际上没有进入可选新 clip 状态。

**根因**

- WebUI job 层只看子进程退出码，没有核对 Seedance shot 目录的实际产物。
- 这是 WebUI job status / artifact verification 层问题，不是 prompt rendering 或模型执行本身的问题。

**有效方案**

- WebUI 在 `run_seedance_test.py` shot job 结束后，若不是 `--prepare-only`，必须检查每个 `--shots` 对应目录是否存在 `output.mp4`。
- 若缺失 `output.mp4`，读取同目录 `error.txt` 追加到 job log，并把 job 标为 `failed`。
- 前端 redo 状态应使用 job SSE 显示 queued/running/completed/failed，并在完成后刷新 shot board，让用户看到 current clip 与新 redo clip 的真实状态。

**系统化改进建议**

- 后续可在 `run_seedance_test.py` 自身汇总 per-shot failure 并返回非零退出码；WebUI 的 output 检查仍应保留为二次保险。

## 2026-05-03 17:02:44 JST - 死亡状态镜头必须锁定眼睛与面部无自主动作

### Case 146: GinzaNight EP01 SH02 尸体视频中眼睑轻微漂移造成“眼睛动了一下”的观感

**现象**

- EP01 SH02 使用粉色丝巾 keyframe 重跑 Seedance 后，道具颜色正确，但抽帧发现前 1.5 秒眼睑/眼角纹理有轻微变化。
- 变化不是明显睁眼，但观感上会像尸体眼睛动了一下，破坏死亡状态可信度。

**根因**

- I2V 模型会自然给人脸添加微表情、眼睑纹理变化或面部肌肉细微运动。
- 原 record 虽写了尸体/瘫软/静止，但没有把眼睛、眼睑、眼球和面部肌肉写成不可动作的硬约束。
- 这是 prompt rendering / model execution 层问题，不是 source parsing 或 keyframe 道具问题。

**有效方案**

- 对 record 中明确出现 `尸体`、`死者`、`遗体`、`死亡`、`死去`、`遇害` 等死亡事实的镜头，keyframe prompt 与 Seedance prompt 自动注入死亡约束：
  `死亡约束:双眼完全闭合，眼睑全程静止，不眨眼，不睁眼，不转动眼球，面部肌肉完全静止，尸体状态无自主动作。`
- 不对普通睡觉、熟睡、装死、假死等非确认死亡状态自动套用。

**系统化改进建议**

- 死亡状态 QA 应抽取眼部高密度帧，检查是否出现眼睑变化、眼球漂移、嘴角或面部肌肉运动。
- 后续可把死亡约束纳入 record schema 的 `character_state_contract`，但当前先保持为 renderer 自动补强，避免复杂化 record 结构。

## 2026-05-03 16:51:35 JST - I2V 重跑不能用已污染 keyframe 修正道具事实

### Case 145: GinzaNight EP01 SH02 重跑 clip 时旧 keyframe 的浅蓝丝巾压过 record 的浅粉丝巾

**现象**

- EP01 SH02 record 与新视频 prompt 都明确要求 `PINK_SILK_SCARF` / `浅粉色丝巾`，并已追加同场景 3000K 暖床头灯色温契约。
- 直接使用当前 `ginzanight_ep01_rerun_20260502_from_scratch_v2_keyframes` 的 SH02 keyframe 重跑 Seedance clip，输出视频仍出现浅蓝丝巾。
- 改用后续修正过的 `ginzanight_ep01_sh02_promptfix_keyframe_20260503_grok` 粉丝巾 keyframe 后，重跑 clip 中丝巾颜色保持为浅粉色。

**根因**

- I2V 的首帧输入图是强约束；当 keyframe 已经含有错误道具颜色时，视频 prompt 中正确的 record 道具事实通常无法可靠覆盖输入图。
- 这是 keyframe 输入层污染影响 model execution 的问题，不是 record 字段或 Seedance prompt 渲染缺失。

**有效方案**

- 重跑 clip 前必须先审计 `image_used.txt` / keyframe 抽帧；若首帧图已违反 record source truth，应先换成正确 keyframe，再跑 I2V。
- 道具颜色、数量、位置这类首帧可见事实，不能指望仅靠 I2V prompt 在视频阶段纠正。

**系统化改进建议**

- Seedance prepare/QA 增加 keyframe-vs-record 检查：首帧图中的关键道具颜色/数量与 `first_frame_contract.key_props`、`prop_contract` 冲突时提示阻断。
- 对同场景色温问题也要区分：视频色温契约能减少动态漂移，但如果输入 keyframe 本身偏冷，仍需要先重生或选择色温正确的 keyframe。

## 2026-05-03 16:14:03 JST - 前夜亲密闪回 keyframe 可能被 OpenAI 图像安全拦截

### Case 144: GinzaNight EP02 SH06/SH07 前夜酒店套房烛光重生时 OpenAI safety block

**现象**

- EP02 SH06/SH07 当前 record 明确为 `银座高级酒店套房（前夜闪回）`，补充了 `shot_execution.time_of_day=前夜` 与 `primary_light_source=前夜酒店套房烛光` 后 prepare-only prompt 正确带入时间与主光源契约。
- 使用 OpenAI image model 重生 SH06/SH07 时连续 10 次被 safety system 拦截，返回 `safety_violations=[sexual]`。
- 同一份当前 record 改用 Grok 生成，SH06/SH07 start keyframe 均成功输出。

**根因**

- SH06/SH07 同时包含前夜酒店套房、烛光、礼服、肩线、靠近/依附、环腰等语义，虽然 record 已有 `人物衣着完整，保持日常社交距离，朴素克制呈现`，但组合仍容易触发 OpenAI 图像安全分类。
- 这是 prompt/provider 执行层问题，不是 source parsing 或 shot selection 问题。

**有效方案**

- 对这类前夜亲密闪回镜头，先用 prepare-only 审计 prompt；若 OpenAI 被拦截，可切换 Grok 生成，并保留 record 的时间/主光源契约与人物脸部可见契约。
- 后续若必须使用 OpenAI，应进一步把亲密动作改写成更中性的人物关系构图，例如“并肩站立、手部靠近领带、克制对视”，弱化肩线/环腰/贴近等组合词。

**系统化改进建议**

- 在 keyframe manifest 中保留 provider 与 safety block error，方便后续判断是否是模型执行层失败。
- 对 `前夜闪回 + 酒店套房 + 礼服 + 靠近/身体接触` 的组合增加 provider fallback 预案。

## 2026-05-03 15:43:58 JST - Keyframe static record 丢失时间意图会造成同场景日夜错位

### Case 143: GinzaNight EP02 SH01/SH02 酒店外街道 record 都是午后阳光，但 SH01 keyframe 生成成夜景

**现象**

- GinzaNight EP02 SH01/SH02 原始 record 都把画面放在 `银座高级酒店大门外街道`，并在核心画面描述中写到 `午后阳光`。
- WebUI 缓存展示的 SH01 keyframe 是夜晚/雨后湿街/酒店暖灯氛围，SH02 keyframe 是白天/午后酒店外街道。
- 两张 keyframe 都来自同一次 EP02 v2 keyframe 生成，provider 都是 `openai`，不是模型差异造成。

**根因**

- SH01 的 keyframe static record / prompt_render 把原始 record 中的 `午后阳光下眯眼停步` 压缩成了泛化的 `背景为现代日本都市街道`，丢失明确时间意图。
- 场景描述中仍有 `银座夜场与酒店空间`、冷暖灯光等泛化酒店氛围词，缺少午后约束时容易把酒店外街道生成成夜景。
- SH02 的 static prompt 仍保留 `午后阳光下脸部正面可见`，因此生成图符合白天/午后。

**有效方案**

- Keyframe static record 不能丢失 record 中明确的 time-of-day / light-source 词，尤其是 `午后阳光`、`清晨窗光`、`前夜烛光` 这类剧情时间锚点。
- 同一场景连续 shots 应使用 episode lighting/time contract；但契约只能补强 record 时间意图，不能替代 record source truth。
- 重生前需要 prepare-only 审计 prompt，检查相邻镜头是否都保留同一时间词与光源词。

**系统化改进建议**

- 对同 scene_id 的连续 shots 增加 time-of-day 差异检查：若 record 都含同一时间词，但 keyframe prompt 某一镜头缺失，应阻断或提示人工确认。
- Keyframe manifest 可记录 `time_of_day_terms_preserved`，用于 WebUI/QA 快速发现日夜错位。

**2026-05-03 16:02:22 JST 更新**

- 采用轻量结构化字段：`shot_execution.time_of_day` 与 `shot_execution.primary_light_source`。
- 未来 record 生成时从 LLM 输出或现有画面文本中保留时间/主光源；keyframe prompt 渲染时注入 `时间与主光源契约`，避免 record 中的午后事实被 static prompt 或场景泛化氛围洗掉。

## 2026-05-03 15:38:13 JST - 同场景连续镜头需要显式色温契约

### Case 142: GinzaNight EP01 SH01/SH02 同一酒店套房 keyframe 色温轻微漂移

**现象**

- WebUI 默认展示的 GinzaNight EP01 SH01/SH02 keyframe 都来自 `ginzanight_ep01_rerun_20260502_from_scratch_v2_seedance` 缓存。
- 图像哈希确认 WebUI 缓存图与原 keyframe 图一致。
- 两张图都为暖色酒店床头灯氛围，但 SH01 更偏暖琥珀，SH02 稍冷/中性；粗略 R/B 比约为 SH01 `1.335`、SH02 `1.273`。
- `provider.used.txt` 与 `grok_response.json` 显示 SH01/SH02 实际都由 Grok/xAI 图像接口生成，不是不同模型导致。

**根因**

- Record 与 keyframe prompt 只有泛化的“写实电影光，低饱和，情绪明确”，没有跨 shot 的固定色温、主光来源、色彩负向约束。
- 同一个图像模型逐张生成时，会因构图、灯具位置、曝光和随机性产生色温漂移。
- 仅靠 location/scene continuity 不足以锁定相邻镜头的调色。

**有效方案**

- 按 episode 建立 `episode_scene_lighting_map.json`，把同场景、同时间段、同光源系统的 shots 放进同一个 lighting group。
- Keyframe prompt 与 Seedance `prompt.final.txt` 都应显式注入同一段色温连续性契约。
- Lighting group 只能补充同场景视觉连续性，不得覆盖 record 中明确的时间、光源或剧情变化；同一地点如果从清晨切到前夜烛光，应拆成不同 lighting group。

**系统化改进建议**

- 在 keyframe/Seedance manifest 中记录 `episode_lighting_map`、`lighting_group_id` 与最终注入的 `contract_text`。
- QA 可增加同 lighting group 的色彩差异检查，比较床品/墙面/肤色区域的 R/B、R-B 或 Lab 色差，超过阈值时提示重生或调色。

## 2026-05-03 14:42:54 JST - Keyframe 安全改写存在 director 与 renderer 双层来源

### Case 132: GinzaNight EP01 SH01/SH02/SH03/SH06/SH07 重生前发现安全改写并未完全移除

**现象**

- 准备重生 GinzaNight EP01 SH01/SH02/SH03/SH06/SH07 keyframe 时，旧 keyframe prompt 仍出现“静止躺卧人物”“固定在颈部外侧作为关键线索”“衣领与肩部线条完整得体”“朴素克制呈现”等安全改写痕迹。
- 对比原始 record 与 `keyframe_static_records` 后，发现 record 中仍保留“尸体”“瘫软”“勒住脖子”“露出苍白肩线”等 source truth 词，但 keyframe prompt 会在渲染阶段再次改写。

**根因**

- `run_novel_video_director.py` 默认会生成 `keyframe_static_records`，这是一层 director-side static sanitize。
- 即使绕过 director static records，`generate_keyframes_atlas_i2i.py` 仍有 renderer-side `sanitize_keyframe_safety_text()` / `sanitize_keyframe_visual_text()`，会把死亡、颈部、肩线相关词替换成 provider-safe 描述。
- 因此“去掉安全改写”如果只关掉 director 层，不会影响 keyframe renderer 层。

**有效方案**

- 若目标是保持 record source truth 并让 keyframe prompt 不做安全语义替换，需要显式提供 renderer 层开关，或另建无安全改写的 keyframe prompt 渲染路径。
- 重生前必须检查 `prompt.txt`，确认是否仍含“静止躺卧人物 / 关键线索 / 衣领与肩部线条完整得体”等二次改写词。

**系统化改进建议**

- 将 director static sanitize 与 renderer safety rewrite 分成两个可审计开关，并在 `keyframe_manifest.json` 中记录每层是否启用。
- 对用户要求“无安全改写”的重生任务，必须先跑 `--prepare-only` 生成 prompt 审计，再进入真实 keyframe 生成。

## 2026-05-03 14:50:00 JST - Keyframe static anchor 不能默认覆盖 record 画面事实

### Case 133: GinzaNight EP01 SH01/SH02 无安全改写重生后仍偏离，因为 static anchor 把床上尸体事实覆盖成泛化脸部契约

**现象**

- 使用 no renderer safety rewrite 重生 EP01 SH01/SH02 后，生成图中人物偏站立/近景，不像 record 中“床上佐藤彩花瘫软 / 尸体 / 丝巾勒住脖子”的发现现场。
- 审计 prompt 发现 SH01/SH02 的 `keyframe_static_anchor.positive_core` 覆盖了 `prompt_render.shot_positive_core`，只保留“首帧人物脸部可见契约”等泛化语句。
- 原始 record 的 `shot_execution.camera_plan.framing_focus`、`prompt_render.shot_positive_core` 和 `first_frame_contract.visual_center` 仍含床上尸体事实。

**根因**

- `generate_keyframes_atlas_i2i.py` 在 start phase 默认使用 `keyframe_static_anchor` 覆盖 `scene_name`、`movement`、`framing_focus`、`action_intent` 和 `positive_core`。
- 这让 keyframe metadata 静默覆盖了 record source truth，违反“record content is source of truth”的项目规则。

**有效方案**

- static anchor 只能作为显式 opt-in 的执行辅助，默认不应覆盖 record 的 prompt_render / shot_execution 事实。
- 重生前审计 `prompt.txt` 时，不仅检查 safety rewrite 词，还要确认 record 中的关键画面事实仍出现在 prompt 核心段。

**系统化改进建议**

- 在 keyframe manifest 中记录 `use_keyframe_static_anchor` 是否启用。
- QA 增加检查：若 `keyframe_static_anchor` 删除了 `first_frame_contract.visual_center` 或 `prompt_render.shot_positive_core` 中的核心实体/位置，应阻断或要求显式确认。

## 2026-05-03 14:58:06 JST - 床上人物必须有完整身体承托关系

### Case 134: GinzaNight EP01 SH03 生成出半个身子在床边/半空中的物理错误

**现象**

- EP01 SH03 keyframe 中，彩花只有上半身明确在床边，身体下半部分像落在床外或悬在床边，物理上不像全身躺在床上。
- Record 事实是石川在床边检查床上彩花，人物应全身完整躺在床上，身体重量由床面承托。

**根因**

- Prompt 强调“床边检查”“床边地毯上酒杯/丝巾”等前景信息后，模型把人物身体位置拖向床边，忽略全身躺卧的承托关系。
- “脸部可见”和“石川蹲在床边”不足以保证彩花全身在床面内。

**有效方案**

- 对床上人物尸体/静止躺卧 keyframe，prompt 必须明确写入：
  - 全身完整躺在床上
  - 头、躯干、双腿都在床面上
  - 身体重量由床垫承托
  - 不允许半个身体悬在床边、滑落床外或漂浮
- 如果床边有地毯证物，证物只能在床下前景，不能把人物身体位置拉到床外。

**系统化改进建议**

- Keyframe QA 增加人体承托关系检查：床上人物、椅上人物、地面人物必须有明确支撑面；发现半身悬空/床外漂浮应重跑。

## 2026-05-03 11:01:07 JST - ScreenScript 多项目目录下自定义 bundle template 必须保留 story parent

### Case 131: father_story 迁移后 dry-run 发现自定义 bundle template 会把输出落回 screen_script 根目录

**现象**

- 将原 `screen_script/` 内容迁移到 `screen_script/father_story/` 后，`scripts/screen2video_play.py` 使用默认 `--bundle-template` 可正确生成 `screen_script/father_story/...` 输出路径。
- 但 README 示例中的自定义 `--bundle-template '{project_name}_{episode}_...'` 缺少 `{script_parent}`。
- dry-run 输出命令因此变成 `--out FatherStory_EP05_dryrun_probe`，会让 `screen2video_plan.py` 把 bundle 写到 `screen_script/FatherStory_EP05_dryrun_probe`，破坏多 screen script 项目的隔离。

**根因**

- `screen2video_play.py` 的默认模板已经包含 `{script_parent}`，但文档示例覆盖默认值时没有继承这一层。
- `screen2video_plan.py` 对相对 `--out` 的约定仍是相对 `screen_script/`，所以缺失 story parent 会静默回到全局根目录。

**有效方案**

- 多 screen script 项目目录下，自定义 batch `--bundle-template` 必须包含 `{script_parent}/...`。
- 已将示例改为 `--bundle-template '{script_parent}/{project_name}_{episode}_...'`。
- WebUI project discovery 改为识别 `screen_script/<story_name>/` 下带 `assets/`、`归档/` 或 markdown 的项目根。
- `screen2video_play.py` 已增加 warning：当 `script_parent` 非空且自定义模板未包含 `{script_parent}` 时，提示 bundle 会落到 `screen_script/` 根目录。
- 迁移既有故事目录时，必须同步重写 `character_image_map.json`、visual manifests、records/director manifests 中的 `screen_script/assets`、`screen_script/归档`、`screen_script/ScreenScript_*` 等旧路径到新的 `screen_script/<story_name>/...`。

**系统化改进建议**

- WebUI 新建/导入 screen script 项目时，应默认创建 `screen_script/<story_slug>/归档/`、`assets/`、`character_image_map.json` 的隔离结构。

## 2026-05-03 10:08:00 JST - 非目标道具不能从模型输出漏入 record 道具库

### Case 130: GinzaNight EP02 浅蓝丝巾污染 SH10-SH12 道具库

**现象**

- 原文第 2 集目标事实中，健一抽屉里的丝巾明确是“浅粉色丝巾”，SH12 request 的 `TARGET_PROP_CATALOG` 也只提供 `SILK_SCARF_PINK` 和 `SAKURA_PHOTO`。
- 落盘后的 EP02 SH10/SH11/SH12 record 却额外出现 `AYAKA_LIGHT_BLUE_SCARF`，并在 `prop_contract` 中标为首帧可见。
- SH12 同时存在 `AYAKA_LIGHT_BLUE_SCARF` 与 `SILK_SCARF_PINK`，造成同镜双丝巾、颜色冲突和来源不清。

**根因**

- 单镜 LLM 输出或后处理合并时，把不属于本镜 `TARGET_PROP_CATALOG` / `first_frame_contract.key_props` 的道具保留进了 record。
- 该蓝色丝巾在全书后文有来源，但不属于 EP02 这一镜的 source truth；record 不应让后文/模型补全静默覆盖本集目标事实。

**有效方案**

- 当前判断：EP02 SH12 的可执行道具应以 `SILK_SCARF_PINK` 为准，移除或忽略 `AYAKA_LIGHT_BLUE_SCARF`。
- 对本集 record 审核时，凡是不在 `TARGET_PROP_CATALOG`、`TARGET_SPINE_ROW.key_props` 或本镜 source basis 中的道具，不得进入 `prop_contract` 的首帧可见项。

**系统化改进建议**

- record normalization 应过滤 `prop_library` / `prop_contract`：只允许本镜目标道具、明确继承道具和服装类 modifiers。
- QA 增加检查：若 `first_frame_contract.key_props` 与 `i2v_contract.prop_contract` 不一致，或同类关键道具出现颜色互斥副本，应阻断。
- 对全书后文同名/同类道具，不得反向注入当前 episode；除非 source basis 明确说明这是同一物件并给出颜色连续性。

## 2026-05-02 18:15:24 JST - 小说卷标题不能被当作 episode 章节标题

### Case 126: GinzaNight EP01 rerun 被 `### 第一卷...` 卷标题截成单镜标题卡

**现象**

- GinzaNight EP01 从头 rerun 时，`source units: 1/188 scoped_ranges=[(1, 2)]`。
- `source_parsing_plan.json` 只有 `U0001`，文本为 `### 第一卷 · 银座的夜晚与隐藏的温柔（1-6章）`。
- LLM selection 只返回 1 个标题卡镜头，planning QA 仍然 pass，旧版 EP01 正常为 13 个 records。

**根因**

- `chapter_heading_number()` 把 `第一卷` 中的 `卷` 当作合法章节编号后缀。
- EP01 按章节编号 scoping 时先匹配到卷标题；由于下一行 `## 1. 酒店的发现` 也是编号 heading，范围被截到卷标题本身。
- 下游 source parsing / selection 只看见卷标题，无法覆盖第 1 章正文。

**有效方案**

- 章节编号 scoping 中排除 `卷` 后缀；`第 N 章`、`N.`、`N、` 仍可作为 episode/chapter 标题。
- 修复后先重跑 EP01 planning 验证：`source_parsing_plan` 应从 `## 1. 酒店的发现` 起，record 数应回到预期 13 个。

**系统化改进建议**

- Planning QA 应增加 `requested_shot_count` 对比：若生产请求 13 镜但 selection/records 只剩 1-2 镜，应阻断。
- Source scoping QA 应检查 scoped range 是否只包含卷/部/篇标题且无正文；这种情况不得继续进入 selection。

## 2026-05-02 18:22:00 JST - 对白镜头中的前置入场动作要压成首帧已到位

### Case 127: EP01 SH06 “姐姐……”对白镜头因推开人群走近床边触发一镜多任务 QA

**现象**

- GinzaNight EP01 v2 planning 中，SH06 source 是美咲进入房间、走近床边、轻触彩花手腕，并低声说“姐姐……”。
- LLM record 的 `first_frame_contract` 和 `positive_core` 已以床边触碰瞬间为视觉中心，但 `action_intent` 仍保留“推开人群走近床边”。
- Planning QA 触发 `i2v_dialogue_action_prop_overload`，判定对白 + 复杂动作 + 丝巾道具同镜过载。

**根因**

- 单镜规划 prompt 要求首帧稳定，但 LLM 会把原文前置入场动作链保留在 `action_intent`。
- QA 会综合 action/prompt/prop 文本检查复杂动作；即使首帧已经稳定，`action_intent` 中的“推开/走近”仍会触发阻断。

**有效方案**

- normalize LLM shots 时，对含对白镜头的前置 `推开/走进/走向/走去/走近` 动作压缩为“已到达画面主位置”，保留触碰、凝视、低声说话等首帧可执行微动作。
- Record 仍以 source 为事实依据，但视频执行层只呈现一个稳定任务：床边已到位后的短对白/微动作。

**系统化改进建议**

- 单镜 prompt 可进一步强调：对白镜头不要把 source 中的前置移动写入 `action_intent`；需要移动时拆成前一镜或改为首帧已到位。
- QA 报告可把具体命中的复杂动作词输出到 finding，便于快速定位。

## 2026-05-02 18:37:00 JST - 命案首帧 keyframe 要避免向图像模型直送高风险身体词

### Case 128: GinzaNight EP01 SH01/SH02 OpenAI keyframe 被 sexual safety 拒绝

**现象**

- EP01 v2 进入 OpenAI keyframe 后，SH01、SH02 连续 10 次失败，HTTP 400 `moderation_blocked`，`safety_violations=[sexual]`。
- prompt 中同时出现酒店床铺、人物参考、`尸体`、`瘫软`、`勒住脖子`、`肩线/露出苍白肩线` 等词。
- SH03 同样是命案现场，但 prompt 更偏刑侦检查和道具，能够成功生成。

**根因**

- record 可以保留命案事实，但 keyframe 图像模型 prompt 直接使用“床上尸体 + 颈部勒痕 + 肩线/露出”等组合，容易触发 OpenAI 图像安全系统的 sexual 分类。
- 只在负向 prompt 或安全句里写“衣着完整”不足以抵消高风险正向词。

**有效方案**

- keyframe prompt renderer 将高风险身体/死亡词改写为正向、克制、可视化等价描述：
  - `尸体/瘫软` -> `静止躺卧人物/安静躺卧`
  - `勒住脖子/勒痕/红痕` -> `固定在颈部外侧作为关键线索/关键线索痕迹`
  - `露出苍白肩线/肩线` -> `衣领与肩部线条完整得体`
- 保留 record 的 source truth；只在 keyframe 图像 prompt 层做 provider-safe rendering。

**系统化改进建议**

- 对酒店床铺、死者、颈部线索、衣领/肩部等组合，应在 keyframe preflight 中提示 OpenAI safety 风险。
- OpenAI keyframe 连续 safety 失败时，不应对同一 prompt 重试 10 次；应立即切换到 safe rewrite 或 Grok fallback。

## 2026-05-02 19:12:00 JST - 同一 source unit 内双人对白可拆镜，但集尾 critical unit 不能漏

### Case 129: GinzaNight EP02 selection 把 U0019 拆成 SH04/SH05，同时漏掉照片/敲门集尾 hook

**现象**

- EP02 source selection QA 阻断：SH04 和 SH05 都引用 `source_range=[37,37]`。
- 该 source unit 同时包含彩花提问“如果我消失了，你会守护小樱吗？”和健一回答“当然，我会。”；为了 I2V 单说话人，拆成两个镜头是合理的。
- 但同一次 selection 只选 8 镜，漏掉 U0024：抽屉深处的小樱照片、健一疑问、门外敲门和集尾 hook。

**根因**

- QA 把所有 source_range overlap 都当作 high，没有区分“同一 source unit 内双人对白拆镜”的合理重用。
- 结尾 critical unit omitted 仅为 medium，未能强制 LLM-rules selection 保留照片/敲门/hook 收束。

**有效方案**

- QA 允许同一 `source_unit_ids` 被多个 selected shots 引用，前提是 dialogue policy 显示单 active speaker / split 意图。
- 对最后 20% source units 中包含照片、证据、敲门、电话、消息、疑问、决定、反转或 hook 的 omitted/missing，升级为 high。
- selection prompt 明确最后 1-2 个 critical units 必须进入 selected_shots，不能静默遗漏或只用 omitted_units 概括。

**系统化改进建议**

- 对单段多说话人小说段落，source selection 可允许 shared source unit，但 per-shot planner 必须各自只保留一个 active speaker。
- Selection QA 报告应区分合理 shared-source dialogue split 与真实重复/回退选择。

## 2026-05-02 14:04:38 JST - 无对白镜头开启模型音频会自动脑补台词

### Case 125: EP05 SH40 no_dialogue 手机响镜头被 Seedance 自动补成接孩子对白

**现象**

- ScreenScript EP05 SH40 的 record 只有“手机响了”，`dialogue_blocking.lip_sync_policy=no_dialogue`，语言计划中 SH40 也没有字幕/对白。
- 重新生成的 Seedance clip 后半段出现“宝宝，妈妈马上就来接你啦。”，原文、record、语言计划均不存在这句。
- 旧版 SH40 也有类似污染，转写为“喂，你到了吗？我在幼儿园门口等你。”，说明不是单次随机错误。

**根因**

- `run_seedance_test.py` 的 payload 对 no-dialogue shot 仍为 `generate_audio=true`。
- SH40 prompt 没有强约束“本镜无人物对白，只允许手机铃声/环境声”，同时还带有“萌宝入园、母子温情”等上游情绪摘要，给音频模型提供了错误联想方向。
- Seedance 在无对白但允许生成音频的电话/手机场景中，会根据画面语境自行补普通话台词。

**有效方案**

- 当前修片：保留 SH40 画面前 3 秒，丢弃原模型音频，替换为短手机铃声和静音环境，再重新拼接。
- 对 no-dialogue 的 phone/setup/prop beat，不需要保留 4-5 秒生成片长；Novita 生成下限是 4 秒，但后期 assembly 可以剪到更短。
- 修复后 SH40 音频转写为空，最终 QA 通过。

**系统化改进建议**

- Seedance prompt renderer 遇到 `dialogue_blocking.lip_sync_policy=no_dialogue` 时，应明确写入“无人物对白、无人说话、无旁白，只允许环境音/道具声”。
- 对 no-dialogue shot，若 provider 支持，应默认 `generate_audio=false`；若必须保留音频，则使用后期可控环境音/道具声替换。
- QA 可对 no-dialogue clips 抽音频转写；若出现可识别中文台词，应标记 high severity，要求重生或音频修复。

## 2026-05-01 17:26:58 JST - 临时/配角可见人物缺少有效参考图会导致跨镜身份漂移

### Case 105: character_image_map 指向缺失的 EXTRA_TEACHER.jpg，老师在相邻 keyframe 中变成不同人

**现象**

- ScreenScript EP05 SH14 和 SH16 都是幼儿园教室中老师面对沈知予的镜头。
- SH14 首帧中老师是低马尾、短袖浅色上衣；SH16 首帧中老师变成丸子头、开衫、桌前拿笔，明显不像同一人。
- record 中 `老师` 是可见人物，且 SH14/SH16 都把老师作为 primary speaker/foreground character。

**根因**

- `character_image_map.json` 中 `EXTRA_TEACHER` / `老师` 指向 `screen_script/assets/characters/EXTRA_TEACHER.jpg`，但该 jpg 文件不存在。
- record 的 `EXTRA_TEACHER` 没有 `lock_profile_id`，`lock_prompt_enabled=false`，只有文字锚点“幼儿园老师，简洁职业装，亲和但紧张”。
- keyframe manifest 中每个相关镜头只有 1 个 character reference；老师缺少可用身份图时，模型按文字重新生成临时老师，表情/动作差异进一步放大服装和发型漂移。

**有效方案**

- 对可见且跨多镜出现的临时人物，如果已进入 `character_image_map`，必须验证图像文件真实存在。
- 若参考图缺失，应先生成或补齐 `EXTRA_TEACHER.jpg`，再重跑相关 keyframes。
- 对 EP05，可用一个确认过的老师形象作为 `EXTRA_TEACHER.jpg`，然后重跑 SH14-SH18 keyframes 和对应 Seedance/chained clips。
- 2026-05-01 17:37:42 JST 起，个体型临时角色在规划/执行 fallback 中应带 episode-local `*_LOCK_V1`，并写入 `lock_prompt_enabled=true`；群体背景角色如人群/路人/围观仍不升级成单人身份锁。

**系统化改进建议**

- keyframe preflight 应检查 `visible_characters` 中每个进入角色参考 map 的人物：路径存在、可读、不是空文件。
- 对 `EXTRA_*` 但跨多镜可见的角色，应自动升级为 episode-local ephemeral lock，至少在同一 episode 内固定发型、年龄、服装和脸型。
- 若 map 路径缺失，不应静默降级为纯文字生成；应在 director/keyframe manifest 中明确记录 `missing_character_reference` warning。

## 2026-05-02 01:47:59 JST - Source selection 默认不能回到 rule-only

### Case 106: Shared LLM Source Selection 已实现但 EP05 fullrun 仍走 rule，导致微场景地点 ownership 丢失

**现象**

- ScreenScript EP05 SH31 原文地点是幼儿园对面梧桐树下的黑色轿车内，赵一鸣坐在驾驶座接陆景琛电话。
- 生成视频中 SH31 变成赵一鸣坐在公交车内接电话。
- `source_selection_plan.json` 显示 `mode=rule`，SH31 的 `source_range=[123,123]`，只包含电话对白，未包含第119行黑色轿车建立和第121行手机响起。

**根因**

- Shared LLM Source Selection Planner 已实现，但 planner/batch 入口仍默认 `--selection-mode rule`，生产跑片没有启用 `llm-rules`。
- rule-only selection 按单个可执行 beat 选镜，缺少 setup-to-dialogue ownership；地点建立 unit 被 omitted，后续 phone/location 继承规则又把公交车内带入 SH31。

**有效方案**

- `screen2video_plan.py`、`novel2video_plan.py`、`screen2video_play.py`、`run_novel_episode_batch.py` 默认 `--selection-mode llm-rules`。
- `rule` 只作为显式离线/legacy fallback 使用。
- `llm-rules` 失败必须默认 fail-fast，不能静默 fallback 到 rule；只有显式传 `--allow-selection-fallback` 时才允许退回 rule，并必须在 fallback report/QA 中留痕。

**系统化改进建议**

- fullrun QA 应检查 `source_selection_plan.mode`；若是 `rule` 且非显式 legacy run，应高危报警或阻断。
- selection QA 应把 critical setup unit omitted but dependent dialogue selected 升级为 blocking，避免地点/主体建立行只留在 context 中。

## 2026-05-02 02:06:00 JST - 临时角色资产 profile 有 lock_id 不等于 record 已锁定

### Case 107: EP05 SH02/SH03 风衣妈妈同一角色在 record 中无 lock，导致相邻镜身份漂移

**现象**

- ScreenScript EP05 SH02 原文是“一个穿着高定风衣的妈妈牵着女儿走过来”，SH03 原文是“风衣妈妈”对闺蜜低声说话；剧情上是同一个人。
- 当前成片中 SH02 的风衣妈妈偏年轻、长发/低马尾，SH03 变成更成熟的短发/盘发感母亲，服装类型一致但人物身份不一致。
- `EXTRA_PARENT.info.json` 后续资产 profile 里有 `EXTRA_PARENT_LOCK_V1`，但 SH02/SH03 record 以及 `35_character_lock_profiles_v1.json` 中 `EXTRA_PARENT.lock_profile_id` 为空。

**根因**

- 这版 EP05 record 在临时角色锁机制修复前生成，record 的 `character_anchor.primary.lock_profile_id=""`、`lock_prompt_enabled=false`。
- 后续生成或补写的角色资产 profile 不会静默覆盖已落盘 record；record 仍是 source of truth。
- keyframe manifest 中 SH02 只有沈念歌等可用人物参考，SH03 `character_refs_count=0`，因此风衣妈妈按文字重新生成。

**有效方案**

- 修当前片：显式 backfill `EXTRA_PARENT` 的 record lock/profile，生成或补齐 `EXTRA_PARENT.jpg`，再重跑 SH02/SH03 keyframe 与 Seedance。
- 修未来片：个体型临时角色进入 record 时必须直接带 episode-local `*_LOCK_V1` 和 `lock_prompt_enabled=true`，不能依赖后续资产 profile 反向补救。

**系统化改进建议**

- keyframe preflight 应检查：若同一 `EXTRA_*` 个体跨多个 shot 可见，但 record/lock profile 中 lock 为空，应阻断或高危报警。
- 若 character asset profile 和 record lock profile 对同一角色的 lock 字段不一致，应输出 `record_asset_lock_mismatch`，并要求显式 backfill。

### Case 108: 临时角色图生成的 heuristic visual bible 可能套用主角白T模板

**现象**

- 为 EP05 显式 backfill `EXTRA_PARENT`、`EXTRA_TEACHER`、`EXTRA_FRIEND_PARENT` 后，首次运行 `character_image_gen.py` 生成的三张角色参考图都变成白 T 恤、牛仔裤、白帆布鞋的朴素女性，近似沈念歌。
- 其中风衣妈妈没有风衣，老师没有教师服/工牌，闺蜜也没有精致家长穿搭。

**根因**

- 角色图脚本在缺少明确 `*.visual_bible.json` 时调用 heuristic visual bible。
- 对“妈妈/老师/闺蜜”等临时角色，heuristic 默认项误用了沈念歌的年龄段、低马尾、白 T 牛仔裤模板；虽然 profile 文本里有正确描述，但 prompt 同时含有强冲突的白 T 模板，模型优先服从了更具体的错误服装。

**有效方案**

- 对当前 EP05 三个临时角色手写 `EXTRA_PARENT.visual_bible.json`、`EXTRA_TEACHER.visual_bible.json`、`EXTRA_FRIEND_PARENT.visual_bible.json`，明确固定服装、发型、身份差异和禁止白 T 牛仔裤。
- 重跑角色图生成后，风衣妈妈为米色风衣，老师为浅蓝教师装带工牌，闺蜜为浅粉外套和丝巾，三者与沈念歌区分明显。

**系统化改进建议**

- `character_image_gen.py` 对 `EXTRA_*` 个体角色不应只依赖 heuristic defaults；应优先从 record lock profile / character info 的 `visual_anchor` 构建 wardrobe 和 body fields。
- 角色图生成后应自动做视觉 QA：若输出服装命中主角模板禁词，如 `白T恤/牛仔裤/帆布鞋`，但角色 profile 要求风衣、教师装或其他固定服装，应标记失败并要求重生。

### Case 109: LLM-rules selection 在固定 shot 预算下可能省略结尾 hook 段

**现象**

- ScreenScript EP05 使用 `llm-rules` 和 `max_shots=36` 从头规划时，LLM 正好返回 36 个 selected shots，但 SH36 停在第 109 行“公交车来了”。
- 第 111-143 行的孩子追问、公交背影顿住、黑色轿车、赵一鸣电话确认孩子在星辉、后视镜收尾等结尾 hook 被写进 `omitted_units`，理由是预算限制。
- 规划 QA 阻断：最终 SH36 同时含沈念歌和沈知予两个 active onscreen speakers，且集尾时长不足、缺少 hook 标记。

**根因**

- selection prompt 只要求“不丢集尾钩子”，但没有明确告诉 LLM：结尾 15%-20% 和电话/消息收束在预算冲突时优先级高于早期环境/过渡镜头。
- 在严格 I2V 单说话人拆分后，36 个 shot 对 EP05 全集偏紧；LLM 用 omitted 解释压掉后段，而不是回头压缩前面的非关键过渡。

**有效方案**

- 在 shared selection rules 中明确：结尾 source units、episode hook、电话/消息收束不得因 `max_shots` 整段省略；预算紧时优先压缩早期无对白环境、过渡和重复反应。
- 电话/语音收束必须保留地点 setup、现场持机/接听者、关键远端问题、关键现场回答和挂断/沉默后的情绪反应。
- 对 EP05 这类对白密集集，生产 rerun 使用更充足的 shot 预算（例如 48），避免 I2V 可执行拆分与完整剧情覆盖互相挤压。

**系统化改进建议**

- selection QA 可把“最后 15%-20% source units 全部 omitted 且含电话/消息/悬念/决策”升级为 blocking。
- 当 LLM 选择数量等于 `max_shots` 且后段关键 units 被 omitted 时，planner 应提示增加 `max_shots` 或自动重试更高预算，而不是继续生成 records。

### Case 110: 小型手持道具 scale_context 规则不能覆盖手机、照片和文本证据

**现象**

- EP05 v3 从头跑时，planning 已通过，但 `create_visual_assets.py` 在 prop visual bible QA 阶段阻断。
- `KENICHI_SMARTPHONE`、`SMARTPHONE_01`、`SAKURA_SCHOOL_PHOTO` 被 LLM 或 normalize 结果写成 `reference_mode=scale_context`，随后 QA 要求 `scale_policy/reference_context_policy`。
- 这与小型手持道具改进计划的排除项冲突：手机和照片应走已有专门规则，不应被通用 scale-context 改写。

**根因**

- `prop_reference_mode()` 对显式 `reference_mode=scale_context` 优先级过高，未先排除手机、照片、报告/文件和结构件。
- `normalize_prop_bible_from_source()` 对 LLM 输出的 `scale_context` 没有按道具类型强制修正回 `product`。
- prop bible prompt 只说“小型手持道具使用 scale_context”，没有明确告诉 LLM 手机、照片、儿童画、报告/文件、门/车门仍使用 product。

**有效方案**

- `prop_reference_mode()` 先检查 non-reference、phone、photo，再读取显式 `reference_mode`。
- normalize 阶段对 phone/photo/non-reference 强制 `reference_mode=product`，并清空通用 `scale_policy/reference_context_policy`。
- prop bible prompt 增加排除句：手机、照片、儿童画、报告/文件、门/车门/车身结构件必须使用 product。

**系统化改进建议**

- regression test 固定覆盖 `SMARTPHONE_01`、`KENICHI_SMARTPHONE`、`SAKURA_SCHOOL_PHOTO`：reference_mode 必须为 product，且不会触发 scale_context QA。
- 小型道具新规则的优先级必须低于既有手机/照片/结构件专门规则。

### Case 111: semantic visible_characters 中的英文群体标签不能当作真实角色

**现象**

- EP05 v5 规划时，source selection 覆盖完整，但 planning QA 阻断多条 `visible_character_missing_from_character_anchor`。
- 触发词是 `all_children_and_parents` 和 `class_group`，来自 semantic annotation 的 `visible_characters`，并非源文本中的具体人物。

**根因**

- semantic normalization 已过滤中文背景群体（孩子们、家长们、全班孩子等），但没有覆盖 LLM 常输出的英文伪群体标签。
- 这些标签进入 `first_frame_contract.visible_characters` 后，被 QA 当成需要 character anchor 的真实人物。

**有效方案**

- 将 `all_children_and_parents`、`all_children`、`all_parents`、`class_group`、`children_group`、`parents_group`、`background_group`、`classmates` 加入背景群体过滤。
- 群体只作为背景反应层/环境层，不进入首帧前景角色锁定。

**系统化改进建议**

- semantic 输出中的英文 snake_case/group 标签默认不得直接进入 `visible_characters`；除非能映射到明确角色 id 或中文人物名。

### Case 112: 角色比例 QA 不能把 forbidden similarity 里的禁词当成正向描述

**现象**

- EP05 v6/v7 生成 `EXTRA_CHILD` 角色资产时，手写 `EXTRA_CHILD.visual_bible.json` 本身通过 QA，但接入 `character_contrast_bible.json` 后仍被判定“4岁半儿童比例契约含低龄/大头风险词: 婴儿”。
- 实际命中来自 `pairwise_forbidden_similarity` / `distinction_anchors` 中的禁项“Q版大头或婴儿比例”，不是正向比例要求。

**根因**

- `validate_character_bible()` 对风险词扫描了完整 JSON，包含 forbidden/drift/pairwise negative fields。
- contrast bible 的“不要像什么”被 normalize 合入角色 bible 后，禁词失去语义方向，被当成要生成的比例描述。

**有效方案**

- 角色比例风险扫描只读取正向字段：`age_band`、`face_geometry`、`hair_silhouette`、`body_frame`、`wardrobe_signature`、`proportion_contract`、`portrait_prompt`、`appearance`、`costume`。
- `pairwise_forbidden_similarity`、`forbidden_drift`、contrast negative items 不参与低龄/成人比例风险词扫描。

**系统化改进建议**

- 所有 QA 禁词检查都应区分正向生成字段和负向禁止字段，避免“禁止 X”被误判为“生成 X”。

## 2026-05-01 16:33:29 JST - 背影修复和状态覆盖不能吞掉连续持有物

### Case 104: “back view, holding child” 修脸部可见时不能把抱孩子状态一起删掉

**现象**

- ScreenScript EP03 最新 LLM+I2V 规则版中，SH05 的语义状态覆盖包含 `walking away holding child`，SH06 的 LLM 语义响应原本包含 `back view, holding child`，SH07 包含 `stopped holding child`。
- 生成后的 SH06 record 被背影修复改成“行走/离开姿态可见，但首帧仍需正侧脸或三分之二侧脸可辨认”，`holding child` 同时丢失。
- SH07 record 的 `character_state_overlay` 仍保留 `stopped holding child`，但 `prompt_render.shot_positive_core` 没有写入抱孩子状态，执行层 prompt 仍看不到孩子。
- 最新目录没有 `shot_chain_plan.json`、`chain_execution_manifest.json` 或 `clip_overrides.json`，SH05-SH07 没有被生产链路确认为 chained continuous shots；只有 SH06 写入了通向 SH07 的 `movement_boundary`。

**根因**

- `repair_character_state_overlay_face_visibility()` 遇到包含 `back view` 的整条 visible constraint 时按整条删除，未拆分保留同一条里的非背影约束，例如 `holding child`。
- `character_state_overlay` 主要落盘到 record，当前 prompt 渲染没有系统地把身体状态、持有物、可视约束写进 `prompt_render.shot_positive_core` / keyframe prompt。
- 相邻 movement boundary 只约束 SH06 到 SH07 的走停衔接，不等同于 Seedance tail-frame chaining，也不会自动保证 SH05-SH07 的持有物连续。

**有效方案**

- 背影修复应做语义拆分：把 `back view, holding child` 改写为“抱着孩子；行走/离开姿态可见，但首帧仍需正侧脸或三分之二侧脸可辨认”，只移除背影构图，不删除持有物。
- 对 `character_state_overlay.visible_constraints` / `key_props` 中的可见持有物，渲染进 prompt 正文和 keyframe prompt；尤其是连续镜头中的婴儿、文件、照片、手机等。
- 对 newborn/child 这类剧情状态证据，可作为“怀中婴儿/孩子”持有物锁定；是否进入 foreground character count 需单独决策，但不能在 prompt 中静默消失。

**系统化改进建议**

- QA 增加检查：语义响应或 record 状态覆盖中出现 `holding child` / `抱着孩子`，但 `prompt_render.shot_positive_core`、keyframe prompt 或 Seedance final prompt 中没有对应持有物时报警。
- 连续 postpartum / newborn 段落中，若上一镜和下一镜都明确抱孩子，中间相邻 dialogue shot 不应丢失孩子，除非源码有交接、放下、出画等明确证据。
- `shot_chain_plan` 与 `movement_boundary` 在报告里分开标记，避免把“相邻动作边界”误认为“生产级连续镜头链”。

## 2026-05-01 15:37:58 JST - Keyframe fallback、链式分流和 QA 必须按实际装配片段对齐

### Case 102: OpenAI keyframe 被 safety 拒绝时可用 Grok 图像补失败镜头

**现象**

- ScreenScript EP03 LLM+I2V 规则 v2 关键帧生成时，OpenAI 拒绝 SH01、SH09、SH23，返回 `moderation_blocked` / `safety_violations=[sexual]`。
- 三个镜头并非性内容：SH01 是验孕棒/床边/早孕证据，SH09 是单亲母亲深夜照顾孩子和兼职，SH23 是母子拥抱和儿童画。

**根因**

- keyframe prompt 中“床边、验孕棒、怀孕、年轻母亲、抱孩子、身体状态”等组合容易被图像安全系统误判。
- 这是 keyframe provider moderation / prompt rendering 层问题，不是 planning record 的剧情错误。

**有效方案**

- `generate_keyframes_atlas_i2i.py` 支持 `--image-model grok` 和 `--xai-model grok-imagine-image`，可只对失败 shot 使用 Grok 重跑，不必改 record 或重跑已成功 keyframes。
- EP03 中 SH01、SH09、SH23 用 Grok 补图成功；SH01 画面中桌上绿萝稳定、未漂浮，验孕棒稳定在手中。
- Grok 局部补跑会重写 `keyframe_manifest.json` 为仅含补跑镜头，后续必须从现有 `start.jpeg` 重建完整 manifest / `image_input_map`，否则 Seedance 只会看到 3 个 keyframes。

**系统化改进建议**

- keyframe runner 应支持 `--merge-manifest` 或自动保留旧 manifest，只更新补跑 shot。
- 对 OpenAI moderation-blocked 的 keyframe，可自动走 Grok fallback；同时记录 provider.used，便于追踪混合 keyframe 来源。
- safety rewrite 层应把验孕/早孕镜头表达成医疗证据/生活证据构图，减少“床边+怀孕+身体状态”触发误判。

### Case 103: 链式 Seedance 分流和 QA 时长检查必须使用实际 clip overrides

**现象**

- EP03 chain plan 把 SH14-SH20、SH22-SH23 识别为高置信连续组，但 `run_chained_seedance.py` v1 对 overlapping chains 会跳过部分 pair。
- SH20 被 screen2video 分流为 chain shot 后，chain runner 实际未生成 SH20，普通 Seedance 也未跑，导致 assembly 前缺片。
- SH20、SH22 原始 Seedance 片段约 12.05 秒，但语言 QA 估算分别需要约 12.98 秒和 12.44 秒，触发 `early_scene_cut`。
- 给 SH20/SH22 追加静帧和静音尾巴并通过 clip override 装配后，原始 concat 仍指向旧片段；`qa_episode_sync.py` 用原始 concat 计算时长，继续误报早切。

**根因**

- overlapping chain groups 在 v1 中不是完整连续链执行，只会执行部分 pair；被分流的末端/中间 shot 可能没有普通补片。
- QA 读取 concat 文件的片段时长，而不是读取 assembly 中实际应用 clip overrides 后的片段。

**有效方案**

- chain runner 完成后检查每个 shot 是否有普通 clip 或 override clip；缺失的 SH20 单独用普通 Seedance 补跑。
- 对超过模型单镜时长上限但只差短尾巴的长对白镜头，可追加短静帧和静音尾巴，生成 padded clip，并写入新的 `clip_overrides_with_padding.json`。
- QA 应使用 applied concat，也就是把 clip overrides/padded clips 展开后的 concat；EP03 使用 `concat_ep03_applied.txt` 后同步 QA 通过：`pass=True, findings=0`。

**系统化改进建议**

- `screen2video_play.py` 在 chain runner 后应检查 chain_shots 的实际覆盖情况，未覆盖的 shot 自动回补普通 Seedance。
- `assemble_episode.py` 可输出 applied concat；`qa_episode_sync.py` 默认优先读取 assembly report 中的实际 overrides，而不是原始 concat。
- 对 12 秒上限附近的对白镜头，planning 阶段应优先拆镜或缩短单镜对白，避免后期用静帧补时长。

## 2026-05-01 14:43:28 JST - semantic action_targets 不能把物体或抽象状态升级成可见人物

### Case 101: LLM 语义标注中的 action_targets 需要人物过滤

**现象**

- ScreenScript EP03 使用 LLM+I2V 规则 v2 重跑后，`remote_listener_marked_visible` 已消失，SH10 正确变成沈念歌对画面内予予唱生日歌。
- 但 semantic annotation 把 `candle flame`、`heart condition implied` 写入 `action_targets`，后续 record 生成把 action target 加入 `visible_characters`，QA 触发 `visible_character_missing_from_character_anchor` 高危。
- 这会把蜡烛火苗、抽象心脏病情等非人物对象错误当成角色锚点。

**根因**

- 语义层 `action_targets` 原本用于“动作作用在谁身上”，但未限制为人物名。
- prompt/record 层为了保住说话人与动作对象的同框关系，会把 onscreen dialogue 的 listener/action target 补进前景人物；如果 action target 是物体或抽象状态，就会污染可见角色列表。

**有效方案**

- 对 semantic `action_targets` 增加人物过滤，只保留主角表、别名表和临时人物 token 中的名字，例如沈念歌、沈知予、护士。
- `candle flame`、`heart condition implied` 等非人物 action target 被丢弃；物体/病情仍可留在 source excerpt 或 prompt 动作文本里表达，但不能进入 `visible_characters` 或 character anchor。
- 过滤后 EP03 LLM+I2V 规则 v2 规划 QA 通过：`planning QA pass: True findings=4`，仅剩 medium 级执行复杂度/结尾 hook 提示。

**系统化改进建议**

- semantic prompt 中明确区分 `action_targets_character` 与 `action_targets_object_or_prop`，后者只允许进入 prop/scene/action 文本，不允许进入 character anchor。
- QA 对 `visible_characters` 增加白名单/证据检查：非人物英文短语、抽象状态、病名、火焰、文件内容等不应作为角色名落盘。

## 2026-05-01 14:30:53 JST - LLM 选镜能保剧情证据，但必须带 I2V 执行约束

### Case 100: 规则选镜会保留建立镜头却丢掉相邻关键证据，LLM 合并后又可能产生多说话人高危镜头

**现象**

- ScreenScript EP03 规则-only 选镜在 `--max-shots 18` 下保留 SH01 小公寓全景和桌上绿萝，但丢掉 line 17-39：沈念歌坐床边握验孕棒、两条红线、落泪、林雨薇短信、扣手机、扔验孕棒、走到窗边、手放小腹。
- LLM 不带规则和 LLM 带规则都能自然保住“验孕棒/两条红线”怀孕证据；带规则版本会把 line 13-23 合并为开场怀孕 reveal，让绿萝退回静态陈设。
- 但 LLM 带规则方案也把多组对话压进单镜，例如护士与沈念歌来回对话、母子问答，触发 `i2v_multiple_active_onscreen_speakers` 高危 QA，不适合直接进入 Seedance。
- 另一个连带问题：SH02 短信内容里出现“果汁”，旧 prop 检测从原始 `source_excerpt` 读到该词，误生成 `JUICE_CUPS_02/CUP_01`，把文档/消息内容实体化成真实画面道具。

**根因**

- 规则选镜只按 draft 分数和每场首镜保留，缺少 pregnancy reveal / evidence prop / irreversible decision 等 must-keep beat gate。
- LLM selection/merging 如果只给剧情保留规则，而不给 I2V 执行规则，会倾向把完整对白交换合并成一个剧情完整镜头，但这违反“一镜一活跃说话人”的视频生成约束。
- prop detection 使用了未清洗的 `draft.source_excerpt`，导致短信、屏幕、报告中的文字内容被当成画面真实物体。

**有效方案**

- 为 `screen2video_plan.py` 增加 `--shot-selection-plan`，允许使用外部/LLM 产出的 `selected_shots[].line_range` 覆盖内置规则选镜；后续 semantic pass、record render、QA 仍走原流水线。
- 对 EP03 使用 LLM 带规则 plan 后，SH01 正确覆盖 line 13-23，并在 record 中写入 `PREGNANCY_TEST_STICK_01`、两条红线提示、沈念歌坐床边握验孕棒的 keyframe moment。
- “绿萝”不作为剧情 prop 出图，进入 `scene_overlay.required_elements` 和 `physical_rules`：桌上一小盆绿萝，花盆底部贴合桌面，全程不漂浮、不滑动、不旋转、不被人物操纵、不新增副本。
- prop detection 对 `source_excerpt` 也先执行 `sanitize_prompt_text`，把短信/消息/引号内容替换为不可读文字块，避免“果汁”等文本内容生成真实道具。

**系统化改进建议**

- LLM selection prompt 必须同时给三类规则：剧情 must-keep、I2V 单镜执行复杂度、record source line truth。尤其要明确“一镜最多一个 active onscreen speaker”，多说话人对话必须拆镜或将非主体说话人改为画外/前后镜处理，不能只因剧情完整而合并。
- selection QA 应在 LLM 方案落盘前检查：高危多说话人、关键证据物缺失、文档/短信内容实体化、静态陈设未加物理锁。
- 对剧情证据物建立 domain lexicon，例如验孕棒、两条红线、出生登记、心内科预约、儿童画等；这些应高于普通建立镜头和环境陈设。

## 2026-05-01 14:02:48 JST - 关键回应镜头不能丢失前置叫住/追问对白

### Case 99: 被 max-shots 淘汰的 setup dialogue 应并入相邻回应 shot

**现象**

- ScreenScript EP03 SH05 源文第 67-71 行是：护士追出来，护士说“沈小姐！你产后还没恢复，不能出院……父亲那一栏你空着，需要补充——”，沈念歌头也没回回应“父亲不详。”
- 规划因 max-shots 代表性选择保留了沈念歌的短回应，但把护士叫住/补登记那句淘汰，只留在 `shot_context_excerpt`。
- I2V prompt 因 `dialogue_lines` 只有沈念歌一句，明确要求护士“不说话、不张口”，导致“护士把主角叫回来/追出来叫住”这部分内容缺失。

**根因**

- shot selection 层按单条 dialogue draft 评分选择，缺少“setup question/callout + direct response”成对保留或合并规则。
- context 字段只供语义参考，不会自动变成可执行 dialogue；record content 才是执行层 source of truth。

**有效方案**

- 不额外增加 shot 数；在 selection 之后检查已选短回应镜头。
- 如果其前一个同场景、不同说话人的未选中 dialogue 含“沈小姐/等等/不能/需要/补充/可是/疑问/破折号”等 setup 迹象，并且当前镜头是短回答或动作回应，则把前置 dialogue 合并进当前 shot 的 `dialogue_lines`。
- 若前置相邻 visual 含“追出来/叫住/喊住/拦住”等动作，只抽取该动作作为 `前置动作`，避免把更早的无关情绪画面一起并入。
- 合并后 prompt renderer 才会生成多说话人 timeline，而不是把 setup speaker 误写成沉默反应。

**系统化改进建议**

- QA 增加 source coverage 检查：当 `shot_context_excerpt` 含关键追问/叫住对白，但 `dialogue_language.dialogue_lines` 未覆盖时报警。
- 对 screen script，短回答如“父亲不详/不知道/不行/好/嗯”应优先检查前一句是否是不可省略的问句、叫住或要求。

## 2026-05-01 13:47:32 JST - 普通 Seedance 第一轮必须跳过 chained shots

### Case 98: high-confidence chain shots 不能先生成普通版再由 chained override 覆盖

**现象**

- full-run production 默认加入 chained path 后，普通 Seedance 仍会先跑全量 shots。
- 对 SH05/SH06 这类已进入 `shot_chain_plan.json` 的连续镜头，后续 `run_chained_seedance.py` 会再跑一遍并输出 `clip_overrides.json`。
- 这样虽然 assembly 能用 override 成片，但第一轮普通版本会造成重复消耗、目录混乱，也容易让人工审查误看旧 clip。

**根因**

- full-run runner 只把 chaining 当作普通 Seedance 后的追加覆盖步骤，没有把 `shot_chain_plan.json` 作为第一轮 Seedance 的排除清单。
- 缺片检查只看普通 Seedance 目录，尚未把 chained `clip_overrides.json` 视为合法产出。

**有效方案**

- `screen2video_play.py` 与 `run_novel_episode_batch.py` 在普通 Seedance 前读取 `shot_chain_plan.json` 的 `groups[].shots`，且只有整组都在本次 selected shots 内时才启用 chained-only 分流。
- 普通 Seedance 只跑不在有效 chain group 里的 shots；chain plan 里的 shots 只交给 `run_chained_seedance.py`。
- assembly 前的缺片检查接受 chained `clip_overrides.json`，保持 concat 的完整 shot 顺序，由 `assemble_episode.py` 在存在性检查前应用 override。

**系统化改进建议**

- full-run summary 记录 `chain_shots` 与 `ordinary_seedance_shots`，让 QA 能直接看出哪些 shots 是 chained-only。
- 若 `shot_chain_plan.json` 存在但 `clip_overrides.json` 缺失，应在 assembly 前明确报错，而不是回退到普通 clip。

## 2026-05-01 13:43:22 JST - 状态覆盖不能把可见说话人退化成背影主体

### Case 97: “头也没回/走开”的状态约束必须保留脸部可辨认

**现象**

- ScreenScript EP03 SH05 加入相邻移动边界后，主 prompt 已正确写入“不得走远、不得出画、为 SH06 停下脚步保留衔接”。
- 但 `character_state_overlay.visible_constraints` 仍保留语义探针给出的“背影，抱着孩子”，导致同一 prompt 里同时出现“脸部可见”和“可视约束=背影”的冲突。
- keyframe prompt 也会继承该状态覆盖，容易把起始帧画成后脑/背影主体，削弱说话人口型和脸部识别。

**根因**

- movement boundary 和 dialogue gaze contract 只修正了动作与视线层，没有同步清洗 shot-local body state overlay。
- 语义层把“头也没回”的表演动作误收敛成“背影”构图要求；这属于 record field propagation / prompt rendering 交界问题。

**有效方案**

- record 生成阶段遇到 `visible_constraints` 含“背影/背对/背向/后脑/只见背/back view/from behind/rear view”等词时，改写为“行走/离开姿态可见，但首帧仍需正侧脸或三分之二侧脸可辨认”。
- 同时加入负约束：“不得只有背影或后脑作为主体”“不得让说话人的脸和嘴不可辨认”。
- keyframe renderer 与 I2V prompt renderer 都做同样的保险清洗，避免旧 record 或外部 record 绕过规划修复。
- 对“头也没回/走开”类镜头，不要允许“三分之二侧后方”作为默认构图；模型仍可能执行成背拍。应明确从侧面或侧前方取景，角色只做小幅横向/斜向移动，一两步内仍留在画面。

**系统化改进建议**

- QA 增加冲突检查：同一 prompt/record 同时出现“脸部可见/嘴部可辨认”和“背影/背对/后脑主体”时直接报警。
- 对“头也没回”这类动作，应表达为眼神不回看听话人，而不是构图上只拍背影。

## 2026-05-01 13:40:02 JST - full-run production 默认走 Novita chained path

### Case 96: 默认全量生产不能静默跳过 high-confidence shot chaining

**现象**

- ScreenScript EP03 20260501 full-run 默认 director 只生成 start keyframes，`image_input_map.json` 全部为 start-only。
- `keyframe_manifest.json` 中 `reuse_next_start_from_prev_end=false`，且 `last_image_used.txt` 为空。
- Seedance 未显式传 `--video-model` 时，曾从 profile/catalog 路径落到 Atlas，触发 `HTTP 402 insufficient balance`。

**根因**

- full-run batch runner 只调用普通 `run_seedance_test.py`，没有默认执行 `run_chained_seedance.py` 的真实尾帧 handoff 和 clip override。
- director 的 `--enable-high-confidence-shot-chaining` 之前不是默认值，只在手工传参时生成 `shot_chain_plan.json`。
- provider 选择没有在生产 runner 中显式锁 Novita，容易被 profile 顺序、环境变量或旧默认影响。

**有效方案**

- `run_novel_video_director.py` 默认生成 high-confidence `shot_chain_plan.json`，需要时用 disable flag 关闭。
- `screen2video_play.py` 与 `run_novel_episode_batch.py` 默认在普通 Seedance 后执行 `run_chained_seedance.py`，产出 `clip_overrides.json`，assembly 默认传入该 override。
- batch runner 和 standalone `run_seedance_test.py` 默认使用 `novita-seedance1.5`；Atlas Seedance 暂时禁用，避免生产路径再次因余额或 provider capability 落空。

**系统化改进建议**

- QA 报告应区分 start-only I2V、tail-frame handoff chaining、provider-native last_image chaining 三类连续性策略。
- Novita chaining 的验收应看 `chain_execution_manifest.json`、tail frame、下一镜 `image_used.txt` 是否匹配，而不是看 payload 是否有 `last_image` 字段。

## 2026-05-01 13:24:19 JST - 相邻对白镜头的移动动作不能破坏下一镜首帧衔接

### Case 95: “继续走/离开”与下一镜“停下脚步/继续对话”必须形成动作连续链

**现象**

- ScreenScript EP03 SH05 原文是沈念歌“头也没回”说“父亲不详”，随后 SH06 原文是沈念歌“停下脚步”说“我说了。不详。”
- 最新 SH05 I2V prompt 中写入“继续走”，模型可自然执行成主角走远或出画。
- SH06 prompt 又要求沈念歌停下脚步并继续对护士说话；若 SH05 结尾已经走出画或远离护士，SH06 首帧会出现跳接。
- SH05 同时存在“头也没回”和默认对白视线“看向护士的脸部或眼睛”，动作逻辑内部冲突。

**根因**

- `screen2video_plan.py` 的对白视线规则默认将画面内 speaker/listener 处理成 mutual eye contact，没有识别“头也没回/没回头/背对回应”等源码动作覆盖。
- character state overlay / keyframe moment 只提取了“继续走”，缺少相邻镜头连续性边界，例如“仍在画面内、不要走远、结尾放慢、为下一镜停下脚步做衔接”。
- 这是 planning / record field propagation / prompt rendering 交界问题，不是源剧本解析错误，也不是 assembly 层能完整补救的问题。

**有效方案**

- 源文动作仍保留：如果原文写“继续走”，不能静默改成站定。
- 当下一镜同一角色仍在同一地点继续对话、停下、转身或回应时，上一镜的移动动作必须加连续性边界：只走一两步、仍留在画面内、不出画、不走远、结尾步伐放慢或即将停下。
- 对“头也没回/没回头/背对回应”类动作，gaze contract 应覆盖默认互看规则：说话人不看听话人，最多侧背/侧脸可见，脸部可见只服务观众识别和口型，不表示角色眼神看向对方。
- 若必须保证口型可见，可采用侧背/三分之二侧后方或侧前方补光构图，但不能把“头也没回”改成正面对视。

**系统化改进建议**

- planning 增加 adjacent-shot motion continuity pass：检查同地点、同角色、相邻对白镜头中的 move-away / continue-walking / exit 与 stop / turn-back / reply 的组合，并写入 shot-local continuity boundary。
- record 增加 movement_boundary 或 continuity_bridge 字段，明确 `end_state` 与 `next_shot_start_state`。
- QA 增加报警：上一镜 prompt/record 含“走开、离开、走远、出画、继续走”，下一镜同角色仍需近景说话或停下脚步时，要求人工确认或自动加入“不出画/不走远/为下一镜停步衔接”。
- Prompt renderer 应将 movement_boundary 放在动作意图附近，而不是只放在连续性泛化段，避免模型把移动动作执行过度。

## 2026-05-01 13:12:29 JST - ScreenScript 远端语音和文档内容不能实体化入镜

### Case 94: 电话/语音远端说话人默认不可见，电脑简报文字只作为文档内容

**现象**

- ScreenScript EP04 审片时，SH14 原文是沈知予发来的手机语音，画面应是沈念歌在档案室听语音；生成 record/prompt 却把沈知予设为首帧焦点，并要求孩子脸部可见。
- SH15 原文是沈念歌对着手机回复“乖，妈咪下班就回去”，孩子仍是远端对象；record 却把沈知予加入前景 exactly 2，视频生成母子同框。
- SH16 原文是总裁办公室电脑屏幕上的简报特写，简报文字里提到沈念歌和四岁半儿子；record 却把文档内容中的人物变成真实前景人物，强制“沈念歌牵着沈知予”。
- SH05-SH07 原文已经进入三十二楼行政部办公区，但 record 仍沿用父级“一楼大堂”。

**根因**

- `screen2video_plan.py` 接受 semantic `visible_characters` 和关系推断时，没有区分 phone/voice-message speaker 与画面内实体人物。
- 对“对着手机”回复的对白，listener 被当作 onscreen listener 加入 visible characters。
- 文档/屏幕特写中的姓名、儿子、年龄被当成场景中真实人物证据。
- 局部地点规则缺少行政部、档案室、档案柜等职场地点，连续对白也没有继承上一镜的 shot-local location。

**有效方案**

- `source == phone` 时，speaker 默认是远端声音，不进入首帧 visible characters；画面优先保留接收者和手机。只有视频通话、屏幕里出现、监控截图、照片等明确视觉证据才允许远端人物可见。
- “对着手机/回复语音/听到儿子的声音”场景中，listener 标为电话远端，不加入前景人物。
- “屏幕上是一份简报/电脑屏幕报告特写”中，文档内容里的姓名与亲属关系不能触发人物入镜；首帧中心应是电脑屏幕/简报/报告道具。
- 增加行政部办公区、档案室等局部地点识别，并允许连续对白继承上一镜有证据的局部地点。
- ScreenScript record patch 阶段要清理小说项目遗留的角色专属通用道具 profile，例如 `KENICHI_SMARTPHONE`；手机只保留当前项目的 `SMARTPHONE_01` 或剧本明确命名的本地 prop id。

**系统化改进建议**

- planning QA 增加高危检查：phone speaker 出现在 `first_frame_contract.visible_characters`、远端 listener 出现在前景人物、屏幕/报告特写出现文档内容人物实体化。
- 对 screen script 的 visual beats 增加 must-keep 权重：档案袋、金色电梯、文件散落、递文件等非对白动作不能被 max-shots 选择轻易丢弃。

## 2026-05-01 13:19:02 JST - 结尾 hook 不能强行污染最后一镜画面

### Case 95: screen script 的集尾钩子可作为元信息保存，不等于最后一镜对白/可见物

**现象**

- ScreenScript EP04 最后一镜原文是陆景琛继续处理文件，电脑屏幕角落留着沈念歌简报，本身是无对白反应镜头。
- 原剧本另有“本集钩子”元信息，说明“四岁半”和四年前时间吻合等追更悬念。
- 旧 QA 要求集尾 hook 必须进入最后一镜对白或 prompt 可见元素，导致修复时容易把追更文案、人物关系或不该出现的孩子/照片塞进最后一镜。

**根因**

- `novel2video_plan.py` 的结尾 hook 校验只识别 dialogue/subtitle/prompt/action/first-frame 中的 hook 词。
- 对 screen script 来说，`本集钩子` 是 episode-level metadata，不一定是最后一镜画面事实；record source truth 不允许它静默覆盖最后一镜原文。

**有效方案**

- 最后一镜无对白时，若有 episode-level hook，把它存入 `i2v_contract.episode_hook_context`，作为剪辑/运营层上下文，不渲染进 `shot_positive_core`。
- 结尾 QA 识别 `episode_hook_context` 后，不再报 `ending_hook_missing_dialogue` 或 `ending_hook_not_marked_as_episode_hook`。
- 最后一镜的可见人物、道具、动作仍只来自该 shot 原文和必要局部上下文。

**系统化改进建议**

- 区分 `episode_hook_context`、`shot_visible_hook` 和 `dialogue_hook` 三种层级；只有后两者允许影响画面和 lip-sync。
- 对 screen script 项目，QA 应检查 hook 是否“污染画面事实”，而不是强制要求 hook 文案实体化。

## 2026-05-01 12:48:14 JST - 结构化 narration 不能被字符串化进 record

### Case 93: semantic `narration_lines` 返回 dict 时必须抽取正文

**现象**

- ScreenScript EP03 重新从头跑 planning 时，SH16 原文是沈念歌画外音：“四年了。我以为这辈子都不会再回到那个城市……”
- Grok semantic pass 返回 `narration_lines` 为结构化对象：`speaker`、`exact_text`、`performance`。
- `screen2video_plan.py` 直接对 list item 执行 `str(item)`，导致 record 中出现 `"{'speaker': 'SHEN_NIANGE_MAIN', 'exact_text': ...}"` 这样的字典字符串。
- 若继续进入 Seedance prompt rendering，模型可能把结构化字串当成旁白或画面文字执行。

**根因**

- semantic annotation schema 允许 narration item 是字符串或对象，但归一化只按字符串处理。
- 这是 record field propagation / prompt rendering 前置层问题，不是 source script parsing、model execution 或 assembly 问题。

**有效方案**

- 归一化 semantic narration 时，若 item 是 dict，优先抽取 `exact_text`，其次 `text`、`line`、`content`。
- 继续过滤音乐提示和纯转场文本。
- 重跑 planning 后检查 affected record：`dialogue_language.narration_lines` 只能包含可朗读正文，不能包含 `{speaker: ...}` 结构化字串。

**系统化改进建议**

- planning QA 增加检查：`narration_lines` / `dialogue_lines.text` 中出现 `"{'"`、`'"speaker"'`、`exact_text` 等结构化残留时报警。
- semantic prompt 可以继续允许结构化输出，但所有进入 record/prompt 的字段必须先 canonicalize 成执行层可消费的文本。

## 2026-05-01 11:29:23 JST - 蒙太奇局部地点不能被父级场景静默覆盖

### Case 92: `【画面X】` 内的具体地点优先于父级蒙太奇场景

**现象**

- ScreenScript EP03 SH11 原剧本父级场景是“出租屋（不同城市辗转）·夜（四年间蒙太奇）”。
- 但本镜头附近原文明确写“【画面六】予予三岁。幼儿园面试。老师问……”，后文又写“沈念歌站在教室门口”。
- 规划 record/prompt 仍把 SH11 场景写成父级“出租屋（不同城市辗转）·夜（四年间蒙太奇）”，导致幼儿园面试场景被静默改写。

**根因**

- `screen2video_plan.py` 只把 `**场景：**` 行登记为 scene anchor，把 `【画面X】` 中的局部地点当作普通 visual context。
- 对白镜头的 `source_excerpt` 只保留对白行，局部地点证据只在 nearby_context 中，没有进入 record 的 source trace。
- semantic pass 可能已经识别“kindergarten interview”，但旧 schema 没有 location override 字段，理解结果无法回写到 scene_anchor。
- 这是 source script parsing、shot drafting、record field propagation 的交界问题，不是 Seedance、assembly 或纯 prompt rendering 错误。

**有效方案**

- 对 screen script 镜头建立 shot-local location：`幼儿园面试`、`教室门口`、`公交车`、`菜市场`、`医院门口` 等局部地点可覆盖父级蒙太奇场景。
- 对白镜头优先读取相邻 visual 行作为地点证据；父级场景只作为 fallback。
- record 中保留 `shot_context_excerpt`、`shot_location_basis`、`shot_location_excerpt`，让 keyframe/prompt/QA 能追溯到原文证据。
- semantic annotation 可返回 `shot_local_location` 和 `location_evidence`；只有有 source/nearby evidence 的 override 才能被接受。

**系统化改进建议**

- QA 检查：如果父级场景含“蒙太奇/不同城市辗转/快速剪辑”，且检测到单一局部地点但最终 scene 仍沿用父级，应报警。
- 多地点 visual-only 蒙太奇不应强行猜一个地点；应保留父级并要求 keyframe_moment 选择单一瞬间，避免首帧拼贴多个地点。

## 2026-05-01 11:25:00 JST - Seedance 可能把短对白烧成画面字幕

### Case 88: 已写“画面内不生成字幕”时仍可能出现白字黑边台词

**现象**

- ScreenScript EP03 SH06 使用 SH05 真实尾帧作为首帧重跑 Novita Seedance I2V。
- `prompt.final.txt` 的 compact context 已包含“画面内不生成字幕或底部文字”，且未开启 `--enable-subtitle-hint`。
- 生成视频中段仍出现白字黑边样式的烧录字幕，内容近似台词但文字错误，例如把“我说了。不详。”画成错误字幕。

**根因**

- 这是 model execution 层的 burned-in text/subtitle 失控，不是 source script parsing、record 字段、language plan、SRT 或 assembly 层错误。
- 对含短对白的 I2V，模型可能把台词文本和嘴型提示误解为画面内字幕需求；单句“不要字幕”约束强度不足。

**有效方案**

- 不改 record 台词，不删除对白音频。
- 在本镜头临时执行 prompt 中加入更强的画面无文字约束：对白只通过普通话声音、嘴型和表情表达；绝对不要把台词文字画进视频帧；禁止中文字幕、英文字幕、caption、closed caption、底部字幕、白字黑边、漂浮文字、衣服上的字、屏幕叠字、title card、UI 文字、水印或 logo；画面下半区和人物衣服必须保持干净。
- 将 `subtitle/caption/on-screen text/bottom text/Chinese characters/text overlay/burned-in subtitles` 加入避免项，即使 provider 无 true negative field，也让其进入正向禁用约束。
- 重跑后必须抽取对白中段帧检查；只看首帧和尾帧不足以发现该问题。

**系统化改进建议**

- 对所有含对白的 Seedance prompt，在 compact context 之外增加统一的 no-burned-in-text block。
- QA 抽帧应覆盖对白高峰时段，而不仅是 shot boundary。

## 2026-05-01 11:02:00 JST - Novita Seedance I2V 不能用 last_image 强制尾帧目标

### Case 87: 高连续性镜头做尾首衔接时，Novita 只可靠支持指定首帧

**现象**

- ScreenScript EP03 SH05/SH06 是同一医院同一护士对话的连续镜头，适合尝试“上一镜尾帧变下一镜首帧”。
- Atlas Seedance I2V profile 支持 `last_image` 字段，但本次运行 Atlas 返回 `HTTP 402 insufficient balance`，无法生成。
- 改用 Novita Seedance I2V 后，脚本会写出 `last_image_used.txt`，但 `payload.preview.json` 不包含 `last_image` 字段；实际请求不会把尾帧目标传给 Novita。

**根因**

- 当前 `builtin_seedance15_i2v_novita_profile()` 中 `payload_fields.last_image_field` 为 `None`。
- 这是 model execution/provider capability 层限制，不是 source script parsing、record planning、prompt rendering 或 assembly 错误。

**有效方案**

- 不改 record。
- 若必须强制“上一镜结束到指定尾帧”，优先使用支持 `last_image` 的 provider/profile，例如 Atlas I2V，并先确认账号余额可用。
- 若只能用 Novita，可靠做法是指定下一镜 `image` 首帧，并在最终报告中明确：只能保证下一镜从桥接图开始，不能保证上一镜实际末帧等于桥接图。

**系统化改进建议**

- 运行前检查 selected profile 的 `last_image_field`，如果为空但用户请求尾首强衔接，应提前报警。
- `last_image_used.txt` 的存在不应被误读为 provider 已收到尾帧目标；验证必须查看 `payload.preview.json`。

## 2026-04-30 16:22:16 JST - 单镜口播超过 Seedance I2V 时长上限时要在 assembly 层补尾

### Case 86: 12 秒上限镜头可能被 QA 判定对白早切

**现象**

- ScreenScript EP03 SH16/SH17、EP04 SH03/SH14 的语言计划提示 `max_duration_limit_risk`。
- Seedance I2V profile `duration_max_sec=12`，生成 clip 实际约 12.05 秒。
- `qa_episode_sync.py` 报 `early_scene_cut`，例如需要 12.4-13.1 秒但 clip 只有约 12 秒。

**根因**

- 单镜对白/画外音文本超过 I2V 单次生成时长上限。
- 重跑同一 Seedance profile 不能突破 `duration_max_sec=12`。
- 这是语言预算与视频模型上限/assembly QA 的交界问题，不是 source script parsing、record planning 或 keyframe 错误。

**有效方案**

- 不改 record 台词，不压缩源剧本文字。
- 对已生成 clip 在 assembly 前做末尾静帧延长，并用静音补齐音轨，保留原视频和原模型音频。
- concat 使用 padded clip 重新组装，再跑 `qa_episode_sync.py` 和 `ffprobe` 验证。
- 若镜头已有电话音频修复产物，应基于 `output.phone_fixed.mp4` 生成 padded 版，避免丢掉电话修复。

**系统化改进建议**

- language plan 中的 `max_duration_limit_risk` 可自动生成 assembly padding 建议。
- assembly 脚本可支持 per-shot tail hold 配置，避免手工生成 `output_padded.mp4` 和替换 concat。

## 2026-04-30 15:17:11 JST - 未成年人困境蒙太奇可能触发 OpenAI keyframe 安全拦截

### Case 85: 儿童/婴儿困境元素叠加会让首帧图像生成被 moderation blocked

**现象**

- ScreenScript EP03 SH07 规划 record 本身通过 QA，内容是四年时光蒙太奇中的无对白视觉镜头。
- OpenAI keyframe 生成 SH07/start 连续 10 次失败，错误为 `moderation_blocked`。
- 同批其他镜头继续生成成功，说明失败集中在该镜头的图像生成请求。

**根因**

- SH07 keyframe prompt 同时包含“哭闹的予予”“婴儿车”“奶粉”“儿童”等未成年人相关元素，以及深夜兼职、贫困生活的困境语境。
- 这是 keyframe 图像生成层的安全拦截，不是 source script parsing、record planning、Seedance 或 assembly 层错误。
- record 仍然忠实表达源剧本；不能为了绕过安全系统静默改写剧情事实。

**有效方案**

- 保持 EP03 SH07 record 不变，单独用 Grok keyframe 生成补出 SH07/start。
- 只把补出的首帧用于后续 SH07 Seedance 补跑，不覆盖已成功的 17 个 OpenAI keyframes。
- 对类似未成年人困境蒙太奇，先尝试 provider fallback 或更中性的首帧构图，避免把多个高敏元素集中塞进同一张首帧 prompt。

**系统化改进建议**

- keyframe 生成器可增加 per-shot provider fallback：OpenAI moderation blocked 时，允许保留 record、转用 Grok/其他 provider 生成首帧。
- 对含儿童/婴儿、哭闹、医院、贫困、深夜照护等组合的 visual-only 镜头，prompt 可优先选择源剧本中较中性的单一瞬间，不做多画面蒙太奇拼接。

## 2026-04-30 14:27:28 JST - 模糊身影不能被实名化，keyframe 必须保留原文摘录

### Case 84: visual-only 床上醒来镜头被语义可见人物和首帧清洗共同改写

**现象**

- ScreenScript EP02 SH14 原文是“一张大床。两个人。被子裹着两个模糊的身影。沈念歌先醒了……”。
- Grok semantic pass 将 `visible_characters` 标为沈念歌、陆景琛，理由是 both in bed / blurred figures。
- planner 接受 semantic visible list 后，自动为两人写入脸部可见契约和角色锁定。
- keyframe static sanitizer 又把原文里的床、被子、模糊身影、醒来等细节裁掉，只留下“首帧人物脸部可见 exactly 2”。
- 最终首帧和视频变成沈念歌、陆景琛穿衣站在套房里正面亮相，违背原文。

**根因**

- visual-only shot 的“模糊身影/人影/轮廓”被 semantic annotation 当成明确可识别角色。
- `screen2video_plan.py` 优先采用 semantic `visible_characters`，缺少“未被本镜头原文点名的模糊人物不能实名化”的保护。
- keyframe sanitizer 偏好含“首帧/可见”的片段，可能裁掉原文场景细节。

**有效方案**

- 对 visual-only 且包含“模糊身影/人影/轮廓”的镜头，semantic `visible_characters` 只能保留本镜头原文明确点名的角色。
- planning record 写入 `source_trace.shot_source_excerpt`，保存本镜头原文逐字摘录。
- keyframe prompt 增加“原文画面依据（逐字摘录）”，直接使用 record 中的原文摘录；不得用推导句冒充原文。
- 对未写明衣着状态的床上镜头，不补写“穿衣/未穿衣”；只使用原文已有的“被子裹着”。
- 当原文以床/被子遮挡衣着状态时，keyframe 人物参考只锁面部、发型、肤质，不注入角色锁里的固定服装描述。

**系统化改进建议**

- planning QA 检查：如果 source excerpt 含“模糊身影/人影/轮廓”，但 `visible_characters` 包含未在本镜头原文中点名的主角，应报警。
- keyframe sanitizer 不应丢弃 `source_trace.shot_source_excerpt`；清洗后的 prompt 仍必须带原文摘录。

## 2026-04-30 12:50:52 JST - 合并后的转场也不能进入 narration

### Case 79: 黑场并入上一镜后仍可能被 semantic pass 写成旁白

**现象**

- ScreenScript EP02 重新规划时，独立 `画面暗下` 镜头已经按 Case 73 并入上一镜。
- 但 OpenAI semantic annotation 仍把 `画面暗下` 写入 SH18 的 `dialogue_language.narration_lines`。
- 下游 Seedance 可能朗读“画面暗下”，把转场说明误当旁白。

**根因**

- `merge_thin_drafts_into_previous()` 只避免转场独立成镜，会把转场保存在上一 shot 的 visual_texts 中。
- semantic pass 看到 source excerpt 和 visual_texts 中的转场文本后，仍可能把它当作 narration_lines。
- 归一化阶段只过滤了音乐提示，没有过滤纯转场文本。

**有效方案**

- 在 screen semantic annotation 归一化阶段过滤纯转场 narration：`画面暗下`、黑场、淡出、切黑、转场等。
- 转场仍可保留在视觉/结尾转场信息中，但不能进入 `dialogue_language.narration_lines`。

**系统化改进建议**

- planning QA 可增加检查：`narration_lines` 只含黑场/淡出/转场说明时报警。
- 合并 thin shot 后，语义模型提示和归一化都要把 transition metadata 与 spoken narration 分开。

## 2026-04-30 12:53:04 JST - semantic pass 也不能替 visual-only shot 写旁白

### Case 80: 无对白视觉镜头被语义模型补成长旁白

**现象**

- ScreenScript EP02 重新规划时，SH01、SH05、SH06、SH07、SH13、SH14 等无对白视觉镜头出现长 `narration_lines`。
- 这些文字来自画面说明，例如酒店全景、手机消息、走廊晕眩、套房醒来等，不是原剧本明确旁白。
- 下游 Seedance 可能把这些画面说明朗读成旁白，造成语速过快和叙事口吻错误。

**根因**

- Case 74 已移除了 planner 机械截取 visual prompt 当旁白的路径。
- 但 OpenAI/Grok semantic annotation 仍可能基于 visual_texts/source_excerpt 主动填 `narration_lines`。
- build_shots 阶段接受了 semantic narration，没有二次确认原文是否明确写了旁白/画外音。

**有效方案**

- 对 screen script 的 visual-only shot，除非原文明确包含 `旁白`、`画外音`、`画外旁白`、`VO/V.O.`，否则清空 semantic `narration_lines`。
- 角色对白和集尾钩子旁白仍走 `dialogue_lines`，不受该过滤影响。

**系统化改进建议**

- planning QA 应检查 visual-only shot 的 `narration_lines` 长度，若无明确旁白标记则报警。
- semantic prompt 和归一化都应强调：视觉描述不是语音资产。

## 2026-04-30 12:54:58 JST - 语义 listener 不能等于 speaker 自己

### Case 81: 电话对白被标成自己对自己说话

**现象**

- ScreenScript EP02 SH18 中，沈念歌拨号后说“爸……我没事。我……我想回家。”
- semantic pass 有时把 listener 标成沈念歌本人。
- 下游 gaze_contract 变成“沈念歌看向沈念歌”，会诱导错误 two-shot 或自指视线。

**根因**

- semantic listener 标注没有硬性禁止 `listener == speaker`。
- 该句台词本身没有写“电话里”，但前文视觉动作写了“掏出手机，拨了一个号码”，上下文足以判断听话人是父亲（电话另一端）。

**有效方案**

- build_dialogue_addressing_contract 中若 listener 等于 speaker，先清空再走本地 listener 推断。
- 对沈念歌台词含“爸”且上下文含拨号/手机/电话的场景，推断 listener 为 `父亲（电话）`。

**系统化改进建议**

- planning QA 应检查 dialogue_addressing 中 `speaker == listener` 的条目。
- 电话/远端通话判断应结合附近视觉动作，而不是只看当前对白文本。

## 2026-04-30 12:57:45 JST - Grok visible_characters 过窄时要回补听话人

### Case 82: 双人对白只保留说话人导致首帧缺听话人

**现象**

- ScreenScript EP02 Grok semantic plan 中，多处双人对白的 `listener` 正确，例如沈念歌对林雨薇、林雨薇对沈念歌。
- 但 `visible_characters` 只返回说话人，导致首帧前景人数从 2 变成 1。
- 下游 keyframe/Seedance 可能只生成说话人，听话人的反应和视线关系缺失。

**根因**

- planner 优先采用 semantic `visible_characters`，而 Grok 在部分对白镜头只标注 active speaker。
- record 中已有 listener/action_targets，但没有在构建 first_frame_contract 前回补到 visible character 清单。

**有效方案**

- 在 build_shots 阶段，归一化 dialogue 后，把 onscreen listener 和 action_targets 合并进 `visible_names`。
- 电话、画外、远端 listener 不进入首帧人物清单，只进入 gaze/phone contract。
- 回补后重新计算 featured_character、scene_overlay 和 foreground cardinality。

**系统化改进建议**

- planning QA 应检查：onscreen dialogue listener 若是实体人物且不是 speaker，本人应出现在 `first_frame_contract.visible_characters`。
- semantic visible_characters 可以补充 record，但不能覆盖 record 已经确定的对白关系。

## 2026-04-30 13:40:00 JST - 饮料道具不能退化成空杯子

### Case 83: “喝果汁”镜头只锁了杯子但没有锁杯中液体

**现象**

- ScreenScript EP02 原文在酒店服务间中写：林雨薇端来两杯果汁，沈念歌接过后说“谢谢”，随后“她喝了一口”。
- 当前 SH09 生成结果里看起来像沈念歌喝空杯子。
- Record 和 prompt 只锁定了 `CUP_01` / 一只玻璃杯，没有明确杯中有果汁、液面可见、杯子不是空的。

**根因**

- planning/prop detection 把“杯子”当成普通静态杯具，而不是“含饮料的杯子/果汁杯”。
- `CUP_01` 的视觉资产和道具契约没有液体颜色、液面高度、透明杯折射等约束。
- “她喝了一口”被写成结尾转场/动作文本，但没有反推到首帧道具状态：杯中必须有可见果汁。

**有效方案**

- 遇到“果汁/橙汁/饮料/喝了一口/端着两杯果汁”时，使用饮料道具而不是空杯泛化道具。
- Prompt 明确：透明或半透明杯中有浅橙色/淡黄色果汁，液面可见，杯子不是空的；喝之前杯中有液体，喝后液面可轻微降低但不能消失。
- 如果 count 固定，写清楚是一杯还是两杯；人物手中/桌上位置也要固定。

**系统化改进建议**

- prop QA 检查饮料类动作：`喝`、`果汁`、`水`、`咖啡`、`酒` 等词出现时，道具 contract 必须包含内容物、液面和非空约束。
- 不能只把容器当作道具；有内容物的容器需要“容器 + 内容物”组合约束。

## 2026-04-30 12:20:00 JST - semantic planning 先用模型探测再固化规则

### Case 78: 动作对象不能误当成对白听话人

**现象**

- ScreenScript EP01 SH12 中，沈念歌“快步上前，一把拉住予予”后说“对不起！对不起！小孩子不懂事——”。
- 旧 planner 把 `拉住予予` 中的动作对象沈知予误判为 listener，首帧只放沈念歌、沈知予两人。
- 成片看起来像母亲在对孩子道歉，而不是对陆景琛道歉。

**根因**

- planning 阶段只有 `speaker/listener` 粗结构，没有显式区分 `action_target`。
- visible character 推断只看当前 dialogue 行和少量近邻上下文，漏掉“孩子站在那个男人面前”“四目相对”等三人关系。
- 当陆景琛没有先进入 `visible_characters` 时，listener 推断 fallback 到唯一可见的沈知予。

**无效或不充分方案**

- 只让 keyframe 或 Seedance prompt 写“看向听话人”：如果 record 里的 listener 已错，下游会忠实放大错误。
- 只给 LLM 当前行上下文：OpenAI 小测试仍会把沈知予当 listener。

**有效方案**

- semantic planning probe 使用 scene-level 上下文、角色别名表和明确字段定义。
- 强制区分：`listener/addressee` 是话说给谁听；`action_targets` 是动作作用在谁身上。
- 对“拉住孩子并对大人道歉”这类情况，输出三人关系：沈念歌为 speaker，陆景琛为 listener，沈知予为 action target，首帧 `foreground_cardinality.exactly=3`。
- Grok/OpenAI semantic pass 只能标注结构字段，不能改台词、改剧情或重排事件；record 仍是 source of truth。

**系统化改进建议**

- planning QA 应检查 dialogue line 同时存在 listener 和 action target 的情况，避免二者被同一个角色误占。
- 对 visible character count、listener、action target 等判断类改动，先跑小 probe，再改代码。

### Case 77: 音乐提示不能进入 narration_lines

**现象**

- ScreenScript EP01 SH09 原文只有 `♪ 音乐提示：轻快钢琴，带一丝慌乱` 和 VIP 候诊区视觉描写。
- planner 将音乐提示写入 `dialogue_language.narration_lines`。
- Seedance prompt 要求画外旁白读出“音乐提示：音乐提示：轻快钢琴，带一丝慌乱”，导致旁白很奇怪。

**根因**

- screen script parser 把 `♪` 行正确识别为 music cue，但 record 渲染阶段把 `draft.music` 机械转成 narration。
- 语言层缺少统一的 `music_cues` 字段，导致配乐/情绪提示被塞进旁白通道。

**无效或不充分方案**

- 只在 Seedance prompt 层过滤“音乐提示”：record 已经把音乐写成 narration，下游各环节仍可能继续误读。
- 只拉长镜头时长：不能解决语义错误，反而会让模型认真读出音乐说明。

**有效方案**

- `dialogue_language.narration_lines` 只保留原文明确旁白/画外旁白。
- `dialogue_language.music_cues` 作为统一 record schema 字段，novel 和 screen records 都保留该字段；无音乐时为空数组。
- screen planner 把 `draft.music` 写入 `first_frame_contract.music_cues` / record `music_cues`，不再转成 narration。

**系统化改进建议**

- 语言计划、Seedance prompt 和 QA 都应把 narration 与 music cue 视为不同通道。
- planning QA 可增加检查：`narration_lines` 中出现 `音乐提示`、`BGM`、`配乐` 等词时报警。

## 2026-04-30 11:22:32 JST - keyframe 必须看见说话人的脸

### Case 76: 修正视线关系时不能把说话人转成后脑/背影

**现象**

- EP01 重新测试手术费镜头时，沈知予作为说话人确实没有看观众，但 keyframe 只看到他的后脑和背面。
- listener 沈念歌的脸可见，且她看着沈知予；但说话人沈知予的脸和嘴不可见。

**根因**

- `gaze_contract` 强调了 speaker 看 listener、listener 看 speaker，但没有把“说话人脸/嘴必须在 keyframe 中可见”作为独立硬约束。
- 模型为了满足互看关系，选择了从 listener 侧拍，让 listener 表情清楚，牺牲了 speaker 的脸部可见性。

**无效或不充分方案**

- 只写“双方互看”：会让模型用一个人背影完成 eye-line。
- 只写“可见人物露出脸部”：模型可能优先露出 listener 的脸，而不是 speaker 的脸。

**有效方案**

- planning record 为对白镜头新增 `first_frame_contract.speaker_face_visibility`。
- keyframe prompt 和 Seedance prompt 都写入硬约束：画面内说话人 keyframe/首帧必须看见脸和嘴；必须是正脸、三分之二侧脸或清晰侧脸。
- 明确禁止：说话人只出现后脑、背影、背面轮廓、低头遮脸或被听话人遮挡。

**系统化改进建议**

- dialogue shot 的首帧 QA 必须同时检查两件事：speaker/listener eye-line 是否成立，speaker face/mouth 是否可见。
- 抽帧验收时，不能只看“谁看谁”，还要确认说话人的脸和嘴没有被构图牺牲。

## 2026-04-30 11:07:59 JST - 视频模型不能自行烧录字幕

### Case 75: `字幕简中` 会诱导 Seedance 在画面底部生成乱码字幕

**现象**

- ScreenScript EP01 SH17 单独 clip 的画面底部出现一行类似字幕的乱码/错字。
- 对应 SRT 和 language plan 中字幕文本正常，说明乱码不是后期 assembly 加上的，而是视频模型直接生成在画面里的 burned-in text。

**根因**

- Seedance prompt 的 compact context 写了 `音频仅普通话，字幕简中` / `简中字幕`。
- 模型将“字幕简中”理解为画面内需要生成中文字幕，但视频模型生成文字不稳定，导致底部乱码。
- 完整 language lock 虽然可以表达语言规则，但 Novita compact prompt 路径会优先使用短上下文，因此短上下文本身也必须明确禁止画面字幕。

**无效或不充分方案**

- 只修 SRT 或 assembly：问题已经存在于单 shot output.mp4，后期无法从根源避免。
- 只关闭 `subtitle_overlay_hint`：compact context 仍有 `字幕简中`，模型仍可能烧字幕。

**有效方案**

- Seedance prompt 中不再写 `字幕简中` / `简中字幕` / `屏幕字幕只使用简体中文` 这类会诱导模型画字幕的短语。
- compact context 改为 `音频仅普通话，画面内不生成字幕或底部文字`。
- 完整 language lock 改为：普通话音频正常生成；字幕、caption、dialogue text、title card、bottom text 都不生成在视频帧内；字幕只由后期流程添加。
- `--enable-subtitle-hint` 即使开启，也只能写成“后期字幕参考（不要画进视频帧）”。

**系统化改进建议**

- 画面生成 prompt 和后期字幕流程必须隔离：视频模型负责画面/动作/音频，不负责生成可读字幕。
- QA 可以抽帧检测底部文字区域；若非后期字幕阶段出现文字，应标记为 burned-in subtitle risk。

## 2026-04-30 11:03:59 JST - 无对白视觉镜头不能自动生成长旁白

### Case 74: 机械截取视觉描述当旁白会造成语速过快

**现象**

- ScreenScript EP01 SH01 是开场视觉建立镜头，没有角色对白。
- planner 将 `prompt_text[:48]` 自动写入 `narration_lines`，但镜头默认时长仍为 4 秒。
- Seedance prompt 要求约 47 个中文字符在 0.4-4.6 秒内读完，实际听感语速很快。

**根因**

- planning 阶段把无对白视觉描述机械截断成旁白，制造了原剧本没有明确要求的长语音层。
- language plan 只按 `dialogue_lines` 计算 spoken duration，没有用 `narration_lines` 扩展时长；Seedance prompt 却会执行 `narration_lines`。
- 视觉建立镜头的画面描述和旁白文案不是同一种资产，不能默认互相替代。

**无效或不充分方案**

- 只把 SH01 时长拉长：能缓解语速，但仍保留了机械截断、不完整的旁白文案。
- 只让 language plan 计入 narration：会把所有 visual-only shot 都变成长旁白镜头，稀释短视频节奏。

**有效方案**

- screen planner 默认不再为无对白视觉镜头生成旁白或字幕；只保留画面动作、场景和人物约束。
- 只有剧本显式提供的对白/旁白、电话/画外音、音乐提示、集尾 hook 才进入语言层。
- 如果未来需要视觉镜头旁白，应由独立 language layer 生成短旁白并反推 shot duration，而不是从视觉 prompt 固定截取。

**系统化改进建议**

- language plan、Seedance prompt 和 planning record 必须共享同一个“语音层 source of truth”。
- QA 应检查 narration 字数/时长比；超过阈值时提示扩时或压缩旁白。

## 2026-04-30 10:55:01 JST - 内容太薄的 shot 应合并到上一镜

### Case 73: 纯转场/黑场不能独立占用最后一个 shot

**现象**

- ScreenScript EP01 原剧本最后是陆景琛说“安排。”，随后 `△ 画面暗下。`
- `--max-shots 18` 选镜时机械保留最后一个候选，导致 `画面暗下` 独立成为 SH18。
- 因为最后一镜无对白，planner 又自动添加集尾旁白，最终 SH18 变成 scene-only 黑场旁白镜头，人物数为 0。

**根因**

- 候选镜头选择规则把“最后一个候选”当成“最后一个有效剧情镜头”。
- 内容密度极低的转场候选没有在 planning 阶段并入上一条有剧情承载的 shot。
- 道具关键词过宽，`画面暗下` 中的 `画` 还可能误触发儿童画道具。

**无效或不充分方案**

- 只提高对白镜头分数：最后一个候选仍会被强制保留。
- 让黑场镜头继续存在但缩短时长：仍会稀释最终钩子，还会产生 scene-only 误导。

**有效方案**

- planning 阶段识别薄内容候选：`画面暗下`、黑场、淡出、切黑、转场等无人物、无动作、无剧情信息的 visual-only draft。
- 如果薄内容候选前面有有效 shot，则把它写入上一 shot 的 `结尾转场`，更新 line range/source trace，不再独立成镜。
- `select_representative_drafts()` 强制保留的是最后一个非薄内容候选，而不是机械保留最后一个候选。
- `画` 只有在儿童画、图画、画纸、那幅画等明确小道具上下文中才触发 `CHILD_DRAWING_01`，不能从 `画面` 触发。

**系统化改进建议**

- “shot 丰富度”应成为选镜 gate：无人物、无道具、无动作、无剧情信息的候选默认只能作为 transition/beat metadata。
- 最后一镜应该落在最后一个剧情决定、关系反转、证据揭示或情绪钩子上；转场只作为 ending transition。

## 2026-04-30 10:33:44 JST - 对白镜头的脸部可见不等于看向观众

### Case 72: A 对 B 说话时，双方视线应形成角色关系而不是看观众

**现象**

- ScreenScript EP01 中多处亲子对话、孩子问陆景琛、陆景琛对赵一鸣下令等镜头，成片里说话人容易直视观众或镜头。
- records 已经写出多角色首帧 cardinality，但 Seedance/keyframe prompt 仍反复要求“说话人面向镜头/面向观众或三分之二侧脸”。

**根因**

- planning record 只表达了 `active_speaker`、`visible_characters`、`foreground_character_cardinality`，没有结构化保存 `listener` / `addressed_to` / `gaze_target` / `listener_gaze_target`。
- “首帧脸部可见”被渲染成“面向观众/面向镜头”，把可辨认五官的技术要求误转成了角色表演方向。
- 下游 prompt 缺少“说话人看向听话人、听话人也看着说话人或保持对说话人的反应”的正向约束，模型自然按 portrait/dialogue close-up 习惯让演员看镜头。

**无效或不充分方案**

- 只要求“脸部可见”或“嘴部可见”：能保证口型，但不能保证角色之间有交流关系。
- 只靠 `visible_characters` 或 cardinality 推断视线：能保证 B 在画面里，不能保证 A 说话时看 B。
- 全局禁止看镜头：独白、自言自语、电话、旁白钩子、主观镜头可能需要不同视线策略。

**有效方案**

- planning 阶段为对白镜头新增 `dialogue_addressing` / `gaze_contract`：speaker、listener、gaze_target、listener_gaze_target、eye_contact_policy、exceptions。
- 亲子/面对面对话写“说话人看向对方脸部或眼睛；听话人也看着说话人或保持对说话人的清晰反应；允许三分之二侧脸，禁止直视镜头/观众”。
- 电话对白写“看向手机、窗外或通话方向”，不要默认看观众。
- 命令/汇报镜头写“看向助理/上司/被命令对象；若对象画外，则看向画外对象方向”，而不是看镜头。
- 保留脸部可见要求，但改成“脸部对观众可辨认”，不等价于“眼神看观众”。

**系统化改进建议**

- record 是 source of truth；keyframe metadata 可以补充但不能自行把 `face_visible` 改写成 `look_at_camera`。
- prompt QA 增加检查：多角色对白若有明确 listener，prompt 里不得出现无条件“面向镜头/面向观众”，必须出现 gaze target。
- 对 EP01 回归覆盖 SH02/SH03/SH04/SH10/SH11/SH15 这类“对白单说话人 + 多角色首帧 + 明确听话人”的镜头。

## 2026-04-30 01:51:15 JST - scene modifier 内部 ID 不能进入模型 prompt

### Case 71: scene_modifiers 已正确移出 prop 后，prompt 仍可能泄漏 `TRAIN_WINDOW_VIEW` 等内部 ID

**现象**

- EP21 固定角色图重跑后，SH05/SH07/SH13 的 keyframe 与 Seedance prompt 中仍出现 `TICKET_GATE_ROW`、`TRAIN_WINDOW_VIEW`、`TRAIN_SEAT_PAIR`、`GINZA_FOGGY_SKYLINE_VIEW`。
- 这些元素没有再生成 prop reference，也没有进入 prop_library/key_props，但内部 ID 仍从 first-frame/core prompt 文本泄漏到模型输入。

**根因**

- record 清洗只移动结构化字段，未清洗 `prompt_render.shot_positive_core`、`camera_plan.framing_focus`、`shot_execution.action_intent` 等自然语言字段中的旧 prop id。
- keyframe 与 Seedance 渲染层会直接拼接这些字段，因此 scene modifier 虽然结构上正确，prompt 文本仍不够干净。

**有效方案**

- 渲染 prompt 时根据 `first_frame_contract.scene_modifiers/costume_modifiers` 建立 `id -> display_name` 映射。
- keyframe prompt 与 Seedance final prompt 写出前统一替换内部 ID，例如 `TRAIN_WINDOW_VIEW` -> `车窗外景`、`TICKET_GATE_ROW` -> `新干线检票闸机`。
- 保留 scene modifier 的空间约束和数量描述，但模型只看自然语言 display name，不看工程 ID。

**系统化改进建议**

- 后续对 `scene_modifiers`、`scene_overlay`、`costume_modifiers` 做统一 prompt sanitizer，QA 中增加“内部 ID 不得出现在模型 prompt”检查。

## 2026-04-30 00:38:03 JST - 角色图 prompt 不应写入其它项目的年龄硬规则

### Case 70: 4岁半 preschool 硬性要求不能进入 14 岁中学生角色图

**现象**

- EP21 visual refs 中 `SAKURA_CHILD` 的 visual bible 已写明 14 岁、mid-teens、中学生比例，但角色图 QA 仍报年龄漂移、身体比例不符和身份区分不足。
- 生成 prompt 的硬性画面要求里全局写着“4岁半儿童保持幼儿园中班年龄感、写实1:4.7到1:5头身比”，容易污染非 preschool 儿童/青少年角色。

**根因**

- `build_character_image_prompt()` 把 screen_script 低龄儿童规则写成全局提示，而不是按角色 visual bible 条件启用。
- 青少年角色的 bible 中如果出现 `childish/immature` 等词，图像模型会把 14 岁中学生拉低到小学生感。
- `pairwise_forbidden_similarity` 若残留 `{'pair': ..., 'forbidden': ...}` 这种结构化字符串，会把其它角色的对比规则整段塞进角色图 prompt，导致身份区分提示过噪。

**有效方案**

- 只有明确命中沈知予、4岁半、preschool、学龄前等低龄设定时，才写 preschool 比例契约。
- 青少年/中学生角色写“符合明确年龄段的写实青少年比例，不要成人化，也不要幼儿化或低龄大头化”。
- 成年角色和其它未成年角色使用通用年龄段比例契约，不再继承 4岁半项目规则。
- 构建青少年角色 prompt 时，将 `childish/immature` 解释为 `youthful adolescent / age-appropriate young teen`，并明确 13-15 岁、14 岁初中生、较长四肢、约 7 头身。
- 过滤结构化 pairwise blob，只保留当前角色真正的 `must_not_look_like` 简短锚点。

**系统化改进建议**

- 角色图 prompt builder 中的项目特定 QA/视觉规则必须条件化；不要把某一项目的角色族群规则写进所有项目的全局 prompt。
- character contrast/bible 的字段类型要严格校验：list 字段不能接受 dict 字符串，否则会污染生成和 QA 双侧 prompt。

## 2026-04-30 00:23:53 JST - 固定场景构件不是道具

### Case 68: 车窗/座椅/扶手/扬声器/闸机/铁轨/城市轮廓应归入 scene modifiers

**现象**

- EP21 visual refs 阶段开始为 `GINZA_FOGGY_SKYLINE_VIEW`、`TRAIN_WINDOW_VIEW`、`TRAIN_SEAT_PAIR`、`STATION_BELL_SPEAKER`、`TICKET_GATE_ROW`、`TOKYO_STATION_PLATFORM_TRACKS` 等生成 prop reference。
- 用户指出车窗、座椅、扶手、扬声器都只是 scene 的修饰或固定构件，不符合新道具定义。

**根因**

- novel planner/LLM 将“首帧必须可见的固定环境元素”写进 `prop_library`、`prop_contract` 和 `first_frame_contract.key_props`。
- visual refs/keyframe/Seedance 下游按 `prop_*` 字段机械收集，导致固定场景构件被当成独立道具图。

**有效方案**

- 新定义：只有会被角色拿起、持有、移动、交互，且不是场景固定组成部分的实体，才算 prop。
- 车窗、座椅、扶手、扬声器、闸机、铁轨、站台、门、车辆、房间、城市轮廓等固定构件归入 `scene_modifiers` / `scene_overlay`。
- 真正 prop 保留照片、文件/报告/记录页、信件、手机、香烟、打火机、丝巾、领带等可移动剧情实体。
- record 写出前清洗 scene modifier props：从 `prop_library`、`prop_contract`、`key_props`、`static_props/manipulated_props` 中移出，并写入 `first_frame_contract.scene_modifiers` 与 `scene_anchor.scene_modifiers`。
- visual asset、keyframe、Seedance 也要过滤 scene modifier prop id，避免旧 records 残留继续生成 prop refs。

**系统化改进建议**

- EP21/EP22 完成后，对齐 screen_script 与 novel 的这部分实现，抽成同一套共享规则：prop 判定、scene_overlay/scene_modifiers 写入、下游 prop refs 过滤、QA 报错口径保持一致。

## 2026-04-30 00:23:53 JST - screen_script 角色图 QA 不能污染 novel 项目

### Case 69: preschool 和商务男性 pairwise 规则只适用于对应 screen_script 角色

**现象**

- EP21 visual refs 生成角色图时，`SAKURA_CHILD` 被报：`儿童角色必须明确 4岁半/preschool，不可泛化为婴幼儿`。
- `ISHIKAWA_DETECTIVE` 被报：`商务男性角色共享模板过强，缺少具体 pairwise 反差锚点`。
- 但 GinzaNight 的樱子是 14 岁中学生，不是 4 岁半学龄前儿童；石川是刑警，不是 screen_script 里的陆景琛/赵一鸣商务男性对照组。

**根因**

- `visual_asset_core.validate_character_bible()` 的儿童判定包含泛化 token `child`，导致所有 child/儿童角色都触发 4岁半 preschool 规则。
- 商务男性判定只看西装/衬衫/领带/短黑发等模板词，误伤现代刑警角色。

**有效方案**

- preschool QA 只对沈知予、4岁半、preschool、学龄前、小男孩等明确低龄设定触发，不对所有 child/儿童角色触发。
- 商务男性 pairwise QA 只对陆景琛/赵一鸣这类 screen_script 对照组触发，不对 GinzaNight 的石川/健一等现代男性角色触发。

**系统化改进建议**

- 角色图 QA 应按项目/角色族群启用，而不是将某个项目的对照策略变成全局硬规则。

## 2026-04-29 23:59:44 JST - QA 不能把多角色同句服装混算到每个人

### Case 66: wardrobe continuity QA 的角色窗口必须在下一个角色名前截断

**现象**

- EP21 clean rerun 的新 records 已正确使用 LLM 输出，planning QA 不再报照片正反面、背对或 generic placeholder。
- QA 仍报 `episode_wardrobe_multiple_major_types`，认为佐藤美咲同时有 `礼服/西装/连衣裙`，佐藤樱子同时有 `校服/西装`。
- 实际 SH07 prompt 是同一句多角色构图：`石川悠一穿深色旧西装...佐藤美咲穿...礼服与佐藤樱子穿...校服...`。QA 把包含三个角色的整句窗口都算到美咲和樱子身上。

**根因**

- wardrobe continuity QA 只按句号/分号等大边界切 clause；中文影视 prompt 经常用一个长句列出多名角色服装。
- 角色名命中后没有在下一个角色名处截断，导致其他角色的服装词污染当前角色的 wardrobe type 统计。

**有效方案**

- `named_text_windows()` 改为从当前角色名位置取局部窗口，并在下一个已知角色 alias/name/lock_profile_id 出现前截断。
- 保留跨镜头服装多类型提示，但只在角色自己的局部文本中计算服装类别。

**系统化改进建议**

- QA 对“多角色同句构图”应先做角色槽位切分，再做服装、动作、嘴型等角色级检查。
- 以后新增角色级 QA 时，避免把整句 prompt 当成单个角色的证据。

## 2026-04-29 23:59:44 JST - EP21 新生/银座影子也属于有效集尾钩子

### Case 67: ending hook QA 不能只识别侦查型悬念词

**现象**

- EP21 SH13 的结尾为美咲低语“从今开始，一切新生。”，画面为列车启动、银座的影子在雾中后退。
- QA 报 `ending_dialogue_lacks_action_or_mystery_hook` 和 `ending_hook_not_marked_as_episode_hook`。

**根因**

- `ENDING_HOOK_KEYWORDS` 主要覆盖“查、真相、秘密、明天、嫌疑、监控”等侦查型悬念词。
- EP21 的结尾是情绪/行动转折型钩子：离开银座、新生、列车启动、银座影子后退，不是追查型台词。

**有效方案**

- 将 `新生`、`离开`、`启动`、`列车`、`银座`、`影子`、`后退`、`樱子` 纳入 ending hook QA 的有效关键词/视觉钩子。

**系统化改进建议**

- 结尾钩子应分型校验：侦查悬念、行动承诺、关系转折、逃离/新生、证据揭示，而不是只用单一侦查词表。

## 2026-04-29 23:57:33 JST - batch force-plan 必须覆盖旧 bundle

### Case 65: `--force-plan` 只重跑不覆盖时，会产生 LLM 已 applied 但 QA 仍读旧 heuristic records

**现象**

- EP21 clean rerun 使用 `run_novel_episode_batch.py --force-plan --strict`，终端显示 `LLM single-shot planner applied: gpt-5.5 SH01` 到 `SH13`。
- planning 结束日志同时显示 `planned/written files: 0`。
- `plan_qa_report.json` 仍为旧内容：`llm_backend=heuristic`、`llm_applied=false`，并报 9 条 `generic_shot_placeholder`。
- records 文件时间仍停在旧时间，说明新 LLM 输出没有覆盖旧 bundle。

**根因**

- `run_novel_episode_batch.py --force-plan` 只强制执行 planning 子进程，但没有把 `--overwrite` 传给 `novel2video_plan.py`。
- `novel2video_plan.py` 在已有 bundle 存在时保护旧文件，导致 LLM 调用真实发生、request/response 也写出，但 record/bible/QA 等正式产物不落盘。

**有效方案**

- batch runner 在 `--force-plan` 时自动给 `novel2video_plan.py` 追加 `--overwrite`。
- 后续重跑如果看到 `planned/written files: 0`，不能继续 refs/keyframes/Seedance；必须确认 records 文件时间、`plan_qa_report.json` 的 `llm_backend/llm_applied` 与本轮命令一致。

**系统化改进建议**

- batch manifest 可记录 planning 输出的 `planned/written files` 或产物 mtime，发现强制重跑但写入数量为 0 时直接报错。
- `--force-plan` 的语义应是“重建当前 planning bundle”，不能只代表“调用 planning 脚本一次”。

## 2026-04-29 22:09:48 JST - 扩集后 assemble 应主动补生成缺失封面

### Case 62: cover_generation_manifest 停在旧 episode_count 时，后续集封面会缺号

**现象**

- GinzaNight 全局 `assets/cover_page` 只生成到 `ginza_night_cover_20.png`，但 EP21/EP22 的新规划 bundle 已经包含 22 集大纲。
- EP21 assemble 使用 `--episode EP21 --cover-page-dir novel/ginza_night/assets/cover_page` 时找不到 `ginza_night_cover_21.png` 并失败。
- 后续手工成功组装的视频报告中 `cover_page.enabled=false`，说明最终成片绕过了 cover 插入。

**根因**

- `generate_cover_pages.py` 按当时 planner 推断的 `episode_count` 一次性生成编号封面；旧 manifest 为 20 集。
- 后续扩展到 EP21/EP22 后，batch assemble 只消费已有 cover 目录，不会主动补生成新编号页。

**有效方案**

- `assemble_episode.py` 在 cover 启用且目标编号封面缺失时，默认调用 `generate_cover_pages.py` 补生成到当前目标集数，再重新解析 cover。
- `run_novel_episode_batch.py` 在 assemble 阶段传入 `--cover-plan-dir` 和 `--cover-project-dir`，让 assemble 能用当前 bundle 的 `project_bible_v1.json` 与项目级 `assets/cover_config.json`。
- 仅当用户显式传 `--no-cover-page` 或 `--no-auto-generate-cover-page` 时跳过该自愈。

**系统化改进建议**

- 批量生产中，封面目录不应被视为静态资产；每次 assemble 目标集号超过已生成封面范围时应自动补齐。
- cover manifest 的 `episode_count` 只能代表上次生成范围，不能作为当前项目总集数的 source of truth。

## 2026-04-29 19:58:38 JST - 禁止点香烟/熄灭香烟动作，但不要扩大到烧文件

### Case 61: cigarette action ban must stay narrow

**现象**

- EP20/EP21/EP22 中石川相关镜头存在 `点燃香烟`、`按灭香烟`、`熄灭烟头` 等动作。
- EP22 SH05 使用打火机烧毁记录页，这属于文件销毁动作，不是点香烟。

**根因**

- 原文烟草意象会被 planner 直接转成可拍动作，进入 records 后又被 keyframe 和 Seedance prompt 继承。
- 如果只写泛化的“禁烟/禁明火”，会误伤 SH05 这类剧情必需的烧文件动作。

**有效方案**

- 禁止范围只限吸烟动作：`点香烟`、`点燃香烟`、`点起烟`、`按灭香烟`、`熄灭烟头`、`掐灭烟头` 等。
- 不扩大到 `打火机烧文件`、`页角被点燃`、`纸灰落下` 等非香烟火源动作。
- planning QA 和 Seedance preflight 都扫描正向视觉/action prompt，命中香烟 + 点燃/按灭/熄灭组合时阻断。

**系统化改进建议**

- 原文烟草气氛可改写为非吸烟动作，例如看向卷宗、合上卷宗、手指停在页角、冷白灯下空气微尘。
- 对“火源”类动作以后分域处理：香烟动作、文件销毁、环境火光、危险动作各自独立，不用一个泛化禁词规则覆盖。

## 2026-04-29 19:43:40 JST - 临时角色不能从 character_image_map 请求 identity 图

### Case 60: lock_prompt_enabled=false 的临时角色应只用场景/道具参考图补视觉质感

**现象**

- screen2video EP01 director/keyframe 试跑时，SH09 的 `西装男人` 已在 record 中写成临时角色：`lock_prompt_enabled=false`、`lock_profile_id=""`。
- `run_novel_video_director.py` 预检正确跳过该角色的 identity reference 校验。
- 但 `generate_keyframes_atlas_i2i.py` 后续仍用 `EXTRA_BUSINESSMAN` 去查 `character_image_map`，并尝试读取不存在的 `screen_script/assets/characters/EXTRA_BUSINESSMAN.jpg`，导致 keyframe 生成失败。

**根因**

- director 的 character image map validation 和 keyframe 的 reference collection 规则不一致。
- planning 层为了声明角色与资产目标，会把临时角色 id 写入 map；这不代表该临时角色需要或拥有固定 identity 图。

**有效方案**

- keyframe reference collection 遇到 `lock_prompt_enabled=false` 且没有 lock profile / appearance lock / costume lock / appearance anchor tokens 的角色时，不请求人物参考图。
- 这类临时角色仍保留在 prompt 人物描述中；图像输入由 scene/style reference 和必要 prop reference 补足。

**系统化改进建议**

- 所有下游资产预检和参考图收集都应以 record 的 `lock_prompt_enabled`、`lock_profile_id` 和真实 lock material 为准。
- `character_image_map` 中的 key 只代表可选解析入口，不应静默覆盖 record 对临时角色的身份锁定策略。

## 2026-04-29 19:31:46 JST - 服装安全改写不能把固定服装改成二选一

### Case 59: clothing `或/or` 会破坏跨镜头 wardrobe continuity

**现象**

- EP21 final video 中角色服装出现明显跳跃。
- records、character lock profiles、keyframe prompts、Seedance prompts 中反复出现 `灰色外套或素色连衣裙`、`校服或日常便服` 等二选一服装描述。
- 同一角色在部分镜头被描述为外套，部分镜头被描述为连衣裙或校服，模型会在每个 shot 独立选择，导致剪辑后换装感很强。

**根因**

- 对原始敏感服装词做安全改写时，把“固定服装”改成了“安全服装候选集合”。
- `character_lock_profiles` 本应锁定身份和稳定外观，却包含 `或/or` 选择，导致所有后续 keyframe/I2V 提示继承不确定性。
- shot-level prop/wardrobe 仍残留礼服/连衣裙语义，而 character lock 又允许外套，记录层自身给出冲突信号。

**有效方案**

- 规则粒度是 episode-level：跨集可以自然换衣服；同一集内部除非原文明确换装，必须保持同一套。
- 安全改写必须选择一个明确服装结果，不写候选项：例如 `低饱和深灰紫色素色长袖连衣裙，衣着完整，同一件衣服贯穿本集`。
- 儿童/学生角色同理，固定为 `深藏青与白色中学校服` 或另一套明确服装，不写 `校服或日常便服`。
- 在 record、character lock profile、prop library、keyframe static record、Seedance prompt 中保持同一套服装文本。

**系统化改进建议**

- planner/render QA 增加 wardrobe continuity 检查：服装字段、角色 anchor、服装道具名中出现 `或/or/任选/候选` 时报警。
- 对每集建立 `costume continuity contract`，列出角色在本集每段使用的固定服装、允许变化、禁止变化。
- 对需要跨 shot 一致的服装生成单独 visual reference，并让 keyframe map 使用该 reference，而不是只依赖自然语言提示。

## 2026-04-29 18:19:08 JST - screen script 占位角色图 map 不能当作真实参考图

### Case 58: screen2video planner 生成的 character_image_map 只代表需要补图，不代表可进入 director

**现象**

- `screen2video_plan.py` 为了沿用现有 bundle 结构，会写出 `screen_script/character_image_map.json` 和角色 prompt/profile 文件。
- 这些 map value 默认指向 `screen_script/assets/characters/*.jpg`，但真实角色参考图可能还不存在。
- 如果 batch runner 只检查 map 文件存在，就可能误以为角色资产已准备好；进入 keyframe/director 时才失败。

**根因**

- planning bundle 需要声明角色资产目标路径，director/keyframe 阶段需要真实 identity reference image。
- “map 文件存在”和“map 中本集 records 实际需要的角色图片存在”是两件事。

**有效方案**

- `screen2video_play.py` 只把 map 存在且 JSON 有效作为基础检查。
- 真正的角色图片完整性继续交给 `run_novel_video_director.py` 按 selected records 精确校验：只检查本集本批 shots 需要的 `character_id/name/lock_profile_id`。
- 缺少图片时允许完成 planning/visual refs，但必须在 director/keyframes 前停止。

**系统化改进建议**

- 后续可增加 `--refs-only-ok-with-missing-characters` / `--preflight-only` 一类模式，避免用户只想检查角色图时误触发 visual refs API。

## 2026-04-29 16:24:52 CST - 非照片道具不要写成“非照片道具/禁止翻面”

### Case 57: QA 会把“非照片道具 + 翻面”误触发照片正反面规则

**现象**

- EP21 planning QA 报 `i2v_photo_side_visibility_missing`，命中 SH05 和 SH13。
- 实际镜头没有照片道具；触发来自服装、车窗、城市轮廓等普通道具的说明里写了“非照片道具”“禁止翻面/不允许翻面”。

**根因**

- QA 的照片规则会同时扫描“照片/photo/影像”和“翻面”等动作词。
- “非照片道具”虽然是排除语义，但仍包含“照片”；“禁止翻面”又包含照片动作词，组合后被当成照片道具缺少正反面契约。

**有效方案**

- 普通道具不要写“非照片道具”，改为 `普通道具`、`不适用`。
- 普通道具不要写“禁止翻面/不允许翻面”，改为 `不做面向切换`。
- 真正的照片道具才写正面、背面、当前可见面、朝向、数量和翻面策略。

**系统化改进建议**

- planner/render prompt 中普通道具的模板应避免把“照片”“翻面”作为否定词写入。
- QA 可后续区分否定语义，但生成 prompt 层仍应避免这类触发词。

## 2026-04-29 15:37:56 CST - Seedance 网关会拒绝过度具体的可读证据页眉

### Case 56: 证据材料页眉/人名/机构名不要强制生成清晰可读文字

**现象**

- EP20 SH02 keyframe 已成功，但 Seedance I2V 在 Atlas 查询阶段失败，错误为 `Invalid ***`。
- `prompt.final.txt` 要求四份 A4 材料的页眉依次清晰可见，并写入具体姓名/机构/材料类型，如俱乐部记录、病室证明、行车影像打印帧、直播截图打印页。
- 同批 SH01、SH03 可正常生成，说明模型、时长、尺寸和 image map 本身不是根因。

**根因**

- 视频生成网关可能会对 prompt 中的具体可读文字、机构/场所名、证据页标题做敏感词替换或参数校验，返回 `Invalid ***` 这类不透明错误。
- 对镜头叙事来说，SH02 只需要观众感知“四份排除嫌疑材料”，不需要模型真的生成可读页眉和具体姓名。

**有效方案**

- 保留数量、位置、动作和剧情意图：固定为 4 份 A4 证据材料，阶梯式叠放，石川逐份翻看并轻叩桌面。
- 将具体可读页眉改成正向视觉描述：`模糊排版块`、`灰阶影像`、`不可读材料标签`。
- 避免要求 I2V 生成清晰可读姓名、机构名、标题或截图文字；这些信息交给字幕/旁白/剪辑层表达。

**系统化改进建议**

- Seedance prompt sanitizer 应扫描“页眉清晰可见、标题可读、姓名可读、记录/证明/截图具体名称”等要求，并改写为不可读排版块。
- 证据/文件道具仍必须保留明确数量、位置和运动政策，但不把剧情文字硬塞给图像/视频模型生成。

## 2026-04-29 15:16:37 CST - 背景方位词不要触发人物背对误报

### Case 55: “金属门位于画面后侧右方”不是角色背对镜头

**现象**

- EP20 LLM planning 已将占位镜头替换为具体原文镜头，但 QA 仍报 `first_frame_character_back_view`。
- 命中词是 SH08 中 “深灰色金属门位于画面后侧右方 / DETENTION_METAL_DOOR_EP20 在画面后侧右方”，不是人物朝向。
- 同一镜头已明确写入石川与健一脸部可见、正侧脸或三分之二侧脸。

**根因**

- QA 对 `后侧` 这类词做了宽泛扫描，没有区分背景物体方位和人物背对镜头。
- 背景空间方位使用“后侧”会被误判，也可能给模型带来人物后背构图联想。

**有效方案**

- 背景物体方位改写为 `画面背景右方`、`远端背景右侧`、`画面深处右侧`，避免使用 `后侧`。
- 人物脸部可见契约保留，不因背景道具方位删减。

**系统化改进建议**

- planner/render prompt 中涉及背景物体位置时，优先用 `背景/远端/画面深处`，不要用 `后侧/背后`。
- QA 后续可区分 prop/location position 与 character pose，但 prompt 层仍应规避歧义词。

## 2026-04-29 14:49:20 CST - planning QA fail 必须阻断批量后续阶段

### Case 54: heuristic fallback 的通用镜头不能继续进入 director/keyframes

**现象**

- EP20 planning bundle 结构完整，但 SH02-SH12 大量使用“人物目标亮相、关系压力入场、关键证据或道具出现”等通用占位词。
- `plan_qa_report.json` 已经正确报出 9 条 `generic_shot_placeholder` high findings，`pass=false`。
- 旧批量入口仍继续执行 visual refs 和 director，导致 keyframes/image map 都生成了，但内容基础是坏的。

**根因**

- `novel2video_plan.py` 的 non-EP01 heuristic fallback 会生成通用 shot spine。
- batch runner 没有把 `plan_qa_report.json` 当作硬门禁；只要 planning 命令 exit 0，就进入后续阶段。

**有效方案**

- 批量入口默认给 planning 命令追加 `--qa-strict`。
- 对已存在 bundle 或跳过 planning 的情况，也必须读取 `plan_qa_report.json`；若 `pass=false`，在 visual refs/keyframes/Seedance 前停止。
- 只有显式传 `--allow-plan-qa-fail` 时才允许越过该门禁。

**系统化改进建议**

- 多集生产中，planning QA 是第一个硬门禁；director/keyframes 只能验证视觉输入完整性，不能修复坏剧本。
- 后续集建议使用 `--plan-extra-args '--backend llm --llm-shot-mode per-shot'` 或增加 chapter-based shot builder，避免 heuristic fallback 生成占位镜头。

## 2026-04-29 07:56:02 CST - 批量跑多集时必须自动生成每集 visual refs

### Case 53: scene-only / temporary-character keyframes 不能靠人工逐镜头补参考图

**现象**

- EP01 首次从 raw novel 跑到 director keyframes 时，SH01、SH02、SH04、SH12 缺少可用参考图。
- 这些镜头分别是 scene-only 酒店套房/证据细节，或服务员、警员这类临时角色镜头；不能用主角身份图硬塞给 keyframe。
- 手动补救命令是为 EP01 生成 `银座高级酒店套房`、`酒店大堂`、`HOTEL_ROOM_DOOR_01`、`HOTEL_EMERGENCY_BUTTON_01` 的 visual refs，再补跑缺失 keyframes。

**根因**

- `run_novel_video_director.py` 只传 character image map，不传场景/道具 reference manifest。
- scene-only 镜头和无 lock profile 的临时角色镜头没有主角参考图，keyframe 生成会缺少 image-edit 输入。
- 批量跑 10 集时，如果继续手写 `--scenes` / `--props`，每集都会出现不同的手工断点。

**有效方案**

- 每集 planning records 生成后，先运行 `generate_visual_reference_assets.py`，不手写 `--scenes` / `--props`，让脚本从该集 `scene_detail.txt` 和 records 自动收集所有场景与重要道具。
- `run_novel_video_director.py` 增加 `--visual-reference-manifest`，并把 manifest 传给 `generate_keyframes_atlas_i2i.py`。
- 批量入口在每集 director 前自动生成/复用 visual refs；scene-only 镜头使用 scene/style reference，临时角色镜头可结合场景 reference 和文字身份描述，不继承主角 identity reference。

**系统化改进建议**

- 多集批量生产应使用统一 batch runner：`plan -> visual refs -> director -> Seedance -> assembly -> QA`。
- visual refs 可放在项目共享目录中复用；manifest 可按当前 episode 重新写入，图片文件已存在时跳过生成。
- keyframe image map 构建后必须检查 selected shots 是否全部有 `image`，缺失则补 reference 后刷新 manifest 和 image map，不直接进入 Seedance。

## 2026-04-29 00:46:40 CST - QA 不应把必要电话道具契约误判为一镜多任务

### Case 52: 短句接电话和远端电话听者镜头需要保留手机/关键道具

**现象**

- EP06 SH03 只有一句“喂？”，但因为画面中有手机和照片，QA 报 `i2v_dialogue_action_prop_overload`。
- EP06 SH10 是远端电话听者镜头，必须保留手机、丝巾和化妆品盒位置契约，也被同一规则误报。

**根因**

- “对白 + 复杂动作词 + 道具”规则用于拦截一镜多任务，但没有区分电话接起短句和远端电话听者这两类必须带道具状态的镜头。

**有效方案**

- 单句极短接电话镜头，例如“喂？”，允许同时保留手机/照片道具契约。
- `lip_sync_policy=remote_voice_listener_silent` 的远端电话听者镜头允许保留手机和关键道具位置，因为这些是听电话动作和剧情连续性的组成部分，不是额外任务。

## 2026-04-29 00:45:33 CST - QA 禁词不要出现在负向道具策略里

### Case 51: “不要生成散落照片”仍会触发 vague prop QA

**现象**

- EP06 复用旧 spine 重新渲染 records 后，planning QA 报多条 `i2v_vague_static_prop_description`，命中词为 `散落`。
- 实际命中主要来自照片道具 `quantity_policy` 里的负向句“不要生成散落照片、照片堆或额外照片”，不是画面正向描述。

**根因**

- QA 会扫描 record 的道具契约文本；即使是禁止句，只要出现 vague prop token，也会被模型或 QA 当成可见概念。
- 负向提示里重复不希望出现的视觉词，仍可能增加模型联想。

**有效方案**

- 道具数量策略改用不包含禁词的正向/结构化措辞：`只允许这一张 SAKURA_SCHOOL_PHOTO；不得生成照片堆或额外照片副本`。
- QA 禁词列表保留；不要为了负向句放宽 QA。

**系统化改进建议**

- 所有 `quantity_policy` / `motion_policy` / `negative_prompt` 中也避免写入模糊数量词本身，改写为数量上限、固定 prop_id 和禁止副本。

## 2026-04-29 00:27:22 CST - 电话听者必须有明确表演动作且 repair 必须复跑

### Case 50: “听电话闭嘴”不能只写成禁止项或信任第一次 phone-fix

**现象**

- 电话远端声音镜头即使有 `remote_voice_listener_silent`，如果只写“不要开口/无口型”，模型仍可能把画面内听者做成被动站立或出现轻微疑似口型。
- 第一次 `output.phone_fixed.mp4` 不一定可靠；人工确认更好的结果来自重新使用 `phone_audio_repair/prompt.final.txt` 这套无音频闭嘴 prompt 抽取新候选。

**根因**

- 负向约束不是明确动作。I2V 更需要一个可表演、可持续的正向动作，例如“认真地听电话，闭着嘴，认真思考”。
- repair artifact 和 repair 成品是两件事；成品可能失败，artifact 才是可复跑的修复源。

**有效方案**

- planning 层开始就把电话听者动作写成明确正向表演：听者认真地听电话，一句话也没有说，闭着嘴，认真思考，只用眼神、眉头、呼吸和握手机手指表现反应。
- record 中同步写入 `action_intent`、`framing_focus`、`prompt_render.shot_positive_core`、`dialogue_blocking.listener_action_contract` 和 `i2v_contract.phone_contract.listener_action_contract`。
- phone repair 执行时必须从 `phone_audio_repair/prompt.final.txt` 与 `payload.preview.json` 重新读取并复跑 `generate_audio=false` 的无音频视频，再把原始 `output.mp4` 音频合回；不要直接信任已有 `output.phone_fixed.mp4`。

**系统化改进建议**

- QA 对 phone remote listener 镜头检查四个动作词是否同时存在：`认真地听电话`、`一句话也没有说`、`闭着嘴`、`认真思考`。
- repair report 应记录 `rerun_source_prompt`、`rerun_source_payload` 和 `rerun_policy`，方便追踪最终候选来自哪套闭嘴 prompt。

## 2026-04-29 00:17:57 CST - phone-fix 候选需要可替换拼接

### Case 49: 无音频闭嘴修复也可能需要保留正脸嘴部并多跑候选

**现象**

- EP06 SH12 自动 phone-fix 已正确使用 `generate_audio=false`，并从原始 `output.mp4` 抽取电话远端音轨合回 `output.phone_fixed.mp4`。
- 但第一次 phone-fix 的无音频视频仍让听电话的人出现疑似讲话口型；原因不是修复 prompt 里仍有台词，而是首帧保留了双人正脸和可见嘴部，I2V 即使无音频也可能生成口部动作。
- 用户要求保留正面和嘴部，再用同一个 `phone_audio_repair/prompt.final.txt` 重跑一次。第二个候选 `output.phone_fixed.frontmouth_rerun_v1.mp4` 效果明显更好。

**根因**

- `generate_audio=false` 只能移除模型音频，不是硬性口型冻结控制。
- 对可见嘴部正脸镜头，闭嘴表现存在随机性；同一 prompt 的不同候选可能差异很大。
- 拼接阶段如果只能手写 concat 文件，容易误用较差候选或难以记录采用了哪个修复版本。

**有效方案**

- 保留正脸嘴部需求下，允许 phone-fix 产生多个候选，人工选择口型最稳的一条。
- episode assembly 支持 shot-level clip override，用 JSON 明确指定某个镜头采用哪条候选视频。
- 本次 EP06 最终拼接使用 SH12 的 `output.phone_fixed.frontmouth_rerun_v1.mp4` 覆盖默认 `output.phone_fixed.mp4`。

**系统化改进建议**

- `assemble_episode.py` 应记录 `clip_overrides_file` 与 `applied_clip_overrides`，让最终成片可追溯到具体候选。
- 未来可给 `run_seedance_test.py` 增加 phone-fix candidate count 参数，自动生成 `output.phone_fixed.candidate_N.mp4`，但最终仍建议由人工确认选择。

## 2026-04-29 00:17:29 CST - 看照片默认正面朝手拿照片的角色

### Case 48: 角色自己看照片时，不应默认把照片正面转给观众

**现象**

- “角色拿起照片看”如果只写照片正面内容，规划或 prompt 可能把照片正面朝向镜头/观众。
- 这会让动作语义变得别扭：角色正在看照片，但照片图像却面向观众，不面向角色本人。
- 只有“展示给另一个角色看”或“展示给镜头/观众看”时，照片正面才应该朝向对应观看者。

**根因**

- 旧照片朝向规则强调必须定义正面/背面/朝向，但没有明确“看照片”的默认观看者是谁。
- `front_visible` 容易因为 prompt 中出现“照片中/影像/校服照片”等正面描述而被误判为“正面朝镜头”。

**有效方案**

- 看照片/拿起照片看时，照片正面默认朝手拿照片的角色；观众通常只看到纯白或浅白背面。
- 如果写明“展示给/拿给/递给另一个角色看”，照片正面朝被展示的角色，而不是自动朝镜头。
- 只有明确写“朝镜头/朝观众/照片特写/观众看清”时，照片正面才朝镜头或观众。
- 规划层写入 `photo_viewer_policy`，keyframe 和 Seedance 渲染同一规则。

**系统化改进建议**

- record QA 应把“看照片”但 `orientation_to_camera=front side faces camera/audience` 且没有展示给观众/他人的镜头标为 high severity。
- 照片展示类镜头最好拆成：角色看照片反应镜头、照片正面特写镜头，避免同一首帧同时要求角色看和观众看清。

## 2026-04-29 00:02:36 CST - 首帧可见角色必须露出脸部

### Case 47: 角色首帧不能背对观众，电话听者也要保持脸部可见

**现象**

- 首帧构图如果只写“人物入镜/清楚入镜”，模型可能选择背影、背对镜头或后侧构图。
- 这会削弱角色身份识别、表情传达和后续 I2V 角色一致性。
- 过去为规避电话远端声音绑定到听者嘴型，可能倾向使用背侧构图；这与“首帧角色需要露出脸部”的新要求冲突。

**根因**

- `first_frame_contract.visible_characters` 只表达“谁在画面中”，没有表达脸部朝向和可见程度。
- 说话人首帧规则已有嘴部可见检查，但普通反应角色、沉默角色和电话听者缺少统一的脸部可见契约。
- 如果只在 Seedance final prompt 里补一句，下游 keyframe 首帧可能已经生成背影，视频阶段很难纠正。

**有效方案**

- 规划层新增首帧人物脸部可见契约：所有首帧可见角色必须露出脸部，优先正面、正侧脸或三分之二侧脸，不能背对观众。
- `first_frame_contract` 增加 `character_face_visibility`，把每个可见角色的脸部朝向写成结构化字段。
- keyframe prompt 必须渲染同一契约，确保首帧图像不是背影。
- Seedance prompt 继续渲染同一契约，并把可见角色脸部自查写入 `render_report`。
- 电话远端听者是例外中的例外：不能背对观众；可以让手机或手部自然遮住部分嘴部以降低 lip-sync 风险，但脸部轮廓、眼睛和鼻梁必须可见。

**系统化改进建议**

- QA 应检查 `first_frame_contract.visible_characters` / `character_face_visibility` / `prompt_render.shot_positive_core` 是否同时保留脸部可见契约。
- 如果 record 或 keyframe prompt 出现“背对、背影、后侧、from behind、back to camera”等首帧主体构图词，应标为 high severity，除非用户显式要求身份隐藏并记录例外。
- 对身份隐藏镜头，优先使用半脸、镜面反射、低头侧脸、遮挡部分面部等仍露出脸部的方案，不默认使用背影。

## 2026-04-28 23:43:10 CST - GinzaNight 原文章节数不应被 20 集模板压缩

### Case 46: 明确要求一章一集时，episode outline count 必须跟原文 numbered chapter 对齐

**现象**

- `ginza_night.md` 原文有 22 个 `## N. 标题` 章节。
- 旧 `build_ginza_episode_outlines()` 固定输出 20 集，把后段 `DNA的觉醒`、`自白的深层`、`告白的泪水`、`守护的代价`、`沉默的注视`、`新干线的牵手`、`献身的终曲` 压成 5 集左右。
- 这会让 EP20 承担原文 20-22 章结局内容，违背“record content is source of truth”和“每章一集”的用户规划意图。

**根因**

- GinzaNight 使用项目专属 20 集硬编码大纲，而不是从原文编号章节生成 episode outline。
- 输出文件名、标题和 QA 也硬编码 `20集分集大纲` / `episode_outline_count == 20`，导致改成 22 集后会被误报。

**有效方案**

- GinzaNight 规划改为读取原文 `## N. 标题` numbered chapter，一章对应一个 EP。
- `source_basis` 只写当前章标题，不再跨章合并或使用 `真相与献身`、`终章` 这类粗粒度标签。
- 分集大纲文件名和标题按 `len(bible.episode_outlines)` 动态生成，例如 `12_GinzaNight22集分集大纲.md`。
- QA 对 GinzaNight 使用原文 numbered chapter count 作为 expected episode count，避免 22 集被当成异常。

**系统化改进建议**

- 未来所有“严格按章节改编”的项目都应走 chapter-to-episode 显式映射，并把 `chapter_index` / `chapter_title` 写入 project bible。
- 若要压缩成 20/40/60 集，必须显式记录 compression map，不能让固定模板静默覆盖原文章节结构。

## 2026-04-28 23:26:53 CST - Seedance duration buffer 不能以小数直接发给 Novita

### Case 45: 时长预算可加 0.5 秒，但 provider payload 必须是整数秒

**现象**

- EP06 全量重跑 Seedance 时，将旧 duration override 加 0.5 秒后直接写入 payload，例如 `6.5`、`7.5`、`11.5`。
- Novita Seedance 返回 HTTP 400，schema 明确要求 `/duration` 是 integer；12.5 也被判定为 invalid duration。

**根因**

- “时长预算 buffer”是项目层的调度意图，不等于 provider API 支持半秒 duration。
- Novita Seedance I2V 的 `duration` 字段只接受 4-12 范围内的整数秒。

**有效方案**

- 先按项目规则计算 `base_duration + duration_buffer_sec`。
- 再对 provider payload 执行向上取整，例如 `7 + 0.5 -> 8`。
- 最后按 profile/provider 范围 clamp，例如 `12 + 0.5 -> 12`。

**系统化改进建议**

- `run_seedance_test.py` 的 `payload.preview.json` 应反映 provider 可接受的最终整数 duration。
- `run_manifest.json` 记录 `duration_buffer_sec` 与 payload rounding policy，避免误以为 provider 收到了小数秒。

## 2026-04-28 13:55:05 CST - 照片道具必须定义正反面与朝向

### Case 44: 看照片/拿照片时，照片正面与背面不能让模型自由脑补

**现象**

- EP06 SH07 的 record 写了 `SAKURA_PHOTO_01 正面影像中`，但 keyframe prompt 丢失了“照片正面/背面/朝向观众”的道具状态。
- Seedance prompt 只写“手指停在照片边缘”，没有定义照片尺寸、材质、正面图像、背面颜色和当前朝向。
- 输出中模型生成了多张散落照片，并让角色手持一张未明确正反面的照片；观众无法稳定判断正在看的是照片正面还是背面。

**根因**

- “照片”是双面道具：正面有图像，背面通常是白色或浅色相纸。只写“看照片/拿照片”不足以让 I2V 稳定选择可见面。
- 当 prompt 没有固定照片数量、位置、朝向和运动权限时，模型会把“照片”扩展成一堆散落照片，甚至在角色手中新增照片。
- keyframe 阶段如果只保留人物和情绪，不保留道具面向信息，下游 Seedance 即使提到照片，也无法恢复精确正反面。

**有效方案**

- 照片第一次出现必须进入道具库，定义：
  - `prop_id`
  - 长宽高/厚度，例如 `10cm x 15cm x 0.3mm`
  - 材质：半光泽相纸
  - 正面：具体图像内容
  - 背面：纯白/浅白色相纸，无图像，无文字，或指定少量背印
  - 默认朝向：正面朝上/朝镜头，或背面朝上/朝镜头
- 每个看照片镜头必须写清：
  - 当前可见面：正面或背面
  - 面向谁：朝观众/朝角色/朝地面/朝镜头
  - 是否允许翻转：不允许翻面，或在指定时间点翻面
  - 数量与位置：只出现 1 张，或明确 N 张及每张位置
- 如果观众需要看到照片内容，写“照片正面朝向镜头/观众，图像可见”；如果角色自己看而观众不看，写“照片正面朝向角色，观众只看到白色背面”。

**系统化改进建议**

- record QA 增加 `photo_side_visibility` 检查：出现 `照片/photo` 且有“看/拿/递/翻/指向”动作时，必须有正面/背面、朝向、数量、运动权限。
- keyframe prompt renderer 不能丢弃照片道具的正反面状态；首帧如果照片可见，必须写入“哪一面朝向镜头”。
- Seedance prompt 增加照片道具展开块，避免“散落照片”这类模糊数量词，除非 record 明确允许多张散落照片。

## 2026-04-28 13:01:37 CST - 电话听者镜头改为视频静音生成、后期叠远端语音

### Case 43: 接电话但画面内角色不说话时，远端对白应后期合成

**现象**

- EP06 SH10 即使强化 `prompt.final.txt`，只要 `generate_audio=true` 且田中健一嘴部可见，Seedance 仍可能让田中出现疑似说话口型。
- 将构图改为非背对的三分之二侧脸、并写清“田中闭嘴/不做口型”后，仍不能完全稳定禁止口型。

**根因**

- I2V 模型在生成音频时会把声音和画面中最显眼的人脸自动绑定；自然语言里的“电话远端声音”不是硬性音轨归属。
- 当远端说话人与听者同为成年男性，且听者拿着手机、嘴部可见时，模型倾向把远端台词同步到听者嘴上。

**有效方案**

- 电话听者镜头的视频阶段使用 `generate_audio=false`。
- `prompt.final.txt` 只写无声画面：画面中没有任何人说话；听者从第一帧到最后一帧保持手机贴耳，不放下、不换手、不看屏幕；嘴唇闭合，只用眼神、眉头、肩背和握手机手指表现反应。
- 远端台词写入后期 audio cue，指定：
  - `speaker`: 远端说话人
  - `voice_profile`: 对应角色音色
  - `source`: `phone_remote`
  - `start_sec`: 例如 `0.5`
  - `text`: 完整台词
  - `effect`: 电话听筒滤波
- EP06 SH10 测试中，OpenAI TTS 生成石川音色台词后，用 `adelay=500ms` 从 0.5 秒叠入视频，并加 `highpass=300, lowpass=3400` 电话滤波，视觉口型稳定性明显优于 `generate_audio=true`。

**系统化改进建议**

- 2026-04-28 13:33:04 CST 已在 `scripts/run_seedance_test.py` 固化为显式 fallback：正常生成仍保留；当视觉 QA 判断电话听者错误开口时，用 `--phone-audio-repair-shots SHxx` 触发二次无声视频生成，再抽取原始 `output.mp4` 音频合成 `output.phone_fixed.mp4`。
- 2026-04-28 22:42:19 CST 已在 `scripts/run_seedance_test.py` 增加自动自查：record-backed 电话远端听者镜头会输出 `phone_lipsync_self_check.json`；若仍用模型生成电话音频且构图显示高风险听者嘴部，默认自动触发同一 repair 流程。可用 `--no-auto-phone-audio-repair` 关闭。
- `run_seedance_test.py` 可在 `lip_sync_policy=remote_voice_listener_silent` 且 record 标记“远端电话听者镜头”时自动关闭 `generate_audio`，并输出 `post_audio_cues.json`。
- episode assembly 可增加 audio cue overlay 阶段，将远端电话声、旁白等后期音轨按 `start_sec` 混入。
- QA 应检查 phone-hold 时间轴：手机是否从第一帧到音频结束后仍贴耳，且画面内听者没有节奏性口型。

## 2026-04-28 09:23:29 CST - 电话远端声音被绑定到画面内听者嘴型

### Case 42: 男性远端电话长对白不应给画面内男性听者清晰嘴部

**现象**

- EP06 SH10 的 `prompt.final.txt` 明确写了石川悠一的声音来自电话/手机听筒，田中健一和佐藤美咲保持沉默。
- 生成视频仍把石川的台词分配给画面内持手机的田中健一，让田中出现说话口型。
- SH04 同样是电话远端声音，但只有田中单人听电话，远端是樱子女声，生成结果更容易正确。

**根因**

- Seedance I2V 对 `generate_audio=true` 的电话远端声音没有硬性的 speaker binding；长对白会倾向绑定到画面中最清楚、最像说话人的脸。
- SH10 原构图是双人中近景，田中是拿手机的成年男性视觉中心，远端石川也是成年男性声音，模型容易把“电话里的男性声音”归因到田中的嘴。
- Prompt 模板还把正确状态写进了 `禁止：只有石川悠一说话，田中健一保持闭嘴。`，语义反向，进一步削弱约束。

**有效方案**

- 对高风险电话远端长对白，优先使用单人听电话构图，不让非说话人正脸嘴部成为视觉中心。
- 如果远端说话人和听者性别/年龄/声线相近，进一步采用背侧或后侧听电话构图，让听者嘴部不可见或被手机和手完全遮挡。
- 将 prompt 的禁止段改为正向执行重点，例如：只有远端声音从听筒传来；画面内听者嘴部不可见；不要把远端台词分配给听者嘴型。

**系统化改进建议**

- `prompt.final.txt` 生成逻辑不应在 `禁止：` 下输出“只有 X 说话，Y 保持闭嘴”这种正向目标，应改成“不要让 Y 开口/不要让 Y 说 X 的台词”。
- Record QA 应把 `remote_voice_listener_silent` + visible listener clear mouth + same-gender remote speaker 标为 high risk，并建议背侧/口部遮挡构图。
- Keyframe QA 应检查电话远端高风险镜头是否仍有画面内听者清晰嘴部；如有，提示改为手部、手机、背侧、道具反应镜头。

## 2026-04-27 23:14:12 CST - per-shot live planning 中途 502

### Case 41: 单镜 OpenAI 临时 502 不应导致整集回退 heuristic

**现象**

- EP06 新流程 live planning 已成功完成 `episode_fact_table`、`episode_shot_spine`、SH01-SH04。
- 生成 SH05 时 OpenAI Responses API 返回 Cloudflare `502 Bad Gateway`。
- 旧的异常处理包住整个 LLM backend，导致最终 artifacts 标记 `llm_applied=false`，并回退为 heuristic records，虽然前序 response 文件已经成功落盘。

**根因**

- per-shot 生成已经把模型任务拆小，但错误处理仍沿用整集调用时代的“一处失败，整集 fallback”策略。
- 重跑时默认不会复用已成功的 response，因此临时网络/服务端错误会浪费前序调用并增加再次失败概率。

**有效方案**

- 默认启用 LLM response resume：如果 `episode_fact_table.response.json`、`episode_shot_spine.response.json` 或 `SHxx.response.json` 已存在且可解析，重跑时直接复用。
- 遇到 SHn 临时失败后，重跑同一命令会从已成功的 SH01-SH(n-1) 继续，当前镜头重新请求。
- 如需强制重建全部 LLM response，显式传 `--no-llm-resume-existing` 或删除输出目录。

**系统化改进建议**

- 未来可给单镜调用增加 bounded retry/backoff，只对当前 SH 重试。
- 最终 bundle 应区分“partial LLM responses saved”和“complete record bundle applied”，避免用户误以为所有 LLM 工作都丢失。

## 2026-04-27 22:56:52 CST - per-shot 新流程仍被 full-novel character catalog 拖大

### Case 40: 默认 LLM planning 不应先跑全书角色表大请求

**现象**

- 将 shot payload 改成 fact table -> episode shot spine -> single-shot record 后，`SH01.request.json` 已经不再携带整集小说原文。
- 但 `novel2video_plan.py --backend llm --llm-dry-run --llm-only-shot SH01` 仍会先写 `full_character_catalog.request.json`，该请求包含大段全文，体积显著大于 fact/spine/shot 三个请求总和。
- 这会让“bite-size per-shot”流程在入口处仍然背负一个全书级 LLM 调用。

**根因**

- 旧流程把 LLM 角色表作为 `--backend llm` 的前置步骤默认执行。
- per-shot I2V 规划阶段真正需要的是稳定角色锚点和本镜头可见角色切片，不需要每次规划单集或单镜都重跑全书角色抽取。

**有效方案**

- 默认关闭 full-novel character catalog LLM 步骤，保留启发式角色表作为 shot planning 的轻量角色锚点。
- 如确实要重建全书角色库，必须显式传 `--llm-character-catalog`。
- single-shot prompt 根据 `TARGET_SPINE_ROW.visible_characters` 与 `active_speaker` 选择角色锚点；live spine 完成后不再传全角色表。

**系统化改进建议**

- 长期角色库应成为可缓存的项目级资产，而不是每次 episode/shot planning 的默认前置 LLM 调用。
- 如果角色库缺失，可单独跑角色库构建任务；I2V shot record 生成只引用已确认角色资产。

## 2026-04-27 22:12:47 CST - I2V 规则加入后整集 shot payload LLM 调用过重

### Case 39: 整集 13 镜头一次性规划在加入 I2V 规则后容易超时或产出过载镜头

**现象**

- EP06 重新规划时，fact table / shot payload 需要同时读取小说原文、角色资产、连续性、I2V prompt design rules，并输出整集 13 个镜头。
- 单次请求长时间无响应，用户要求停止。
- 已完成的旧 EP06 v1 虽然通过旧 QA，但存在多画面说话人、电话远端声音与画面内回复混在同镜、道具不定量、负向安全词等 I2V 结构问题。

**根因**

- 整集 shot payload 一次性生成，把剧本、13 个镜头、对白归属、首帧构图、道具库、电话规则和 I2V QA 全部压进一个 LLM 输出任务。
- I2V 规则越严格，单次输出越长，越容易超时或让模型为了满足总量而回到旧式“一个镜头承担多个任务”的写法。
- 对 `SHn` 缺少明确的 `SHn-1` 已确认镜头上下文，导致连续性、道具位置和说话/沉默状态只能靠整集隐式推断。

**有效方案**

- LLM planning 保持 fact table 一次生成，但 shot payload 改为逐镜生成：`SH01`、`SH02`、`SH03`……
- 生成 `SHn` 时显式传入 `SHn-1` 的 accepted/generated shot 信息，包括地点、人物状态、道具、对白归属和 source basis。
- 每个 `SHxx` 单独写 request/response，失败时只重试当前镜头，不重跑整集。
- 每个镜头生成后仍进入 record 层 I2V QA：一镜一口、电话拆分、手机屏幕朝内、道具库、首帧稳定、正向安全措辞。

**系统化改进建议**

- `novel2video_plan.py` 的 LLM shot mode 默认使用 per-shot。
- 仍保留 episode-level mode 作为兼容选项，但生产 I2V 规划不应默认使用。
- 下一步可增加 `--only-shot SHxx` 或 resume 机制，让人工审核某一镜后再继续下一镜。

## 2026-04-27 04:03:48 CST - Atlas Seedance `Invalid ***` 与安全负向词/静态道具不定量

### Case 38: Seedance I2V 可能因负向性词和“散落/数个”道具描述失败

**现象**

- EP08 SH06 在 Atlas Seedance 1.5 I2V 阶段 10 次重试后失败。
- Provider 状态返回 `status=failed`，错误为 `One or more parameters specified in the request are not valid: Invalid ***`。
- 同一集其他 12 个镜头成功；SH06 的首帧图片本身正常，失败集中在视频 prompt / payload。

**根因**

- SH06 final prompt 仍包含“不出现裸露或性暗示”这类负向性词，且同一 prompt 包含樱子照片/母女照片等家庭证据上下文，可能被 provider 侧安全或参数校验拒绝。
- 静态道具写成“散乱照片”“散落照片”“数个信封”，违反项目的静态道具明确计数、位置、首帧可见和 motion policy 规则，也会削弱 I2V 对首帧道具稳定性的执行。

**有效方案**

- 在 record 层把负向性词改为正向安全视觉事实，例如“人物衣着完整，保持日常社交距离”。
- 把不定量道具改为明确数量和位置：
  - 旧木箱在画面左下方首帧固定可见。
  - 3张照片在地板上首帧固定可见：1张樱子照片、1张母女合照、1张彩花照片。
  - 3个信封在地板右下方首帧固定可见。
  - 玄关门板在画面深处首帧固定可见。
- 单独重跑失败镜头即可，不需要重跑整集；修正后 EP08 SH06 成功生成 `output.mp4`。

**系统化改进建议**

- Seedance prepare QA 应扫描 `prompt.final.txt` 和 record：发现“不出现裸露或性暗示/裸露/性暗示/情色”等负向性词时提示改为正向安全表述。
- QA 应把“散落/散乱/数个/若干”等静态道具不定量词作为 high severity，尤其当镜头要求道具首帧固定可见时。

## 2026-04-27 03:35:40 CST - OpenAI keyframe safety 对负向性词和角色锁档案误触发

### Case 37: “不出现裸露或性暗示”等负向约束进入 image prompt 也可能触发 sexual safety

**现象**

- EP08 OpenAI keyframe 中 SH04、SH07、SH09、SH11 被拒绝，错误均为 `safety_violations=[sexual]`。
- 失败镜头集中在樱子照片/樱子入镜/美咲旧礼服/母女遗物语境。
- prompt 已包含“不出现裸露或性暗示”“必须非情色化安全呈现”等安全意图，但这些词本身与“十四岁少女、旧礼服、丝质、夜场”等角色锁档案组合后仍触发 OpenAI image safety。

**根因**

- OpenAI image safety 对 prompt 关键词组合敏感，负向性词并不会被可靠理解为“禁止”，反而可能扩大 sexual 语义场。
- keyframe prompt 的人物锁定段会把角色锁档案中的“未成年、少女、非情色化、旧礼服、丝质礼服”等词带入图像模型；这些词对静态首帧不是必要视觉事实。

**有效方案**

- 图像 prompt sanitizer 需要连同人物锁定 brief 一起重写，而不是只清洗 `shot_positive_core`。
- 对 OpenAI keyframe，删除或正向替换高风险负向词：
  - “不出现裸露或性暗示” -> “衣着完整、保持日常社交距离”
  - “必须非情色化安全呈现/非情色化” -> “朴素日常呈现”
  - “十四岁少女/未成年/少女” -> “中学生/学生”
  - “旧礼服/丝质礼服/丝质/丝绸” -> “灰色外套、素色连衣裙、柔和布料”
- 这类 rewrite 只用于 keyframe 图像安全，不改变 record 的剧情真相；Seedance 视频 prompt 仍以 record 为源头。

**系统化改进建议**

- `generate_keyframes_atlas_i2i.py` 的 `build_character_brief()` 应调用 keyframe visual sanitizer，避免锁档案绕过安全重写。
- OpenAI keyframe QA 可扫描最终 prompt 是否残留“性暗示、裸露、情色、未成年、十四岁、旧礼服、丝质礼服”等组合，并在正式调用前阻断或自动重写。

## 2026-04-27 03:15:39 CST - `novel2video_plan.py --out` 相对目录嵌套误用

### Case 36: `--out` 传入 `novel/...` 会被解析成 `novel/novel/...`

**现象**

- 从根目录运行 EP08 planning 时传入 `--out novel/ginza_night/GinzaNight_EP08_openai_atlas_fullrun_v1`。
- 脚本实际输出到 `/Users/leiyang/Desktop/Coding/Short_videoGEN/novel/novel/ginza_night/GinzaNight_EP08_openai_atlas_fullrun_v1`。
- 规划本身成功，`llm_applied=true`，但 bundle 不在既有 `novel/ginza_night/` 项目目录下；如果继续跑 director，会使用错误资产相对结构。

**根因**

- `novel2video_plan.py` 的 `--out` 设计为 `novel/` 根目录下的相对路径，而不是仓库根目录相对路径。
- 因此用户或脚本如果把仓库路径前缀 `novel/` 一并传入，会被二次拼接。

**有效方案**

- 在仓库根目录运行时，GinzaNight EP 输出应使用 `--out ginza_night/GinzaNight_EPxx_openai_atlas_fullrun_vN`。
- 如果已误生成 `novel/novel/...`，确认该目录是本轮误输出后删除，并用正确 `--out` 重跑。

**系统化改进建议**

- `novel2video_plan.py` 可在 `--out` 以 `novel/` 开头时提示并自动剥离前缀，或直接报错说明 `--out` 是相对 `novel/` 的路径。
- 生产运行手册应明确区分“仓库根目录相对路径”和“novel 根目录相对路径”。

## 2026-04-27 00:20:45 CST - OpenAI keyframe safety 对亲密/未成年照片上下文误触发

### Case 35: 克制亲密镜头和未成年人照片证据镜头也可能被 OpenAI image safety 判为 sexual

**现象**

- EP02 SH03 是前夜套房中彩花触碰健一领带的心理操控镜头，prompt 已写“不出现裸露或性暗示”，但仍因 `safety_violations=[sexual]` 被 OpenAI image generation 拒绝。
- EP02 SH10 是健一看到小樱照片的证据镜头，prompt 包含“十四岁少女小樱”“照片”“丝巾”等上下文，也被同类 safety 拒绝。
- 失败后 `generate_keyframes_atlas_i2i.py` 会继续后续镜头，最后 `build_image_input_map.py --strict` 报缺少对应 shot image。

**根因**

- 单纯添加“不出现裸露或性暗示”不足以抵消高风险词组合；“套房、丝质礼服、靠近、白衬衫、身体记忆、亲密距离”等会使成人镜头被判高风险。
- 未成年人相关词与“照片、卧室、丝巾、摩挲”等放在同一图像 prompt 内，会触发更严格的 sexual safety。

**有效方案**

- keyframe prompt 只保留安全视觉事实，把亲密动作改写为非接触、公开/桌边对话构图：人物保持克制距离，领带作为已佩戴道具或桌面道具可见，不描述靠近胸前、白衬衫、身体记忆、礼服边缘。
- 未成年人照片镜头改成“桌面证据照片/家庭照片/学生证件照”构图，避免“卧室 + 十四岁少女 + 丝巾 + 摩挲照片”组合；强调照片小而不可读、只作为剧情证据、人物不进入照片细节展示。
- 对 OpenAI keyframe 的静态 record 可做 provider-safe rewrite，但不得改变 record 的剧情真相；视频 prompt 仍以原 record 为源头真相。

**系统化改进建议**

- `generate_keyframes_atlas_i2i.py` 在 OpenAI provider 下可加入 safety rewrite 层：检测亲密空间/未成年人/床/卧室/丝巾/照片等组合，自动转为证据化、非接触、公共构图。
- image map 构建前应输出失败 shot 列表，并建议只重跑缺图镜头。

## 2026-04-26 23:58:55 CST - LLM planning 未加载 `.env` 时静默回退占位草案

### Case 34: `novel2video_plan.py --backend llm` 如果没有导出 `OPENAI_API_KEY`，会回退 heuristic 并继续产出占位镜头

**现象**

- 使用 `novel2video_plan.py --backend llm` 从 EP02 开始全链路运行时，规划输出 `llm_applied=false`，`llm_requests/` 只有 request JSON，没有 response JSON。
- `plan_qa_report.json` 出现大量 high severity：`generic_shot_placeholder`、`shot_missing_dialogue`、`narration_only_shot`。
- record 和 Seedance prompt 中出现“第2集核心场景”“人物目标亮相”“第2集，前夜的回响开场异常。”等模板化内容；如果不拦截，会继续进入 OpenAI keyframe 和 Atlas/Seedance 视频生成，浪费额度并生成不可交付视频。

**根因**

- `novel2video_plan.py` 当前不会自动读取项目 `.env`。
- 如果当前 shell 没有显式导出 `OPENAI_API_KEY`，LLM backend 会记录 fallback 并保留 heuristic 结果；默认不以非零状态退出。

**有效方案**

- 运行完整生产链路前先执行 `set -a; source .env; set +a`，再显式覆盖本轮 provider，例如 `IMAGE_MODEL=openai`、`VIDEO_MODEL=atlas-seedance1.5`。
- planning 后必须检查 `plan_qa_report.json`：`llm_applied` 必须为 true，且不能有阻断级 `generic_shot_placeholder`。
- 如果发现占位镜头，立即停止后续 keyframe/video，不要继续烧生成额度。

**系统化改进建议**

- `novel2video_plan.py` 可补充 `.env` 读取或在 `--backend llm` 且 API key 缺失时默认失败，除非用户显式传 `--llm-dry-run` 或 `--allow-heuristic-fallback`。
- director / full-run 脚本可在进入 keyframe 前检查 `plan_qa_report.json`，发现 `llm_applied=false` 或 high severity 占位内容时阻断。

## 2026-04-26 23:12:42 CST - 电话/画外对话的 keyframe 单端构图

### Case 33: 明显不在同一物理空间的对话不能为了对白完整而把两端角色塞进同一 keyframe

**现象**

- EP03 SH04 是电话对话：石川悠一在电话另一端要求田中健一来警视厅，田中健一在家中回应“我现在过去”。
- 如果按“对白说话人必须入镜”的一般规则机械处理，容易把石川和健一错误放到同一空间，或生成分屏/电话气泡/字幕式画面。
- keyframe static anchor 还可能弱化“手机贴耳听电话”这个动作，只留下人物和丝巾，导致 I2V 音频归属不稳定。

**有效方案**

- 电话/画外对话以 record 的 `source` 和 `listener` 为准：`source=phone` 的远端 speaker 不强制入镜，listener 必须入镜并呈现接听/倾听动作。
- keyframe 只选择一个物理空间作为画面真相，不做分屏，不同图呈现两端空间。
- 对电话镜头自动注入视觉契约：`listener` 在画面内接听手机，手持 1 部手机贴近耳边或正在接听；远端角色只作为电话另一端角色，不在画面内，不要分屏，不要第二空间。

**系统化改进建议**

- keyframe prepare QA 应检查电话对白镜头是否同时满足：listener 入镜、手机/接听动作可见、远端 speaker 不被错误加入人物锁定。
- 静态首帧 sanitizer 不能把电话道具和接听动作从 `shot_positive_core` 中清掉；如果清掉，下游 keyframe prompt renderer 必须根据 `dialogue_lines.source=phone` 补回视觉契约。

## 2026-04-26 23:06:41 CST - Grok keyframe 误生成字幕/旁白文字

### Case 32: keyframe 图像 prompt 带入视频语言锁和镜头编号，Grok 会把它画成叠字

**现象**

- EP03 Grok keyframe 图片下方出现大段白色字幕/旁白样文字，画面左上角还出现 `SH01` 这类镜头编号。
- 这些文字不是后期字幕，而是被生图模型直接画进 keyframe，后续 I2V 会把文字作为首帧内容继承。

**根因**

- `generate_keyframes_atlas_i2i.py` 的 keyframe prompt 直接拼入 `prompt_render.positive_prefix`，其中包含“所有角色对白、旁白和模型音频只使用普通话中文，屏幕字幕只使用简体中文”。
- prompt 首段以 `SH01 镜头起始帧` 开头，Grok 容易把镜头编号当作画面标签生成。
- `continuity_rules` 和 `shot_positive_core` 中的“对白/旁白/台词”等视频执行语义，对图像模型不是必要视觉事实，反而会触发字幕化。

**有效方案**

- keyframe prompt 渲染时只保留视觉事实，不把对白、旁白、字幕、普通话、简体中文、模型音频、台词等视频/音频/字幕控制语句传给图像模型。
- keyframe prompt 不再以 shot id 开头；shot id 只保存在目录和 manifest 中。
- 在 prompt 前部加入纯电影画面约束：无后期叠加文字、标题、镜头编号、水印、logo 或说明性文字；实体道具文字只有剧情必需时才允许小而自然地贴合物体。

**系统化改进建议**

- keyframe prepare QA 应扫描 prompt，如果出现 `SH\d+`、字幕、旁白、对白、台词、普通话、简体中文、模型音频、subtitle/caption/dialogue/narration 等触发词，应提示或阻断正式生图。
- record 仍然是源头真相；语言锁和字幕稿应进入 Seedance/assembly 字幕链路，而不是进入 keyframe 图像 prompt。

## 2026-04-26 22:59:40 CST - cover page 自动发现目录新旧约定

### Case 31: assemble_episode 未传 `--cover-page-dir` 时容易漏加封面

**现象**

- EP03 首次 assembly 没有传 `--cover-page-dir`，最终视频直接从 SH01 开始，没有片头封面。
- 项目期望 `assemble_episode.py` 能按小说目录自己找到封面；用户指定新约定为 `novel/小说名/asset/characters/cover_pages`。
- 当前仓库实际可用封面仍在旧目录 `novel/ginza_night/assets/cover_page`。

**根因**

- 旧版 `assemble_episode.py` 只在显式传入 `--cover-page-dir` 时启用 cover page。
- 封面资产存在新旧目录命名差异：`asset`/`assets`、`cover_pages`/`cover_page`、是否位于 `characters` 下。

**有效方案**

- `assemble_episode.py` 在未传 `--cover-page-dir` 且未禁用封面时，自动从 `novel/` 下发现 cover page 目录。
- 自动发现优先匹配 `asset/characters/cover_pages` 和 `assets/characters/cover_pages`，再 fallback 到旧目录 `assets/cover_page`。
- 选图仍必须按 episode number 匹配，例如 EP03 选择 `ginza_night_cover_03.png`，不能按最新文件选择。

**系统化改进建议**

- 小说资产迁移后保留兼容搜索，但 QA/assembly report 应明确记录实际 cover path、episode number、封面时长和音频策略。
- 项目初始化或资产检查阶段可提示缺少新规范目录，避免长期依赖旧目录 fallback。

## 2026-04-26 22:44:50 CST - 对白优先与 keyframe 可见说话人契约

### Case 30: 旁白镜头和不可见说话人会导致 Seedance 音频/口型错配

**现象**

- narration-only 镜头容易让 I2V 模型把旁白分配给画面内角色口型。
- 如果对白说话人没有出现在 keyframe 首帧中，I2V 可能让错误角色开口、无口型、或生成随机说话人。
- 双人对白如果 keyframe 只包含其中一人，另一人的声音容易被错误分配给画面内人物。
- 电话/手机声音如果只写“电话里传来”，没有明确谁在听电话，模型容易把远端声音当成画面内角色开口。

**有效方案**

- 剧本规划阶段默认每个 shot 用角色对白推进，尽量不使用旁白；旁白只作为无法自然对白化时的例外。
- onscreen 对白说话人必须出现在 keyframe 首帧：一个人说话就让这个人入镜，两个人说话就让两个人同时入镜。
- 电话/画外声必须结构化标注 `source=phone/offscreen` 和 `listener`；keyframe 必须包含 listener 和听电话动作，远端 caller 不强制入镜。
- keyframe prompt、Seedance prompt、QA 都应读取同一套 dialogue source/listener 字段，不能靠自然语言猜测。

**系统化改进建议**

- `novel2video_plan.py` 的 LLM prompt、ShotPlan normalize、record QA 应把缺对白、narration-only、speaker 不在 character_anchor、电话缺 listener 作为 high severity。
- keyframe static anchor 和 director sanitizer 应在首帧描述里注入“对白可见人物契约”，避免 sanitizer 清掉说话人。
- `generate_keyframes_atlas_i2i.py` 应优先选择 onscreen speakers 和 phone listener 的角色参考图。

## 2026-04-26 22:30:52 CST - Seedance 1.5 I2V 旁白被画面角色说出

### Case 28: narration-only prompt 使用“旁白说”时，模型可能把旁白分配给可见角色口型

**现象**

- EP03 SH01 是 record-only narration：`dialogue_lines=[]`，`narration_lines=["事件次日的下午，龙崎第一次坐到了石川对面。"]`。
- final prompt 已写“不要新增旁白 / 不要省略旁白 / 人物不张口说旁白”，但 Seedance 1.5 I2V 输出中最后一句仍由画面角色说出，而不是画外旁白。
- 该镜头含两个正面可见角色（石川、龙崎），且 prompt 中时间轴写法为“旁白说：……”，容易触发模型寻找可见说话人。

**根因**

- “旁白说”对人类是旁白语义，但对带音频/口型生成的 I2V 模型仍包含“说”的动作暗示。
- 闭嘴约束只在后置禁止段里，离具体时间轴较远，权重弱于时间轴里的“说”。
- Novita/Seedance prompt 长度较长时，后置禁止项更容易被稀释。

**有效方案**

- narration-only 时间轴不再写“旁白说”，改为“画外旁白音轨播放”。
- 在同一条旁白时间轴内绑定可见角色：声音来自画面外独立旁白，不属于画面角色；可见角色全程闭嘴、嘴唇闭合、不做说话口型。
- 对 Novita compact prompt，在开头紧跟“音频角色：只有画外旁白音轨，不是 X/Y 对白；X/Y 全程闭嘴无口型”。
- 禁止段继续保留兜底：旁白只能是画外音/独立旁白音轨，禁止把旁白分配给可见角色。

**系统化改进建议**

- QA 可扫描 narration-only 的 `prompt.final.txt`，如果出现“旁白说”或缺少“画外旁白音轨/闭嘴/无口型”组合，应阻断正式调用。
- 对有可见角色的旁白镜头，音频归属约束应放在时间轴附近或 prompt 前部，不能只依赖末尾 negative-style 禁止项。

### Case 29: Novita `camera_fixed=false` 与 record 固定机位意图不一致

**现象**

- EP03 SH01 的 record / prompt 明确写“固定机位”，但 Novita profile 默认 payload 包含 `camera_fixed=false`。
- 即使 prompt 文字要求固定机位，API 参数层仍可能放开镜头运动，削弱固定构图和道具稳定约束。

**根因**

- `run_seedance_test.py` 之前只读取 `global_settings.camera_fixed`，record 未显式配置时传 `None`，导致 payload 保留 Novita profile 默认值 `false`。
- 镜头运动意图存在于 `shot_execution.camera_plan.movement`，没有映射到 provider payload 开关。

**有效方案**

- 当 `movement` 明确包含“固定机位 / 固定镜头 / 静止机位 / 锁定机位 / fixed camera / static camera / locked camera”时，自动推断 `camera_fixed=true`。
- 如果 `global_settings.camera_fixed` 显式设置为 true/false，则以 record 显式字段为准。

**系统化改进建议**

- Seedance prepare QA 应比较 prompt/record 的镜头运动意图与 provider payload 参数；固定机位但 `camera_fixed=false` 时提示或阻断。

## 2026-04-26 22:09:04 CST - Novita Seedance 1.5 I2V prompt 长度建议

### Case 27: Novita 官方建议 prompt 不超过 500 字符，长结构化提示词可能被稀释

**现象**

- Novita Seedance 1.5 Pro I2V 官方文档对 `prompt` 的说明是：必填字符串，支持中文和英文，建议不超过 500 characters。
- 当前 EP03 Novita prepare 的 `prompt.final.txt` / `payload.preview.json` 约 2600-2800 个字符，远超官方建议长度。
- 实测 Novita 可接受长 prompt 并返回 task id，但生成结果容易出现比例、角色、道具、声音约束执行不稳定。

**根因**

- 管线为 Atlas/Seedance 通用执行生成了完整结构化 prompt，包含角色锁、语言锁、运动契约、质量约束、负向控制项等多段内容。
- Novita Seedance 1.5 I2V 更适合短而聚焦的动作/构图/对白提示；过长 prompt 会让模型注意力分散。

**有效方案**

- Novita provider 应使用压缩版 final prompt：保留首帧事实、主体动作、镜头运动、对白/旁白、关键禁令和比例参数，删除冗长角色档案和重复质量条款。
- 角色身份优先依靠首帧图像和少量差异化锚点，不把完整 `profile.md` 全量塞进 I2V prompt。
- 生成音频对白时，按 Novita 官方建议把说话内容放入双引号中，以提高音频生成效果。

**系统化改进建议**

- 为 Novita 增加 provider-specific prompt compactor，并在 prepare QA 中报告 prompt 字符数；超过 500 字符时提示 manual review，超过更高阈值时阻断正式调用。
- 保持 record 为源头真相，但根据 provider 能力 profile 选择不同长度的执行 prompt。

## 2026-04-26 22:05:31 CST - Novita I2V adaptive ratio 覆盖竖屏意图

### Case 26: Novita payload 使用 `ratio=adaptive` 时，即使 prompt 写竖屏9:16，输出也可能跟随参考图变成 3:4

**现象**

- EP03 最新 Novita director 生成的单镜输出为 `834x1112`，实际比例为 3:4。
- 对应 `payload.preview.json` / `generate_request_response.json` 显式传了 `resolution: 720p` 和 `ratio: adaptive`，没有传 `aspect_ratio: 9:16`。
- prompt 文本中虽然写有“竖屏9:16”，但 API 参数层面的 `adaptive` 仍可能让模型按参考图或内部策略选择非 9:16 输出。

**根因**

- `seedance15_i2v_novita` 内置 profile 的 `default_ratio` 是 `adaptive`，且 Novita 的比例字段名是 `ratio`，不是 Atlas 使用的 `aspect_ratio`。
- 当前 `run_seedance_test.py` 选择比例时只读取 profile 默认值，没有从 record 的竖屏意图或 prompt 文本自动改写为 `9:16`。

**有效方案**

- 需要严格竖屏短剧输出时，Novita profile 或调用参数应显式设置 `ratio: 9:16`，不能只依赖 prompt 文本里的“竖屏9:16”。
- `resolution` 可继续使用 `720p` / `480p` / `1080p` 档位，但它不是精确像素宽高；最终像素仍受 provider 的比例和尺寸策略影响。

**系统化改进建议**

- Seedance/Novita prepare QA 应检查 prompt 中的比例意图与 payload 的 `ratio` 是否一致；如果 prompt 写 9:16 但 payload 是 `adaptive`，应提示或阻断。
- 后续可增加 CLI/profile override，让 record 或项目级竖屏配置显式控制 Novita `ratio`，避免 Atlas `aspect_ratio` 与 Novita `ratio` 字段名差异造成误判。

## 2026-04-26 22:01:21 CST - EP03 record 音频意图未稳定映射到 I2V final prompt

### Case 25: record 只有旁白时 final prompt 没有旁白执行段，且部分旧 prompt 与当前 record 台词状态错位

**现象**

- EP03 SH01 的 record 有 `narration_lines`，但最新 `prompt.final.txt` 只有语言锁定里的“对白、旁白必须普通话”，没有明确旁白文本或旁白时间轴。
- EP03 SH04/SH06 同时有旁白和对白，final prompt 只应保留对白，避免旁白与角色开口抢占音频。
- EP03 SH10/SH11 当前 record 只有旁白，但旧 final prompt 里仍出现对白，说明如果不重跑或不做映射校验，会出现 record/source-of-truth 与执行 prompt 不一致。
- EP03 SH03/SH04/SH08 等镜头有手机入镜，但 prompt 如果只写“手机”而不写谁控制、屏幕朝向谁，容易生成手机换手、屏幕朝向错误或随机界面。

**根因**

- `run_seedance_test.py` 只有 `dialogue_lines` 到“台词与嘴型必须严格对应”的渲染路径，没有 `narration_lines` 到 final prompt 的等价执行路径。
- `subtitle_overlay_hint` 默认关闭，且字幕参考不是旁白执行规则，不能替代明确 narration line。
- 手机作为动态道具缺少统一的归属和屏幕朝向约束，单靠画面主体文字不够稳定。

**有效方案**

- 在 Seedance prompt renderer 中建立 record 音频映射规则：
  - record 只有 `dialogue_lines`：final prompt 必须出现对白时间轴。
  - record 只有 `narration_lines`：final prompt 必须出现旁白时间轴。
  - record 同时有旁白和对白：保留对白，旁白不进入执行 prompt。
- 旁白镜头增加“旁白与画面必须严格对应”段落，并追加“不要新增旁白、不要省略旁白、人物不张口说旁白”的禁止项。
- 有手机入镜时增加“手机道具约束”，明确手机由谁控制、屏幕朝向谁、显示内容必须符合剧情。

**系统化改进建议**

- QA 应比较 record 的 `dialogue_language.dialogue_lines/narration_lines` 与 `prompt.final.txt`，发现 record-only narration 缺失、record-only dialogue 缺失、或 prompt 多出 record 没有的对白时阻断。
- 正式生成前应优先用当前 record 重新 prepare final prompt，避免沿用旧实验目录中的过期 prompt。

## 2026-04-26 21:02:01 CST - 同性别角色参考图撞脸

### Case 24: 角色 profile 的【容貌】过于抽象，导致同性别角色脸型、发型、服饰趋同

**现象**

- 角色参考图生成时，同性别角色容易共享默认美型脸、相似发型和相似服装轮廓。
- 原 `profile.md` 的【容貌】只写“年龄、脸型、发型、服装身份、职业气质和情绪边界必须稳定”，没有给模型足够的可执行差异。

**根因**

- 生图 prompt 虽然要求“稳定”，但缺少脸型骨相、五官特征、体态、服饰颜色材质和“与其他角色的区别”。
- `character_image_gen.py` 使用整个 `profile.md` 生图；如果 `profile.md` 不提供差异锚点，下游只能按性别/年龄/职业套默认模板。

**有效方案**

- `novel2video_plan.py` 生成结构化 `appearance_profile`，并渲染到 `profile.md` 的【容貌】中：
  - 年龄观感、脸型骨相、五官特征、发型、体态/身高感、服饰主锚点、服饰颜色/材质、职业/阶层细节、表情默认值、与其他角色的区别、禁止漂移。
- GinzaNight 已为 9 个长期角色写入差异化容貌模板，重点区分石川/健一/龙崎/山田/阿彻/太郎，以及美咲/彩花/樱子。
- `character_image_gen.py` 生图硬性要求增加：必须遵守【容貌】逐项锚点，同项目角色不得复用相同脸型、发型、体态或服装模板。

**系统化改进建议**

- LLM 全书角色表抽取时必须输出 `appearance_profile`，不能只写 `visual_anchor`。
- 后续可把 `appearance_profile` 提升为 `Character` dataclass 的结构化字段，而不是只在 payload/profile 渲染阶段生成。
- QA 可检查同项目角色是否缺少“与其他角色的区别”或是否多名同性别角色共享同一发型/服饰锚点。

## 2026-04-26 20:46:06 CST - 全书角色表未覆盖后续核心人物

### Case 23: `bible.characters` 只取启发式/硬编码角色，导致全文重要配角缺少角色资产

**现象**

- `ginza_night.md` 是 1-22 章全文，但 `detect_characters()` 的 Ginza 分支只返回石川悠一、田中健一、佐藤美咲、佐藤彩花 4 人。
- 全文核心人物佐藤樱子/小樱/樱子，以及重要嫌疑人/关系人龙崎、山田老先生、阿彻、太郎没有进入 `bible.characters`。
- 下游只会生成这 4 人的 `profile.md`、`info.json`、lock profile 和角色图映射，后续集数遇到缺失角色时容易错误退化为 scene-only、临时人物，或误绑定主角资产。

**根因**

- `bible.characters` 在 `build_project_bible()` 前由 `detect_characters(source.text)` 生成。
- `--backend llm` 只改写 episode fact table 和 shot plan，没有在生成剧本前让 LLM 基于全文补全角色表。
- `Character` 数据结构没有显式 aliases 字段，`小樱/樱子/佐藤樱子` 这类别名如果不写进可解析文本，会影响 record 角色匹配和 `character_image_map`。

**有效方案**

- 在 LLM 剧本规划前增加 `full_character_catalog` 步骤，基于全文输出长期连续性角色表，排除服务员、警员、女招待、经理、护士、邻居、客人、人群等 ephemeral 角色。
- LLM 角色表成功时，用其结果构建 `ProjectBible.characters`，再生成 episode plan、shot plan、角色资产、lock profiles、records。
- LLM 不可用或 dry-run 时保留启发式 fallback；同时将 Ginza 离线启发式补齐为 9 个长期角色。
- 将别名写入视觉锚点并由 `character_aliases()` 解析，使 `小樱`、`樱子`、`佐藤樱子` 映射到同一角色资产。

**系统化改进建议**

- 长篇项目应优先采用“全文角色抽取 -> 去重合并别名 -> 角色分级 -> 单集规划”的顺序，不能只根据当前集或前 8000 字生成角色表。
- `Character` 未来应增加结构化 `aliases`、`role_tier`、`needs_reference_image`、`include_in_lock_profiles` 字段，避免把别名塞进文本锚点。
- QA 应检查全文高频人物是否缺失于 `bible.characters`，尤其是后续 episode outline/hook 中出现的人名。

## 2026-04-26 20:00:00 CST - GinzaNight EP03 SH13 Seedance invalid parameters

### Case 22: 结尾证据钩子镜头被 Atlas/Seedance 判 Invalid parameters

**现象**

- EP03 SH01-SH12 Seedance 均生成成功。
- SH13 连续 10 次失败，状态为 `failed`，错误为 `One or more parameters specified in the request are not valid: Invalid ...`。
- prepare-only 阶段 payload 结构正常，台词模板也已修复，没有明显 JSON 字段错误。

**根因判断**

- 失败镜头同时存在两个风险：
  - `lock_profile_id` 写成 `ISHIKAWA_DETECTIVE`，但角色锁定表里的正式 profile id 是 `ISHIKAWA_DETECTIVE_LOCK_V1`。
  - 镜头里加入“烟灰缸边有熄灭的烟”等非核心物件，增加了 provider 参数/安全判定不确定性。
- 由于 provider 只返回泛化 `Invalid parameters`，无法确认单一根因；本次按“修正 profile id + 删除非核心烟具”一起收敛。

**有效方案**

- 将 SH13 `character_anchor.primary.lock_profile_id` 改为 `ISHIKAWA_DETECTIVE_LOCK_V1`。
- 保留核心剧情事实：石川悠一、1张旧纸质名片、冷白桌灯、山田字样、集尾对白。
- 删除非核心烟具描述，只保留旧名片和抽屉半开。
- 单镜重跑 SH13 成功，再与 SH01-SH12 混合合成。

**系统化改进建议**

- Seedance prepare QA 应把 `character_lock_profile_not_found` 从 manual review 提升为 blocking warning，至少在正式 API 调用前提示。
- 对 provider 返回泛化 invalid 的镜头，优先最小化 prompt：保留 record 核心事实，删除非必要道具、烟酒等可能增加安全/参数歧义的元素。

## 2026-04-26 19:38:00 CST - GinzaNight EP03 说话人短名导致嘴型冲突

### Case 21: dialogue speaker 使用短名，Seedance 台词模板把同一角色当成说话人和非说话人

**现象**

- EP03 SH13 Seedance prepare-only 的 `prompt.final.txt` 同时出现：
  - “石川开口说：下一个名字，山田老先生。”
  - “石川悠一不说话，不张口，只保持沉默反应。”
- 同一个角色被写成开口和闭嘴，实际生成时容易导致无口型、旁白化或嘴型错位。

**根因**

- record 的 `character_anchor.primary.name` 是“石川悠一”，但 `dialogue_lines[].speaker` 写成短名“石川”。
- `run_seedance_test.py` 的 dialogue timeline 会用 speaker 名称与角色名匹配；短名未归一化时，正式角色名被误判为“其他非说话人”。

**有效方案**

- 将 `dialogue_lines[].speaker` 改为与角色锁定完全一致的正式名“石川悠一”。
- 重新 prepare 后，台词块变为：
  - “石川悠一开口说：下一个名字，山田老先生。”
  - 不再出现同角色闭嘴约束。

**系统化改进建议**

- dialogue timeline 生成前应按角色别名表归一化 speaker，比如“石川” -> “石川悠一”。
- QA 应检查同一台词块内是否出现“X开口说”和“X不说话/保持闭嘴”的矛盾约束。

## 2026-04-26 19:29:56 CST - EP02 Seedance 台词节奏与 QA 估算不一致

### Case 20: language plan 保守字速导致已压缩到 12 秒内的 Seedance prompt 被 QA 误判早切

**现象**

- EP02 `SH11`、`SH12` 的 Seedance `prompt.final.txt` 已把台词段落压缩到 11.5 秒内，且输出 clip 为 12.05 秒。
- `qa_episode_sync.py` 使用默认 `chars_per_sec=4.2` 的 language plan 估算台词总长，认为 `SH11` 需要 13.46 秒、`SH12` 需要 20.15 秒，因此报 `early_scene_cut`。

**根因**

- `build_episode_language_plan.py` 的默认字速适合较慢对白，但 Seedance renderer 会在 12 秒模型上限内压缩多句对白的执行 timing。
- QA 对比的是 language plan 的估算时间，而不是实际写入 `prompt.final.txt` 的台词时间段。

**有效方案**

- 对 Seedance 已压缩对白的 QA，重建一份与执行 prompt 节奏一致的 language plan，例如提高 `--chars-per-sec` 到可容纳最终 timing 的范围。
- 长远应让 QA 优先读取 `prompt.final.txt` / `payload.preview.json` 里的实际台词时间段，而不是只依赖 language plan 的保守估算。

## 2026-04-26 19:26:07 CST - EP02 assemble/QA 路径解析与 start-only I2V 假阳性

### Case 19: 实验目录名含 SH01_SH13 时，assemble/QA 把所有 clip 误识别成 SH01

**现象**

- EP02 全 13 段 Seedance clip 已成功生成并 assemble，但 `qa_episode_sync.py` 报 `character_scene_consistency_risk`。
- `assembly_report.json` 中每个 clip 的 `shot_id` 都变成 `SH01`，即使实际路径分别位于 `SH02/output.mp4`、`SH03/output.mp4` 等目录下。
- 同时 start-only I2V 的 `image_input_map` 只有 `image`，没有 `last_image`，QA 把缺少 `last_image` 当成缺少 keyframe。

**根因**

- `assemble_episode.py` 和 `qa_episode_sync.py` 的 `extract_shot_id()` 对整条路径做 `re.search("SH\\d+")`，实验目录名 `..._sh01_sh13` 先于 clip 父目录命中。
- QA 的 frame consistency 检查没有区分必需的首帧 `image` 和可选的尾帧 `last_image`。

**有效方案**

- shot id 解析应优先从路径末端的父目录精确匹配 `SHxx`，最后才 fallback 到文件名。
- start-only I2V map 中只要 `image` 存在，就不应作为缺失 keyframe 失败；`last_image` 缺失只记录计数，用于边界共享判断，不作为失败项。

## 2026-04-26 19:25:00 CST - GinzaNight EP03 keyframe 静态化覆盖显式首帧意图

### Case 18: director 静态首帧 sanitizer 忽略 `keyframe_static_anchor`，导致人物和道具数量漂移

**现象**

- EP03 SH04 的 record 明确是田中健一进入警视厅调查室角落，但 prepare-only keyframe prompt 里出现“人物锁定:无人物”，并把插入记忆里的丝巾当成首帧固定道具。
- EP03 SH06 的 record 动作写“2只玻璃杯”，但 prompt 中同时出现“1只玻璃酒杯”和“2只玻璃杯”的冲突。
- EP03 SH13 手动补了石川把旧名片放在桌灯下，但 prepare-only 后角色筛选仍显示“人物锁定:无人物”。

**根因**

- `run_novel_video_director.py` 的 `prepare_keyframe_static_records()` 会重新 sanitize `shot_execution` 和 `prompt_render.shot_positive_core`。
- sanitizer 没有优先使用 record 内显式提供的 `keyframe_static_anchor`，导致手工或上游已经写好的“首帧静态真意”只进入 prompt 尾部，未进入角色筛选上下文。
- 道具规则中旧的 `continuity_rules` / `scene_motion_contract.static_props` 没有同步更新，造成数量冲突继续被下游拼进 prompt。

**有效方案**

- 修改 `prepare_keyframe_static_records()`：
  - 如果 record 含 `keyframe_static_anchor.scene_name / movement / framing_focus / action_intent / positive_core`，优先用这些字段生成静态首帧 record。
  - 只有缺字段时才回落到自动 sanitizer。
- 对本集受影响 record 同步修正：
  - SH04 首帧为田中健一 + 1条领带，不把丝巾带入首帧。
  - SH06 玻璃杯数量固定为2只。
  - SH13 石川作为可见动作主体，旧名片数量固定为1张。

**系统化改进建议**

- keyframe prepare QA 应检查 `character_anchor.primary` 与最终 keyframe prompt 的“人物锁定”是否矛盾。
- 道具 QA 应跨 `action_intent`、`scene_motion_contract.static_props`、`continuity_rules.prop_continuity`、`prompt_render.shot_positive_core` 检查固定数量是否一致。

## 2026-04-26 19:14:37 CST - GinzaNight EP03 集尾钩子被规划成旁白空镜

### Case 17: 最后一镜只有道具特写和旁白，未由角色对白完成悬念

**现象**

- EP03 LLM 规划成功生成 13 个具体镜头，但 QA 在 SH13 报 blocking findings：
  - `ending_hook_missing_dialogue`
  - `ending_hook_narration_only`
  - `ending_hook_not_marked_as_episode_hook`
- SH13 实际镜头是警视厅桌边旧名片特写，旁白说明“下一张名字，指向山田老先生”，没有角色对白。

**根因**

- LLM 为了突出“旧名片”证据钩子，把最后一镜处理成 scene-only 道具 reveal。
- 但当前短剧执行规则要求集尾钩子由角色对白完成，不能只靠旁白或字幕，否则 Seedance 音频和字幕层容易变成小说朗读腔。

**有效方案**

- 保留 record 的核心事实：1 张旧纸质名片、警视厅调查室桌边、冷白桌灯、模糊山田字样、不拍山田本人。
- 将 SH13 从 `SCENE_ONLY` 改为石川可见手部/半侧身参与的证据特写。
- 在 `action_intent` 与 `shot_positive_core` 显式写入：
  - “集尾钩子必须由角色对白完成，保留完整台词，不使用旁白替代。”
- 将旁白改为石川低声对白：
  - “下一个名字，山田老先生。”

**系统化改进建议**

- LLM shot normalization 对最后一镜应强制检查：如果 hook 镜头只有 `narration_lines` 或 `SCENE_ONLY`，但存在可见侦查角色动作，应自动转为角色对白钩子。
- ending hook QA 可继续允许道具特写，但必须要求至少一条角色对白或明确的 offscreen 角色对白来源。

## 2026-04-26 18:23:50 CST - GinzaNight EP02 静态首帧被生成成三格分镜

### Case 16: keyframe prompt 带入视频时间序列/闪回语汇，图像模型输出拼贴分镜

**现象**

- EP02 LLM 版 SH12 的 OpenAI keyframe 输出不是单一竖屏首帧，而是一张纵向三格图：
  - 上格为警视厅调查室双人中景。
  - 中格为手部/手背插入特写。
  - 下格又回到调查室双人中景。
- 这类输出看似像视频分镜或 contact sheet，不能作为 Seedance 的单一首帧输入。

**根因**

- record 和 keyframe prompt 把视频动作过程直接塞进“镜头起始帧”：
  - `movement` 含“轻微手持与插入闪回”。
  - `action_intent` 含“警员带健一入座”“石川问关系”“听到龙崎名字时”“短暂闪回彩花指尖触他手背”“美咲回答后避开目光”等多个时序动作。
  - `shot_positive_core` 含“短暂插入彩花手指轻触健一手背的回忆近景”。
- 静态图模型为了同时满足主镜头和插入闪回，倾向把多个时间点画成同一张拼贴/三格分镜。

**有效方案**

- keyframe prompt 必须只描述单一瞬间，不能包含“插入闪回”“短暂插入”“回忆近景”“随后/听到/回答后”等视频剪辑或时间序列语汇。
- 对 start keyframe，保留第一帧可见状态：
  - 调查室双人中景。
  - 健一坐定、领带可见。
  - 美咲坐在对面、笔录静置。
- 把闪回、问答、手指僵住、避开目光等内容留给 Seedance 视频 prompt，不进入首帧静态图 prompt。
- 在 keyframe prompt 加硬约束：
  - “只生成一张连续完整画面，不要拼贴、不要多格漫画、不要分屏、不要 contact sheet、不要插入镜头。”

**系统化改进建议**

- `generate_keyframes_atlas_i2i.py` 应增加 keyframe 专用 sanitizer：
  - 从 `movement`、`action_intent`、`shot_positive_core` 中剔除或改写闪回/插入镜头/多动作时序词。
  - 自动补入 single-frame / no-collage 约束。
- QA 应检查 keyframe prompt 是否含“闪回”“插入”“回忆近景”“随后”“同时表现多个阶段”等词，命中时提示需拆成首帧状态和视频动作两层。

## 2026-04-26 17:38:28 CST - GinzaNight EP02 重复镜头规划修复

### Case 12: 非第1集被 heuristic 13镜头模板泛化，导致整集重复

**现象**

- GinzaNight EP02 生成后，SH01-SH12 大量使用“第2集核心场景”“人物目标亮相”“关系压力入场”“情绪临界点”等泛化表达。
- 下游 `run_novel_video_director.py` 和 `run_seedance_test.py` 按 record 执行后，画面变成同一组人物、同一类场景、相似动作的重复。
- 修复短名角色匹配后，SH01-SH12 都正确锁到健一和彩花，但因为上游镜头本身泛化，视觉重复更明显。

**根因**

- `novel2video_plan.py` 的非特例集数 fallback 使用通用 `intents` 模板，没有从本集小说原文抽取具体剧情事实。
- EP01 连续性、EP02 原文、输出格式示例没有被共同输入给高质量模型生成本集剧本和镜头脚本。
- QA 没有拦截“第N集核心场景”这类看似可执行、实际不可拍的占位镜头。

**有效方案**

- 在 `novel2video_plan.py --backend llm` 中加入 OpenAI 两步规划：
  1. 从本集小说原文抽取剧情事实表、场景清单、道具清单、人物出场建议和重复风险。
  2. 基于事实表、EP01 连续性、EP02 原文、角色资产和格式示例，生成严格 13 个可执行 `ShotPlan`。
- 生成镜头时强制：
  - 每个 SH 必须有具体地点、人物、动作、画面重点和原文依据。
  - 相邻镜头不能复用完全相同的“地点 + 人物 + 动作”组合。
  - 禁止使用“人物目标亮相”“关系压力入场”“第2集核心场景”等泛化表达。
- 在 plan QA 中增加 `generic_shot_placeholder` 检查，防止旧模板静默进入 director/Seedance。

**系统化改进建议**

- 后续应把 LLM 规划产物中的 `fact_trace` 持久化为正式 artifact，方便人工审片时追踪每个镜头的原文依据。
- 对所有非特例 episode，默认使用小说事实抽取驱动的 shot planning；heuristic 仅作为离线 fallback 或 request preview。

## 2026-04-26 17:54:12 CST - GinzaNight EP02 LLM 规划 QA 误报

### Case 13: 集尾“记录对不上/不一致”钩子未被 ending hook QA 识别

**现象**

- EP02 LLM 规划成功生成 13 个具体镜头，但 `plan_qa_report.json` 仍有 3 个 medium findings，全部集中在 SH13：
  - `ending_dialogue_lacks_action_or_mystery_hook`
  - `ending_prompt_lacks_dialogue_hook_instruction`
  - `ending_hook_not_marked_as_episode_hook`
- SH13 实际对白已经包含“田中先生说没待太久，可酒店记录对不上”，剧情上属于有效案件钩子。

**根因**

- ending hook QA 的关键词主要覆盖“小樱/真相/秘密/明天”等通用追问词，没有覆盖刑侦类钩子的“记录”“对不上”“不一致”“监控”“嫌疑”等词。
- LLM 生成的最后一镜虽然有角色对白，但 `positive_core` 和 `action_intent` 未显式写入“集尾钩子/角色对白完成”的执行提示，导致 QA 认为下游可能把它当普通资料镜头。

**有效方案**

- 扩展 `ENDING_HOOK_KEYWORDS`，加入“记录”“对不上”“不一致”“嫌疑”“监控”“排除”。
- 在 LLM shot normalization 阶段，如果最后一镜有 dialogue，自动给 `action_intent` 和 `positive_core` 补入：
  - “集尾钩子必须由角色对白完成，保留完整台词，不使用旁白替代”

**系统化改进建议**

- ending hook QA 应按类型区分：行动钩子、身份钩子、案件证据钩子、关系钩子，而不是只依赖一组通用关键词。

## 2026-04-26 18:03:16 CST - GinzaNight EP02 人物锚点过度继承

### Case 14: “被对白/资料提到的人”被错误当成画面人物锁定

**现象**

- EP02 LLM 版 records 具体度已经提升，但 director prepare-only 显示部分镜头传入了过多人物参考图：
  - SH06 美咲接电话镜头错误带入彩花参考图。
  - SH07 美咲门外偷听镜头错误带入石川和彩花参考图。
  - SH12 调查室镜头因为闪回文字错误带入彩花参考图。
  - SH13 资料桌特写因为“健一笔录/健一名字/美咲离去”等文字错误带入健一、美咲参考图。

**根因**

- `resolve_shot_characters()` 早期用 `action_intent`、`positive_core`、dialogue speaker/text 混合判断角色。
- 这种逻辑无法区分“画面中可见的人”和“电话、对白、资料、照片、笔录、记录中被提到的人”。
- 首帧生成会把 character anchors 当成 identity references，导致不该出现的人进入构图。

**有效方案**

- 角色锚点判断先使用 `framing_focus + scene_name` 中的视觉人物。
- 在人物匹配前剔除非视觉提及片段，例如：
  - 电话声、声音、传出、提到、说、回答、问、对白、台词
  - 笔录、记录、名字、照片、合影、屏幕文字、表格
- 只有视觉文本没有命中时，才 fallback 到 `positive_core`，最后再考虑 `action_intent`。

**系统化改进建议**

- LLM shot schema 应增加 `visible_characters` 字段，后续 record 直接用该字段锁定人物。
- `dialogue` 应允许标记 `offscreen=true` 或 `source=phone/room/voiceover`，避免电话和隔门声音误触发人物锁定。

## 2026-04-26 18:17:55 CST - GinzaNight EP02 OpenAI 首帧安全拦截

### Case 15: 前夜亲密托付镜头触发 OpenAI image safety

**现象**

- EP02 LLM 版 director 正式生成首帧时，SH03 和 SH04 被 OpenAI image safety 拒绝，返回 `safety_violations=[sexual]`。
- 两个镜头都属于前夜套房里彩花与健一的“领带/托付小樱”段落。

**根因**

- LLM 生成的视觉动作包含“贴近胸口”“贴近耳侧”“环上腰侧”“呼吸”等身体接触或亲密语汇。
- 虽然剧情意图是悬疑操控和承诺压力，但图像模型容易把这些词判断为性暗示。

**有效方案**

- 在 `novel2video_plan.py` 的 LLM shot normalization 阶段加入安全改写：
  - 将贴近胸口、耳侧、腰侧等表达改成“保持克制距离”“抬眼低声说话”“手停在身侧”。
  - 保留领带、小樱承诺、操控感等剧情事实。
  - 自动追加“两人全程衣着完整，保持克制社交距离，不出现裸露或性暗示”。

**系统化改进建议**

- 对所有亲密关系镜头建立“悬疑亲密安全词表”，用手部道具、距离、眼神和资料线索表达关系，不使用身体贴近、裸露、呼吸等高风险词。

## 2026-04-26 15:01:31 CST - GinzaNight EP01 调试总结

### Case 1: record 剧本和 run_seedance prompt 发生明显漂移

**现象**

- `novel2video_plan.py` 生成的 record 里，镜头剧本/镜头意图相对清楚。
- 到 `run_seedance_test.py` 生成最终 prompt 时，部分字段被 keyframe prompt metadata 补写或覆盖，导致视频 prompt 和原始 record 差异很大。
- 结果是 Seedance 实际执行的镜头可能偏离剧本本意。

**根因**

- 下游合并 keyframe metadata 时，部分字段优先级不清晰。
- keyframe prompt 是为了生成首帧服务的，它可能更偏视觉补全；但 Seedance 视频 prompt 应该以 record 为主。
- 当 keyframe metadata 与 record 存在冲突时，如果没有显式记录冲突，就很难追踪是哪一层改写了语义。

**无效或不充分方案**

- 只人工检查最终 prompt：能发现问题，但不能防止下一轮再次发生。
- 只改某个镜头的 prompt 文案：局部有效，但合并策略仍可能让其它镜头漂移。

**有效方案**

- 在 `run_seedance_test.py` 中采用 record-first 合并策略：
  - record 标量字段优先。
  - keyframe metadata 只做补充，不静默覆盖 record。
  - 记录 `keyframe_conflicts` 和 `keyframe_supplements`，方便定位漂移来源。

**系统化改进建议**

- 把 prompt merge policy 固化成单独的 schema 或测试。
- 对核心字段增加冲突报告：
  - `shot_type`
  - `movement`
  - `framing_focus`
  - `action_intent`
  - `emotion_intent`
  - `scene_name`
- 如果 keyframe 与 record 冲突，应默认保留 record，并在报告里写明。

### Case 2: 无人物/路人镜头错误继承主角 character_anchor

**现象**

- SH01 是酒店套房空镜，但首帧或视频 prompt 会错误带入系列主角。
- SH02 应该是服务员，但如果 record 默认把 primary 设置成第一位系列角色，后续首帧和 Seedance prompt 就会锁错人。

**根因**

- `novel2video_plan.py` 早期 record 生成逻辑倾向于把系列角色默认写入每个镜头。
- 下游首帧和 Seedance 都会读取 `character_anchor.primary` / `secondary`，于是默认角色被放大为硬约束。
- 对临时角色（服务员、警员、背景人群）和空镜没有统一的表达方式。

**无效或不充分方案**

- 手动删除 SH01/SH02 record 里的主角锚点：容易被重新跑 plan 覆盖。
- 只在首帧 prompt 里说“无人物”：Seedance 阶段仍可能从 record 里读到旧 character_anchor。

**有效方案**

- 在 `novel2video_plan.py` 中按镜头文本解析角色：
  - 明确出现系列角色时才锁系列角色。
  - 出现服务员时使用 `EXTRA_WAITER`。
  - 出现警员时使用 `EXTRA_POLICE`。
  - 出现群体/路人时使用 `EXTRA_CROWD`。
  - 没有明确人物时使用 `SCENE_ONLY`。
- 在 `generate_keyframes_atlas_i2i.py` 和 `run_seedance_test.py` 中增加运行时过滤，兼容旧 record。

**系统化改进建议**

- `character_anchor` 应该从“全局角色默认注入”改成“镜头显式角色选择”。
- 对 `SCENE_ONLY` 和 ephemeral characters 建立标准 schema。
- QA 报告中增加检查：镜头文本未提及主角时，不应出现主角 lock profile。

### Case 3: SH02 服务员镜头的首帧角色信息如何处理

**现象**

- SH02 的视觉主体是服务员，但服务员不是主角，也没有角色参考图。
- 首帧生成会读取 `character_anchor.primary` / `secondary`，如果没有特殊处理，可能锁成主角，或者因为没有参考图失败。

**根因**

- 临时角色没有 lock profile 和参考图。
- 但镜头又需要一个清晰的人物语义：服务员、制服、惊恐、按下紧急按钮。

**无效或不充分方案**

- 给服务员强行绑定某个主角参考图：会让身份和外观混乱。
- 只写“服务员”但仍传主角参考图：模型可能混合主角脸和服务员身份。

**有效方案**

- 将 SH02 识别为 `EXTRA_WAITER`：
  - `lock_prompt_enabled=false`
  - 不强制人物身份参考图
  - prompt 中明确写“银座高级酒店服务员，整洁制服，普通工作人员气质，反应真实不过度戏剧化”
- 首帧生成时，如果当前角色没有身份参考，输入图只作为写实质感、光影和服装材质参考，人物身份以文字为准。

**系统化改进建议**

- 临时角色应有统一的 `ephemeral_character` catalog。
- 对无参考图角色，prompt 应自动生成“身份以文字为准，参考图只作质感参考”的说明。

### Case 4: 现代银座项目被错误套用古代/现代禁用词

**现象**

- 部分通用提示词里出现“不要生成现代元素”这类约束。
- 对 GinzaNight 这种现代日本都市悬疑项目来说，这是反向错误。

**根因**

- 负面 prompt 或时代约束原本更适合古代/穿越项目。
- 下游脚本没有根据项目时代自动区分现代/古代。

**无效或不充分方案**

- 手工在某个 prompt 中删除“不要生成现代元素”：下一次生成可能再次出现。

**有效方案**

- 在首帧生成脚本中根据 record 文本推断时代：
  - 现代关键词：银座、东京、酒店、都市、刑警、警车、公司。
  - 古代关键词：古代、西汉、长安、穿越、破庙、布衣。
- 现代项目使用约束：“不要生成古装、古代建筑、年代错置道具或非现代日本都市环境。”

**系统化改进建议**

- 项目 bible 中增加显式 `era_profile` / `locale_profile`。
- 不要只靠关键词推断时代；关键词推断可以作为 fallback。

### Case 5: OpenAI 首帧生成遇到 SCENE_ONLY 空镜

**现象**

- SH01 是空镜，`character_anchor` 为 `SCENE_ONLY`。
- `run_novel_video_director.py` 的 character image map 预检仍要求 `SCENE_ONLY` / `场景主体` 有参考图。
- OpenAI image edit 接口实际需要一张输入图，场景空镜没有人物图时会失败。

**根因**

- 预检逻辑把所有 character_anchor 节点都当成人物参考需求。
- 但 `SCENE_ONLY` 是场景语义，不应该要求人物图。
- OpenAI image edit 又不是纯 text-to-image，需要输入参考图。

**无效或不充分方案**

- 给 `SCENE_ONLY` 加人物参考图：会污染空镜。
- 直接跳过首帧生成：后续 Seedance 缺少图像输入。

**有效方案**

- `run_novel_video_director.py` 预检跳过：
  - `lock_prompt_enabled=false`
  - `lock_profile_id` 为空
  - 这种场景/临时节点不要求 character image map。
- 给 director 增加 `--default-image`，让空镜可以用场景参考图进入 OpenAI image edit。

**系统化改进建议**

- 区分 reference image 类型：
  - identity reference
  - scene reference
  - style/material reference
- keyframe manifest 中记录 reference purpose，避免人物身份和场景质感混用。

### Case 6: SH01 酒杯从地面冒出 / 额外杯子生成

**现象**

- SH01 开头是酒店套房空镜。
- 视频后段出现两个玻璃杯从地面或阴影处冒出的问题。
- 加入“禁止新增、消失、漂移、滑动、弹出、从地面冒出；酒杯数量固定，不生成额外杯子”等约束后，问题仍然存在。

**根因**

- prompt 内部仍有冲突：
  - 原始 core 写“床边散落酒杯与丝巾”。
  - 新增约束写“酒杯数量固定为一只”。
  - “散落酒杯”天然暗示多个杯子或杂物，强于后面的限制。
- 首帧虽然有一只倒杯，但位置在画面底部边缘，且处于阴影/地毯纹理区域。
- Seedance 当前 profile 没有真正独立 negative prompt 字段，负面词被合并进正向约束，约束力有限。
- “缓慢推进”会触发模型对前景地毯和玻璃物体的重新建模，边缘物体最容易被增生或重绘。

**无效或不充分方案**

- 只追加负面词：
  - `appearing objects`
  - `objects popping into existence`
  - `cups emerging from floor`
  - `duplicate cups`
  - `extra cups`
  这些有帮助，但在没有真正 negative channel 的模型 profile 下，不能完全阻止。
- 只写“视频中不要再增加道具”：如果正向 core 仍写“散落酒杯”，模型仍可能按“散落”补物体。
- 只剪掉尾巴：可临时避开已生成视频的后段问题，但不是根治。

**有效或更接近有效的方案**

- 必须先消除正向 prompt 冲突：
  - 不再使用“散落酒杯”。
  - 改成“床边地毯上只有一只倒下的玻璃杯和一条丝巾，没有其他杯子或玻璃器皿。”
- 首帧构图要主动配合：
  - 杯子不要贴近画面底边。
  - 杯子要完整可见，轮廓清晰。
  - 避免放在强阴影、复杂地毯纹理或反光高光里。
  - 如果杯子不是剧情必要，宁可不放杯子，只保留丝巾。
- 对镜头运动降风险：
  - 从“缓慢推进”改成“固定机位”或“极轻微推镜”。
  - 明确“房间内所有道具完全静止，镜头只做极轻微摄影机运动”。

**系统化改进建议**

- 建立静态道具风险检测：
  - 一旦出现“散落 + 可数道具”，自动改写为数量明确的描述。
  - 如 `散落酒杯` 应改为 `一只倒下的玻璃杯` 或 `若干固定可见的杯子，数量为 N`。
- 对静态道具生成 `prop_lock`：
  - `object_name`
  - `count`
  - `position`
  - `visibility`
  - `motion_policy=static`
- 对高风险道具镜头默认使用固定机位。
- 如果模型 profile 不支持 negative prompt，应在 profile 报告中标注“负面约束弱”，并优先通过正向改写和首帧构图解决。

### Case 7: 重新拼接时新旧片段尺寸不一致

**现象**

- 新生成 SH01/SH02 是 `560x752`。
- 旧片段里有 `496x864`。
- 2026-04-26 15:30:27 CST 复查 GinzaNight EP01 all13 时，当前片段仍混用两组尺寸：
  - `560x752`: SH01, SH02, SH04, SH06, SH08, SH09
  - `496x864`: SH03, SH05, SH07, SH10, SH11, SH12, SH13
- 原拼接脚本使用 concat filter，要求所有输入尺寸一致，导致拼接失败。

**根因**

- 不同批次或不同 provider 生成的视频分辨率/画幅不完全一致。
- 即使 payload 写了 `ratio=9:16` / `resolution=480p`，具体 provider 仍可能按输入首帧尺寸、模型内部 bucket、或旧 payload 字段名差异输出不同像素尺寸。
- 早期片段的 payload 使用过 `aspect_ratio` 字段，后续片段使用 `ratio` 字段；不同批次的兼容路径可能不同。
- 首帧来源不同也会放大差异：OpenAI 首帧、Atlas 首帧、旧远程 URL 首帧的原图尺寸不一致，I2V 输出可能跟随或近似跟随输入图 bucket。
- 拼接脚本没有统一 scale/pad。

**无效或不充分方案**

- 直接用原 concat 清单拼接：会因尺寸不一致失败。
- 只用 `scale=decrease + pad` 做 contain 归一化：可以避免 concat 尺寸错误，也能保留完整画面，但当 `560x752` 片段放进 `496x864` 目标竖屏时，会在顶部和底部产生黑边，不适合需要全屏输出的交付文件。

**有效方案**

- 需要完整保留画面时，拼接前用 contain 模式统一规范化到 `496x864`：
  - `scale=496:864:force_original_aspect_ratio=decrease`
  - `pad=496:864:(ow-iw)/2:(oh-ih)/2:black`
  - `setsar=1`
- 需要全屏无黑边时，拼接前用 cover 模式统一规范化到 `496x864`：
  - `scale=496:864:force_original_aspect_ratio=increase`
  - `crop=496:864:(iw-ow)/2:(ih-oh)/2`
  - `setsar=1`
- cover 的代价是会裁掉源画面左右或上下溢出的部分；对于 `560x752` 转 `496x864`，主要是左右裁切。只有在“保留完整画面”比“全屏无黑边”更重要时，才显式使用 contain。
- 音频统一重采样到 `24000Hz` 后 concat。
- 2026-04-26 15:41:49 CST 已将 `assemble_episode.py` 默认行为改为：
  - `--audio-policy keep`
  - 默认归一化到 `496x864`
  - assembly report 记录每段源尺寸与输出尺寸。
- 2026-04-26 15:52:22 CST 已将 `assemble_episode.py` 增加 `--fit-mode cover|contain`，默认 `cover`，用于交付全屏无黑边视频；如需保留完整源画面，可手动指定 `--fit-mode contain`。
- 2026-04-26 15:41:49 CST 已将 `novel2video_plan.py` 生成的 Atlas Seedance profile `ratio_field` 从 `ratio` 改为 `aspect_ratio`，避免同一 provider profile 的字段名不一致。

**系统化改进建议**

- `assemble_episode.py` 增加统一尺寸参数，默认对所有片段做 cover 归一化，避免交付视频出现黑边。
- 保留 contain 模式作为调试/审片选项，用于检查被 cover 裁掉的画面内容。
- assembly report 记录每个源片段原始尺寸和最终输出尺寸。
- 在 `run_seedance_test.py` 写入 payload 前统一 provider 字段名，避免同一 profile 不同批次出现 `aspect_ratio` / `ratio` 混用。
- 在 keyframe 阶段将首帧统一裁切/填充到目标竖屏画布，例如 `496x864` 或项目标准尺寸，再送入 I2V。
- 在每个 shot 生成后自动 `ffprobe`，把实际输出宽高写入 shot manifest；如果不符合项目目标尺寸，立即生成 normalized clip 供拼接使用。

### Case 9: 用场景运动契约约束静态场景和可动主体

**现象**

- SH01 酒杯问题暴露出一个更通用的 prompt 设计风险：场景描述里如果混入“散落、浮现、露出、滑落”等隐含动作或生成感的词，视频模型会把它理解成几秒内要发生的视觉变化。
- 即使追加负面词，若正向 prompt 仍保留“散落酒杯”等模糊语义，模型仍可能补画、重绘或新增道具。
- 场景建立镜头中，本来应该静止的道具会被模型当作可运动/可生成对象。

**根因**

- 原始 record 只有 scene / prop / camera 字段，没有明确区分：
  - 静态场景状态
  - 可动主体
  - 人物直接操纵的可动道具
  - 禁止自行运动的场景道具
- “场景”和“动作”在同一段自然语言 prompt 里混写，导致模型不知道哪些元素是背景状态，哪些元素允许变化。
- 对不支持 true negative prompt 的 Seedance profile，单纯添加负面词会被降级并合并到正向约束里，约束力有限。

**无效或不充分方案**

- 只追加负面 prompt，例如 `appearing objects`、`duplicate cups`、`cups emerging from floor`。
- 只写“视频中不要再增加道具”，但不消除正向 prompt 里的“散落酒杯”等冲突描述。
- 只剪掉已有视频的问题尾巴：可以临时规避，但下一次重跑仍可能复现。

**有效方案**

- 在 `novel2video_plan.py` 中生成 `scene_motion_contract`，把每个镜头的运动许可显式结构化：
  - `scene_mode`
  - `description_policy`
  - `camera_motion_allowed`
  - `active_subjects`
  - `static_props`
  - `manipulated_props`
  - `allowed_motion`
  - `forbidden_scene_motion`
- 将静态场景正向描述改成状态句。例如 SH01 从“床边散落酒杯与丝巾”改为：
  - “床边地毯上只有一只倒放的玻璃杯和一条静止的丝巾，没有其他杯子或玻璃器皿。”
- 在 `generate_keyframes_atlas_i2i.py` 中读取 `scene_motion_contract`，首帧 prompt 明确：
  - 场景只写静态状态
  - 能动的只允许人物和人物直接操纵的物体
  - 静态场景建立帧不要暗示任何场内物体即将移动、出现或消失
- 在 `run_seedance_test.py` 中读取同一个契约，视频 prompt 增加“场景运动契约”块。
- 对 `static_establishing` 镜头，将“缓慢推进”等高风险运动降级为：
  - “固定机位或极轻微稳定推镜，不改变道具相对位置。”

**系统化改进建议**

- 将“场景是状态，人物才是动作；道具只有被人物操纵时才允许运动”作为全链路默认 prompt 语法。
- 对所有 scene-only establishing shots 默认生成 `static_establishing` 契约。
- 对人物镜头默认生成 `character_action_in_static_scene` 契约，并列出 `manipulated_props`。
- QA 中增加检查：
  - 静态镜头是否仍含“散落 + 可数道具”等模糊语义。
  - 静态道具是否有数量、位置、首帧可见性、motion policy。
  - Seedance prompt 是否包含 `scene_motion_contract` 展开的文本。

### Case 8: 拼接时不要 mute

**现象**

- 用户明确要求最终拼接不要 mute。
- 脚本默认 audio policy 可能是 mute。

**根因**

- 自动拼接时为了规避模型音频错配，常默认静音。
- 但这次需要保留每段视频自带音频。

**无效或不充分方案**

- 只输出视频流，不检查 audio stream：可能误以为带音频。

**有效方案**

- 拼接时保留每段音频。
- 统一重采样到 `24000Hz`。
- 拼完后用 `ffprobe` 验证最终文件存在 audio stream。

**系统化改进建议**

- assembly CLI 默认明确输出 audio policy。
- 每次输出最终成片后自动检查：
  - video stream
  - audio stream
  - duration
  - resolution

## 追加模板

### 2026-04-26 15:53:22 CST - Case 10: 角色短名未命中导致整集误判为 SCENE_ONLY

**现象**

- GinzaNight EP02 重跑后，SH01-SH12 的 `character_anchor.primary` 都变成 `SCENE_ONLY`。
- `run_novel_video_director.py` 使用场景默认图后，生成到 SH06 仍没有人物，start keyframe 全是空场景。

**根因**

- EP02 自动镜头文本使用“健一”“彩花”等短名。
- `novel2video_plan.py` 旧逻辑只匹配完整角色名（如“田中健一”“佐藤彩花”）或 character_id，未把短名映射到同一套 character asset / lock profile。

**无效或不充分方案**

- 给 SCENE_ONLY 传 `--default-image` 只能解决 OpenAI image edit 的输入图问题，但会把应有人物的镜头继续当空镜生成。
- 手动给 director 换人物参考图如果 record 仍是 SCENE_ONLY，会掩盖上游角色锚点错误。

**有效方案**

- 在 `novel2video_plan.py`、`generate_keyframes_atlas_i2i.py` 和 `run_seedance_test.py` 中为角色名增加短名 alias，例如“田中健一”同时匹配“健一”，“佐藤彩花”同时匹配“彩花”。
- 重新生成 EP02 record 后再跑 director，确保 keyframe 阶段使用 `novel/ginza_night/assets/characters/` 下与 EP01 相同的 character asset。

**系统化改进建议**

- QA 增加检查：episode goal / conflict 明确出现主角色短名时，record 不应批量生成 `SCENE_ONLY`。
- character asset map 应支持 canonical name、short name、character_id、lock_profile_id 四类别名。

### 2026-04-26 16:54:07 CST - Case 11: cover_page 不能按最新文件选图

**现象**

- GinzaNight EP01 片头封面误用了 `cover_page` 目录中最新生成的 `ginza_night_cover_20.png`。
- 第一集成片开头显示了第 20 集封面数字。

**根因**

- 包装阶段把“最新生成的 cover_page 图片”误当成“当前集封面”。
- 但 `cover_page` 文件名里的编号代表集数，必须与当前 episode 编号对应。

**无效或不充分方案**

- 只按文件修改时间选择 cover_page：多集批量生成或后补封面时会选错。
- 只人工检查封面画面：容易漏掉片头数字和 episode 不一致的问题。

**有效方案**

- 拼接 EP01 片头时显式选择 `ginza_night_cover_01.png`。
- 片头封面持续 1 秒，封面段静音，后续正片音频保留。

**系统化改进建议**

- assembly / packaging 脚本增加 episode number 参数，并按 `cover_page/*_{episode:02d}.png` 选择封面。
- 输出前自动校验 cover_page 文件编号与 episode 编号一致。

### 2026-04-28 16:00:29 CST - Case 12: OpenAI keyframe payload 预览与实际 provider 设置不一致

**现象**

- `generate_keyframes_atlas_i2i.py --image-model openai --prepare-only` 写出的 `payload.preview.json` 里曾显示 Atlas 风格 model（如 `openai/gpt-image-2/edit`），但实际直连 OpenAI 请求使用的是 `--openai-model`（如 `gpt-image-2`）。
- 本地 `IMAGE_MODEL` 环境变量会覆盖空的 `--image-model`，所以即使脚本默认 provider 已改为 `openai`，prepare-only 验证也可能解析成 `grok` 或其他 provider。

**根因**

- payload preview 最初复用 Atlas payload 构造参数，没有在 `image_model == "openai"` 时同步写入 `args.openai_model`。
- provider 解析顺序是显式 `--image-model`、`IMAGE_MODEL` 环境变量、legacy `--provider`、代码默认值；验证默认值时如果不清空环境变量，容易误判。

**无效或不充分方案**

- 只看 `payload.preview.json.model` 判断实际 OpenAI 请求 model，可能读到旧 Atlas model 字符串。
- 只运行不带 `--image-model` 的 prepare-only 来确认默认 provider，可能被环境变量覆盖。

**有效方案**

- 直连 OpenAI 时让 preview payload 的 `model` 与 `--openai-model` 保持一致。
- 验证代码默认 provider 时清空 `IMAGE_MODEL`，或在命令里显式传入 `--image-model openai`。
- 检查 `keyframe_manifest.json` 的 `provider/image_model` 与单 shot `payload.preview.json`，两者一起确认。

**系统化改进建议**

- provider 默认值测试应覆盖“无环境变量”和“环境变量覆盖”两种路径。
- OpenAI/Grok/Atlas 三类 prepare-only payload 应分别检查 model、quality、size、reference image count，避免 provider-specific 预览字段漂移。

### 2026-04-28 16:28:06 CST - Case 13: 照片道具 alias 重复导致 Seedance prompt 反面文字自相矛盾

**现象**

- EP06 SH13 的 record 明确要求 `SAKURA_PHOTO_01` 背面朝向镜头，并显示一行给小樱的手写承诺字迹。
- Seedance prepare-only 后，`prompt.final.txt` 同时出现“背面有手写承诺字迹”和默认照片约束“背面无文字”，会增加 I2V 阶段把承诺字迹抹掉或变成空白照片的风险。

**根因**

- 同一张照片在 record 中同时出现旧 prop id `SAKURA_SCHOOL_PHOTO` 和 canonical prop id `SAKURA_PHOTO_01`。
- `run_seedance_test.py` 的照片道具约束没有识别 alias，也没有从 `structure` 字段解析正反面描述；旧 id 缺少 `back_description` 时回退到“无文字”的默认句。

**无效或不充分方案**

- 只依赖 keyframe 首帧已有文字：I2V prompt 冲突时仍可能在视频中弱化、擦除或改写照片背面。
- 只在画面主体里写“手写承诺字迹”，但保留照片约束里的“无文字”，会让模型收到互相矛盾的指令。

**有效方案**

- 在 `run_seedance_test.py` 中跳过 `SAKURA_SCHOOL_PHOTO -> SAKURA_PHOTO_01` 这类 alias 重复照片约束。
- 从 prop `structure` 中解析“正面...”和“背面...”描述，生成一致的照片道具约束。
- Seedance prepare-only 后检查 `prompt.final.txt`，确认照片背面约束不再出现“无文字”。

**系统化改进建议**

- 道具库需要维护 canonical prop id 与 alias 映射，照片、手机、丝巾这类贯穿多镜头道具都应走 canonical id。
- 对照片道具增加 QA：如果本镜头要求背面文字，最终 I2V prompt 不得同时出现“背面无文字/无图像/无花纹”等冲突描述。

### 2026-04-28 16:56:22 CST - Case 14: EP 级 Seedance 批跑漏传 duration overrides 导致视频整体变短

**现象**

- EP06 使用新版 visual refs start keyframes 跑 Seedance 时，13 条视频全部成功，但总时长从旧完整批次约 117.542s 变成约 64.542s。
- 单镜头时长从旧版对白完整性时长（如 SH07=12s、SH10=7s、SH13=7s）回退到 record 基础时长（SH01-SH02=4s、SH03-SH12=5s、SH13=6s）。

**根因**

- 旧完整批次使用了 language plan 生成的 `duration_overrides.json`：
  `test/ginzanight_ep06_openai_atlas_fullrun_v1_language/language/duration_overrides.json`
- 新批次命令漏传 `--duration-overrides`，`run_seedance_test.py` 因此只读取 `record.global_settings.duration_sec` 或文本估算基础时长。
- `duration_overrides.json` 是按对白/字幕估算出来的“说完台词所需时长”，不是可有可无的后处理配置。

**无效或不充分方案**

- 只检查 Seedance API 是否 completed：API 成功不代表节奏/对白完整性正确。
- 只对比 record 中的 `global_settings.duration_sec`：这会忽略 language plan 对对白完整播完的时长扩展。

**有效方案**

- EP 级 Seedance/I2V 批跑默认带上对应 language experiment 的：
  `--duration-overrides test/<language_experiment>/language/duration_overrides.json`
- 只有在明确要重新按 record 基础时长测试时，才省略 duration overrides。
- Seedance prepare-only 后检查 `run_manifest.json.duration_overrides` 非空，并抽查 `payload.preview.json.duration` 是否与 language plan 一致。

**系统化改进建议**

- `run_novel_video_director.py` 已会把 language plan 的 duration overrides 传给 Seedance；手动运行 `run_seedance_test.py` 时必须复制这个行为。
- QA 增加总时长对比：同一集重跑时，逐镜头 `payload.duration` 和总时长应与目标 language plan 对齐。
- 若更换 language plan 或台词内容，先重新生成 `duration_overrides.json`，再跑 I2V。

### 2026-04-28 22:32:34 CST - Case 44: EP06 SH12 复现电话远端声音绑定到听者嘴型

**现象**

- EP06 SH12 的 Seedance final prompt 明确要求“电话/手机听筒里传来石川悠一的声音”，且“田中健一、佐藤美咲保持闭嘴，不做说话口型”。
- 实际视频中，田中健一前半段持手机贴耳倾听，但约 8 秒附近嘴部明显张开，视觉上像是接电话的人在说石川悠一的台词。
- SH10 使用背侧近景、手机和手遮挡嘴部，实际视频没有明显可见口型问题。
- 这是 Case 42/43 的同类复现，不应只靠继续强化普通 prompt 解决。

**根因**

- 生成音频包含一整段电话台词时，I2V 模型倾向于把可见持手机角色自动绑定为说话人，即使 prompt 写了远端声音。
- SH12 是正面双人中近景，田中健一嘴部清楚可见，给模型留下了做口型同步的空间。
- 仅用文字写“闭嘴/不要说话口型”不够强，尤其当画面里有手机贴耳和可见嘴部时。

**无效或不充分方案**

- 只在台词段落写“电话另一端声音”：模型仍可能把手机持有者当成说话者。
- 只加“保持闭嘴、不做口型”：可见嘴部仍可能被音频驱动出开口动作。
- 让接电话者正脸清楚入镜，同时希望远端声音不触发口型，是高风险构图。

**有效方案**

- 优先使用 Case 43 已固化流程：`--phone-audio-repair-shots SH12`。即二次生成 `generate_audio=false` 的无声听电话画面，再抽取原始 `output.mp4` 的电话音频合成为 `output.phone_fixed.mp4`。
- 电话远端说话镜头优先采用 SH10 这种背侧、侧后方、低头或遮挡嘴部构图，让画面中没有可做口型同步的可见嘴部。
- 如果必须双人正面入镜，远端电话台词段内让接电话者的嘴部被手机、手、前景道具、低头角度或裁切持续遮挡。
- 对 Seedance final prompt 增加更硬的视觉约束只能作为辅助：远端说话期间，画面内所有可见人物嘴唇闭合且不可见张口；如无法保证，改用无声视频 + 后期音频合成。
- 生成后必须抽帧检查电话镜头中接电话者是否开口，不能只检查 prompt 是否写对。

**系统化改进建议**

- `run_seedance_test.py` 已提供 `--phone-audio-repair-shots` fallback；视觉 QA 一旦发现电话听者开口，应直接走该路径，而不是继续用 `generate_audio=true` 重试。
- 电话远端台词 QA 增加抽帧检查：若画面内接电话者正脸可见且有张口帧，应标记重跑。
- 对远端电话台词，优先把可见角色动作写成“听、停顿、低头、握紧手机”，并把嘴部从构图焦点中移除。

### 2026-04-29 20:26:55 JST - Case 62: 统一视觉资产清单不能被旧 scene/prop 入口覆盖掉人物区块

**现象**

- 新的统一资产创建流程会在 `visual_reference_manifest.json` 中同时写入 `characters`、`scenes`、`props`。
- 旧的 `generate_visual_reference_assets.py` 只负责 scene/prop，如果它按旧逻辑整文件重写 manifest，会丢失统一流程写入的 `characters` 区块。
- 下游 director/keyframe 仍依赖 `character_image_map.json` 和 visual manifest 的补充信息；人物区块丢失会让统一资产创建看似成功但后续缺少可追踪的 bible/prompt/image 元数据。

**根因**

- legacy scene/prop CLI 原本只面向场景和道具资产，没有把 manifest 当成跨资产类型的共享契约。
- 统一资产流程引入人物、场景、道具共用清单后，任何单类型重写都必须保留其他类型的既有内容。

**无效或不充分方案**

- 只要求新 runner 不再调用旧入口：开发和回归测试仍可能直接运行旧 CLI。
- 只从 `character_image_map.json` 恢复人物图路径：会丢失 bible、prompt、quality report、llm model 等新字段。

**有效方案**

- 旧 scene/prop 入口重写 `visual_reference_manifest.json` 前先读取已有 manifest，并保留既有 `characters` 区块。
- 统一资产创建入口仍作为 batch runner 的默认 refs 阶段，legacy CLI 只作为兼容入口。
- 回归检查 manifest counts 时同时确认 `characters`、`scenes`、`props` 三类都存在且没有被单类型入口清空。

**系统化改进建议**

- 任何新增资产类型写 manifest 时，先把 manifest 当作共享 schema，增量更新自己负责的区块。
- dry-run 也要写同样结构的 manifest，方便在不生图时发现 schema 覆盖问题。

### 2026-04-29 20:43:58 JST - Case 63: 门/车门结构件不能按手持小道具生成 reference

**现象**

- screen EP01 的 `DOOR_PANEL_01`、`VEHICLE_DOOR_01` 在 record prop profile 中被写成 `手持或桌面小道具尺寸`、`现实材质`、`固定位置可见道具`。
- 资产生成时 Grok bible 虽然通过数量校验，但 prompt 继承了“手持/桌面小道具”语义，导致医院入口门、车门这类真实结构件可能被生成成小型产品道具。

**根因**

- planning 层把所有 prop 都套用了通用小道具模板，未区分建筑/车辆结构件与可手持道具。
- `DOOR_PANEL`、`VEHICLE_DOOR` 在镜头中是场景结构的一部分，但被放入 prop library 后，下游 asset creation 会按独立产品图处理。

**无效或不充分方案**

- 只让 LLM 重写 visual bible：如果源 profile 明确写了“手持或桌面小道具尺寸”，LLM 可能继续继承坏语义。
- 只补 `count=1件`：能通过数量门禁，但不能修正真实比例、材质和运动政策。

**有效方案**

- asset creation 对 `DOOR_PANEL`、`VEHICLE_DOOR` 做结构件归一化：真实建筑门/车辆门尺寸，玻璃/金属/门框/铰链/导轨等明确材质结构，不再使用手持或桌面小道具模板。
- source contract 中泛化的 `手边/桌面/随手部移动` 位置或运动政策，需要改写为门框、车身门框、轨道或铰链上的固定结构运动。
- prompt 中若出现 `手持/桌面/小道具/现实材质/固定位置可见道具`，用结构件 reference prompt 覆盖。

**系统化改进建议**

- planning 阶段区分 `portable_prop` 与 `structural_prop`，门、车门、窗、墙面、柜门等默认归 structural。
- 对 structural prop，优先作为 scene reference 的空间构件；只有镜头确实聚焦该结构件时，才生成独立 prop reference。

### 2026-04-29 22:24:29 JST - Case 64: 角色相似描述不能劫持身份默认视觉模板

**现象**

- EP01 赵一鸣的源设定含“眼睛像陆景琛”等相似关系，资产创建时被错误归入陆景琛的 CEO 模板，生成了宽肩、方脸、深灰定制西装、不拿平板等反向特征。
- 4岁半沈知予的旧 bible/prompt 中残留 `Toddler/Baby/toddlers/babies` 等大小写或复数低龄词，导致修复重试仍被 validator 卡住。

**根因**

- 角色默认视觉模板先扫描 `profile_text/visual_anchor` 的 combined 文本，再判断精确 `character_id/name`；相似描述里的另一个主角姓名会污染当前角色身份。
- 风险词清理只做大小写敏感的简单 `replace`，无法覆盖英文大小写和复数变体。

**无效或不充分方案**

- 只在 prompt 里加“不要像某人”：如果基础模板已经拿错，后续 QA/repair 会围绕错误身份反复修补。
- 只替换小写 `baby/toddler`：LLM 输出常见大小写、复数或混合表达，仍会残留低龄风险词。

**有效方案**

- 角色默认视觉模板必须先按精确 `character_id` 或当前角色 `name` 分类，再把 combined 文本作为未知角色的兜底判断。
- 相似关系只进入 `pairwise_forbidden_similarity/distinction_anchors`，不能改变当前角色的年龄、脸型、体态、服装签名。
- 低龄/大头风险词清理使用大小写无关替换，并覆盖 `baby/babies/toddler/toddlers/infant/infants/chibi` 等变体。

**系统化改进建议**

- 任何人物资产修复都要有“当前角色身份优先级”回归测试，特别是亲子、替身、像某人、兄弟姐妹、前任相似等关系文本。
- 对年龄比例相关禁词，validator 和 normalizer 必须使用同一套词表或至少同等覆盖范围。

### 2026-04-29 23:28:12 JST - Case 65: 大物件不能进入小道具 contract

**现象**

- screen EP01 SH01 把公交车门/车门当成 `VEHICLE_DOOR_01` 小道具写进 prop contract，后续 keyframe/Seedance prompt 出现“道具尺寸与物理约束”，模型可能生成独立漂浮门板或让人物拖动车门。
- 医院大门、VIP区大门、公交车、柜台、沙发、楼梯、电梯门等空间构件如果进入 prop reference，会污染资产库并让结构比例失真。

**根因**

- planning 层把“镜头中重要可见物”直接归入 prop，但项目语义里的 prop 应该是可拿取、放置、展示、交换或被角色直接操作的小物件。
- 大物件是场景布局或镜头临时修饰，不应该套用小道具的数量、手持、桌面、随手移动等模板。

**无效或不充分方案**

- 只在 prompt 加“车门不要漂浮”：如果 record 仍把车门列为 prop，下游资产、keyframe 和 Seedance 仍会反复强化“独立道具”语义。
- 把公交车写进基础 `scene_detail.txt`：会把单镜头临时元素污染成全场景常驻元素。

**有效方案**

- prop 只保留小物件；门、车、公交车门、医院入口、柜台、沙发、楼梯、电梯门等写入 `first_frame_contract.scene_overlay`。
- `scene_overlay.required_elements` 描述 shot-level 大物件修饰，`scene_overlay.physical_rules` 描述门固定在车身/建筑结构上、不脱离、不漂浮、不被角色拖动。
- keyframe 和 Seedance 渲染层显式消费 `scene_overlay`，并对 screen record 中残留的 `DOOR_PANEL`、`VEHICLE_DOOR`、`BUS` 等 prop id 做 preflight 报错。

**系统化改进建议**

- 规划 QA 需要扫描 `prop_library`、`prop_contract`、`first_frame_contract.key_props`，发现大物件 prop 即高危失败。
- 场景资产只保留基础场景；反复出现的大物件未来可升级为 scene variant reference，但不要回退到 prop 类型。

### 2026-04-29 23:34:13 JST - Case 66: 现代题材地域兜底不能默认成日本都市

**现象**

- screen EP01 明确是现代中国滨海市儿童医院门口，但 keyframe prompt 的时代地域约束写成“非现代日本都市环境”，与 record 的中国滨海市设定冲突。

**根因**

- keyframe 的现代题材兜底规则把“现代/都市/公司/酒店”等通用现代词统一映射到既有 novel 项目的日本银座语境。
- screen script 与 novel 共用渲染脚本后，缺少按 record 文本识别地域的分支。

**无效或不充分方案**

- 只在 scene prompt 后半段写“中国滨海市”：前半段负向地域约束仍会强力拉向日本都市。

**有效方案**

- era/region 约束先识别“中国/滨海市/儿童医院/集团大厦/幼儿园/公寓”等中国现代项目 token，再识别“银座/东京/日本”。
- 通用现代词只输出“现代都市环境”约束，不绑定具体国家或城市。

**系统化改进建议**

- 多项目共用 keyframe/Seedance 脚本时，地域和时代约束必须来自 record/project metadata 或明确 token，不要从旧项目默认值推断。

### 2026-04-30 01:07:40 JST - Case 67: 说话人焦点不等于首帧前景人数

**现象**

- screen EP01 多个亲子互动镜头被压成单人首帧，例如“帮他整理背带”“牵住他的手”“予予靠在她怀里”，生成时只保留说话人或显式名字。
- 结果 keyframe/Seedance 虽然抓住了对白焦点，却丢掉了关系动作里的另一名前景人物。

**根因**

- planner 早期把 `visible_characters` 主要绑定到画面内说话人和视觉文本中的显式角色名。
- “他/她/怀里/牵手/抱着/妈咪/予予/那个叔叔”等关系词没有被提升为首帧人数契约。
- 为避免场景无脑继承主角，系统没有从上一镜头自动继承人物；这个原则正确，但需要用关系动作推断补足。

**无效或不充分方案**

- 让 keyframe/Seedance 自行根据对白猜人物数量：下游会把 close-up 语义理解成单人，且不同模型行为不稳定。
- 对所有相邻镜头继承上一镜头人物：会重新引入主角乱入、scene-only 镜头被污染的问题。

**有效方案**

- planning 阶段区分 `featured_character` 和 `foreground_character_cardinality`。
- 说话人/情绪承接者写入 `featured_character`；首帧必须出现的人物写入 `foreground_character_cardinality.mode/count/names/focus`。
- 对亲子互动、牵手、抱着、靠在怀里、被拖走、回头冲某人喊、孩子喊妈咪/叔叔/爸爸等关系动作，用局部文本加近邻上下文推断前景人物，但不做全局无脑继承。
- keyframe/Seedance prompt 明确输出“焦点人物可以说话或承接情绪，但不得删除其他前景人物”。

**系统化改进建议**

- 回归测试要覆盖“对白单说话人 + 关系动作双人/三人首帧”的情况。
- 后续如接 LLM planner，也必须保留显式 cardinality 字段，不让下游根据镜头景别自行重算人数。

### 2026-04-30 14:05:20 JST - Case 84: 相邻镜头道具交接不能退化成泛化容器

**现象**

- screen EP02 SH07/SH08 已明确出现 `JUICE_CUPS_02` 果汁杯，但 SH09 的镜头切分只保留“接过杯子/喝了一口”，record 只写入泛化 `CUP_01`。
- 下游 keyframe 只拿普通杯子参考图，最终喝果汁动作变成空杯/普通杯。

**根因**

- shot split 把“果汁”证据放在上一 shot，而当前 shot 只有泛化容器词。
- semantic pass 没有输出跨 shot 的 prop handoff；record builder 只按当前 shot 文本关键词生成道具，不读取上一 shot 道具连续性。

**无效或不充分方案**

- 只在 keyframe prompt 临时补“有果汁”：会让 keyframe 绕过 record source of truth，后续 Seedance/QA 仍可能读取弱 record。
- 仅扩大关键词上下文：能救部分场景，但不能表达“上一 shot 的具体道具传递到下一 shot”的持有人和状态变化。

**有效方案**

- semantic pass 增加 `prop_handoffs` 字段，只允许引用 `previous_shot_key_props` 中已有 prop_id。
- record builder 本地校验 `from_shot` 必须是上一 shot、prop 必须存在于上一 shot、当前 shot 必须有接过/递给/拿起/端起/喝/放下等动作。
- 校验通过后，用上一 shot 的具体 prop_id 替换当前 shot 的泛化道具，例如 `JUICE_CUPS_02` 替换 `CUP_01`，并写入 `i2v_contract`、`first_frame_contract.prop_handoffs`、`continuity_rules.prop_continuity`。
- 如果 semantic handoff 选择了上一 shot 中同时存在的泛化 prop，例如 `CUP_01`，而上一 shot 还有可覆盖它的具体 prop，例如 `JUICE_CUPS_02`，本地 builder 必须自动升级到具体 prop。

**系统化改进建议**

- 跨 shot 道具连续性应由 LLM 判断关系、本地规则校验落盘；LLM 不能发明 prop_id。
- 回归测试覆盖“上一 shot 递饮品，下一 shot 只写接过杯子/喝一口”的场景。

### 2026-04-30 14:16:58 JST - Case 85: 视觉参考 profile 不能覆盖 record 的道具数量

**现象**

- SH09 record 已正确写入 `JUICE_CUPS_02` 且数量为 `1杯`，但 keyframe prompt 仍显示 `数量:2杯`。
- 生成的首帧中沈念歌手里出现两杯果汁，虽然已经不再是空杯。

**根因**

- keyframe prompt 构造时把 visual reference manifest 的 prop profile 合并在 record prop library 之后。
- visual reference asset `JUICE_CUPS_02` 是两杯参考图，其 profile count=`2杯`，覆盖了 SH09 record 中本镜头实际的 `1杯`。

**无效或不充分方案**

- 只在 record 层写 `1杯`：keyframe 层如果用 manifest profile 覆盖 record，仍会把两杯带进 prompt。
- 只换参考图：同一个参考资产可能用于“端着两杯”和“接过其中一杯”两个不同镜头，不能让资产默认数量替代 record。

**有效方案**

- keyframe 的 prop profile 合并顺序必须让 record/root/i2v 的 prop_library 覆盖 visual reference profile。
- visual reference 只补充外形、材质、风格参考；数量、位置、持有人、当前状态以 record 为 source of truth。

**系统化改进建议**

- Prompt QA 检查：若 record prop count 与 keyframe prompt 中数量不一致，必须报警。
- 对成组参考图，如 `JUICE_CUPS_02`，下游必须允许单镜头用 record 限定“其中一杯”。

### 2026-04-30 14:39:19 JST - Case 86: 模糊身影去实名化后不能被人数约束抹掉

**现象**

- SH14 修掉“第二个人被当成陆景琛露脸/西装亮相”后，keyframe 与视频又变成沈念歌单人床上镜头。
- 原文中的“两个人。被子裹着两个模糊的身影”没有被稳定保留。

**根因**

- record 层把 `visible_characters` 修正为只含原文点名且脸部可见的沈念歌，这是对的。
- 但 scene overlay 和 keyframe prompt 又从 `visible_characters` 推出 `首帧前景主体人物数量 exactly 1`，并追加“不要生成多余人物”，把原文未点名的第二个模糊身影压掉。

**无效或不充分方案**

- 只删除陆景琛：会避免实名化，但不能保证原文人数和模糊身影存在。
- 只在原文摘录中写“两个人”：如果同时存在 exactly 1 / 不要生成多余人物，模型会优先听硬约束。

**有效方案**

- `visible_characters` 只用于实名角色锁定和脸部可见契约；未点名模糊身影不进入角色锁。
- 当原文出现“两个人/两个模糊身影/被子裹着”时，scene overlay 必须按原文写 `foreground_character_count=2`，第二个主体以“被子裹着的模糊身影”保留，不赋予具体身份。
- keyframe prompt 对这类镜头不能写“不要生成多余人物”，改为“只按原文呈现两个人和两个模糊身影，不新增原文以外的人物身份”。

**系统化改进建议**

- Prompt QA 检查：同一 prompt 中若原文摘录包含“两个人/两个模糊身影”，但硬约束出现 exactly 1 或“不要生成多余人物”，必须报警。
- 将“实名可见角色数量”和“原文画面人物/身影数量”分成两个字段，避免身份锁定字段吞掉匿名视觉主体。

### 2026-04-30 14:49:05 JST - Case 87: 混合对白和集尾旁白时可见人物会继续对旁白做口型

**现象**

- SH18 前半段沈念歌电话对白正确，但后半段“下一集，秘密继续逼近。”应为画外旁白，画面内沈念歌仍容易继续张嘴说话。

**根因**

- record 中旁白已标为 `source=offscreen`，但自动集尾钩子同时被写入视觉 `prompt_text/action_intent`，让“旁白”混进了画面动作描述。
- Seedance 同一片段同时生成可见角色对白和画外旁白音频时，即使 prompt 写了“不替画外声音开口”，模型仍可能把后半段语音 lip-sync 到画面里唯一清晰人脸上。

**无效或不充分方案**

- 只写“画外旁白/不要让沈念歌说旁白”：模型仍可能因音频-人脸耦合继续做口型。
- 只保留 offscreen source：如果视觉动作里还写“集尾钩子旁白”，下游 prompt 仍有混淆。

**有效方案**

- 纯旁白 shot 可以存在，但不能和同一个 shot 内的画面对白混用；如果需要集尾旁白，应拆成独立纯旁白/黑场/无可见嘴部 shot。
- planning 阶段自动追加的集尾旁白只保留在 `dialogue_language.dialogue_lines`，不要写入视觉 `prompt_text/action_intent`。
- Seedance prompt 对 mixed onscreen dialogue + offscreen narrator 增加时间段约束：旁白开始前画面淡出或明显转暗；旁白期间可见人物嘴唇闭合、下颌静止、不做旁白口型。
- 禁止规则必须覆盖混合对白场景，而不只覆盖“全片只有旁白”的场景。

**系统化改进建议**

- 对所有包含 `source=offscreen` 且画面里有可见人脸的镜头，QA 应检查 prompt 是否有“旁白开始前淡出/闭嘴静止”约束。
- 对所有 `dialogue_lines` 同时包含 `onscreen` 与 `offscreen/narration` 的 record，QA 应报警：必须拆 shot 或去掉非原文自动旁白。
- Prompt-only 修复不可靠时，允许在组装层保留模型音频，但从旁白开始前把画面淡出到黑场或切到无可见嘴部的反应镜头，确保旁白段没有可见口型。
- 更稳的长期方案是把 onscreen dialogue 和 offscreen hook 拆成两个视频段，旁白段使用无可见嘴部或黑场/反应镜头，再在 assembly 层合成音频。

### 2026-04-30 16:29:03 JST - Case 88: 群体听众被语义规划误当成硬可见角色锚点

**现象**

- EP05 重新规划时，`大家`、`孩子们` 这类群体听众被写入 `first_frame_contract.visible_characters`。
- QA 随后报 `visible_character_missing_from_character_anchor`，要求这些群体逐个进入 `character_anchor`。
- `闺蜜` 这类临时个体也可能出现在可见人物中，但不应被升级成主角锁定角色。

**根因**

- 语义标注中的 `visible_characters` 同时承载了“实名/临时个体前景主体”和“群体听众/背景反应层”。
- 下游首帧契约把 `visible_characters` 视为硬脸部锚点清单，导致群体语义被错误升级为角色身份锁定。

**无效或不充分方案**

- 直接把 `大家`、`孩子们` 加进角色库：会违反“临时/群体不使用主角锁定”的策略，也会制造不可能的逐脸可见约束。
- 直接删除原文里的听众语义：会丢失对白对象和现场反应。

**有效方案**

- 将 `大家`、`孩子们`、`人群`、`家长们` 等群体听众从硬 `visible_characters` 中过滤，只保留在背景/听众呈现策略里。
- `闺蜜`、`老师`、`风衣妈妈` 等临时个体允许使用 ephemeral anchor，不使用主角 lock profile。
- scene overlay 写明群体听众只作为背景反应层呈现，不进入首帧前景主体人数，不要求逐个脸部锁定。

**系统化改进建议**

- `visible_characters` 应只表示需要脸部稳定和锚点同步的前景主体。
- 另设 `background_listeners` 或 `crowd_reaction_layer` 字段承接群体听众，避免 QA 和 prompt 把群体误判为硬角色。

### 2026-04-30 18:21:20 JST - Case 89: Novita 单镜 content/internal 失败可能是瞬时执行错误

**现象**

- EP05 批量 Seedance 生成时，SH05/SH11 报 `InvalidParameter: Invalid content.text`，SH18 报 `InternalServiceError`。
- 三个镜头的 record、keyframe 和 prompt 均已成功生成；单独 retry 同一 record、同一 keyframe、同一 Novita profile 后全部成功。

**根因**

- 失败发生在 model execution/provider 层，不是 source script parsing、planning record、keyframe 或 assembly 层。
- `Invalid content.text` 在本例中不是确定性内容拦截；同一 payload 重新提交可通过。

**无效或不充分方案**

- 直接改写 record 台词或删掉儿童/亲子对白：会破坏 record/source truth，且没有证据证明内容本身不可生成。
- 只看第一次批量错误就判定 prompt 违规：容易把 provider 瞬时异常误诊为规划错误。

**有效方案**

- 对单镜 `Invalid content.text` 或 `InternalServiceError`，先做最小重试实验：只重跑失败 shot，保持 record、keyframe、duration overrides 不变。
- 若重试成功，将 retry 输出补回主 Seedance 目录或在 concat/clip override 中引用 retry 输出。
- 只有同一 shot 多次独立重试仍稳定失败时，再进入 provider prompt fallback 或正向改写。

**系统化改进建议**

- Seedance 批处理可记录失败类型并自动生成 retry-only 命令。
- 对非确定性 provider 错误，应区分 `transient_execution_error` 与 `deterministic_prompt_rejection`，避免过早修改源台词。

### 2026-05-01 00:00:00 JST - Case 90: 身体/年龄/健康变化必须作为 shot-local character_state_overlay

**现象**

- EP03 中同一角色跨时间线出现早孕、孕晚期、产后/疲惫带娃、儿童年龄阶段等可视身体状态。
- 如果把这些状态写入全局角色锁，后续 shot 会被污染；如果只靠普通 prompt 文本，下游 keyframe / Seedance 容易被全局年龄或服装锁覆盖。
- voiceover/画外音若被误归为 offscreen 远端声音，会凭空生成 listener，继而把不该出现的人物拉进画面。

**根因**

- 身体/生理/年龄/疲惫/伤病等状态属于镜头局部视觉事实，不等同于角色身份锁。
- screen semantic pass 已有 `nearby_context`，适合让 LLM 依据当前镜头附近原文判断这些状态，但旧 schema 没有状态 overlay 字段。

**无效或不充分方案**

- 预设固定枚举（只覆盖怀孕、产后、儿童年龄等）：会漏掉伤病、醉酒、病弱、疲惫、狼狈等新情况。
- 修改 `character_anchor.visual_anchor` 或 `character_lock_profiles`：会把局部身体状态扩散到其他镜头。
- 仅在 negative prompt 里禁止错误状态：缺少正向可视约束，容易被角色锁或上下文覆盖。

**有效方案**

- 让 LLM 在 screen semantic pass 中输出 `character_state_overlays`，每项必须有 `source_basis` 和 `evidence_quote`，并限定 `scope=shot_local`。
- record 根字段写入 `character_state_overlay`，按角色分组；不修改全局角色锁。
- keyframe 与 Seedance prompt 都渲染该 overlay，并明确“只适用于本镜头，不延续到其他镜头；与年龄/身形/身体状态冲突时本 overlay 优先，身份连续性仍参考角色锁”。
- voiceover/旁白/画外音默认不生成 listener；只有电话、广播、门外声等明确被画面内角色听见的远端声音才需要 listener。

**系统化改进建议**

- QA 必须检查 overlay 是否有 `source_basis` 和 `evidence_quote`，以及 overlay 角色是否为本 shot 可见人物。
- 蒙太奇/跳时镜头允许 LLM 给出 `keyframe_moment`，首帧只取一个瞬间，避免把多个时间点拼贴在同一 keyframe。

### 2026-05-01 11:02:01 JST - Case 91: 首帧重复出现两次的角色必须升级为锁链角色

**现象**

- ScreenScript EP03 的 `19_ScreenScript角色统一视觉设定包` 和角色出图清单列出多个 `EXTRA_*` / 配角，但实际 character image 只生成了部分主角色。
- 护士、老师等临时人物虽然是 `EXTRA_*`，但如果在多个首帧里反复出现，仅靠 ephemeral anchor 会导致脸型、年龄、服装和气质跨镜头漂移。

**根因**

- 旧口径把 `EXTRA_*` 默认当作临时功能人物，不给真实 `lock_profile_id`，也不强制生成 character image。
- 但“是否临时”不能只看 ID 前缀；如果同一角色或同一 `EXTRA_*` 在首帧中累计出现 2 次或以上，它已经承担跨镜头连续性，需要锁链/锁脸。

**无效或不充分方案**

- 只因为 ID 是 `EXTRA_*` 就永久跳过锁定：会让重复出镜的老师、护士、保安、前台等角色在多镜头中漂移。
- 只在 `19` 或 `22` 文档里列角色，但不生成 `lock_profile_id` 和 character image：下游无法稳定引用。
- 只依赖文字 visual_anchor：对重复首帧角色不足以保证面部和服装连续性。

**有效方案**

- 统计每个角色/`EXTRA_*` 在 `first_frame_contract.visible_characters` 或 record 首帧人物锚点中的出现次数。
- 若同一角色或 `EXTRA_*` 首帧出现次数 >= 2，升级为锁链角色：分配稳定 `lock_profile_id`，生成 profile/prompt/info，补齐 character image，并写入 `character_image_map.json`。
- 单次首帧出现的功能人物仍可保持 ephemeral anchor，不强制锁脸。
- 升级后仍遵守 record source truth；角色锁只保证身份/外观连续性，不能覆盖本镜头原文动作、状态、人数和构图。

**系统化改进建议**

- planning QA 增加检查：首帧出现次数 >= 2 且 `lock_profile_id` 为空时报警。
- 角色出图清单应区分 `required_locked_reference`、`optional_ephemeral_reference` 和 `not_in_episode_first_frame`，避免把“列入角色库”误读为“已生成并会使用”。

### 2026-05-01 15:55:15 JST - Case 92: 小型手持道具 reference 需要同机位比例锚点

**现象**

- EP03 SH01 的验孕棒虽然在 record 中写了约 12 厘米长、2 厘米宽，但下游视频里仍容易显得过大。
- 默认 prop reference 规则会生成孤立产品图，并且硬性排除人物、手、身体局部；这会丢失小道具相对成人手掌、身体和镜头距离的比例信息。

**根因**

- 绝对厘米尺寸对图像/视频模型约束较弱；模型更依赖画面构图、前景占比、镜头距离和参照物来判断大小。
- “两条红线清楚”等剧情证据若没有比例约束，模型可能通过放大道具或做近景特写来满足清晰度。

**无效或不充分方案**

- 只在 prop profile 中写厘米尺寸：容易被后续“清楚可见”“特写”等 prompt 权重覆盖。
- 生成白底产品图作为 reference：形状清楚但缺少真实使用尺度，反而可能把道具推成前景大物。
- 只加 negative prompt 禁止 oversized：缺少正向比例锚点时效果不稳定。

**有效方案**

- 对验孕棒、钥匙、戒指、药片、纸条等小型手持道具，生成 scale-context prop reference：使用与人物镜头相同或相近的中景距离和焦段。
- reference 允许出现手掌、手指、前臂、膝盖、床沿/桌面等比例锚点，但不出现清晰陌生人脸，避免污染角色身份。
- prompt 同时写明道具真实尺寸、画面占比、不可贴近镜头、不可微距、不可产品棚拍；剧情细节可辨但不能靠放大道具实现。
- keyframe prompt 中的文字约束仍以 record / static record 的 `prop_library` 为准；visual reference profile 只能补充画面参考，不能替代旧 record 字段。若已生成 record，需要同步修正 record 和 keyframe static record 后再重跑。

**系统化改进建议**

- prop reference 生成应区分 `product_reference` 与 `scale_context_reference`；小型手持剧情道具默认使用后者。
- keyframe / I2V 渲染 small prop 时优先传入 scale-context reference，并把 reference 标注为“只补充比例，不覆盖 record 和角色身份”。

### 2026-05-01 16:10:17 JST - Case 93: 小道具比例政策中的反例词不能参与道具类型判定

**现象**

- 验孕棒的 `scale_policy` 会写“不得像遥控器、体温计、手机或大号牌子一样巨大”。
- 如果道具类型判定把 `scale_policy` / `structure` 全文都纳入 phone/photo 检测，验孕棒会因为反例词“手机”被误判为手机道具，进而跳过 scale-context 小道具规则。
- 儿童画 `CHILD_DRAWING_01` 也容易被“小型纸张”启发式误判为普通小道具，但它实际属于照片/画面类道具，应保留正反面规则。

**根因**

- 类型判定和约束文本混用同一个全文 blob，导致 negative/comparison words 被当作实体类型证据。
- Drawing/photo/front-back 规则比 generic small handheld scale rule 更具体，优先级必须更高。

**无效或不充分方案**

- 简单搜索全文是否包含“手机/照片/小型/手持”：容易被反例词、禁止词和描述性类比污染。
- 只用尺寸判断小道具：会把照片、儿童画、票据、报告等不同语义的纸面物混在一起。

**有效方案**

- phone/photo/drawing 类型判定只看 prop id、display/name 等身份字段；不要把 `scale_policy`、`visibility_policy` 或含反例词的 `structure` 当作类型依据。
- generic small handheld 规则在 phone/photo/drawing/scene-structure 排除之后再执行。
- `PHOTO` / `DRAWING` / 儿童画类道具继续走照片/正反面规则，不进入通用小手持道具约束。

**系统化改进建议**

- Prompt/QA 检查应包含反例词用例：例如验孕棒 scale policy 中含“手机”，仍必须判为 small handheld 而不是 phone。
- Backfill dry-run 必须人工检查 proposed changes，尤其是纸面类道具，避免把 photo/drawing/front-back 语义改成普通 scale-context。

### 2026-05-01 17:07:30 JST - Case 105: 连续片段混用 padded clip 与 chained clip 时需检查边界音频静音

**现象**

- EP03 SH22 -> SH23 画面都在孩子举画，视觉上接近连续，但实际总片边界处有“一顿”的感觉。
- 抽取最终片边界音频后发现，SH22 padded 尾部约 0.8 秒静音与 SH23 头部约 0.6-0.9 秒低能量/静音叠加，形成跨切点的长停顿。

**根因**

- SH22 在总片 overrides 中使用了 padded 版本，而相邻 SH23 使用 chained 版本；padded 版本为补时保留了尾部静音/停顿。
- Assembly 硬切不会自动判断相邻片段的音频能量，也不会移除尾部 padding 与头部静音。

**无效或不充分方案**

- 只检查画面抽帧：能发现动作/构图重复，但不能定位声音停顿。
- 只看 ffprobe 的 duration、fps、音轨存在与否：这些指标正常时，边界仍可能有长静音。
- 对所有边界统一加转场：可能掩盖问题，但不能解决对白/情绪节奏上的空拍。

**有效方案**

- 对怀疑“一顿”的相邻 shot，先抽边界前后 2-3 秒音频，用 `silencedetect` 和 waveform 检查跨切点静音。
- 若 padding 造成尾部空白，优先改用未 padding 的 chained/source clip，或剪掉 padded 尾部静音。
- 若下一 shot 头部有生成静音，可只裁掉少量头部静音，保留必要的情绪呼吸和对白起势。
- 修复后重新合片，并再次抽边界 waveform，确认长静音不再跨切点。

**系统化改进建议**

- Assembly QA 对所有 override 边界增加音频静音检测，尤其是 `padded_clips/*` 与 chained clip 相邻时。
- Clip override 生成时标记 `padded_tail_sec`，若下一条为连续镜头或共享视觉状态，自动提示人工复核边界音频。

### 2026-05-02 09:51:25 JST - Case 113: 道具 count 不能只有裸数字，必须带可读单位

**现象**

- GinzaNight EP21 fresh rerun 的 visual reference 阶段在 `ISHIKAWA_CIGARETTE` 阻断。
- `create_visual_assets.py` 连续 4 次生成 prop visual bible 失败，错误为 `count 缺失`。
- 相关 records 的 `prop_library.ISHIKAWA_CIGARETTE.count` 写成 `"1"`，但同一 prop contract 已写 `quantity_policy="1支，无新增副本"`。

**根因**

- Record 里数量语义是对的，但 `count` 字段只有裸数字，没有中文单位。
- `validate_prop_bible()` 要求 `count` 至少是可读数量短语；`"1"` 长度不足，被判为缺失。
- LLM prop bible normalize 会从 record 继承 `"1"`，因此重试仍无法通过。

**有效方案**

- 对当前 EP21 产物，将 SH06/SH08 的 `ISHIKAWA_CIGARETTE.count` 从 `"1"` backfill 为 `"1支"`，不改剧情、不改道具含义。
- 后续 planning / prop normalization 应优先从 `quantity_policy` 推断带单位 count，例如 `1支`、`1张`、`1份`。

**系统化改进建议**

- Planning QA 增加检查：`prop_library.*.count` 不应只有纯数字，必须包含单位或明确名词。
- `prop_source_defaults()` 遇到纯数字 count 时，应结合 prop display / quantity_policy 自动补单位，而不是原样继承。

### 2026-05-02 09:54:01 JST - Case 114: scale_context 占位值必须当作缺失字段回填

**现象**

- GinzaNight EP21 fresh rerun 中，修复 `ISHIKAWA_CIGARETTE.count` 后，visual reference 阶段仍在同一道具阻断。
- 新错误为 `scale_context 道具必须声明 reference_context_policy`。
- 该道具是小型手持细长物，默认进入 `reference_mode=scale_context`，需要手指/手掌比例上下文。

**根因**

- `normalize_prop_bible_from_source()` 只把空字符串和少数通用中文占位词当作缺失。
- LLM prop bible 可能输出 `N/A`、`none`、`null`、`不适用` 这类占位值；这些字符串长度足够，未被默认 `reference_context_policy` 覆盖，随后被 QA 判为缺失或无效。

**有效方案**

- prop bible normalize 阶段把 `N/A`、`NA`、`NONE`、`NULL`、`无`、`不适用` 统一视为缺失。
- 对 `scale_policy`、`reference_context_policy`、`shooting_angle`、`readable_text_policy` 等字段使用同一占位值过滤，再从 record/defaults 回填。

**系统化改进建议**

- 对所有 LLM 视觉 bible normalize 增加占位值过滤，不要只依赖字符串长度判断字段有效性。
- regression test 覆盖 scale-context 小道具：当 LLM 返回 `reference_context_policy=N/A` 时，最终 bible 必须回填默认比例上下文并通过 QA。

### 2026-05-02 10:13:04 JST - Case 115: Language plan 不能忽略 narration-only records

**现象**

- GinzaNight EP21 尝试给静默镜头补旁白时发现，`build_episode_language_plan.py` 只读取 `dialogue_lines`。
- 如果 record 只有 `narration_lines`，language plan、shot SRT、episode SRT 和 duration overrides 仍会把该 shot 当作静默。

**根因**

- language plan 的 spoken line 收集逻辑把 `dialogue` 当成唯一音频来源。
- 这与执行层规则不一致：record 有对白时对白优先；只有旁白时，旁白应该作为画外音进入 prompt 和时长估算。

**有效方案**

- 增加 narration line 收集：当 shot 没有 `dialogue_lines` 但有 `narration_lines` 时，将旁白作为 spoken line 进入 language plan。
- 如果同时存在 dialogue 与 narration，仍然 dialogue wins，旁白不覆盖对白。

**系统化改进建议**

- Language plan regression 应覆盖三类 record：dialogue-only、narration-only、dialogue+narration。
- Sync QA 应检查 record 中 narration-only shot 是否在 SRT/duration plan 中变成非空音频段。

### 2026-05-02 10:27:12 JST - Case 116: 已建立为月台的镜头不能再回到检票闸机

**现象**

- GinzaNight EP21 的 SH01 首帧已经在 `新干线ホーム/月台`，但 SH11/SH12 records 又回到 `检票口/闸机/闸口`。
- 视觉上会变成角色已经进入月台后，又倒退回检票闸机，空间顺序不成立。

**根因**

- 原文同段同时写了“新干线ホーム”和“走向检票口”，存在现实空间矛盾。
- Planner 没有建立地点 ownership 优先级，导致前段采用月台，后段又继承原文闸机动作。

**有效方案**

- 若首帧/前序镜头已明确建立在月台，后续过渡应使用“车厢门打开 / 车厢入口 / 上车提示音 / 金属门声”，不要再回到检票闸机。
- 对 SH11/SH12 这类上车过渡镜头，删除 `检票口`、`闸机`、`闸口` 等词，改为 `新干线车厢门`、`车厢入口前`、`列车鸣笛`。
- `source_trace` 也要同步改写为“空间顺序修正版”，否则后续 prompt 审计可能再次把旧闸机词带回。

**系统化改进建议**

- Planning QA 增加空间顺序检查：同一站内流程不得从 `platform/home/月台` 回退到 `ticket gate/检票口/闸机`。
- Source parsing 遇到现实空间矛盾时，应按首帧建立地点与后续镜头连续性选择一种空间路径，并在 `source_trace` 留下修正说明。

### 2026-05-02 10:43:23 JST - Case 117: Source selection schema QA failed 不能被后续 planning QA 掩盖

**现象**

- ScreenScript EP05 v7 的 `source_selection_plan.json` 为 `mode=llm-rules` 且生成 48 shots。
- `source_selection_qa_report.json` 中 `passed=false`，几乎所有 selected shots 都报 `missing_must_include_evidence`。
- 后续 `plan_qa_report.json` 和 final sync QA 仍为 pass，流程继续生成 keyframe、Seedance 和 assembly。

**根因**

- Shared LLM Source Selection Planner 的 schema/QA 要求与实际 LLM 输出不一致：`must_include_evidence` 字段为空数组时被 QA 认为 high severity。
- 生产入口没有把 source selection QA 的 failed 状态作为阻断条件，导致 selection 层的 schema 不合规被后续 planning QA 掩盖。

**有效方案**

- `llm-rules` 模式下，source selection QA failed 应立即停止，除非显式传入允许继续的 debug 参数。
- 若某个 shot 没有实体证据，也必须写出非空 evidence 或明确 `no_physical_evidence_required` 一类结构化说明，避免空数组既像缺失又像无证据。

**系统化改进建议**

- Planning batch preflight 统一读取 `source_selection_qa_report.json`，`passed=false` 时阻断。
- Selection QA finding 应区分 schema 必填缺失、字段允许为空、和 truly critical evidence omitted，避免所有 shots 被同一种 high severity 淹没。

### 2026-05-02 10:43:23 JST - Case 118: 荣誉墙照片不能被当成角色手持照片道具

**现象**

- ScreenScript EP05 SH30 原文是予予说自己在幼儿园走廊荣誉墙上看到了陆景琛照片。
- 实际 keyframe/Seedance 画面中，予予手里举着一张陆景琛照片给沈念歌看，变成了不存在的实体手持照片。
- `source_selection_plan.json` 的 `key_props` 写入 `照片 (荣誉墙), PHOTO_01`，后续 prompt 把它当成普通道具执行。

**根因**

- Source selection / semantic prop extraction 没有区分 `environmental evidence`（墙上照片、门牌、公告栏、荣誉墙文字）和 `held prop`。
- 通用照片规则默认倾向“照片道具可见”，但这里照片属于背景环境记忆/转述内容，不应进入首帧手持道具契约。

**有效方案**

- 对“荣誉墙上/公告栏上/墙上/屏幕上看到的照片”标记为 `environmental_evidence`，只允许作为背景位置证据或回忆信息，不自动生成可拿取的 PHOTO prop。
- SH30 这类低语镜头应表现“孩子凑近说秘密”，照片只作为对白内容，不应手持出现；如果需要视觉化，应另拆一镜走廊荣誉墙 close-up。

**系统化改进建议**

- Prop extraction 增加字段：`prop_ownership = held | worn | environment_mounted | screen_content | quoted_or_reported`。
- Keyframe/Seedance prompt 渲染时，只有 `held` 才写入手持和首帧可见道具约束。

### 2026-05-02 10:43:23 JST - Case 119: 电话远端 speaker 不能反向生成画面内双人对话

**现象**

- ScreenScript EP05 SH41/SH44/SH47 的 selection 明确写了 `dialogue_policy=offscreen far-end speaker`，且 risk note 是远端不 onscreen。
- Records 和 Seedance prompt 却把陆景琛作为画面内 speaker，甚至把赵一鸣和陆景琛渲染成面对面 two-shot。
- SH41 更严重：prompt_core 写成“沈念歌正在听手机语音”，visible characters 包含沈念歌、沈知予、赵一鸣，实际画面也偏离赵一鸣车内接电话。

**根因**

- Semantic dialogue annotation 按台词署名把陆景琛升级为 onscreen active speaker，没有尊重 selection 的 `offscreen far-end speaker`。
- 电话听者/远端 speaker 规则在 record 合成阶段没有统一优先级，导致远端说话人又进入 `visible_characters`、`featured_character` 和 two-shot 视线关系。

**有效方案**

- 当 source line 含“电话里/电话那头/语音/画外声音”或 selection `dialogue_policy=offscreen far-end speaker` 时，record 可见主体必须是现场听者，远端 speaker 只进入 audio/dialogue metadata。
- Prompt 应渲染“赵一鸣听手机里的陆景琛声音，闭嘴反应，陆景琛不出现在画面内”，不能生成陆景琛与赵一鸣面对面。

**系统化改进建议**

- Record QA 增加：offscreen far-end speaker 不得出现在 `first_frame_contract.visible_characters`、`foreground_character_cardinality`、two-shot prompt、character refs。
- Phone scene ownership 应继承最近的现场 setup（车内/黑色轿车/驾驶座），不让单行电话对白重新决定画面地点和可见人物。

### 2026-05-02 11:01:04 JST - Case 120: 月台开场后后续镜头不能回退到检票口/闸机

**现象**

- GinzaNight EP21 SH01 首帧已经建立角色在东京站新干线月台。
- SH11/SH12 已改为新干线车厢门/车厢入口，但 SH09/SH10 仍生成在检票口/闸机背景。
- 抽帧可见 SH09/SH10 背后是自动闸机，和“已经过闸机、人在月台”的空间连续性冲突。

**根因**

- SH09/SH10 的 record、`keyframe_static_anchor`、`prompt_render.shot_positive_core`、source trace 仍保留“东京站新干线检票口前 / 检票闸机背景”。
- Keyframe prompt 和 Seedance prompt 是按 record 执行，问题来自 record 语义层，不是模型执行层单独幻觉。

**有效方案**

- 在同一 train-door variant 中把 SH09/SH10 改为月台内/新干线车门附近的对话反应镜头，禁止 `检票口/闸机/闸口`。
- 改 record 后重跑 SH09/SH10 keyframe，再重跑对应 Seedance。

**系统化改进建议**

- 若 episode 已有首帧建立“已过闸机/已在月台/已进车厢”等空间状态，后续 records QA 应阻断回退到上一区域的地点词。
- 对 station/train 场景增加 spatial stage：outside station -> ticket gate -> platform -> train door -> carriage，后续 shot 只能前进或保持，不能无说明回退。

### 2026-05-02 11:01:04 JST - Case 121: 不完整入画角色的拉手动作会生成陌生人手

**现象**

- GinzaNight EP21 SH12 抽帧中，小樱在车厢入口前，画面右侧伸入一只手，但美咲没有完整入画。
- 观感变成“小樱被陌生人拉手”，破坏人物关系和安全感。

**根因**

- SH12 的 Seedance prompt 写入“美咲手牵其后 / 美咲拉手准备踏入”，但该镜 keyframe 与角色锚定主要只锁小樱。
- record 的 `first_frame_contract.visible_characters` 又要求美咲可见，实际执行层没有给出完整美咲构图，导致模型用局部手部补全动作。

**有效方案**

- 若牵手已经在前一镜 SH11 建立，SH12 应改为小樱独立转向车厢入口/迈步进入，不再写拉手、手牵其后、画外手。
- 若必须保留牵手，则必须让美咲完整可见、脸部可见，并使用美咲角色参考；不能只写一只手或局部身体。

**系统化改进建议**

- Record QA 增加：任何 `handholding / 拉手 / 牵手 / hand reaches in` 动作中，手的 owner 必须完整入画或明确不生成该手。
- 对仅单人构图的 shot，prompt 渲染应删除另一个角色的局部肢体动作，避免模型生成无身份的手臂。

### 2026-05-02 11:17:30 JST - Case 122: LLM selection 的 source_range 不能替代 source_unit_ids 回映射

**现象**

- EP05 使用既有 `source_selection_plan.json` 做 dry-run 时，SH01 的 `source_range=[11,13]` 不能在当前解析后的 screen events 中找到可执行 visual/dialogue 行。
- 这类错位会让 setup 行、地点行或 scene 行被 adapter 丢掉，后续 record 只剩对白或局部动作。

**根因**

- LLM selection 的 `source_range` 可能是 source unit 范围或包含 scene 行，不一定等于 screen script 的可执行行号。
- screen adapter 只按 `source_range/line_range` 取 visual/dialogue/music，没有优先按 `source_unit_ids` 回映射。

**有效方案**

- screen adapter 优先用 `source_unit_ids` 映射回 `SourceUnit.line_start/line_end`，再收集可执行事件。
- 只有缺少可用 `source_unit_ids` 时，才 fallback 到 `source_range`。

**系统化改进建议**

- selection QA 应检查 adapter 能否从每个 selected shot 的 `source_unit_ids` 找到至少一个可执行 beat。
- `source_range` 只作为审计和 source excerpt 范围，不作为唯一执行依据。

### 2026-05-02 11:17:30 JST - Case 123: 电话段必须跟踪现场接听者地点，不能逐行重判

**现象**

- EP05 SH41-SH47 中，LLM selection/semantic 已经表示陆景琛是电话远端，但旧 record 仍把陆景琛放进画面，或把赵一鸣地点从黑色轿车丢到公交/幼儿园门口。
- 生成结果变成面对面 two-shot 或错误地点电话镜头。

**根因**

- record 合成缺少连续通话状态；后续对白行如果没有重复“电话里”，就被当成 onscreen 对话。
- 角色地点没有跨 shot 状态表，前一镜建立的“赵一鸣在幼儿园对面黑色轿车驾驶座”没有稳定传入后续电话镜头。

**有效方案**

- 新增 Character Location Tracker，在 record 渲染前用上一 shot 状态、当前 source、selection、semantic 输出角色地点和 visibility。
- record 合成维护连续电话状态：远端 speaker 不入镜，现场接听/回复者保留为 visible listener/speaker。
- phone listener contract 一旦生成，不允许再被普通 onscreen dialogue blocking 覆盖。

**系统化改进建议**

- 对电话/语音段增加 QA：远端 speaker 不得出现在 visible characters；现场 listener 必须有明确地点和闭嘴听电话动作。
- 对连续地点增加 artifact `character_location_trace.json`，便于检查每个角色在每镜的位置继承依据。


### 2026-05-02 12:06:20 JST - Case 122: 停靠列车镜头不能让反射和阴影暗示列车启动

**现象**

- GinzaNight EP21 SH12 已修为小樱单人站在新干线车厢入口前，但视频里能看到车身反射/影子像在移动。
- 观感变成列车已经启动，而用户要求 SH12 的火车静止不动。

**根因**

- SH12 record 中仍有“列车鸣笛震动铁轨”“列车启动，银座的影子在雾中后退”等运动语义。
- 即使 prompt 写了背景稳定，Seedance 仍会把鸣笛、震动、影子后退解释成车身、反射或窗景移动。

**有效方案**

- 对停靠车门镜头使用正向静止锁：列车处于停靠状态；车身、车门、车窗反射、车内光影、地面影子和窗外城市背景全程固定。
- 鸣笛只作为声音提示，不表现铁轨震动、车身滑动、反射移动或窗外景物位移。

**系统化改进建议**

- train-door / platform shots 增加 `stationary_train_lock` 字段，显式约束车身、反射、阴影、窗景是否可动。
- 若同一 shot 需要车门开启但列车停靠，应区分 `door_motion` 与 `train_body_motion`，避免车门动作扩散成整列车运动。


### 2026-05-02 12:19:00 JST - Case 123: 旁白镜头的转身动作会诱发背影和口型

**现象**

- GinzaNight EP21 SH12 修成停靠列车后，小樱中段转成背影，随后出现疑似开口说话。
- 该镜是旁白镜头，要求小樱全程闭嘴、无口型，且主体脸部应持续可辨。

**根因**

- Prompt 中“回望一瞬后转向车厢内”的动作幅度过大，I2V 会自然生成转身过程，导致脸部不可见。
- 旁白音频存在时，若人物正脸/侧脸可见且动作较多，模型仍可能把声音绑定到人物嘴部。

**有效方案**

- 旁白镜头应使用更小的静态表演：固定三分之二侧脸，轻轻抬眼或微微呼吸，不做完整转身/走动。
- 明确写“嘴唇自然闭合，全程不张口、不说话、不做口型；旁白来自画外”。

**系统化改进建议**

- narration-only shot 的动作复杂度应低于 dialogue shot，优先静态表情和眼神，不使用大幅转身、走动、回头再转向等连续动作。
- 若主体脸部可见是强约束，动作描述不得要求角色转向画面深处或背对镜头。

### 2026-05-02 12:36:47 JST - Case 124: 环境照片不能触发旧手持照片 prop contract

**现象**

- EP05 SH31 原文是孩子口述“幼儿园走廊荣誉墙上的照片”，record 的 `first_frame_contract.key_props` 已为空，但 keyframe prompt 仍注入 `SAKURA_SCHOOL_PHOTO` 的照片道具尺寸、正反面和首帧位置，导致首帧把照片生成为孩子手持照片。

**根因**

- screen2video 复用 `novel2video_plan.build_auto_i2v_contract()` 时，旧小说道具 profile 用通用“照片”命中 `SAKURA_SCHOOL_PHOTO`。
- record 渲染层没有在“荣誉墙/墙上/展板照片”语境下清除手持 photo prop contract。
- QA 会扫描 first-frame 元信息，`semantic_quality.reasoning_brief` 中保留“背影”等词时也会触发首帧背面人物 high finding。

**有效方案**

- `SAKURA_SCHOOL_PHOTO` 只允许由“樱子照片/小樱照片/佐藤樱子照片/校服照片”等明确词触发，不再由泛化“照片”触发。
- screen record 渲染时，若 source 明确为荣誉墙/墙上/展板照片，清除所有手持 photo prop library/contract/key_props，并把“墙面或荣誉墙上的固定照片”写入 scene overlay。
- 对进入 first-frame 的语义质量文字也执行首帧可视化用语清洗，避免 QA 被元信息误触发。

**系统化改进建议**

- 视觉资产/manifest/profile 只能补充 record 已请求的道具字段，不能因为 alias 或历史 profile 自行添加新道具。
- 环境照片、荣誉墙、墙上展板应作为 scene overlay / environment_mounted_photo，不进入手持照片正反面规则。

## 2026-05-02 12:47:30 JST - EP21 旁白、服装细节、小道具数量和重复 beat 复发

### Case 125: 旁白镜头使用 Seedance 自带音频会把中文旁白带偏或绑定到可见人物嘴部

**现象**

- GinzaNight EP21 SH01 record/prompt 中旁白文本是中文“晨雾压低了过去。”，但成片旁白不是中文。
- SH07 是旁白镜头，record/prompt 已写“佐藤美咲全程闭嘴无口型”，但成片中美咲仍出现疑似开口。

**根因**

- `generate_audio=true` 时，Seedance 的语音语言锁只是 prompt 软约束；东京站、新干线ホーム等日语环境词会把模型音频带向日语或混合语境。
- 当画面中有清楚人脸且音轨存在旁白时，I2V 会倾向把声音绑定到可见人物嘴部，即使 record 写明旁白来自画外。

**有效方案**

- narration-only shots 默认使用 `generate_audio=false` 生成闭嘴视频。
- 中文旁白用后期 TTS/音频合成叠加，不能依赖 Seedance 自带音频。
- 视频 prompt 中明确“视频阶段无声；中文旁白后期合成；可见人物全程嘴唇闭合，不做说话口型”。

**系统化改进建议**

- run_seedance 层遇到 `dialogue_lines=[]` 且 `narration_lines` 非空时，默认关闭模型音频并输出 post-audio cue。
- assembly 或 post-audio 阶段统一把 narration cue 合成到无声视频，避免每个镜头手工修。

### Case 126: 原文亲密/服装细节不应默认进入逃离月台镜头视觉 prompt

**现象**

- EP21 SH01/SH02 原文有“旧礼服肩带隐约滑落一丝”“凉滑贴近肌肤”。
- record 将该细节写入 first-frame costume modifiers 和 `prompt_render.shot_positive_core` 后，成片中美咲出现不必要的肩部裸露。

**根因**

- record 生成时过度保留小说感官细节，没有判断该细节是否是当前短视频镜头的必要剧情信息。
- 逃离、托付、月台离站这类镜头中，服装暴露细节会抢夺叙事重点，并增加不必要的安全和审美风险。

**有效方案**

- 将该类细节降级为可省略文学描写，不进入 I2V visual prompt。
- 使用正向服装契约：“完整灰色上衣覆盖双肩、锁骨和上臂；衣领和袖线稳定贴合”。
- 同步清理 source trace、first-frame contract、prompt_render 和 keyframe_static_anchor，避免旧词在任一层泄漏。

**系统化改进建议**

- planner 对“肩带、肌肤、凉滑、贴近”等感官服装词做视觉必要性过滤。
- 未成年人同框、逃离/保护类镜头优先使用完整衣着和社交距离表达关系，不用身体暴露表达情绪。

### Case 127: 小型手持道具数量只留在 prop_contract 不足以阻止 I2V 复制

**现象**

- EP21 SH06 record 的 `prop_library.count` 和 `quantity_policy` 已写“1支，无新增副本”，但成片中石川手部出现两支香烟观感。

**根因**

- 最终 Seedance prompt 的画面主体只写“手指夹着未点燃的香烟”，没有把“画面中只能出现1支香烟、另一只手放入口袋、禁止烟盒和多根白色细条”等硬约束写进主视觉句。
- 香烟体积小、靠近手指，I2V 容易把手指边缘或高光复制成第二根细白物体。

**有效方案**

- 数量约束必须进入 `prompt_render.shot_positive_core` 和 keyframe prompt 的主视觉句。
- 对香烟这类细长小道具写清：只在一只手指间出现一支；另一只手放入口袋；不出现烟盒或其他细白条。

**系统化改进建议**

- 对 `count=1支/1个/1张` 的小型手持道具，prompt renderer 自动把数量和禁止副本提升到最终视频 prompt 主体，而不只放在 prop contract。

### Case 128: 同一人物同一地点同一句台词被拆成两镜时必须去重

**现象**

- EP21 SH06 和 SH08 都来自同一 target fact：石川在月台边缘夹烟低喃。
- 两条 record 都写了同一句台词“守护孩子，比抓犯人更重要。”，keyframe 和 Seedance prompt 也几乎相同，最终成片出现重复镜头和重复台词。

**根因**

- shot 拆分把“石川出现 / 美咲反应 / 石川低喃”拆成多个镜头后，没有明确区分建立镜头、反应镜头和台词镜头。
- record 生成缺少邻近 shot 去重检查：同一角色、同一地点、同一句对白在相邻几镜内重复时没有报警。

**有效方案**

- SH06 改为石川无台词观察镜头，只建立烟草味来源和人物存在。
- SH07 保持美咲无台词反应并后期旁白。
- SH08 才是唯一石川台词镜头。

**系统化改进建议**

- planning QA 增加近邻重复对白检查：同一 speaker + 同一 text + 同一 scene 在 3 个 shot 内重复，默认 blocking。
- 对同一 fact 拆多镜时，必须给每个 shot 明确不同 primary task：establishing / reaction / dialogue，不得三者都写成 dialogue。

## 2026-05-02 13:08:10 JST - 后期旁白不能静默降级为系统 TTS

### Case 129: OpenAI TTS key 只在 `.env` 中时，后期旁白脚本若不加载 `.env` 会退化成机械系统声音

**现象**

- EP21 SH01/SH02/SH07 为避免旁白驱动角色开口，先用无声 Seedance 视频，再后期合成中文旁白。
- 首版后期旁白听感机械、生硬、情绪薄，明显不像电影短剧旁白。

**根因**

- `OPENAI_API_KEY` 没有出现在当前 shell 环境中，但项目根目录 `.env` 实际有 key。
- 后期补音临时流程只检查了环境变量，没有像 keyframe/Seedance 脚本一样加载 `.env`，于是降级使用 macOS `say -v Tingting`。
- 系统 TTS 缺少自然气息、情绪控制和电影化停顿，短句更容易暴露机械感。

**有效方案**

- 后期 TTS 真实调用前必须先加载项目 `.env`，或使用同一套 dotenv helper。
- 若 OpenAI TTS 不可用，应显式阻断或向用户说明，不应静默降级为系统声音并覆盖成片。
- 对旁白镜头，保留无声视频作为底片，只替换音轨；无需重跑 keyframe 或 Seedance。

**系统化改进建议**

- 增加统一 post-audio 脚本：读取 record 的 post-audio cue，加载 `.env`，生成 OpenAI TTS，合成音轨并写入 manifest。
- manifest 应记录 TTS provider、model、voice、instructions、文本、输出音频路径和是否发生 fallback。
- fallback 到本机系统 TTS 时默认只生成 preview，不覆盖正式 `output.mp4`。

## 2026-05-02 13:25:20 JST - Seedance 自带旁白需要候选循环和音频转写 QA

### Case 130: 旁白交给 Seedance 生成时，日语场景词会污染语种，正脸反应镜头会把旁白绑到嘴

**现象**

- EP21 SH01/SH02/SH07 改为 Seedance 生成普通话画外旁白后，第一轮候选中 SH01 音频转写为非中文内容，SH07 画面中美咲在旁白期间明显张口。
- 第二轮去掉 `ホーム` 等日语场景词后，SH01 音频转为中文；SH07 仍出现口型。
- 第三轮把 SH07 改成静态反应镜头，要求身体、头部、嘴部和下颌像静态照片一样不动，只允许眼神变化，才得到嘴部稳定闭合的候选。

**根因**

- 即使语言锁写了普通话，prompt 开头的日语地点词仍会影响 Seedance 音频语言分布，可能生成非中文或混合语音。
- 当旁白镜头中人物正脸清晰且有轻微表情动作时，Seedance 容易把画外旁白当成可见人物口型。
- 普通“闭嘴、不做口型”约束对正脸中近景不够，需要把运动区域限制到眼神或手部，并把嘴部/下颌写成静态不可动。

**有效方案**

- 旁白候选采用最多三轮循环：生成后抽帧检查嘴部，抽取音频转写检查语种；失败的 shot 单独重跑。
- 有模型音频的中文旁白镜头中，scene header 使用中文地点词，例如“月台”，避免 `ホーム` 等日语词出现在 prompt 开头。
- 对高风险反应镜头，写成“静态照片式表演”：身体、头部、嘴部和下颌不动，只允许眼神变化；旁白来自画外，不属于可见人物。
- 2026-05-02 13:44:35 JST 起，`scripts/run_seedance_test.py` 默认对 `dialogue_lines=[]` 且 `narration_lines` 非空、并且 `generate_audio=true` 的 record 启用 Seedance 旁白候选循环：最多 3 次，生成 contact sheet、抽取音频、转写检查语种、视觉检查口型风险，并把最佳候选提升为正式 `output.mp4`。

**系统化改进建议**

- post-Seedance QA 应自动抽取旁白期间帧序列，检测可见人物口型风险，并保存 contact sheet。
- 对 `narration_lines` 且 `generate_audio=true` 的镜头，自动抽取音频转写；若转写明显非目标语言，应标记失败并重试。
- 旁白镜头 prompt renderer 应将日语/英语环境词从音频敏感的 compact header 中移出，只放入无声背景文字规则。

## 2026-05-02 13:30:00 JST - 跨项目默认背景锚点不能进入 record

### Case 131: SampleChapter EP02 背景人群被写成“银座酒店或街头背景人群”

**现象**

- `novel/sample_chapter/SampleChapter_EP02_fullrun_20260502` 从头跑通，planning QA、sync QA 都通过。
- 但 `EP02_SH07_record.json` 和 `EP02_SH09_record.json` 的 `character_anchor.primary.visual_anchor` 写入了“银座酒店或街头背景人群，低调真实，只作为环境反应存在”。
- 同一 record 的 `language_policy.rules` 还包含“东京/银座环境可以出现日文招牌”，与 SampleChapter 的西汉长安集市场景冲突。
- Keyframe prompt 仍主要使用古代集市场景，且 scene visual ref 正确；但 Seedance `prompt.final.txt` / `payload.preview.json` 会把错误背景锚点带入最终视频提示词。

**根因**

- 错误发生在 planning record 层，而不是 keyframe reference 或 Seedance payload 层。
- 通用/旧项目默认值把 Ginza/Tokyo 背景群体和语言环境规则带进了非 Ginza 项目。
- QA 当前只检查计划结构与同步，没有检查 record 中是否出现跨项目地点、时代或语言政策污染。

**有效方案**

- 修当前片时，应回写受影响 record：把背景人群 visual anchor 改成“西汉长安村口集市围观闲汉和农妇，只作为环境反应存在”，并删除东京/银座语言规则；然后重跑 SH07/SH09 keyframe、Seedance 和 assembly。
- 修未来片时，背景群体默认锚点必须从 project bible / episode scene context 派生，不能使用硬编码现代 Ginza/Tokyo fallback。

**系统化改进建议**

- Planning QA 增加跨项目污染检查：古代/非东京项目中出现“银座、东京、日文招牌、酒店”等不属于 project bible 的地点/时代词时阻断或高危报警。
- Prompt render QA 增加 record-to-final prompt audit：`character_anchor.*.visual_anchor` 与 `setting/time_period/location` 冲突时阻断。
- 背景群体不应作为 primary character anchor 写入带项目特定身份描述的锁定块；应作为场景人群层，且由当前场景文本约束。

## 2026-05-02 13:52:47 JST - llm-rules selection 不等于 records 由 LLM 生成

### Case 132: SampleChapter EP02 只在 selection/tracker 用了 LLM，planning records 仍由 heuristic backend 生成

**现象**

- `run_novel_episode_batch.py` 跑 `SampleChapter EP02` 时传入了 `--selection-mode llm-rules`，产物中也有 `source_selection.rules.request/response.json` 和 `character_location_tracker.request/response.json`。
- 用户检查 keyframe 人物锁定后发现 record 层已出现主角锚点缺失和跨项目背景人群污染。
- 进一步检查命令和日志发现 planning 阶段打印 `backend: heuristic`，且 `llm_requests/` 中没有 `episode_fact_table.response.json`、`episode_script_and_shots.response.json` 或逐镜 `SHxx.response.json`。

**根因**

- `--selection-mode llm-rules` 只控制 source selection / merging，不控制 planning record backend。
- `novel2video_plan.py` 的 `--backend` 默认仍是 `heuristic`，batch/webui 入口也没有显式传 `--backend llm`。
- `run_llm_backend()` 在 LLM key 缺失或主规划失败时会保留 heuristic output，导致“看起来用了 LLM”，但正式 records 仍是 heuristic。

**有效方案**

- `novel2video_plan.py` 默认 backend 改为 `llm`；batch/webui 入口显式传 `--backend llm`。
- Source parsing 增加 `--source-parse-mode llm-rules`，生产默认先做 raw segmentation，再做 LLM-with-rules semantic parsing。
- LLM 主规划失败、key 缺失或 requests 不可用时 fail-fast，不再静默保留 heuristic output。
- README 明确：只有 `source_selection.*` 或 `character_location_tracker.*` 不足以证明 records 是大模型生成；必须有主规划 LLM 响应产物。

**系统化改进建议**

- Planning QA 应检查 backend provenance：正式 bundle 中 `backend != llm` 或缺少主规划 LLM response 时阻断。
- Director / Seedance 入口应 preflight 检查 bundle provenance，避免坏 records 继续进入 keyframe 和视频生成。
- CLI 日志应把 `source_parse_mode`、`selection_mode`、`backend` 和主规划 response 路径一起打印，降低误判。

## 2026-05-02 14:02:08 JST - LLM source parsing 不能整本一次性返回

### Case 133: SampleChapter 全文 1199 个 source units 单次 LLM parsing response 被截断

**现象**

- `SampleChapter EP02` 启用 `--source-parse-mode llm-rules --backend llm` 后，source parsing 阶段先写出 `source_units.raw.json`，但 live run 在解析 LLM response 时失败。
- 原始请求一次包含 1199 个 source units，request 约 447KB；返回 JSON 在约 68KB 处截断，导致 `json.decoder.JSONDecodeError: Expecting ',' delimiter`。
- dry-run 证明未分块时只生成一个 `source_parsing.rules.request.json`，后续 selection/planning 无法进入。

**根因**

- Source parsing 需要保留每个 unit 的 id、文本、行号和语义字段；整本一次性要求 LLM 返回完整结构化数组，输出 token 与 JSON 完整性风险过高。
- 这是 model execution / orchestration 层问题，不是原文解析规则本身的问题。

**有效方案**

- Novel source parsing 先按 `第 N 章 = EP N` 的规则缩小到本集章节；SampleChapter EP02 从 1199 个整本 raw units 缩到第 2 章 74 个 units。标题/source_basis 只作为找不到章节编号时的 fallback。
- LLM-with-rules source parsing 按固定小批次处理 source units，当前默认每 20 个 units 一个请求。
- 每个分块写出 `llm_requests/source_parsing.rules.partNNN.request.json` 和对应 response，成功后合并为 `source_parsing_plan.json`、`source_parsing_qa_report.json` 以及聚合 `source_parsing.rules.response.json`。
- QA 合并后检查 missing/extra unit、文本/行号被改写、跨项目污染词等，阻止坏解析进入 selection。

**系统化改进建议**

- 对长篇小说 source parsing，默认先按章节编号做 episode scoping，再分块；禁止整本一次性结构化返回。
- Source parsing request/response manifest 应记录 chunk size、chunk count、每段 units 范围和是否 dry-run，方便复盘成本与失败点。
- 若某一 chunk 失败，应只重试该 chunk，而不是重跑整本 parsing。

## 2026-05-02 14:35:20 JST - LLM record 中可见临时人物必须进入 anchor

### Case 134: SampleChapter EP02 胖婶子可见且说话，但 record anchor 只保留主角

**现象**

- `SampleChapter EP02` 走 `--backend llm --source-parse-mode llm-rules` 后，source parsing、selection、逐镜 LLM response 都已落盘。
- `EP02_SH07_record.json` 的 `first_frame_contract.visible_characters` 包含“林辰、胖婶子”，`speaking_state` 和 `dialogue_lines` 也表明胖婶子是画面内说话人。
- 但 `character_anchor` 只包含林辰，planning QA 阻断 `onscreen_dialogue_speaker_not_in_character_anchor: 胖婶子`。类似地，SH09 的胖婶子/农妇、SH13 的赵霸手下小偷/赵霸虽在首帧可见，但缺少相应临时 anchor 时会增加 keyframe 人物漂移风险。

**根因**

- LLM 已经生成了正确的可见人物和说话状态；问题发生在 record normalization / anchor resolving 层。
- 旧 resolver 主要从主角表和少量硬编码临时角色中匹配，只把对白相关人物或主角放入 `character_anchor`，没有把 LLM `first_frame_contract.visible_characters` 中的未知临时人物补成 episode-local anchor。
- 通用临时人群 fallback 还残留“银座酒店或街头背景人群”的跨项目描述，非东京古代项目会被污染。

**有效方案**

- Anchor resolving 同时读取 `visible_dialogue_characters` 和 LLM `first_frame_contract.visible_characters`。
- 对找不到角色表匹配的个体型临时可见人物，生成 episode-local `EXTRA_TEMP_*_LOCK_V1` anchor；对人群/农妇/家丁等群体型临时人物只写环境型 anchor，不启用锁。
- 临时 anchor 的 visual_anchor 只引用源文本、本镜头 first_frame_contract、位置/脸部可见/动作/时代地点，不继承主角脸、主角服装或跨项目默认背景。
- 非东京/非日本项目的 language policy 不允许日文招牌或现代日本街景文字；东京/银座 signage 只在源文本确实需要时出现。

**系统化改进建议**

- Planning QA 应继续阻断：画面内说话人不在 `character_anchor`、两人可见但缺少对应 anchor、跨项目地点/语言污染。
- Keyframe preflight 应检查：`first_frame_contract.visible_characters` 中的个体型人物是否都有 anchor 或明确标记为群体背景。
- 临时人物 anchor 应尽量从 LLM semantic/source parsing metadata 中提取身份、位置和动作，规则层只做 schema completion，不擅自改写剧情。

## 2026-05-02 15:43:41 JST - 混合 chained/base clips 时 QA 必须使用 assembly 的 clip overrides

### Case 135: SampleChapter EP02 已成功 assembly，但 sync QA 仍 probe 基础 seedance 目录的缺失 clip

**现象**

- `SampleChapter EP02` 完整跑片时，assembly 已使用 `test/samplechapter_ep02_llm_rules_v2_chained_seedance/clip_overrides.json`，最终视频 `EP02_final.mp4` 成功生成。
- `assembly_report.json` 记录 SH03、SH04、SH07、SH08、SH11、SH12 实际来自 chained seedance 目录。
- QA 阶段仍只解析基础 seedance 目录下的 `concat_ep02.txt`，尝试 `ffprobe test/samplechapter_ep02_llm_rules_v2_seedance/SH03/output.mp4`，因该路径不存在而失败。

**根因**

- Assembly 层支持 `--clip-overrides` 并正确替换 mixed-generation clips。
- `qa_episode_sync.py` 只按 concat 文件 probe clip duration，没有读取同一份 overrides，也没有用 `assembly_report` 的已解析 clip path。
- Batch QA 调用没有把 chain `clip_overrides.json` 继续传给 QA，导致 QA 检查的素材集合与最终成片素材集合不一致。

**有效方案**

- `qa_episode_sync.py` 增加 `--clip-overrides`，按 shot id 将 concat 中的基础 clip 路径替换为 assembly 实际使用的 chained clip 路径。
- `run_novel_episode_batch.py` 在启用 shot chaining 且 overrides 存在时，把同一份 `clip_overrides.json` 传给 QA。
- QA report 写入 `applied_clip_overrides`，方便复盘检查的是最终成片使用的 clip。

**系统化改进建议**

- 所有 post-assembly QA 都应以 assembly 实际 resolved clip list 为准；concat 文件只能作为基础顺序来源。
- mixed-generation assembly 的 report/QA 应统一记录 clip provenance，避免基础目录、chained 目录和修音输出之间发生 silent drift。

## 2026-05-02 15:43:41 JST - Prop visual bible QA 不能把短但明确的值判为缺失

### Case 136: SampleChapter EP02 道具 count/material 值为“1”等短字段时被误判缺失

**现象**

- `SampleChapter EP02` visual refs 阶段生成 `CLOTH_BAG_MONEY`、`CLAY_JAR`、`BROKEN_CLOTH_BAG` 等道具 bible 后，QA 报 `count 缺失` 或 `material 缺失`。
- 实际 LLM/normalize 输出中存在 `count: "1"` 或简短材质值，只是长度较短。
- 部分小道具被 LLM 标为 `reference_mode=scale_context`，但没有完整填入 `scale_policy/reference_context_policy`，导致后续 QA 阻断。

**根因**

- Prop visual bible QA 将 `count/material` 的长度阈值当作存在性判断，短而明确的结构化值被误判为空。
- Normalize 阶段接受了 LLM 的 `scale_context` 选择，但没有在缺少 scale policy 时补齐默认政策。

**有效方案**

- `count/material` 只要非空即视为存在，不用长度阈值判断。
- 若 LLM 输出 `reference_mode=scale_context` 且 scale policy 缺失或过短，normalize 阶段补入默认 `scale_policy` 和 `reference_context_policy`。

**系统化改进建议**

- Visual bible QA 应区分“结构化字段为空”和“字段值短但有效”，尤其是 count、material、color 这类可能天然很短的字段。
- `scale_context` 的默认补全应在进入 QA 前完成，保证 LLM 只负责语义选择，规则层负责 schema completeness。

## 2026-05-02 15:45:56 JST - 单镜长台词不能超过视频生成时长上限

### Case 137: SampleChapter EP02 SH04 单句对白估算 17.15 秒，但 Seedance clip 只有 12.05 秒

**现象**

- SH04 语言计划中一整句林辰对白 `spoken_total_sec=17.15`，但 `duration_overrides.json` 被 provider 上限 clamp 到 12 秒。
- Seedance prompt 写成 `0.5-11.5秒` 内完成整句对白，生成 clip 为 12.05 秒。
- Sync QA 按语言计划检查时阻断 `early_scene_cut`，提示 12.05 秒小于 17.27 秒需求。

**根因**

- Planning/selection 阶段没有在进入视频生成前把超过 provider 单镜上限的长台词拆成多个 shot，导致语言计划和视频 payload 的时间预算不一致。
- `build_episode_language_plan.py` 虽然记录 `max_duration_limit_risk` 并 clamp duration，但 batch strict 阶段没有在 Seedance 前把该风险转成拆镜或阻断。

**有效方案**

- 当前修片：先抽取 SH04 模型音频转写，确认完整台词已在 12 秒内说完；再将 SH04 末帧延长到 17.5 秒，音频后段补静音，作为 `output.sync_extended.mp4` 写入 `clip_overrides.json` 并重做 assembly/QA。
- QA 最终通过，且 `assembly_report.json` 明确 SH04 使用修复后的 extended clip。

**系统化改进建议**

- 规划/语言计划阶段应把 `spoken_total_sec + margin > provider_max_duration` 作为 blocking，优先要求 LLM 拆镜，而不是只 clamp duration。
- 如果用户选择后期修片，必须先转写或人工核验原 clip 是否包含完整台词；不能只靠延长静帧让 QA 通过。
- `duration_overrides.json` 应同时记录 unclamped recommended duration 和 provider-clamped duration，便于 batch 阶段发现时间预算丢失。

## 2026-05-02 16:58:30 JST - 厨房刀具递交首帧需要非攻击化安全表达

### Case 138: SampleChapter EP03 SH08 “递菜刀提醒小心”触发 OpenAI keyframe violence moderation

**现象**

- EP03 从头跑时，SH08 keyframe 连续 10 次被 OpenAI 图像安全系统拒绝，错误为 `safety_violations=[violence]`。
- SH08 record 的剧情事实是阿翠递菜刀给林辰并提醒“辰哥，小心！”，keyframe prompt 同时包含“菜刀”“战斗余波”“小心”等词。
- 其它 12 个 keyframes 均已生成，只有 SH08 缺失，导致 image input map 初次只有 12 条。

**根因**

- 问题在 keyframe prompt rendering / model execution 层，不是 source parsing 或角色 anchor。
- “可见刀具 + 战斗余波 + 小心提醒”组合让首帧被判为暴力生成请求，即使剧情意图是递交道具而非伤害。
- 单镜重跑 SH08 会覆盖 `keyframe_manifest.json`，需要再做全 shot no-overwrite manifest pass，否则 image input map 会只剩单镜条目。

**有效方案**

- 保留 record 事实“阿翠递厨房工具给林辰”，但将首帧视觉表达改为：粗布包裹的小型厨房工具、木柄朝外、金属部分完全藏在布内、不出现锋利边缘、非攻击姿态、无冲突动作。
- 同步更新正式 record 和 keyframe static record，再只重跑 SH08 keyframe；生成成功后，全 shot no-overwrite 重建 keyframe manifest，再重建 image input map 至 13 条。
- 后续 Seedance 使用修复后的 SH08 首帧成功生成，最终 assembly 和 sync QA 均通过。

**系统化改进建议**

- Keyframe prompt renderer 遇到厨房刀具/工具递交且同场有冲突语境时，应默认首帧使用“包裹/木柄朝外/金属不外露/非攻击姿态”的安全构图。
- 对 source truth 中的刀具，不应删除剧情事实；应在首帧层做非攻击化呈现，并把攻击/伤害动作留给 offscreen 或后续可控镜头表达。
- 单 shot keyframe rerun 后，应自动 merge 或 rebuild manifest，避免覆盖全片 manifest。

## 2026-05-02 18:12:00 JST - WebUI artifact history must trust real shot files over incomplete manifests

### Case 126: GinzaNight EP21 clips existed for SH01-SH13 but WebUI counted only seven clips

**现象**

- GinzaNight EP21 的 `test/ginzanight_ep21_train_door_narration_v1_seedance/SH01-SH13/output.mp4` 均存在。
- WebUI shot browser 能在部分 inspector 中预览 clip，但顶部计数只显示 7 个 clips，部分历史版本也无法选择。

**根因**

- WebUI 索引层把 `run_manifest.json` 的 shot 列表当作硬过滤器，导致真实存在但 manifest 未完整声明的 `SHxx/output.mp4` 被漏掉。
- 旧表还把 shot keyframe/clip 混进 assets review 语义，缺少 project/episode/shot 级别的候选历史和用户选择状态。

**有效方案**

- 建立 WebUI-only artifact index：扫描真实文件优先，任何 `test/<run>/SHxx/output.mp4` 都作为 clip candidate。
- `run_manifest.json`、`keyframe_manifest.json`、prompt、payload、image input map 和缓存 data URI keyframe 只作为 candidate metadata。
- 用户选择持久化到 WebUI SQLite，不修改 record JSON、生成文件或 manifest；record 仍是 source of truth。

**系统化改进建议**

- WebUI browsing/indexing 不应使用 manifest shot 列表作为真实文件存在性的硬过滤器。
- 对每个 project/episode/shot 维护 keyframe/clip candidate history，并区分 default/latest selection 与 user override。
- 后续若 assembly 需要引用 WebUI selection，应作为独立功能显式实现，不能静默改写当前生成产物。

## 2026-05-02 20:17:27 JST - GinzaNight EP03 record QA phone/photo/prop false positives

### Case 130: EP03 planning QA failed after valid source selection because record post-processing misclassified visual details

**现象**

- GinzaNight EP03 source parsing and source selection passed, but planning QA failed before keyframes.
- Findings included `i2v_phone_screen_orientation_missing` on nearly every shot, `i2v_photo_side_visibility_missing` on SH03, `i2v_dialogue_action_prop_overload` on SH08, and earlier `i2v_prop_canonical_profile_missing` on SH11.
- Probe showed the phone QA was triggered by the language policy phrase `普通话中文` containing `通话`, not by an actual phone call in those shots.

**根因**

- A generic phone orientation rule matched broad visual text instead of only real phone-call/listener shots.
- Smartphone-as-photo-display shots need visible screen content, so they must not inherit the phone-call default `screen facing inward / content hidden`.
- Photo profiles with `front_description/back_description` in `prop_library` were not always copied into each `prop_contract`, and some back descriptions omitted the literal word `背面`, failing strict QA text checks.
- `名片/CARD` was not classified as a true prop, so old business cards could be moved out of prop contracts as scene modifiers.
- Dialogue shots that mentioned an offscreen phone pickup setup overloaded one onscreen speaker with an unrelated prop/action.

**有效方案**

- Limit phone orientation QA to actual phone-call visual terms or `source=phone` dialogue; do not match the substring `通话` inside `普通话中文`.
- When LLM provides a specific phone/smartphone prop such as `KENICHI_PHONE`, drop the generic auto `KENICHI_SMARTPHONE` duplicate.
- Enrich photo prop contracts from photo prop library profiles and force literal `照片正面` / `照片背面` wording where needed.
- Treat `CARD/名片/卡片` as true props and add an `OLD_BUSINESS_CARD` canonical profile.
- Strip offscreen phone setup wording from onscreen dialogue shots; let the dedicated phone-listener shot handle the call.

**系统化改进建议**

- QA rules should distinguish language-policy text from visual/action text before keyword matching.
- A phone used as evidence display is a prop-display shot, not a phone-call shot; only phone-call shots get inward-screen listener defaults.
- For two-sided visual evidence props, required side/count/orientation fields should be normalized structurally rather than depending only on text snippets.

## 2026-05-02 20:27:04 JST - Visual asset contrast bible parser must tolerate trailing model output

### Case 131: EP03 visual refs failed because Grok returned extra data after character contrast JSON

**现象**

- GinzaNight EP03 passed planning QA, then failed at `scripts/create_visual_assets.py` during character reference generation.
- Error: `character contrast bible generation failed after 4 attempts ... JSON 解析失败: Extra data`.
- The failure happened before keyframes, Seedance, or assembly; it was visual asset prompt/LLM response parsing.

**根因**

- `visual_asset_core.extract_json_object()` parsed the entire model response with `json.loads`.
- On parse failure it retried from first `{` to last `}`, which still fails if the model emits two JSON objects or a valid JSON object followed by extra structured text.
- The contrast bible generator already validates the parsed object structurally, so the parser only needs the first complete JSON object.

**有效方案**

- After locating the first `{`, use `json.JSONDecoder().raw_decode()` to parse the first complete object and ignore trailing text.
- Keep existing schema validation after parsing, so malformed or incomplete first objects are still rejected.

**系统化改进建议**

- Any LLM JSON parser used in production retries should tolerate fences and trailing explanatory text, then validate structurally.
- If a parser supports recovery, record the raw response path or model name in error metadata to make future incidents easier to audit.

## 2026-05-02 21:10:45 JST - Short judgment dialogue in transition shots

### Case 132: EP04 SH12 short exclusion line was flagged as dialogue/action/prop overload

**现象**

- GinzaNight EP04 planning used the correct chapter range and produced 13 shots, but strict plan QA failed on SH12 with `i2v_dialogue_action_prop_overload`.
- SH12 source combines several transition facts: Yamada is temporarily excluded, Misaki reacts to the unfinished novel, Ishikawa takes out the Acher driving-record folder, and the line “暂时排除山田。”

**根因**

- The QA rule treated any dialogue plus complex action plus prop contract as overload.
- For a very short judgment/announcement line, the dialogue can function as a transition marker while the visual task remains a controlled transition.
- A separate overly broad auto-prop trigger matched `山田老先生` and injected `OLD_BUSINESS_CARD` into unrelated Yamada shots, inflating prop text and overload risk.

**有效方案**

- Remove `山田老先生` from the `OLD_BUSINESS_CARD` auto-detection tokens; only explicit `旧名片/名片` should trigger that prop.
- Allow a narrowly scoped exception for single-speaker short judgment/announcement lines (<=12 chars, e.g. 排除/宣布/判断/线索) so transition shots with source-truth micro-dialogue do not fail solely because they also carry transition props.

**系统化改进建议**

- Auto-prop token lists must not include ordinary character names unless the character name is part of the prop itself.
- Dialogue/action overload QA should distinguish full dialogue performance from short procedural announcements that label a transition beat.

## 2026-05-02 21:44:32 JST - Chained Seedance overlapping groups need fallback clips

### Case 133: EP04 chained Seedance skipped overlapping groups and left SH08/SH12 missing

**现象**

- EP04 keyframes and ordinary Seedance subset succeeded.
- Shot chain plan had high-confidence overlapping groups: `SH06->SH07`, `SH07->SH08`, `SH10->SH11`, `SH11->SH12`.
- `run_chained_seedance.py` generated `SH06`, `SH07`, `SH10`, `SH11`, but skipped `SH07->SH08` and `SH11->SH12` with `overlapping_chains_are_not_auto_executed_in_v1`.
- Batch assembly then failed with missing clips: `SH08`, `SH12`.

**根因**

- `run_novel_episode_batch.py` removed all chain-plan shots from ordinary Seedance, assuming chained execution would produce every shot in those groups.
- `run_chained_seedance.py` intentionally skips overlapping groups, so some chain-listed shots may not be generated by either ordinary or chained execution.

**有效方案**

- Before assembly, after loading chained `clip_overrides`, call `ensure_outputs_exist`.
- If clips are missing and the seedance stage is enabled, run a fallback ordinary Seedance pass for exactly the missing shots, then re-check outputs before assembly.

**系统化改进建议**

- Chain planning and batch scheduling must distinguish “candidate chain shots” from “actually produced chain clips”.
- Any chain runner that skips groups should either emit fallback requirements or the batch runner must derive them from missing outputs.

## 2026-05-02 22:49:10 JST - Tiny speech-tail underrun after chained Seedance

### Case 134: EP05 SH02 failed sync QA by 0.102 seconds despite complete assembly

**现象**

- EP05 assembled successfully with all 13 clips, but sync QA failed with one `early_scene_cut` finding.
- SH02 generated by chained Seedance was 12.05s; language QA required 12.152s because spoken content plus tail safety margin exceeded the clip by about 0.102s.

**根因**

- Seedance returned the expected nominal 12s clip, but the language plan's spoken duration nearly filled the full clip.
- The QA rule correctly requires a small tail margin after speech completion, so a visually complete clip can still fail sync safety by a fraction of a second.

**有效方案**

- For sub-second tail-margin failures, pad the affected clip tail with a frozen last frame plus silence instead of rerunning the whole episode.
- Update clip overrides to point to the padded clip, reassemble, and rerun sync QA.

**系统化改进建议**

- Batch QA repair can safely offer an automatic padding repair when `needed_sec - clip_duration_sec` is small and the issue is only tail safety margin.
- Do not shorten language timing or alter record dialogue to satisfy duration QA; preserve record content and add neutral tail room.

## 2026-05-03 14:10:34 JST - Stale auto props must be pruned from records, not only deleted from assets

### Case 135: EP01 generic scarf auto profile reintroduced `AYAKA_LIGHT_BLUE_SCARF` after the asset library no longer wanted it

**现象**

- EP01 source and LLM shot responses define the key scarf as `PINK_SILK_SCARF` / `SILK_SCARF_PINK` with `浅粉色丝巾`.
- Existing EP01 records for `SH01/SH02/SH03/SH06/SH07` also contained `AYAKA_LIGHT_BLUE_SCARF` in `i2v_contract.prop_library` and `i2v_contract.prop_contract`.
- Keyframe prompts therefore rendered both the wrong blue scarf contract and the correct pink scarf contract, allowing stale prop references and visual-reference assets to pollute downstream keyframes.

**根因**

- `KNOWN_PROP_PROFILES` in `scripts/novel2video_plan.py` matched the generic token `丝巾` and auto-injected `AYAKA_LIGHT_BLUE_SCARF`.
- Deleting or excluding the visual asset was insufficient because the record remained the source of truth and still referenced the stale prop id.

**无效或不充分方案**

- Only delete `AYAKA_LIGHT_BLUE_SCARF` asset files or remove it from the active asset catalog. Keyframe and prompt renderers can still revive the stale prop from record JSON.
- Only rely on prompt wording like `浅粉色丝巾` while the structured `prop_contract` still contains a conflicting blue scarf id.

**有效方案**

- Narrow the auto profile trigger from generic `丝巾` to explicit blue-scarf terms only.
- During `merge_i2v_contract`, suppress auto `AYAKA_LIGHT_BLUE_SCARF` when the LLM/source contract already defines a pink scarf, and leave a `removed_prop_tombstones` entry.
- Use structured record pruning for existing polluted records: remove the stale prop from `prop_library`, `prop_contract`, `first_frame_contract.key_props`, and scene-motion prop lists, then add a tombstone with the intended replacement.

**系统化改进建议**

- Treat polluted prop removal as a data migration, not a file deletion.
- QA and rerender workflows should inspect active record `prop_library`/`prop_contract` first; derived keyframe manifests, keyframe prompts, and `prompt.final.txt` must be regenerated after record prop migration.
- Generic auto-prop token profiles must not map an ordinary noun to a color-specific prop unless the text contains the specific color or prop id.

## 2026-05-03 14:22:58 JST - Prop aliases must normalize before records become source of truth

### Case 136: EP01 duplicated props through alternate ids and Chinese bare names

**现象**

- EP01 represented the same pink scarf as `PINK_SILK_SCARF` and `SILK_SCARF_PINK`.
- EP01 represented the same whiskey bottle as `WHISKEY_BOTTLE`, `WHISKY_BOTTLE`, and bare Chinese `威士忌瓶`.
- EP01 represented the same lipprint glass as `LIPPRINT_GLASS`, `CUP`, and bare Chinese `杯子` where the local profile said `杯沿有唇印`.

**根因**

- LLM output, target spine `key_props`, and auto/record merge paths allowed prop ids and bare Chinese labels to land directly in structured fields.
- Downstream renderers treated every distinct string as a distinct prop, so duplicate aliases could become duplicated constraints or visual references.

**有效方案**

- Add a canonical prop alias registry before record write:
  - `SILK_SCARF_PINK` -> `PINK_SILK_SCARF`
  - `WHISKY_BOTTLE` / `威士忌瓶` -> `WHISKEY_BOTTLE`
  - `CUP` / `杯子` / `酒杯` -> `LIPPRINT_GLASS` only when the same record context contains lipprint/glass-rim evidence.
- Normalize `prop_library`, `prop_contract`, `first_frame_contract.key_props`, and scene-motion prop lists together, leaving a `prop_canonicalization_log`.
- QA should fail records that still contain active alias ids after canonicalization.

**系统化改进建议**

- Bare Chinese prop names can be used in natural-language prompt text, but structured record prop ids must be canonical ids.
- Conditional aliases should require local semantic evidence for ambiguous generic nouns like `杯子`; do not globally map every cup to a story-specific glass.

## 2026-05-03 14:30:49 JST - Prop registry must live at novel/project scope, not episode scope

### Case 137: Cross-episode props can fork into new ids if the registry only sees the current episode

**现象**

- EP01 cleanup showed that the same prop could appear under multiple ids inside one episode, but the same problem can also happen when EP02+ reuses a prop first established in EP01.
- If planning only looks at the current episode's records, a later episode can invent a new id for an existing scarf, bottle, notebook, glass, or other continuity prop.

**根因**

- Episode-local normalization only protects the batch currently being generated.
- Long-running novels and screen scripts need continuity memory at the project/novel level, because props can recur across episodes even when they are absent from the current episode's source slice.

**无效或不充分方案**

- Keep a per-episode registry only.
- Rely only on static alias tables; they cannot know every future LLM variation.
- Re-scan old polluted records without honoring tombstones, because removed props such as `AYAKA_LIGHT_BLUE_SCARF` can be revived as canonical continuity props.

**有效方案**

- Maintain a project-level `prop_registry.json` under the novel/screen-script root and load it before rendering new records.
- Merge registry file data with existing project records outside the current output directory, while excluding active removed-prop tombstones and known polluted ids.
- Canonicalize new records against the project registry before writing them, then update and emit the registry artifact with the new canonical prop profiles.

**系统化改进建议**

- Treat prop registry scope as novel/screen-script level by default; episode scope is only a temporary in-memory generation detail.
- Cross-episode matching should remain conservative: merge strong semantic matches such as scarf/bottle/lipprint-glass, require color or distinctive evidence where relevant, and never revive tombstoned polluted ids.

## 2026-05-03 14:45:30 JST - Character and scene continuity also need project-level registries

### Case 139: Episode-local character locks and scene details can fork identities across later episodes

**现象**

- Character reference images already have a project-level `character_image_map.json`, but character lock profiles are emitted per output directory as `35_character_lock_profiles_v1.json`.
- Scene detail is emitted per episode as `scene_detail.txt`, so later episodes can create separate identities for the same location, such as `银座高级酒店套房` and `酒店套房`.

**根因**

- Character and scene identity are continuity objects, not just episode artifacts.
- Per-episode files are convenient for execution, but they cannot prevent cross-episode alias drift by themselves.

**无效或不充分方案**

- Only rely on current episode character locks while overwriting the root image map.
- Treat every new scene name as a new scene id.
- Automatically merge temporary characters such as waiter, police, crowd, or one-off extras into the project character registry.

**有效方案**

- Maintain project-level `character_registry.json` for stable recurring characters, aliases, lock profile ids, visual anchors, and reference image paths.
- Maintain project-level `scene_registry.json` for canonical scene ids, canonical names, aliases, stable environment detail, and scene signatures.
- Use the registries when rendering new records, while still emitting episode-local `35_character_lock_profiles_v1.json` and `scene_detail.txt` for existing downstream tools.

**系统化改进建议**

- Character matching should be stricter than prop matching; avoid auto-merging ambiguous same-name or temporary characters without an explicit alias.
- Scene registry should store stable environment information only. Shot-specific states such as crime-scene disorder, bodies, glass placement, or temporary evidence belong in record/prop contracts, not in the reusable scene identity.

## 2026-05-03 15:14:00 JST - WebUI latest keyframes hidden by narrow scan and clip pairing

### Case 140: Shot Browser can miss final merged keyframes or prefer old Seedance input frames

**现象**

- A final merged keyframe directory such as `test/ginzanight_ep01_sh01_sh06_ok_sh02_sh03_sh07_promptfix_final_20260503` did not appear as the default keyframe set in Shot Browser.
- The backend could show older OpenAI/Grok patch runs or materialized Seedance input frames even after newer keyframes existed.

**根因**

- Artifact scanning only looked under `test/*keyframe*/keyframe_manifest.json`, so final directories without the substring `keyframe` were skipped.
- Merged final directories used copied images whose file mtimes could be older than the manifest creation time.
- Shot Browser paired the default keyframe with the default clip run even when the user had not explicitly selected that clip, causing old Seedance input images to hide newer keyframe-manifest outputs.

**无效或不充分方案**

- Refreshing the frontend only; the missing or deprioritized candidates were decided by backend indexing and default selection.
- Relying only on copied image mtimes; merged/copy2 workflows can preserve old source mtimes.
- Always pairing keyframes with the default clip; this is useful for clip inspection but wrong for a default "latest keyframe" browser view.

**有效方案**

- Scan all one-level `test/*/keyframe_manifest.json` manifests, then require actual keyframe outputs and project matching before indexing.
- Rank keyframe candidates with the newer of output image mtime and manifest mtime.
- In Shot Browser, use the latest keyframe as the default; only pair a keyframe to a clip run when the user explicitly selects a clip.

**系统化改进建议**

- Treat final merged artifact directories as first-class outputs even when their names do not include a media-type keyword.
- Separate "latest generated keyframe" defaults from "clip input provenance" views or make the pairing behavior explicit in the UI.

## 2026-05-03 15:33:45 JST - WebUI clip previews must bind to the exact source keyframe

### Case 141: A shot-level clip list can show a video generated from a different keyframe

**现象**

- Shot Browser is organized by shot, but one shot can have many regenerated keyframes and many Seedance clips.
- If the detail panel simply shows the latest/default clip for the shot, it can display a video generated from an older keyframe while the visible keyframe image is the newest one.

**根因**

- Existing clip artifacts were indexed mainly by `shot_id` and `run_name`.
- The Seedance image input was available as a data URI, but the artifact metadata did not preserve the exact source keyframe file path.
- Pairing by shot or default run is too loose once iterative keyframe regeneration exists.

**无效或不充分方案**

- Show the latest clip for the shot regardless of source image.
- Infer clip-keyframe pairing from run name only; merged final keyframe runs and Seedance runs often have different names.
- Re-materialize Seedance input images into cache and treat those as equivalent to the original keyframe without preserving provenance.

**有效方案**

- When WebUI launches Seedance from a keyframe, write a dedicated image input map containing both `image` and `source_keyframe_path`.
- During artifact scan, copy `source_keyframe_path` into clip candidate metadata.
- For older Seedance runs whose image input map lacks `source_keyframe_path`, infer the source keyframe path from the standard keyframe run layout: `<image_input_map parent>/<SHOT>/start/start.{jpeg,jpg,png,webp}`.
- In Shot Browser detail, only display a clip beside a keyframe when the clip metadata's `source_keyframe_path` exactly matches the visible keyframe path.

**系统化改进建议**

- Treat keyframe-to-clip relation as an explicit artifact edge, not a UI guess.
- Future DB schema can promote `source_keyframe_path` or `source_candidate_id` to first-class columns if clip provenance becomes central to review and assembly.

## 2026-05-03 16:34:59 JST - Seedance clip run names must be discoverable by WebUI artifact scan

### Case 145: Generated clips succeeded but were invisible because the experiment directory omitted `seedance`

**现象**

- EP01 `SH01/SH02/SH03/SH06/SH07/SH13` Novita outputs were successfully generated under `test/ginzanight_ep01_missing6_clips_20260503_novita`.
- `ffprobe` confirmed valid `output.mp4` files with video and AAC audio streams.
- WebUI Shot Browser still showed missing linked clips after refresh, because the artifact scan did not pick up the new run.

**根因**

- `webui/backend/main.py` scans clips with a `test/*seedance*/SH*/output.mp4` glob.
- The successful experiment directory name contained `novita` but not `seedance`, so the files were outside the discoverable scan pattern.
- A stale backend process can make this worse by clearing indexed candidates with old scan logic during refresh.

**无效或不充分方案**

- Trust generation success alone; WebUI counts depend on artifact discovery and provenance metadata.
- Rename only the `run_manifest.json` fields while leaving the directory outside the scan glob.
- Refresh Shot Browser repeatedly without restarting a stale backend process after backend indexing code changes.

**有效方案**

- Use Seedance experiment names that include `seedance`, for example `ginzanight_ep01_missing6_clips_20260503_seedance_novita`.
- If the videos were already generated under a non-discoverable name, create a same-content discoverable run directory and resync the WebUI index.
- Restart the backend after indexing logic changes, then verify `/api/projects/<id>/shot-board` reports every latest keyframe with a linked clip.

**系统化改进建议**

- Relax the WebUI scan from `*seedance*` to manifest-driven clip discovery where `run_manifest.json` or `output.mp4` layout identifies video runs.
- Add a warning when a completed Seedance run writes `output.mp4` files under a directory that WebUI will not index.

## 2026-05-03 16:48:27 JST - WebUI redo must preserve the selected clip prompt and active shot record source

### Case 146: Redo generation can drift if it re-renders prompts or trusts the default plan bundle

**现象**

- Shot Browser redo is intended to generate a new clip from the current clip's displayed `prompt.final.txt`.
- A dry redo command initially failed because the shell environment resolved Seedance to Atlas unless WebUI explicitly passed Novita.
- The same dry run also exposed that the project default `plan_bundle_path` could point to a bundle without the selected shot record, while the shot index already had the correct active `record_path`.

**根因**

- Re-rendering a prompt from record/keyframe is not equivalent to reusing the current reviewed `prompt.final.txt`; it can pick up new renderer defaults or stale record state.
- WebUI job construction used the project-level bundle for `--records-dir` instead of the selected shot's indexed record directory.
- Provider selection was left to environment/default resolution rather than being explicit in the WebUI Seedance command.

**无效或不充分方案**

- Start redo with only `keyframe_path`; this recreates a prompt instead of preserving the reviewed current one.
- Use `model_profile_id` alone; provider routing still depends on `--video-model`.
- Assume `plan_bundle_path` is the active record source for every selected shot.

**有效方案**

- For redo, write a `prompt_final_map` pointing to the source clip's `prompt.final.txt`, and have `run_seedance_test.py` override both `prompt.final.txt` and the positive prompt field in `payload.preview.json`.
- Validate the source clip candidate belongs to the same project, episode, shot, and exact source keyframe before allowing redo.
- Build single-shot Seedance commands from the selected shot's indexed record directory, and pass `--video-model novita-seedance1.5` explicitly unless the caller overrides it.

**系统化改进建议**

- Treat reviewed `prompt.final.txt` as an executable artifact, not just a renderer output.
- Promote clip redo provenance (`source_clip_candidate_id`, `source_prompt_path`, `source_keyframe_path`) into first-class metadata if redo chains become common.

### YYYY-MM-DD HH:MM:SS TZ - Case 标题

**现象**

- 

**根因**

- 

**无效或不充分方案**

- 

**有效方案**

- 

**系统化改进建议**

- 

## 2026-05-04 22:58:34 CST - Semantic interview must precede record generation for ambiguous local/offscreen scenes

### Case 167: Compressed record summaries can invert door-side visibility and audio origin

**现象**

- GinzaNight EP02 SH11 should show only 佐藤美咲 outside 彩花's closed hotel suite door, silently eavesdropping.
- 石川刑警's voice is heard from inside the suite; 佐藤彩花尸体、小樱 and 丝巾勒痕 are only mentioned by that local offscreen voice.
- The record/keyframe path could compress this to a generic hotel doorway or treat the heard content like a phone/dialogue/prompt visual target, allowing death-state constraints to leak onto 美咲.

**根因**

- The old LLM planning path jumped from compact facts/spine rows into `ShotPlan`/record fields. Those summaries are useful for continuity, but they are not detailed enough ground truth for door referents, inside/outside relations, voice origin, listener silence, mentioned-only people, or production dialogue status.
- Character location continuity and downstream death-state prompt logic could then amplify the compressed mistake.

**无效或不充分方案**

- Add many one-off negative prompt restrictions such as "do not show corpse" for every similar shot.
- Trust `TARGET_SPINE_ROW` or `positive_core` when they conflict with the original shot text.
- Let keyframe/Seedance scripts infer visible death state from the word "尸体" without checking whether the death target is actually visible.

**有效方案**

- For `backend=llm`, run a fixed semantic interview per shot before single-shot planning and record writing.
- Save `SHxx.semantic_interview.request.json` and `SHxx.semantic_interview.response.json`; pass the interview payload into the single-shot planner as high-priority ground truth.
- Use the interview to overwrite record-critical fields: precise location, visible/offscreen/mentioned-only people, local vs phone voice origin, listener lip-sync policy, dialogue `text_status`, visible props, mentioned-only objects, and whether a death visual target is visible.
- Keep `TARGET_SPINE_ROW` and character location tracking as reference/continuity helpers only; they must not override semantic ground truth.

**系统化改进建议**

- Prefer LLM semantic recovery over accumulating mechanical restrictions when the failure is about meaning.
- Fixture-test door inside/outside, offscreen voice vs phone, mentioned-only corpse/object handling, interview-over-record conflict resolution, no-op behavior without interview, and the `--no-semantic-interview` debug path.

## 2026-05-04 23:11:17 CST - Semantic interview record contract must not re-compress q2 answers

### Case 168: `record_ready_contract.location_for_record` can undo the correct door-side analysis

**现象**

- Live semantic interview for GinzaNight EP02 SH11 correctly identified the important spatial relation: 美咲在门外靠墙，石川声音从门内警方现场传出，尸体和丝巾只被提及。
- The same response's `record_ready_contract.location_for_record` still compressed the result to `银座高级酒店门外至门内`.
- Record generation initially trusted `location_for_record` before `q2.visual_location`, so the regenerated record still had a multi-location first-frame location.

**根因**

- The interview JSON contains both detailed reasoning fields and a compact record-ready summary. The compact summary can repeat the old failure mode by mixing first-frame location with later motion.
- `visual_location` must be treated as the first-frame spatial answer; `location_for_record` is only a convenience summary and should not override a more precise q2 answer.

**有效方案**

- Prefer `q2_onscreen_people_location_and_action.visual_location` over `record_ready_contract.location_for_record`.
- If the interview says the listener is outside a door and the inside side is the police/corpse/crime scene, refine generic `酒店门外/酒店入口` to `银座高级酒店彩花案发套房关闭房门外，走廊门边墙侧`.
- Do not let `positive_intent_contract` with `推门/进入/至内` become first-frame `positive_core`; rebuild the contract from `first_frame_ground_truth` plus `audio_ground_truth`.

**系统化改进建议**

- Treat `record_ready_contract` as lower priority than the fixed interview answers when the two conflict.
- Add tests for contract-level re-compression, especially `门外至门内` and later action leaking into first-frame record fields.
## 2026-05-04 23:10 - Seedance 2.0 Ark reference images require HTTPS URLs

- Symptom: Seedance 2.0 reference workflow can resolve the correct local character and scene reference images, but Ark payload `content[].image_url.url` cannot safely use the local file path or the Seedance 1.5 data-URI keyframe path.
- Root cause: Seedance 1.5 image-to-video accepts a first-frame image payload, while Ark Seedance 2.0 expects reference images as externally reachable image URLs in `content[]`; local WebUI files are only audit sources until uploaded.
- Handling rule: Keep local `path` entries in `reference_input_map` and `reference_images.used.json` for provenance, but only include `content` image entries when an HTTPS `url` is available. Real Ark API runs must fail early with a clear missing-reference-URL error until a TOS/public upload step is configured.
- Verification: `test/seedance2_sh10_prepare_probe_20260504/SH10/prompt.final.txt` contains `@image1/@image2`; `payload.preview.json` uses Ark `model= doubao-seedance-2-0-260128` and `content[]`, with `image_url_count=0` because the probe intentionally used local-only paths.

## 2026-05-04 23:25 - WebUI Seedance 2.0 reference map must upload refs and avoid stale character paths

- Symptom: WebUI Seedance 2.0 job prepared SH11 but failed before Ark generation with `missing_reference_image_url`; the generated `reference_input_map.seedance2.json` contained local paths with empty `url`.
- Additional evidence: The project contained multiple `character_image_map.json` files; the newest map could point at copied episode-local character paths that no longer existed, causing the visible character reference to be dropped.
- Root cause: The initial WebUI reference-map writer recorded local provenance only and did not perform the TOS upload step required by Ark. Character map merging also let newer non-existent paths override older existing canonical paths.
- Effective fix: During WebUI Seedance 2.0 map creation, upload missing local reference images to TOS and write HTTPS URLs back into the map. When merging character maps, prefer paths that exist on disk and deduplicate references by resolved image path.
- Verification: `test/seedance2_sh11_webui_payload_verify_20260504/SH11/payload.preview.json` contains Ark `content` entries `['text', 'image_url', 'image_url']`, `image_url_count=2`, and both image URLs are HTTPS.

## 2026-05-04 23:21:24 CST - Stale prop registries can pollute otherwise-correct semantic records

### Case 169: Mentioned-or-unrelated project props can leak into SH11 keyframes

**现象**

- GinzaNight EP02 SH11 的 semantic record 已经正确：画面内只有佐藤美咲，地点是彩花案发套房关闭房门外，石川声音从门内传出，尸体和丝巾勒痕只在对白中提及。
- 首次 keyframe 重跑后，画面主体和地点基本正确，但右下角出现了不该出现的手机。

**根因**

- `record` 的语义人物/地点/声音字段已经修好，但 `i2v_contract.prop_library` 和 `prop_contract` 仍从旧项目道具注册表继承了 `KENICHI_SMARTPHONE`，并保留了重复的 `AYAKA_OLD_HANDBAG` 别名。
- keyframe prompt 忠实使用 record 里的道具契约，导致一个与 SH11 无关的手机被当作可见物体生成。问题层不是 semantic interview，也不是图像模型任意发挥，而是 record 道具层的陈旧状态污染。

**有效方案**

- 对 SH11 record 做最小化 prop 清理：移除 `KENICHI_SMARTPHONE`，把 `AYAKA_OLD_HANDBAG` 合并到当前实际可见的 `HANDBAG`，并留下 tombstone 说明删除原因。
- 重新生成 keyframe 后确认画面只保留美咲、手袋和酒店套房门/走廊关系，不再出现手机。

**系统化改进建议**

- 在 keyframe 生成前审计 `first_frame_contract.key_props`、`i2v_contract.prop_library` 和 `prop_contract`，确保它们只包含 semantic ground truth 中画面内可见或明确需要的道具。
- 只被对话提及的人物、尸体、伤痕、凶器、手机或其他对象不得因为项目级 registry 存在就进入首帧可见道具。
- 当 bundle-local `character_image_map.json` 指向缺失资产时，可以使用项目级有效 image map，但必须记录所用路径，避免 silent fallback。

## 2026-05-04 23:36:00 CST - Offscreen local dialogue can still lip-sync to the only visible listener

### Case 170: Model audio binds offscreen dialogue to the visible face

**现象**

- GinzaNight EP02 SH11 的 record 正确标记：画面内只有佐藤美咲，石川刑警是门内 `offscreen_local` 声音，美咲闭嘴偷听。
- Seedance 生成 clip 时虽然 prompt 写了 `无onscreen唇同步`，但美咲仍出现随画外对白张嘴的现象。

**根因**

- `prompt.final.txt` 中仍有误导词：段落标题是 `画面内声音`，并且约束写成 `画面内说话人只有石川悠一`。石川并不在画面内，这会和 record 的 offscreen 语义冲突。
- 当 `generate_audio=true` 且画面中只有一个可见人脸时，I2V 模型倾向把生成的对白音轨自动绑定到唯一可见人物的嘴部，即使 prompt 另有闭嘴约束。

**有效方案**

- 对 `offscreen_local` 声音且可见人物全是沉默听者的镜头，不直接用模型音频生成最终视频。
- 先生成 `generate_audio=false` 的闭嘴听者视频，视觉 prompt 明确：没有画面内说话人、可见听者不是说话人、嘴唇全程闭合、画外对白由后期合成。
- 再把先前或单独生成的画外音音轨 mux 到闭嘴视频上，形成最终 `output.mp4`。

**系统化改进建议**

- Prompt renderer 不应把 offscreen dialogue 放在 `画面内声音` 下；应渲染为 `画外声音/门内声音`。
- 当 `audio_source_contract.source=offscreen_local` 且 `visible_listener_silent` 非空时，应加入和 phone-audio-repair 类似的自动修复路径：闭嘴视频 `generate_audio=false` + 画外音后期合成。
- 不能仅靠追加更多“闭嘴”负面限制解决；关键是切断模型音频到可见人脸的自动 lip-sync 绑定。

## 2026-05-04 23:47:30 CST - Remote phone dialogue should use the same silent-video plus mux repair

### Case 171: EP03 SH09 phone listener must not be fixed by prompt wording alone

**现象**

- GinzaNight EP03 SH09 是警员接听电话，店经理远端声音说“是的，龙崎当夜在我们店，时间吻合。”，画面内警员和龙崎都应沉默。
- Record/prompt 已经写了电话听者闭嘴、不做说话口型，但 `generate_audio=true` 仍属于高风险：模型可能把远端电话对白绑定到警员或龙崎的嘴部。

**根因**

- 这是 Case 170 的电话版本。只要模型在同一次 I2V 生成里同时负责画面和对白音频，且画面里有清晰人脸，模型就可能自动做 lip-sync 绑定。
- 对电话远端声音，增加更多“闭嘴”文字仍不如切断模型音频驱动可靠。

**有效方案**

- 使用同一 keyframe 先生成 `generate_audio=false` 的静默听电话画面。
- Prompt 明确：画面内没有说话人，警员是电话听者不是说话人，龙崎是沉默反应者，两人全程闭嘴。
- 再从旧 clip 或独立音频源取远端电话音轨，mux 到静默视频上，最终标准输出仍写为 `SH09/output.mp4`。

**系统化改进建议**

- 将 Case 170 的策略从 `offscreen_local` 扩展到 phone/remote-speaker/voiceover：可见人物如果是沉默听者，不直接用模型音频生成最终视频。
- 自动修复路径应覆盖 `phone_contract.listener_lip_policy` 或 `audio_source_contract.visible_listener_silent` 这两类证据。

## 2026-05-05 03:00:25 CST - Evidence/report props need unreadable text policy before visual refs

### Case 172: Text-heavy report props can fail visual-reference generation without an explicit text policy

**现象**

- GinzaNight EP12 全流程中，`PROP_EXCLUSION_REPORT_SET` 和 `PROP_KENICHI_FINGERPRINT_REPORT` 两个证据报告类道具在 visual reference 阶段报错。
- 后续 keyframe、Seedance、assembly 和 sync QA 仍可完成，但缺少这两个道具的专用 visual reference 会提高后续近景中文字乱写、报告内容过度可读或报告版式漂移的风险。

**根因**

- 这类道具是文本密集型报告/文件，但道具 canonical profile 只写了报告结构、标签、指纹图等视觉信息，没有明确 `unreadable text policy` 或“文字只作模糊纹理/不可读占位”的约束。
- 视觉资产生成器需要清楚知道报告文本是否要真实可读；没有策略时，既可能被文本生成安全/质量规则拦住，也可能在图像中生成伪文字。

**有效方案**

- 报告、票据、聊天记录、监控打印件、病例、GPS轨迹、证据表等 text-heavy props，进入 visual reference 前必须写明文字策略。
- 如果记录内容才是事实源，visual reference 只应承载版式和物理外观：正文不可读、只保留少量大块标签或抽象线条；真正可读信息由 record dialogue/subtitle/prompt 正文表达。

**系统化改进建议**

- 在 `create_visual_assets.py` 或 prop bible 生成前增加预检：`needs_closeup=true` 且 prop 类型包含 report/document/printout/text 时，必须有 `unreadable_text_policy`、`readable_text_allowed=false` 或等价正向描述。
- 不要依赖负面提示禁止“乱字”；用正向合同写清：页面上只出现模糊灰黑线条、表格块、指纹图或大号非叙事标签，不能生成可读正文。
