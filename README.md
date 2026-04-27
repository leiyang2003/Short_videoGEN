# Short_videoGEN 文件理解与关系说明

## 1. 当前仓库定位（已校正）

这个仓库是一个“文档主导 + 生成脚本 + 实验产物”的 AI 短剧工程，而不只是纯文档仓库。  
核心内容围绕 `SampleChapter`，已经包含从方法论、改编、剧本、分镜到 Seedance 生成执行与复盘的完整链路。

仓库内有两套主文档目录：

- `SampleChapter_1-23_项目文件打包/`：平铺打包版（便于交付）
- `SampleChapter_项目文件整理版/`：分层结构版（便于协作）

说明：

- 两套目录里的“核心业务文档 23 份”是一一镜像。
- 但这两个目录不止 23 份文件，还包含执行层扩展资产（`prompt_*.json`、`*_profiles_v1.json`、`records/*.json`、复盘文档等）。
- 仓库还包含 `scripts/` 与 `test/`，用于实际生成和实验验证。

---

## 2. 全量文件盘点（不漏文件）

### 2.1 根目录
- `.DS_Store`
- `.env`
- `.env.example`
- `.gitignore`
- `README.md`（本说明）
- `requirements.txt`
- `Technical_Architecture_Document.md`
- `episode_01.mp4`
- `Short_videoGEN_Intro.mp4`
- `scripts/`
- `test/`
- `SampleChapter_1-23_项目文件打包/`
- `SampleChapter_项目文件整理版/`

### 2.2 打包版目录（共 51 个文件）
- 核心业务文档（23 个）：
1. `AI短剧生成手册.md`
2. `Log.md`
3. `SampleChapter.md`
4. `SampleChapter20集分集大纲.md`
5. `SampleChapter人物关系与角色卡.md`
6. `SampleChapter前3集分集设计.md`
7. `SampleChapter短剧总纲.md`
8. `SampleChapter短剧适配诊断与骨架提取.md`
9. `SampleChapter第1集AI生成提示词包.md`
10. `SampleChapter第1集剧本.md`
11. `SampleChapter第1集场景出图清单.md`
12. `SampleChapter第1集封面标题测试包.md`
13. `SampleChapter第1集旁白字幕稿.md`
14. `SampleChapter第1集角色出图清单.md`
15. `SampleChapter第1集镜头脚本.md`
16. `SampleChapter视觉风格与分镜方案.md`
17. `SampleChapter角色海报提示词包.md`
18. `SampleChapter角色统一视觉设定包.md`
19. `小说改编成短剧的提示词模板.md`
20. `小说短剧骨架卡模板.md`
21. `小说转AI短剧工作流.md`
22. `当前文件清单.md`
23. `爆款题材库.md`
- 扩展执行文档（7 个）：
1. `EP01_P0三镜头实跑复盘报告.md`
2. `EP01_P0.5_AB优化复盘报告.md`
3. `SampleChapter提示词字段映射研究.md`
4. `SampleChapter第1集Seedance2.0逐镜头执行表.md`
5. `SampleChapter第1集Seedance2.0最终提示词包.md`
6. `prompt_adapter_interface_v1.md`
7. `角色容貌服饰锁定模板_v1.md`
- 执行配置 JSON（5 个）：
1. `model_capability_profiles_v1.json`
2. `character_lock_profiles_v1.json`
3. `prompt_schema_v1.json`
4. `prompt_record_template_v1.json`
5. `prompt_episode_manifest_v1.json`
- `records/` 下记录文件（16 个）：`EP01_SH01_record.json` ... `EP01_SH13_record.json`（13 个）+ `*_prompt.preview.txt`（3 个）。

### 2.3 整理版目录（共 53 个文件）
- `.DS_Store`
- `00_目录清单.md`
- `01_总方法论与项目底层文档/01_AI短剧生成手册.md`
- `01_总方法论与项目底层文档/02_爆款题材库.md`
- `01_总方法论与项目底层文档/03_小说转AI短剧工作流.md`
- `01_总方法论与项目底层文档/04_Log.md`
- `01_总方法论与项目底层文档/05_当前文件清单.md`
- `02_模板与通用执行文档/06_小说短剧骨架卡模板.md`
- `02_模板与通用执行文档/07_小说改编成短剧的提示词模板.md`
- `03_当前项目的原始输入文档/08_SampleChapter.md`
- `04_当前项目的诊断与结构设计文档/09_SampleChapter短剧适配诊断与骨架提取.md`
- `04_当前项目的诊断与结构设计文档/10_SampleChapter短剧总纲.md`
- `04_当前项目的诊断与结构设计文档/11_SampleChapter前3集分集设计.md`
- `04_当前项目的诊断与结构设计文档/12_SampleChapter20集分集大纲.md`
- `04_当前项目的诊断与结构设计文档/13_SampleChapter人物关系与角色卡.md`
- `05_当前项目的剧本与镜头层文档/14_SampleChapter第1集剧本.md`
- `05_当前项目的剧本与镜头层文档/15_SampleChapter第1集镜头脚本.md`
- `05_当前项目的剧本与镜头层文档/16_SampleChapter第1集旁白字幕稿.md`
- `06_当前项目的视觉与AI执行层文档/17_SampleChapter视觉风格与分镜方案.md`
- `06_当前项目的视觉与AI执行层文档/18_SampleChapter第1集AI生成提示词包.md`
- `06_当前项目的视觉与AI执行层文档/19_SampleChapter角色统一视觉设定包.md`
- `06_当前项目的视觉与AI执行层文档/20_SampleChapter角色海报提示词包.md`
- `06_当前项目的视觉与AI执行层文档/24_SampleChapter第1集Seedance2.0逐镜头执行表.md`
- `06_当前项目的视觉与AI执行层文档/25_SampleChapter第1集Seedance2.0最终提示词包.md`
- `06_当前项目的视觉与AI执行层文档/26_SampleChapter提示词字段映射研究.md`
- `06_当前项目的视觉与AI执行层文档/27_prompt_schema_v1.json`
- `06_当前项目的视觉与AI执行层文档/28_prompt_record_template_v1.json`
- `06_当前项目的视觉与AI执行层文档/29_prompt_episode_manifest_v1.json`
- `06_当前项目的视觉与AI执行层文档/30_model_capability_profiles_v1.json`
- `06_当前项目的视觉与AI执行层文档/31_prompt_adapter_interface_v1.md`
- `06_当前项目的视觉与AI执行层文档/32_EP01_P0三镜头实跑复盘报告.md`
- `06_当前项目的视觉与AI执行层文档/33_EP01_P0.5_AB优化复盘报告.md`
- `06_当前项目的视觉与AI执行层文档/34_角色容貌服饰锁定模板_v1.md`
- `06_当前项目的视觉与AI执行层文档/35_character_lock_profiles_v1.json`
- `06_当前项目的视觉与AI执行层文档/records/EP01_SH01_record.json` ... `EP01_SH13_record.json`
- `06_当前项目的视觉与AI执行层文档/records/EP01_SH02_prompt.preview.txt`
- `06_当前项目的视觉与AI执行层文档/records/EP01_SH05_prompt.preview.txt`
- `06_当前项目的视觉与AI执行层文档/records/EP01_SH10_prompt.preview.txt`
- `07_当前项目的包装与生产任务单文档/21_SampleChapter第1集封面标题测试包.md`
- `07_当前项目的包装与生产任务单文档/22_SampleChapter第1集角色出图清单.md`
- `07_当前项目的包装与生产任务单文档/23_SampleChapter第1集场景出图清单.md`

### 2.4 代码与实验目录（新增说明）
- `scripts/`
1. `run_seedance_test.py`：主生成与 prepare/API 流程脚本。
2. `README_seedance.md`：脚本用法说明。
- `test/`
1. 多个 `exp_*` 目录：按实验维度保存 prompt、payload、render 报告、输出视频。
2. `p0_review_frames/`、`p05_review_frames/`：抽帧对比图。
3. `concat_*.txt` 与 `episode_01_SH01_SH07.mp4`：拼接产物。

### 2.5 如何校验“覆盖是否完整”
```bash
# Git 跟踪文件总数
git ls-files | wc -l

# 打包版/整理版文件总数
find SampleChapter_1-23_项目文件打包 -type f | wc -l
find SampleChapter_项目文件整理版 -type f | wc -l
```

---

## 3. 每个业务文件是做什么的（按整理版编号）

说明：这里按整理版 `00-23` 核心业务文档编号说明；打包版对应的是核心业务文档镜像（映射见第4节）。

### 00_目录清单.md
- 作用：整理版总目录入口，说明各层文档分区。
- 上游：无。
- 下游：帮助快速导航 01-23 文件，不直接产出业务内容。

### 01_AI短剧生成手册.md
- 作用：总方法论底座，定义 AI 短剧全流程（选题、结构、提示词、制作、发布、复盘、合规、组织）。
- 上游：行业认知与项目目标。
- 下游：给 `02`、`03` 与后续执行文档提供统一标准。

### 02_爆款题材库.md
- 作用：题材决策系统（一级题材地图、二级拆解、题材卡、评分、标签、证据来源）。
- 上游：`01` 的方法论与平台认知。
- 下游：为 `03` 的改编流程、`09` 的适配判断提供题材判断依据。

### 03_小说转AI短剧工作流.md
- 作用：定义“小说输入 -> 诊断 -> 骨架 -> 重构 -> 生产 -> 测试复盘”的标准转化链路。
- 上游：`01`、`02`。
- 下游：约束 `06`、`07`、`09-23` 的实际执行顺序。

### 04_Log.md
- 作用：项目演进日志，记录每次需求变化、产出文件和阶段结论。
- 上游：实际协作过程。
- 下游：用于追溯为什么生成某个文件、当前进度到哪一步。

### 05_当前文件清单.md
- 作用：阶段性资产清点与关系摘要（比 `00` 更偏阶段报告）。
- 上游：当时已产出的基础文件。
- 下游：指导下一批应补充的文档。

### 06_小说短剧骨架卡模板.md
- 作用：标准化“骨架提取表单”（母题、人设、冲突、爽点、反转、高潮、适配判断）。
- 上游：`03` 工作流要求。
- 下游：可直接用于生成 `09` 类诊断文件。

### 07_小说改编成短剧的提示词模板.md
- 作用：按阶段封装提示词（诊断、骨架、重构、总纲、分集、剧本、分镜、标题封面）。
- 上游：`03` 的流程分步设计。
- 下游：直接驱动 `09-23` 的文本产出。

### 08_SampleChapter.md
- 作用：原始内容输入（改编素材源头）。
- 上游：原始样章文本。
- 下游：`09` 诊断、`10-13` 结构化改编、`14-23` 执行层文档都依赖它。

### 09_SampleChapter短剧适配诊断与骨架提取.md
- 作用：对 `08` 做短剧适配评估和骨架抽取，给出“是否值得立项”的判断。
- 上游：`08` + `02` + `06/07`。
- 下游：为 `10` 总纲提供输入边界。

### 10_SampleChapter短剧总纲.md
- 作用：定义项目级 Logline、阶段主线、核心卖点、平台与人群、改编原则。
- 上游：`09` 的诊断结论。
- 下游：`11` 前3集、`12` 20集、`13` 角色卡的总控文档。

### 11_SampleChapter前3集分集设计.md
- 作用：完成冷启动最关键的前3集抓人方案（目标、冲突、爽点、集尾钩子）。
- 上游：`10`。
- 下游：`14` 第1集剧本。

### 12_SampleChapter20集分集大纲.md
- 作用：把 `10` 总纲展开为20集结构，保证中长期升级路径。
- 上游：`10`。
- 下游：后续多集剧本扩写与连载规划。

### 13_SampleChapter人物关系与角色卡.md
- 作用：定义主次角色功能与关系优先级，防止改编时角色线失衡。
- 上游：`08` + `10`。
- 下游：`14` 剧本写作、`17/19/20` 视觉角色一致性。

### 14_SampleChapter第1集剧本.md
- 作用：第1集场景化剧本（场景、对白、情绪、节奏、集尾钩子）。
- 上游：`11` + `13`。
- 下游：`15` 镜头脚本、`16` 旁白字幕、`21` 包装测试。

### 15_SampleChapter第1集镜头脚本.md
- 作用：把 `14` 转成可拍/可生成的镜头级拆解（时长、景别、声音、台词）。
- 上游：`14`。
- 下游：`18` 提示词包、`22/23` 出图任务单。

### 16_SampleChapter第1集旁白字幕稿.md
- 作用：给成片提供旁白文本和字幕压缩版，并给时长调整策略。
- 上游：`14`（并参考 `15` 节奏）。
- 下游：后期剪辑与字幕制作。

### 17_SampleChapter视觉风格与分镜方案.md
- 作用：定义项目视觉基调、角色气质、场景风格和重点分镜方向。
- 上游：`10` + `13` + `14/15`。
- 下游：`18/19/20` 与 `21-23` 的视觉执行标准。

### 18_SampleChapter第1集AI生成提示词包.md
- 作用：把剧本与镜头转成 AI 可直接调用的角色/场景/镜头/视频/封面提示词。
- 上游：`14` + `15` + `17`。
- 下游：第1集 AI 出图与视频生成执行。

### 19_SampleChapter角色统一视觉设定包.md
- 作用：角色一致性规范（防串脸、风格漂移、年龄/服装错位）。
- 上游：`13` + `17`。
- 下游：`18`（角色提示词校准）与 `20`（海报提示词）。

### 20_SampleChapter角色海报提示词包.md
- 作用：将 `19` 转为宣发可用的角色海报提示词和文案方向。
- 上游：`19`。
- 下游：角色海报生成、宣发素材生产。

### 21_SampleChapter第1集封面标题测试包.md
- 作用：第1集上线前包装测试（标题方向、封面短文案、首轮组合建议）。
- 上游：`14`（剧情卖点）+ `17/18`（视觉执行）。
- 下游：发布前A/B测试与首发包装选择。

### 22_SampleChapter第1集角色出图清单.md
- 作用：角色维度的生产任务单（必须出哪些图、用途、优先级、顺序）。
- 上游：`15` + `18` + `19`。
- 下游：角色资产生成与素材管理。

### 23_SampleChapter第1集场景出图清单.md
- 作用：场景维度的生产任务单（破庙/溪边/氛围图的最小可开工清单）。
- 上游：`15` + `17` + `18`。
- 下游：场景资产生成、镜头背景与过渡素材。

---

## 4. 打包版与整理版核心业务文档镜像关系（23对1:1）

| 打包版路径 | 整理版对应路径 |
|---|---|
| `SampleChapter_1-23_项目文件打包/AI短剧生成手册.md` | `SampleChapter_项目文件整理版/01_总方法论与项目底层文档/01_AI短剧生成手册.md` |
| `SampleChapter_1-23_项目文件打包/爆款题材库.md` | `SampleChapter_项目文件整理版/01_总方法论与项目底层文档/02_爆款题材库.md` |
| `SampleChapter_1-23_项目文件打包/小说转AI短剧工作流.md` | `SampleChapter_项目文件整理版/01_总方法论与项目底层文档/03_小说转AI短剧工作流.md` |
| `SampleChapter_1-23_项目文件打包/Log.md` | `SampleChapter_项目文件整理版/01_总方法论与项目底层文档/04_Log.md` |
| `SampleChapter_1-23_项目文件打包/当前文件清单.md` | `SampleChapter_项目文件整理版/01_总方法论与项目底层文档/05_当前文件清单.md` |
| `SampleChapter_1-23_项目文件打包/小说短剧骨架卡模板.md` | `SampleChapter_项目文件整理版/02_模板与通用执行文档/06_小说短剧骨架卡模板.md` |
| `SampleChapter_1-23_项目文件打包/小说改编成短剧的提示词模板.md` | `SampleChapter_项目文件整理版/02_模板与通用执行文档/07_小说改编成短剧的提示词模板.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter.md` | `SampleChapter_项目文件整理版/03_当前项目的原始输入文档/08_SampleChapter.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter短剧适配诊断与骨架提取.md` | `SampleChapter_项目文件整理版/04_当前项目的诊断与结构设计文档/09_SampleChapter短剧适配诊断与骨架提取.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter短剧总纲.md` | `SampleChapter_项目文件整理版/04_当前项目的诊断与结构设计文档/10_SampleChapter短剧总纲.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter前3集分集设计.md` | `SampleChapter_项目文件整理版/04_当前项目的诊断与结构设计文档/11_SampleChapter前3集分集设计.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter20集分集大纲.md` | `SampleChapter_项目文件整理版/04_当前项目的诊断与结构设计文档/12_SampleChapter20集分集大纲.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter人物关系与角色卡.md` | `SampleChapter_项目文件整理版/04_当前项目的诊断与结构设计文档/13_SampleChapter人物关系与角色卡.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter第1集剧本.md` | `SampleChapter_项目文件整理版/05_当前项目的剧本与镜头层文档/14_SampleChapter第1集剧本.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter第1集镜头脚本.md` | `SampleChapter_项目文件整理版/05_当前项目的剧本与镜头层文档/15_SampleChapter第1集镜头脚本.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter第1集旁白字幕稿.md` | `SampleChapter_项目文件整理版/05_当前项目的剧本与镜头层文档/16_SampleChapter第1集旁白字幕稿.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter视觉风格与分镜方案.md` | `SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/17_SampleChapter视觉风格与分镜方案.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter第1集AI生成提示词包.md` | `SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/18_SampleChapter第1集AI生成提示词包.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter角色统一视觉设定包.md` | `SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/19_SampleChapter角色统一视觉设定包.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter角色海报提示词包.md` | `SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/20_SampleChapter角色海报提示词包.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter第1集封面标题测试包.md` | `SampleChapter_项目文件整理版/07_当前项目的包装与生产任务单文档/21_SampleChapter第1集封面标题测试包.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter第1集角色出图清单.md` | `SampleChapter_项目文件整理版/07_当前项目的包装与生产任务单文档/22_SampleChapter第1集角色出图清单.md` |
| `SampleChapter_1-23_项目文件打包/SampleChapter第1集场景出图清单.md` | `SampleChapter_项目文件整理版/07_当前项目的包装与生产任务单文档/23_SampleChapter第1集场景出图清单.md` |

---

## 5. 文件之间的主干依赖关系（端到端）

### 5.1 方法论与规则层
`01` + `02` + `03` + `06` + `07`

这些文件决定“怎么做、按什么标准做、用什么模板做”。

### 5.2 项目输入与诊断层
`08` -> `09`

先读原始样章，再做是否适合短剧化的诊断与骨架抽取。

### 5.3 结构设计层
`09` -> `10` -> (`11`, `12`, `13`)

先有总纲，再分出前3集、20集和人物关系三条并行设计线。

### 5.4 单集落地层
`11` + `13` -> `14` -> (`15`, `16`)

先成剧本，再转镜头和旁白字幕。

### 5.5 视觉与AI执行层
`13` + `14` + `15` + `17` -> `18` + `19` + `20`

角色与剧情约束共同驱动 AI 提示词与角色视觉一致性体系。

### 5.6 包装与生产任务层
`14` + `15` + `17` + `18` + `19` -> (`21`, `22`, `23`)

最后形成上线测试包和最小可开工出图清单（角色/场景）。

---

## 6. 一句话总结

这个仓库已经形成了一个可复用的 AI短剧文档生产线：
**从原始小说输入（08）出发，经过方法论与模板约束（01-07），完成诊断与重构（09-13），再落地单集剧本和镜头（14-16），最后进入视觉执行与发布测试（17-23）。**
