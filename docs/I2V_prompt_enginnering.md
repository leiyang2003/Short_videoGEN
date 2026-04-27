# I2V提示词工程宝典

## 一、核心结论

1. I2V 的核心难点，不只是“提示词不够细”，而是单镜头任务经常过载。
2. 多角色对话、复杂道具、连续动作，本质上都应拆成更小的视觉任务单元。
3. 提示词要从“小说叙述”改成“导演调度语言”，重点写主体、机位、动作、道具、约束。
4. 稳定出片靠的是“角色控制 + 镜头拆分 + 动作降维 + 后期拼接”，而不是一个超长提示词。

---

## 二、你遇到的三个典型问题

### 1. 两个角色对话，结果都从一个角色嘴里说出来

#### 问题本质
AI 容易把连续对话理解成单一主体表演，无法稳定区分多角色口型归属。

#### 常见错误
- 在一个镜头里同时让两个人轮流说话
- 用小说式描述写完整对白
- 没有明确“谁在说、谁在听”

#### 正确解法

##### 解法1：一镜一口
一个镜头里，最好只允许一个角色承担“说话”任务。

##### 解法2：用反打和过肩镜头
把对话拆成：
- A 说话镜头
- B 反应镜头
- B 说话镜头
- A 反应镜头

##### 解法3：明确静默角色
在提示词里直接写：
- only character A speaks
- character B remains silent
- no lip movement from character B

##### 解法4：用空间锚点强化归属
例如：
- Character A on the left side of frame
- Character B on the right side of frame
- over-the-shoulder shot from Character B

#### 可直接套用模板

##### 镜头1，A说话
```text
Cinematic realistic office scene, medium close-up on Character A, over-the-shoulder shot from Character B, Character A is the only speaker, speaking calmly, natural lip movement, Character B remains silent and still, listening without moving lips, consistent eye line, subtle head movement, no double speaking, no extra mouth movement.
```

##### 镜头2，B说话
```text
Reverse shot, medium close-up on Character B, over-the-shoulder shot from Character A, Character B is the only speaker, clear and natural lip movement, Character A remains silent, listening with a subtle reaction, no lip movement from Character A, stable facial features.
```

#### 操作原则
**一镜一口。一个镜头只解决一个角色说话的问题。**

---

### 2. 道具有问题，比如显示屏移动时很厚，像一块砖

#### 问题本质
AI 对抽象道具名词的结构理解不稳定，尤其在移动和侧面角度下，容易把“屏幕”生成成厚重长方体。

#### 常见错误
- 只写“显示屏”“平板”“终端”
- 没有描述厚度、材质、边框、比例
- 让道具在同一镜头里做大幅旋转和复杂交互

#### 正确解法

##### 解法1：给道具加工业设计描述
不要只写“超薄显示屏”，要写：
- ultra-thin body
- 8mm thickness
- narrow black bezel
- flat glass panel
- lightweight aluminum frame

##### 解法2：描述侧面和运动状态
例如：
- maintains a thin side profile during movement
- held lightly with one hand
- no visible thickness increase while rotating

##### 解法3：减少高风险三维翻转
如果道具要被拿起、旋转、放下，最好拆成多个镜头，不要一镜到底。

##### 解法4：负面提示词短而准
推荐：
- thick monitor
- bulky object
- toy-like prop
- distorted proportions

#### 可直接套用模板
```text
A slim futuristic display, ultra-thin body, 8mm thickness, narrow black bezel, flat glass panel, lightweight aluminum frame, elegant industrial design, maintains a thin side profile during movement, no bulky thickness, no brick-like shape, realistic proportions.
```

#### 操作原则
**道具不是一个名词，而是一件有尺寸、材质、边缘和受力状态的工业产品。**

---

### 3. 人的动作经常穿帮，比如开门

#### 问题本质
模型很难自动补全过程动作链，涉及手部接触、关节过渡、门扇运动时，尤其容易变形。

#### 常见错误
- 直接写“他开门走进去”
- 在一个镜头里要求完整复杂动作
- 同时叠加说话、走位、开门、转身等任务

#### 正确解法

##### 解法1：拆成物理步骤
开门至少拆成：
1. 走近门
2. 手伸向门把
3. 门开始打开
4. 人侧身通过

##### 解法2：弱化最难的接触瞬间
“手精确压门把并转动”的镜头是高风险区，可以用剪辑省略最难的瞬间。

##### 解法3：用结果镜头替代全过程镜头
比如：
- 手伸向门把
- cut
- 门已半开，人准备进入

##### 解法4：加入物理合理性约束
例如：
- realistic body mechanics
- physically plausible movement
- stable hands
- smooth motion continuity

#### 可直接套用模板

##### 镜头1
```text
A man walks toward the apartment door, slows down naturally, reaches his right hand toward the silver door handle, realistic body mechanics, smooth motion, stable anatomy.
```

##### 镜头2
```text
Close shot of the door already opening inward smoothly, the handle slightly turned down, realistic hinge motion, no distorted hand, no broken geometry.
```

##### 镜头3
```text
Medium shot, the man turns sideways and walks through the half-open door naturally, realistic spacing between body and door frame, smooth continuous movement.
```

#### 操作原则
**不要生成完整复杂动作，要生成让观众脑补为完整动作的镜头组合。**

---

## 三、元宝方案的优点与不足

### 优点
1. 强调分镜脚本而不是小说叙述，这个方向正确。
2. 强调动作拆解，这对减少穿帮有效。
3. 强调道具具体化，能显著提升生成稳定性。

### 不足
1. 最大问题不是“提示词不够细”，而是“单镜头任务过载”。
2. 仅仅写“反打镜头”还不够，应尽量避免双人同框同时说话。
3. 负面提示词不是越多越好，应短、准、强约束。
4. 真正的提升不只靠提示词，还依赖镜头拆分和后期拼接。

---

## 四、I2V真正可落地的方法论

### 1. 做导演，不做小说家
提示词要写成拍摄控制语言，而不是剧情复述。

不要写：
- 他很愤怒地冲过去开门离开房间

要写：
- medium shot
- walks quickly to the door
- reaches toward the handle
- slight body lean
- realistic motion
- door begins to open inward

### 2. 一次只解决一个难点
如果镜头重点是“说话”，就不要同时追求：
- 双人轮流开口
- 大幅手部动作
- 道具联动
- 复杂运镜

### 3. 把复杂动作交给镜头组合和剪辑
成熟做法不是让模型一镜到底完成一场戏，而是：
- 生成多个稳定碎镜头
- 用剪辑建立连续性
- 用声音、字幕、音效补戏

### 4. 保留一致性锚点
同一个角色或道具，在不同镜头里反复使用相同特征词。
例如：
- gray suit
- slim curved display
- silver door handle

---

## 五、推荐工作流

### 1. 对话场景工作流
推荐结构：
1. 建立镜头，双人同框，不说话
2. A 单人说话镜头
3. B 反应镜头
4. B 单人说话镜头
5. A 反应镜头
6. 必要时补双人环境镜头

### 2. 道具场景工作流
推荐结构：
1. 先生成稳定道具镜头
2. 再生成人物与道具弱交互镜头
3. 避免道具移动、人物说话、镜头运动、UI变化同时发生

### 3. 动作场景工作流
推荐结构：
- 起始动作镜头
- 动作结果镜头
- 连接反应镜头

中间最复杂的接触过程，能省则省。

---

## 六、通用提示词模块

### 1. 对话镜头模板
```text
Cinematic realism, stable character design, medium close-up, only one speaker in this shot. Character A is speaking, natural lip sync, subtle facial expression, controlled head movement. Character B remains silent, no lip movement, only listening reaction. Clear eye line, stable face, no identity drift, no double speaking, no extra mouth motion.
```

### 2. 道具镜头模板
```text
A realistic modern device with precise industrial design, ultra-thin body, slim side profile, flat glass surface, narrow bezel, lightweight metal frame, correct proportions, no bulky thickness, no toy-like shape, no brick-like geometry.
```

### 3. 动作镜头模板
```text
Smooth realistic body mechanics, natural transition between poses, physically plausible movement, stable hands, stable joints, correct contact with objects, no sudden deformation, no broken motion continuity.
```

---

## 七、一个更实用的黄金原则

### 原则1：一镜一任务
一个镜头只解决一个核心目标：
- 要么说话
- 要么展示道具
- 要么完成动作

### 原则2：少写情绪，多写控制项
少写抽象词，多写：
- 机位
- 景别
- 主体
- 空间位置
- 运动方向
- 材质尺寸
- 物理约束

### 原则3：复杂问题不要靠堆词解决
复杂场景优先通过拆镜头、改调度、降动作复杂度来解决。

### 原则4：AI短剧更像“镜头素材生成”
现阶段不要把模型当成完整导演系统，而要把它当成一个高波动的镜头生成器。

---

## 八、网上案例补充，按置信度排序（问题 + 解法）

> 排序原则：优先采用官方产品文档、官方帮助中心、官方学习中心中能直接支持的实践。越靠前，置信度越高。

### A级高置信案例

#### 1. 问题：长视频里多个事件硬连在一起，结果像硬切，不连贯
**解法：** 把长视频改成时间轴卡片式结构，在镜头之间留出过渡空间，而不是把事件写成一整段大提示词。

**为什么置信度高：** OpenAI Sora 官方帮助明确提到 Storyboard 可以按时间戳为视频不同阶段分别写内容，并且建议卡片之间“留空间”，否则更容易出现 hard cuts。

**对你的启发：**
- 不要把 10 到 20 秒剧情写成一个大段 prompt
- 把关键节点拆成 3 到 5 个时间卡片
- 卡片之间保留衔接区，让模型自己补过渡

**可执行写法：**
- 0s 到 2s：角色A看向门口
- 3s 到 5s：角色A走向门
- 6s 到 8s：门已经半开，角色侧身进入

**来源：** OpenAI Help Center, *Generating videos on Sora*；明确提到 Storyboard、timestamp cards、留出间隔减少硬切。

---

#### 2. 问题：想让模型一次完成复杂叙事，结果场景、动作、主体都不稳定
**解法：** 先生成多个 variations，对比后再进入 remix、re-cut、blend，而不是指望首条 prompt 一步到位。

**为什么置信度高：** Sora 官方帮助明确把工作流写成“先生成多个 variations，再对结果进行 re-cut、remix、blend、loop 等编辑”。

**对你的启发：**
- I2V 更像“生成可剪素材”，不是一次成片
- 复杂镜头先拿多个版本做筛选
- 选到一个稳定版本，再局部改动

**可执行动作：**
1. 先同 prompt 生成 4 个变体
2. 选主体最稳定的一个
3. 用 remix 只改动作或道具，不同时改所有变量

**来源：** OpenAI Help Center, *Generating videos on Sora*；明确列出 variations、Re-cut、Remix、Blend、Loop 工作流。

---

#### 3. 问题：镜头之间衔接很生硬，角色像瞬移
**解法：** 在分镜设计中为动作过渡预留“连接帧”，不要把相邻镜头写得过满、过紧。

**为什么置信度高：** Sora 官方帮助明确说，Storyboard 卡片之间如果间隔太少，更容易出现 hard cuts。

**对你的启发：**
- “走向门”与“门后室内”之间要有连接动作
- “坐下”与“开始说话”之间最好有停顿镜头
- “举起手机”与“屏幕特写”之间最好有过渡镜头

**来源：** OpenAI Help Center, *Generating videos on Sora*。

---

#### 4. 问题：角色在不同镜头里脸不一样、身份漂移
**解法：** 使用角色一致性机制，或者把角色作为固定资产管理，在不同镜头中重复调用同一人物设定和约束。

**为什么置信度高：** OpenAI Sora 官方角色页明确支持 character feature，并允许设置角色外观限制；Luma Learning Center 也明确提供 Character Consistency 工作流。

**对你的启发：**
- 同一角色必须反复使用同一组锚点描述
- 如果平台支持角色资产，优先用角色资产而不是每次重写外貌
- 不要在连续镜头里频繁修改发型、服装、年龄、镜头语言

**可执行写法：**
- gray suit, short black hair, narrow face, calm expression
- 每个镜头都重复这组固定描述

**来源：** OpenAI Sora Characters 页面；Luma Learning Center 中的 *Character Consistency* 示例板。

---

#### 5. 问题：你想改一个局部，比如表情或道具，但一改 prompt 整段都崩
**解法：** 用局部编辑思路，只对单一变量做 remix，不要重写整段镜头设定。

**为什么置信度高：** Sora 官方帮助明确将 Remix 定义为“描述变化并基于当前结果生成新视频”。Luma Learning Center 也展示了 facial expression control、replace background、modify lighting 等单变量编辑思路。

**对你的启发：**
- 改表情，就只改表情
- 改背景，就只改背景
- 改道具厚薄，就只改道具描述
- 不要同时改角色、镜头、光线、动作

**来源：** OpenAI Help Center, *Generating videos on Sora*；Luma Learning Center 相关教程列表。

---

### B级中高置信案例

#### 6. 问题：双人对话镜头容易嘴型归属混乱
**解法：** 降维成“单说话主体镜头 + 静默听反应镜头”，并在平台允许时用角色机制锁定人物身份。

**为什么是中高置信：** 官方资料没有直接写“双人对话必须拆镜”，但 Sora 官方强调复杂场景可做，且角色机制和 Storyboard 支持拆解控制。结合实际生成规律，这条推断可信度高。

**可执行写法：**
- Shot 1: only character A speaks, character B listens silently
- Shot 2: reverse shot, only character B speaks

**来源支撑：** OpenAI Sora 支持复杂场景和多角色；Storyboard 支持分时间卡片；Characters 支持角色一致性。

---

#### 7. 问题：同一镜头里变量太多，模型顾不过来
**解法：** 一次只改一个维度，把工作流拆成“主体稳定、动作稳定、道具稳定、镜头稳定”几轮。

**为什么是中高置信：** Luma Learning Center 中多个教程本质都是单变量控制，如 facial expression、background、lighting、camera model、art style。这说明成熟工作流本身就在避免多变量同时改动。

**对你的启发：**
- 不要一次同时改动作、机位、服装、道具、表情
- 先锁主体，再锁动作，再锁风格

**来源：** Luma Learning Center 教程结构本身。

---

#### 8. 问题：复杂动作一镜到底很容易穿帮
**解法：** 改成“起始帧 + 结果帧 + 中间弱化”的结构，用 re-cut 或剪辑完成连续感。

**为什么是中高置信：** 官方帮助没有直接写“开门要拆”，但 Storyboard / Re-cut 的设计就是在鼓励按片段构造视频，而不是把所有动作强塞进一个原生连续镜头。

**可执行写法：**
- 卡片1：角色走近门
- 卡片2：门已打开一半
- 卡片3：角色进入屋内

**来源支撑：** OpenAI Help Center, Storyboard 与 Re-cut 工作流。

---

### C级启发型案例

#### 9. 问题：想要角色长期一致，但每次从零写提示词都在漂
**解法：** 把角色、场景、道具都资产化，形成“可复用控制模块”。

**为什么是启发型：** 这是从 Sora character feature 和 Luma boards / shared context 进一步抽象出的生产方法，不是官方逐字规则，但很符合实际生产。

**具体做法：**
- 角色卡：外貌、服装、体型、神态、禁改项
- 道具卡：材质、颜色、厚度、使用方式
- 场景卡：空间结构、光线、机位限制

**来源支撑：** OpenAI Characters 页；Luma 关于 shared context、boards、character consistency 的介绍。

---

#### 10. 问题：提示词写得很长，但结果反而更散
**解法：** 把长 prompt 改成“结构化控制项”，把剧情交给 storyboard，把单镜头交给局部 prompt。

**为什么是启发型：** 官方没有直接说“长提示词更差”，但 Storyboard、cards、captions、局部编辑体系，本质上就在鼓励结构化控制而不是大段叙述。

**具体模板：**
- 主体：谁在画面中
- 动作：只写一个核心动作
- 镜头：景别、角度、运动
- 约束：谁说话、谁静默、什么不变形

**来源支撑：** OpenAI Help Center 的 Storyboard 机制；Luma Learning Center 的模块化教程。

---

## 九、实战模板库（可直接复制）

### 1. 双人对话模板

#### 场景目标
适用于办公室、客厅、会议室等静态对话戏。

#### 镜头结构
1. 建立镜头，双人同框，不说话
2. A 说话镜头
3. B 反应镜头
4. B 说话镜头
5. A 反应镜头

#### 建立镜头模板
```text
Cinematic realistic interior, two characters facing each other in a modern office, medium wide shot, both characters visible, neither is speaking, subtle breathing and natural posture, stable identity, clean eye line, no lip movement, calm atmosphere.
```

#### A 说话镜头模板
```text
Medium close-up on Character A, over-the-shoulder shot from Character B, Character A is the only speaker, natural lip sync, controlled head movement, calm but focused expression, Character B remains silent and slightly out of focus, no double speaking, no extra mouth movement.
```

#### B 反应镜头模板
```text
Close-up on Character B listening silently, subtle eye movement, slight nod, no lip movement, realistic facial reaction, stable identity, cinematic realism.
```

#### 使用规则
- 一个镜头只允许一个角色说话
- 双人同框镜头尽量不安排台词
- 先保口型归属，再追求情绪复杂度

---

### 2. 开门动作模板

#### 场景目标
适用于进门、出门、推门、拉门等常见动作。

#### 镜头结构
1. 接近门
2. 门已开始开启
3. 人通过门框

#### 镜头1
```text
Medium shot, a man walks toward a wooden apartment door, slows down naturally, reaches his right hand toward the silver handle, realistic body mechanics, stable anatomy, smooth motion.
```

#### 镜头2
```text
Close shot of the door already opening inward smoothly, the silver handle slightly turned down, realistic hinge motion, correct door geometry, no distorted hand, no broken motion.
```

#### 镜头3
```text
Medium shot, the man turns sideways and passes through the half-open door, realistic spacing between body and door frame, natural walking motion, no body deformation.
```

#### 使用规则
- 避免把“抓把手 + 压把手 + 开门 + 进门”塞进一个镜头
- 最难的接触瞬间能弱化就弱化
- 门和手都属于高风险形变区

---

### 3. 递手机模板

#### 场景目标
适用于角色之间递交手机、名片、文件等小物件。

#### 镜头结构
1. 角色A拿出手机
2. 手机递出
3. 角色B接过或看向手机

#### 镜头1
```text
Medium close-up, Character A lifts a slim smartphone from the desk with one hand, smooth natural wrist motion, realistic fingers, stable phone shape, thin side profile.
```

#### 镜头2
```text
Side shot, Character A extends the smartphone forward slowly, offering it to Character B, the phone remains slim and flat, realistic hand pose, no distorted fingers, no thick phone body.
```

#### 镜头3
```text
Close-up on Character B looking at the smartphone, focused expression, subtle eye movement, the device is held steadily in the foreground, realistic proportions.
```

#### 使用规则
- 手机尽量避免高速移动
- 手机不要做大角度翻转
- 先保设备形状，再保手部接触

---

### 4. 坐下模板

#### 场景目标
适用于会议室、办公室、餐桌边等坐下动作。

#### 镜头结构
1. 走到椅子前
2. 身体下沉开始坐
3. 已坐稳并进入表演

#### 模板
```text
Medium shot, Character A walks to the chair and stops, turns slightly, lowers the body naturally into the chair, realistic leg bending, stable torso, smooth seated transition, no broken joints, no sudden deformation.
```

#### 更稳的拆法
- 镜头1：走到椅子边
- 镜头2：已坐下，整理姿态

#### 使用规则
- 坐下属于关节高风险动作
- 如果穿帮率高，优先拆成结果镜头

---

### 5. 回头模板

#### 场景目标
适用于情绪反应、突然察觉、听到声音后的回头。

#### 模板
```text
Medium close-up, Character A slowly turns the head over the left shoulder after hearing something behind, subtle eye movement first, then smooth neck rotation, realistic facial continuity, stable identity, cinematic tension.
```

#### 使用规则
- 回头比转身稳定
- 先眼神动，再头动，更自然
- 大角度快速回头容易脸崩

---

### 6. 显示屏/平板模板

#### 场景目标
适用于办公室、实验室、科技感场景中的屏幕类道具。

#### 模板
```text
A slim futuristic display with an ultra-thin 8mm body, flat glass surface, narrow bezel, lightweight aluminum frame, clean industrial design, realistic proportions, maintaining a thin side profile during movement, no bulky thickness, no brick-like geometry.
```

#### 交互模板
```text
Character A lightly taps the flat glass screen with one finger, subtle touch response on the display, the device remains thin and elegant, no object distortion, no thickened side profile.
```

#### 使用规则
- 明确写厚度、边框、材质
- 强调侧面仍薄
- 避免一镜里又旋转又放大又同步 UI

---

### 7. 文件/纸张模板

#### 场景目标
适用于办公桌、签字、递交资料等情节。

#### 模板
```text
A thin stack of printed documents on the desk, crisp paper edges, realistic paper thickness, slightly matte surface, Character A slides the document forward gently with one hand, natural friction, stable hand pose, no cardboard-like thickness.
```

#### 使用规则
- 纸张要强调 thin paper edges
- 否则容易生成成硬纸板或塑料板

---

### 8. 咖啡杯模板

#### 场景目标
适用于日常生活戏、办公室戏、情绪戏。

#### 模板
```text
A ceramic coffee mug with a thin rim and realistic handle, natural reflection, warm coffee inside, Character A lifts the mug gently from the desk, stable hand position, realistic wrist motion, no melting handle, no oversized cup.
```

#### 使用规则
- 杯把是高风险区
- 不要一边说话一边大幅举杯

---

## 十、场景化方法

### 1. 办公室戏

#### 常见问题
- 显示器太厚
- 文件像硬板
- 说话和翻屏同步时容易炸

#### 建议策略
- 对话镜头和道具操作镜头分开
- 先做稳定办公桌 establishing shot
- 屏幕交互尽量简化成点击、滑动，不做大幅拿起翻转

#### 推荐镜头顺序
1. 办公室环境建立镜头
2. A 说话镜头
3. B 反应镜头
4. 屏幕特写镜头
5. 文件或手部补镜头

---

### 2. 家庭室内戏

#### 常见问题
- 起身、坐下、开门容易穿帮
- 双人情绪对话时口型混乱

#### 建议策略
- 家庭戏优先做中近景，不要过多复杂走位
- 情绪靠表情和停顿，不靠大动作
- 门口戏必须拆镜头

---

### 3. 情绪戏

#### 常见问题
- 一加大情绪，五官就容易漂
- 哭、怒吼、剧烈转头都容易出问题

#### 建议策略
- 先做低强度版本，再逐步加情绪
- 优先做“忍住情绪”的戏，不要直接追求爆发
- 情绪变化最好拆成三个镜头：平静、波动、结果

---

## 十一、推荐生产流程

### 1. 先做角色资产
包括：
- 外貌锚点
- 服装锚点
- 常用表情
- 禁改项

### 2. 再做道具资产
包括：
- 手机
- 显示屏
- 文件
- 门
- 咖啡杯

### 3. 再做场景资产
包括：
- 办公室
- 客厅
- 走廊
- 门口
- 电梯间

### 4. 再写分镜 prompt
每镜只写一个目标。

### 5. 每镜先出多个变体
筛掉：
- 口型错乱
- 角色漂移
- 道具变形
- 动作断裂

### 6. 最后用 remix / re-cut / 剪辑修正
把难问题后置，不要一上来硬拼。

---

## 十二、最后的执行建议

如果要稳定提升出片率，建议按以下顺序优化：

1. 先改镜头设计，再改提示词长度。
2. 先做单人说话镜头，再做双人同框镜头。
3. 先生成稳定道具静态镜头，再加交互。
4. 先拆复杂动作，再考虑一镜到底。
5. 用后期剪辑连接镜头，而不是把所有任务交给模型。
6. 优先采用官方工作流里的 Storyboard、Variations、Remix、Re-cut，而不是纯靠一条 prompt 硬顶。
7. 把角色、道具、场景做成可复用资产库，长期效率会高很多。

---

## 十三、参考来源

1. OpenAI Help Center: *Generating videos on Sora*  
2. OpenAI Sora product page  
3. OpenAI Sora Characters page  
4. OpenAI research/product page: *Sora 2 is here*  
5. Luma Learning Center  
6. Luma product / use case / board examples

---

## 十四、一句话总结

I2V 提示词工程的核心，不是把提示词写得更像小说，而是把生成任务拆得更像拍电影，并尽量复用官方支持的时间轴、变体、角色一致性和局部编辑工作流。