I2V规则53条

下面是把你这套 I2V 方法论“压缩成机器可执行规则”的版本——全部用 if → then 表达，并尽量做到可程序化判断（共 32 条，覆盖对话 / 道具 / 动作 /镜头 /工作流五大类）。

⸻

一、镜头级控制（核心规则）
	1.	if 一个镜头包含多个核心目标（说话+动作+道具） → then 拆成多个镜头
	2.	if 当前镜头目标是“说话” → then 禁止复杂动作和道具交互
	3.	if 当前镜头目标是“动作” → then 禁止台词或口型变化
	4.	if 当前镜头目标是“展示道具” → then 禁止人物复杂行为
	5.	if 一个镜头描述超过3个动作 → then 强制拆分
	6.	if prompt 是剧情描述句子 → then 转换为镜头控制语言（shot + subject + action）
	7.	if 出现抽象词（愤怒/紧张/激动） → then 替换为可见行为（眼神/头部/速度）

⸻

二、对话控制规则（口型稳定）
	8.	if 一个镜头中出现两个人说话 → then 强制改为单人说话
	9.	if 存在对话 → then 拆成 A说 / B反应 / B说 / A反应
	10.	if 一个角色说话 → then 明确写 only X speaks
	11.	if 一个角色不说话 → then 明确写 no lip movement
	12.	if 双人同框 → then 默认禁止说话（除非单人主导）
	13.	if 出现口型错乱 → then 增加“no double speaking”约束
	14.	if 角色容易混淆 → then 添加空间锚点（left/right/foreground）
	15.	if 使用过肩镜头 → then 明确 from which character

⸻

三、道具控制规则（防变形）
	16.	if 道具是抽象名词（屏幕/手机） → then 必须补充尺寸+材质+结构
	17.	if 道具会被移动 → then 描述侧面形态（thin profile）
	18.	if 道具发生旋转 → then 限制为小角度运动
	19.	if 道具+动作+镜头运动同时存在 → then 至少去掉两个
	20.	if 道具出现变厚 → then 添加 no bulky / no thick
	21.	if 道具比例异常 → then 添加 realistic proportions
	22.	if 手+道具接触复杂 → then 拆镜头（接触前/接触后）
	23.	if 道具是高风险物（屏幕/杯把/纸） → then 强化结构描述

⸻

四、动作控制规则（防穿帮）
	24.	if 动作包含多个物理步骤 → then 拆成动作链
	25.	if 动作涉及“接触+受力” → then 避免完整展示接触瞬间
	26.	if 动作复杂（开门/坐下/递物） → then 使用“起始+结果”结构
	27.	if 同时存在走路+说话+交互 → then 保留其中一个
	28.	if 出现关节变化（坐下/转身） → then 降低动作幅度或拆镜头
	29.	if 手部参与精细动作 → then 添加 stable hands
	30.	if 动作连续失败 → then 用 cut 跳过中间过程
	31.	if 动作不自然 → then 添加 physically plausible movement
	32.	if 画面出现形变 → then 强化 stable anatomy / smooth motion

⸻

五、镜头与结构（Storyboard）
	33.	if 视频 > 5秒 → then 使用时间卡片（timeline cards）
	34.	if 相邻镜头衔接生硬 → then 插入过渡镜头
	35.	if 两个镜头变化过大 → then 增加中间状态镜头
	36.	if 想表达连续动作 → then 用多个镜头拼接而不是一镜到底
	37.	if 镜头切换太密 → then 留时间间隔（避免 hard cut）

⸻

六、一致性控制（角色/资产）
	38.	if 同一角色出现在多个镜头 → then 复用相同描述锚点
	39.	if 角色发生漂移 → then 减少变量（发型/服装/光线）
	40.	if 多镜头制作 → then 建立角色资产（固定关键词）
	41.	if 道具反复出现 → then 使用同一描述模板
	42.	if 场景重复 → then 固定空间结构描述

⸻

七、生成工作流（真正决定成功率）
	43.	if 需要稳定结果 → then 每个镜头生成多个 variations
	44.	if 首次生成不稳定 → then 不改全部 prompt，只改一个变量
	45.	if 需要优化局部 → then 使用 remix 而不是重写
	46.	if 镜头已基本稳定 → then 用 re-cut 拼接而不是重生成
	47.	if 复杂场景 → then 先生成素材，再剪辑成片
	48.	if prompt 变长但效果变差 → then 改为结构化模块
	49.	if 同时调整多个因素 → then 拆成多轮迭代（单变量优化）

⸻

八、终极约束（最重要的4条）
	50.	if 一个镜头解决多个问题 → then 必失败（必须拆）
	51.	if 试图用更长prompt解决问题 → then 基本方向错误
	52.	if 复杂效果不稳定 → then 用剪辑解决而不是生成
	53.	if 不知道为什么失败 → then 检查是否违反“一镜一任务”

⸻

一句话压缩（机器核心逻辑）

if 复杂 → 拆镜头；if 不稳 → 减变量；if 出错 → 加约束；if 还不行 → 用剪辑。