# Corner Case Handling Log

> Last updated: 2026-04-29 00:46:40 CST

这个文档记录小说转视频链路中实际遇到的 corner cases，包括问题现象、根因判断、试过但无效或不充分的方案、当前有效方案，以及未来可以系统化改进的方向。

后续每次新增内容时，建议保留时间戳，避免把一次局部修补误认为通用规则。

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
