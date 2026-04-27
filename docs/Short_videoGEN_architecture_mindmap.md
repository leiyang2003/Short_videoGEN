# Short_videoGEN 全流程 Architecture Mind Map

> 用途：把当前仓库的“小说/样章 -> 短剧计划包 -> 镜头提示词 -> 关键帧 -> 视频生成 -> 成片装配 -> QA 复盘”流程整理成可视化架构草图。  
> 你可以把本文件直接交给大模型、Mermaid 渲染器、Figma/Whimsical/Miro/Excalidraw 等工具，让它生成更漂亮的 diagram。

---

## 1. 一句话架构

`Short_videoGEN` 是一个“文档主导 + JSON 结构化计划 + Python 脚本流水线 + 文件化实验产物”的 AI 短剧生成工程。

核心闭环：

```text
小说/样章输入
  -> 短剧改编与结构设计
  -> 分集/剧本/镜头计划
  -> record JSON + profile JSON
  -> language plan + keyframes + image_input_map
  -> Seedance / provider 视频生成
  -> FFmpeg 成片装配
  -> QA 报告与复盘
```

---

## 2. Mind Map 版本

```mermaid
mindmap
  root((Short_videoGEN))
    输入资产
      原始小说/样章
        novel/ginza_night/ginza_night.md
        SampleChapter.md
      方法论与模板
        AI短剧生成手册
        爆款题材库
        小说转AI短剧工作流
        小说短剧骨架卡模板
        小说改编提示词模板
      角色参考资产
        assets/characters/*.profile.md
        assets/characters/*.prompt.md
        character_image_map.json
    规划生成层
      novel2video_plan.py
        读取小说 markdown
        识别标题/设定/人物/章节
        构建 Project Bible
        构建 Episode Plan
        构建 Shot Plan
        输出计划包
      计划包文档
        诊断与骨架提取
        短剧总纲
        前3集设计
        20集大纲
        人物关系与角色卡
        第N集剧本
        镜头脚本
        旁白字幕稿
      结构化执行文件
        project_bible_v1.json
        episode_plan_EPxx_v1.json
        prompt_schema_v1.json
        prompt_record_template_v1.json
        prompt_episode_manifest_v1.json
        model_capability_profiles_v1.json
        character_lock_profiles_v1.json
        records/EPxx_SHxx_record.json
      计划 QA
        plan_qa_report.json
        检查残留样例内容
        检查占位符
        检查 episode label
        检查 record 字段完整性
    生产编排层
      run_novel_video_director.py
        找到计划包 execution dir
        发现 episode shots
        串联语言计划
        串联关键帧生成
        串联 image_input_map
        输出 director_manifest
      build_episode_language_plan.py
        从 records 抽取台词/字幕
        估算每镜头时长
        生成 episode.srt
        生成 shot_srt/SHxx.srt
        生成 duration_overrides.json
        生成 language_plan.json
      generate_keyframes_atlas_i2i.py
        读取 records
        读取 character locks
        读取 character image refs
        生成 start/end keyframe prompt
        调 Atlas generateImage
        可调 OpenAI image edit
        可 auto fallback
        输出 keyframe_manifest.json
      build_image_input_map.py
        读取 keyframe_manifest
        解析 start/end image
        可转 data URI
        输出 image_input_map.json
    视频生成层
      run_seedance_test.py
        CLI Orchestrator
          prepare-only
          api-generate
          profile/shot 批处理
        Catalog Loader
          discover records
          load model profiles
          load character locks
          load duration overrides
          load image input map
        Character Lock Hydrator
          lock_profile_id 展开
          appearance/costume 注入
          forbidden_drift 注入
        Prompt Renderer
          positive prompt
          negative prompt
          dialogue timeline
          subtitle hint
          hand constraints
          avoid 降级为正向约束
        Generation Resolver
          duration clamp
          ratio fallback
          resolution fallback
          image/last_image resolve
          provider payload fields
        API Runner
          Atlas generateVideo
          Novita video API
          poll prediction
          download output.mp4
      模型能力适配
        seedance2_text2video_atlas
        seedance15_i2v_atlas
        seedance15_i2v_novita
        supports_negative_prompt
        supports_audio_generation
        supported_ratios/resolutions
        payload_fields 映射
    成片装配层
      assemble_episode.py
        读取 concat file
        读取 image_input_map
        ffprobe 每段视频
        判断共享边界帧
        shared boundary -> hard cut
        non-shared boundary -> fade
        audio-policy mute/keep
        ffmpeg 输出 episode mp4
      装配产物
        episode_01.mp4
        assembly_report.json
        concat_EPxx_SHxx.txt
    QA 与复盘层
      qa_episode_sync.py
        读取 language_plan
        读取 concat file
        读取 image_input_map
        读取 assembly_report
        检查早切风险
        检查镜头时长对齐
        检查边界帧策略
        输出 qa_sync_report.json
      文件化可观测性
        run_manifest.json
        profile_manifest.json
        render_report.json
        record.snapshot.json
        payload.preview.json
        final_status.json
        output_url.txt
        error.txt
      实验复盘
        P0/P0.5 复盘报告
        A/B prompt 对比
        抽帧检查
        下一轮 record/prompt 调整
    外部依赖
      环境变量
        ATLASCLOUD_API_KEY
        NOVITA_API_KEY
        OPENAI_API_KEY
      外部 API
        Atlas Cloud generateVideo
        Atlas Cloud generateImage
        Novita Seedance
        OpenAI image edits
      本地工具
        FFmpeg
        FFprobe
        requests
```

---

## 3. 端到端 Flowchart 版本

```mermaid
flowchart TD
  A["原始小说/样章<br/>novel/*.md / SampleChapter.md"] --> B["方法论与模板<br/>01-07 通用文档"]
  B --> C["scripts/novel2video_plan.py<br/>生成短剧计划包"]
  A --> C

  C --> D["结构设计文档<br/>09 诊断<br/>10 总纲<br/>11 前3集<br/>12 20集大纲<br/>13 角色卡"]
  C --> E["剧本与镜头文档<br/>14 剧本<br/>14A 完整成片剧本<br/>15 镜头脚本<br/>16 旁白字幕"]
  C --> F["视觉与执行文档<br/>17-26 prompt/视觉/Seedance 执行表"]
  C --> G["结构化执行 JSON<br/>project_bible<br/>episode_plan<br/>records<br/>model profiles<br/>character locks"]
  C --> H["plan_qa_report.json"]

  G --> I["scripts/run_novel_video_director.py<br/>生产编排入口"]
  I --> J["build_episode_language_plan.py<br/>生成 SRT / language_plan / duration_overrides"]
  I --> K["generate_keyframes_atlas_i2i.py<br/>生成 start/end keyframes"]
  K --> L["build_image_input_map.py<br/>生成 image_input_map.json"]

  G --> M["scripts/run_seedance_test.py<br/>视频生成主脚本"]
  J --> M
  L --> M

  M --> N{"prepare-only?"}
  N -- "Yes" --> O["只写文件<br/>prompt.final.txt<br/>payload.preview.json<br/>render_report.json<br/>record.snapshot.json"]
  N -- "No" --> P["调用视频模型 API<br/>Atlas / Novita"]
  P --> Q["轮询 prediction<br/>下载 output.mp4"]

  O --> R["test/<experiment>/<shot>/..."]
  Q --> R

  R --> S["concat_EPxx_SHxx.txt"]
  L --> T["assemble_episode.py<br/>边界帧感知装配"]
  S --> T
  T --> U["episode_xx.mp4<br/>assembly_report.json"]

  J --> V["qa_episode_sync.py"]
  S --> V
  L --> V
  U --> V
  V --> W["qa_sync_report.json<br/>早切/时长/边界/同步检查"]

  W --> X["复盘与迭代<br/>调整 records / prompts / profiles / durations"]
  X --> M
  X --> K
```

---

## 4. 数据与产物流

```mermaid
flowchart LR
  subgraph Source["Source / Templates"]
    S1["novel/*.md"]
    S2["SampleChapter_项目文件整理版<br/>方法论 + 模板"]
    S3["assets/characters<br/>角色设定与参考图映射"]
  end

  subgraph Planning["Planning Bundle"]
    P1["project_bible_v1.json"]
    P2["episode_plan_EPxx_v1.json"]
    P3["Markdown Docs 09-26"]
    P4["records/EPxx_SHxx_record.json"]
    P5["30_model_capability_profiles_v1.json"]
    P6["35_character_lock_profiles_v1.json"]
  end

  subgraph Production["Production Inputs"]
    I1["language_plan.json"]
    I2["duration_overrides.json"]
    I3["keyframe_manifest.json"]
    I4["image_input_map.json"]
  end

  subgraph ShotOutputs["Per-shot Outputs"]
    O1["prompt.final.txt"]
    O2["negative_prompt.txt"]
    O3["payload.preview.json"]
    O4["render_report.json"]
    O5["record.snapshot.json"]
    O6["output.mp4"]
  end

  subgraph EpisodeOutputs["Episode Outputs"]
    E1["concat file"]
    E2["episode_xx.mp4"]
    E3["assembly_report.json"]
    E4["qa_sync_report.json"]
  end

  S1 --> Planning
  S2 --> Planning
  S3 --> Planning
  Planning --> Production
  Planning --> ShotOutputs
  Production --> ShotOutputs
  ShotOutputs --> EpisodeOutputs
  EpisodeOutputs --> Planning
```

---

## 5. 关键脚本职责表

| 脚本 | 位置 | 主要输入 | 主要输出 | 职责 |
|---|---|---|---|---|
| `novel2video_plan.py` | `scripts/` | 小说 md、模板、平台参数 | 计划包目录、records、profiles、QA | 从小说生成短剧项目计划包 |
| `run_novel_video_director.py` | `scripts/` | 计划包目录、episode、shots | director manifest、语言计划、关键帧、image map | 串联生产前置流程 |
| `build_episode_language_plan.py` | `scripts/` | records | SRT、language_plan、duration_overrides | 统一台词/字幕/时长规划 |
| `generate_keyframes_atlas_i2i.py` | `scripts/` | records、character locks、character image map | keyframes、keyframe_manifest | 生成 I2V 起止关键帧 |
| `build_image_input_map.py` | `scripts/` | keyframe_manifest | image_input_map.json | 把关键帧转换成视频生成输入映射 |
| `run_seedance_test.py` | `scripts/` | records、profiles、locks、duration、image map | prompt、payload、report、output.mp4 | 渲染 prompt/payload 并调用视频模型 |
| `assemble_episode.py` | `scripts/` | concat file、image_input_map、shot mp4 | episode mp4、assembly_report | 装配镜头，处理硬切/淡入淡出 |
| `qa_episode_sync.py` | `scripts/` | language_plan、concat、image map、assembly report | qa_sync_report | 检查同步、早切、边界帧策略 |

---

## 6. 可视化设计建议

如果要生成更漂亮的 architecture diagram，建议使用三段式横向布局：

```text
[Content Planning] -> [AI Production Pipeline] -> [Assembly + QA Loop]
```

推荐视觉分组：

- 蓝色：输入与方法论文档
- 紫色：计划包与结构化 JSON
- 绿色：生产脚本与中间产物
- 橙色：外部 AI provider/API
- 红色：QA、降级、错误与复盘
- 灰色：文件化可观测性产物

---

## 7. 可直接复制给大模型的美化提示词

```text
请根据下面的 Short_videoGEN 架构信息，生成一张漂亮、清晰、类似 mind map + architecture diagram 的系统图。

目标：
- 表达这是一个“文档主导 + JSON 结构化计划 + Python 脚本流水线 + 文件化实验产物”的 AI 短剧生成工程。
- 图要能让技术负责人、提示词工程师、内容制作团队都看懂。
- 使用横向三段式布局：Content Planning -> AI Production Pipeline -> Assembly + QA Loop。
- 保留关键脚本名、关键文件名、关键数据流。
- 风格专业、清爽、适合放进技术文档或产品说明。

核心流程：
1. 原始小说/样章和通用方法论模板进入 scripts/novel2video_plan.py。
2. novel2video_plan.py 生成短剧计划包：
   - 09 诊断与骨架提取
   - 10 短剧总纲
   - 11 前3集设计
   - 12 20集大纲
   - 13 人物关系与角色卡
   - 14 剧本
   - 15 镜头脚本
   - 16 旁白字幕
   - 17-26 视觉、提示词、Seedance 执行文档
   - project_bible_v1.json
   - episode_plan_EPxx_v1.json
   - records/EPxx_SHxx_record.json
   - 30_model_capability_profiles_v1.json
   - 35_character_lock_profiles_v1.json
3. scripts/run_novel_video_director.py 作为生产编排入口，串联：
   - build_episode_language_plan.py -> language_plan.json、duration_overrides.json、SRT
   - generate_keyframes_atlas_i2i.py -> keyframes、keyframe_manifest.json
   - build_image_input_map.py -> image_input_map.json
4. scripts/run_seedance_test.py 是视频生成主脚本：
   - 加载 records、model profiles、character locks、duration overrides、image_input_map
   - 注入角色锁定
   - 渲染 positive prompt / negative prompt / dialogue timeline / subtitle hint
   - 根据模型能力做 duration、ratio、resolution、negative prompt 降级
   - prepare-only 模式输出 prompt.final.txt、payload.preview.json、render_report.json、record.snapshot.json
   - api-generate 模式调用 Atlas/Novita，轮询 prediction，下载 output.mp4
5. assemble_episode.py 读取 concat file、image_input_map、shot output.mp4，使用 FFmpeg 装配 episode_xx.mp4：
   - 共享边界帧使用 hard cut
   - 非共享边界帧使用轻量 fade
   - 输出 assembly_report.json
6. qa_episode_sync.py 读取 language_plan、concat file、image_input_map、assembly_report，输出 qa_sync_report.json，检查早切、时长、同步、边界帧策略。
7. QA 和复盘结果会反馈到 records、prompts、profiles、duration 或 keyframe 策略，形成迭代闭环。

外部依赖：
- ATLASCLOUD_API_KEY / NOVITA_API_KEY / OPENAI_API_KEY
- Atlas Cloud generateVideo / generateImage
- Novita Seedance
- OpenAI image edits
- FFmpeg / FFprobe

请把图分成以下颜色：
- 输入与方法论文档：蓝色
- 计划包与 JSON：紫色
- 生产脚本与中间产物：绿色
- 外部 AI API：橙色
- QA、降级、错误、复盘：红色
- 文件化可观测性产物：灰色

请突出：
- records 是镜头语义单元
- model profiles 是模型能力适配层
- character locks 是角色一致性层
- image_input_map 是关键帧到 I2V 的桥
- render_report / run_manifest / profile_manifest 是可追溯观测层
- QA loop 会回写改进下一轮生成
```

