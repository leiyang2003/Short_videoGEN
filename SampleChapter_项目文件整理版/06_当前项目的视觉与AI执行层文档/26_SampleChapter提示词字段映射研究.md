# SampleChapter 提示词字段映射研究（基于前期23个文件）

## 0. 研究范围与目标

本研究仅基于前期 23 个核心文件（01-23），目标是回答：

1. 如何在不改现有代码和 prompt 的前提下，定义“有效 prompt”所需字段
2. 如何把 23 个文件中的信息稳定映射到这些字段
3. 如何解决“画面有了但对话缺失、人物/场景不稳”的核心问题

---

## 1. 核心结论

### 1.1 只用视觉提示词无法保证一致性
原因：一致性不是单句文本问题，而是“结构化约束”问题。

- 手册已定义 AI短剧核心约束是“内容结构与一致性”
- 一致性至少包含：人物稳定性、镜头风格、情绪表达、成片统一度

### 1.2 对话必须作为独立字段进入生成链
前期文件已经给出完整台词/旁白/字幕，但当前视频提示词没有系统挂载。

因此需要“双通道”组织：
- 通道A：视觉生成字段（角色/场景/动作/镜头/氛围）
- 通道B：语言生成字段（台词/旁白/字幕/口语化风格）

### 1.3 有效 prompt 不是“更长”，而是“字段齐全 + 来源可追溯”
每个字段都要能追溯到 01-23 的明确来源，才能稳定复现。

---

## 2. Prompt最小字段模型（建议）

以下字段是从 23 个文件反推得到的最小可用集合。

1. `project_meta`
2. `platform_target`
3. `emotion_arc`
4. `character_anchor`
5. `scene_anchor`
6. `prop_anchor`
7. `shot_intent`
8. `camera_plan`
9. `performance_plan`
10. `dialogue_plan`
11. `narration_plan`
12. `subtitle_plan`
13. `continuity_rules`
14. `style_rules`
15. `qa_rules`
16. `packaging_hook`

---

## 3. 23文件 -> Prompt字段映射总表

## 3.1 方法论与底层文档（01-05）

### 01_AI短剧生成手册.md
- 提供字段：`platform_target`, `dialogue_plan`, `style_rules`, `qa_rules`
- 关键贡献：
  - AI短剧质量核心是结构与一致性
  - 对白规则（口语化、功能性、短句化）
  - 提示词框架总则与分镜提示词模板

### 02_爆款题材库.md
- 提供字段：`project_meta`, `emotion_arc`, `platform_target`
- 关键贡献：
  - 题材标签与用户情绪机制
  - 题材-平台匹配逻辑

### 03_小说转AI短剧工作流.md
- 提供字段：`shot_intent`, `dialogue_plan`, `continuity_rules`
- 关键贡献：
  - “内心戏外化”为动作+对话+场景
  - 生产包标准：单集剧本、分镜脚本、视觉设定

### 04_Log.md
- 提供字段：`qa_rules`, `continuity_rules`
- 关键贡献：
  - 历次决策上下文与变更追溯

### 05_当前文件清单.md
- 提供字段：`project_meta`
- 关键贡献：
  - 当前资产状态与协作入口

## 3.2 模板与通用执行文档（06-07）

### 06_小说短剧骨架卡模板.md
- 提供字段：`emotion_arc`, `shot_intent`, `packaging_hook`
- 关键贡献：
  - 钩子强度、情绪回报频率、反转与高潮节点

### 07_小说改编成短剧的提示词模板.md
- 提供字段：`dialogue_plan`, `camera_plan`, `character_anchor`, `qa_rules`
- 关键贡献：
  - 单集剧本模板：动作与关系变化必须明确
  - 分镜模板：角色外形一致、景别/动作/氛围明确

## 3.3 输入与诊断结构层（08-13）

### 08_SampleChapter.md
- 提供字段：`project_meta`, `emotion_arc`, `character_anchor`
- 关键贡献：
  - 原始世界观、事件母体、角色原始语气素材

### 09_SampleChapter短剧适配诊断与骨架提取.md
- 提供字段：`emotion_arc`, `shot_intent`, `packaging_hook`
- 关键贡献：
  - 主/次情绪主线
  - 开头钩子强度
  - 爽点与反转方向

### 10_SampleChapter短剧总纲.md
- 提供字段：`project_meta`, `emotion_arc`, `character_anchor`
- 关键贡献：
  - 核心卖点与长期角色功能分配

### 11_SampleChapter前3集分集设计.md
- 提供字段：`shot_intent`, `packaging_hook`
- 关键贡献：
  - 第1集目标、核心情绪、集尾钩子

### 12_SampleChapter20集分集大纲.md
- 提供字段：`emotion_arc`, `continuity_rules`
- 关键贡献：
  - 中长线节奏与分集回报机制

### 13_SampleChapter人物关系与角色卡.md
- 提供字段：`character_anchor`, `dialogue_plan`, `continuity_rules`
- 关键贡献：
  - 角色关键词、功能、关系优先级
  - 角色“怎么说话/怎么行动”的边界

## 3.4 剧本与镜头层（14-16）

### 14_SampleChapter第1集剧本.md
- 提供字段：`shot_intent`, `dialogue_plan`, `performance_plan`
- 关键贡献：
  - 场景目标、关键对白、情绪重点

### 15_SampleChapter第1集镜头脚本.md
- 提供字段：`camera_plan`, `dialogue_plan`, `subtitle_plan`, `qa_rules`
- 关键贡献：
  - 镜头时长/景别/动作/台词逐镜头绑定
  - 硬节奏门槛（15秒、45秒、末10秒）

### 16_SampleChapter第1集旁白字幕稿.md
- 提供字段：`narration_plan`, `subtitle_plan`, `dialogue_plan`
- 关键贡献：
  - 旁白版与字幕压缩版
  - 语言口语化与信息密度控制

## 3.5 视觉与执行层（17-20）

### 17_SampleChapter视觉风格与分镜方案.md
- 提供字段：`style_rules`, `scene_anchor`, `camera_plan`
- 关键贡献：
  - 视觉总基调、角色气质与分镜建议

### 18_SampleChapter第1集AI生成提示词包.md
- 提供字段：`character_anchor`, `scene_anchor`, `style_rules`
- 关键贡献：
  - 角色/场景基础提示词
  - 一致性补充规则

### 19_SampleChapter角色统一视觉设定包.md
- 提供字段：`character_anchor`, `continuity_rules`, `style_rules`
- 关键贡献：
  - 明确提示词结构：
    `角色统一描述 + 场景描述 + 动作描述 + 氛围描述 + 风格描述`

### 20_SampleChapter角色海报提示词包.md
- 提供字段：`character_anchor`, `style_rules`
- 关键贡献：
  - 角色视觉扩展、情绪版角色状态

## 3.6 包装与生产任务单层（21-23）

### 21_SampleChapter第1集封面标题测试包.md
- 提供字段：`packaging_hook`, `platform_target`
- 关键贡献：
  - 标题/封面方向与测试组合

### 22_SampleChapter第1集角色出图清单.md
- 提供字段：`character_anchor`, `performance_plan`, `continuity_rules`
- 关键贡献：
  - 第1集角色最小资产与顺序（林辰/阿翠）

### 23_SampleChapter第1集场景出图清单.md
- 提供字段：`scene_anchor`, `prop_anchor`, `continuity_rules`
- 关键贡献：
  - 破庙/溪边/热粥三类场景锚点
  - 明确“盐渍必须可见”这类硬约束

---

## 4. 一致性问题的根因拆解

### 根因1：角色一致性靠“文本记忆”，缺“角色锚点ID”
- 需要把角色描述从自然语言升级为可复用的角色锚点。

### 根因2：场景一致性靠“氛围词”，缺“场景资产锚点”
- 需要把破庙/溪边拆成必需元素清单（地面、光线、道具、色调）。

### 根因3：对话存在于剧本层，未进入视频提示词层
- 需要把 15/16 的台词与字幕，按镜头绑定到 prompt 数据结构。

### 根因4：镜头目标与语言目标未绑定
- 当前很多提示词只写“画面像什么”，没写“这句台词正在完成什么关系变化”。

---

## 5. 研究建议：有效prompt的生成顺序（不改代码版）

1. 先抽取 `13 + 19` 形成角色锚点
2. 再抽取 `23 + 17` 形成场景锚点
3. 用 `15` 建立镜头骨架（时长、景别、动作、节奏）
4. 用 `14 + 16` 绑定台词/旁白/字幕
5. 用 `09 + 10 + 11` 校正情绪目标与钩子目标
6. 用 `22 + 23` 校验是否有最小可开工资产
7. 用 `21` 校验是否服务封面与传播钩子

---

## 6. SH02/SH05/SH10 的字段注入示例（研究示意）

## SH02
- 角色锚点：林辰（消瘦、清俊、眼神由惊惧转警觉）
- 场景锚点：破庙中景（冷风、泥地、残墙）
- 动作目标：惊醒 + 身份落差成立
- 对话目标：建立“穿越确认”
- 语言来源：`15` 的台词 + `16` 的开头字幕

## SH05
- 角色锚点：阿翠（温柔、克制、朴素）+ 林辰
- 场景锚点：破庙门口冷暖反差
- 动作目标：递粥触手，关系由警惕转信任
- 对话目标：建立情感锚点（“你守了我多久？”）
- 语言来源：`15` 镜头5-6台词 + `16` 阿翠出场字幕

## SH10
- 角色锚点：林辰（虚弱转锐利）
- 场景锚点：溪边盐渍近景（盐渍必须可见）
- 动作目标：触盐渍，完成“机会发现”
- 对话目标：从求生切换到翻盘预期（“等等……盐渍？”）
- 语言来源：`15` 镜头10台词 + `16` 发现机会字幕

---

## 7. 质量改进优先级（后续可执行）

1. 先补“对话字段层”再继续扩提示词长度
2. 先固化“角色/场景锚点ID”再做更多镜头
3. 先做 SH02/SH05/SH10 三镜头一致性回归，再全量13镜头
4. 每镜头必须做“画面通过 + 语言通过”双重验收

---

## 8. 一句话结论

前期23个文件已经足够支持高质量生成。问题不在“素材不够”，而在“没有把这些文件转换成统一字段体系”。

真正有效的 prompt 不是一段更长的文字，而是：
**从 23 个文件抽取出的、可追溯的结构化字段组合。**
