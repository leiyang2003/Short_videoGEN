# GinzaNight提示词字段映射研究

> 项目标题：GinzaNight

## 字段映射
- project_meta：来自短剧总纲、分集大纲、第10集封面标题测试包。
- emotion_arc：来自适配诊断、第10集镜头脚本。
- character_anchor：来自人物关系与角色卡、角色统一视觉设定包。
- scene_anchor：来自视觉风格与分镜方案、场景出图清单。
- shot_execution：来自第10集镜头脚本和Seedance逐镜头执行表；`time_of_day` 与 `primary_light_source` 来自小说事实/FACT_PAYLOAD 中明确的时间和光源词。
- dialogue_language：来自第10集剧本和旁白字幕稿。
- language_policy：来自 project_bible_v1.json，并复制进每个 records/EPxx_SHxx_record.json，由 run_seedance_test.py 注入最终 prompt。
