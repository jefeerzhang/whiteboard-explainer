# whiteboard-explainer 样式增强方案

> 调研对象：`frametell-main`（AGPL-3.0，pnpm monorepo，Sitor 团队）
> 目标：让 whiteboard-explainer 不再只有「纯白底 + 记号笔」一种样子
> 结论日期：2026-10-16

---

## 一、诊断：为什么换配色没用

你观察到「样式单调 = 白背景」。深挖代码后，真实原因不是配色选得不好，而是**渲染引擎的架构性硬编码**。

### 1.1 引擎的两处白底硬编码

`whiteboard-animator`（PyPI 官方包 `==0.1.1`）内部：

| 位置 | 代码 | 后果 |
|---|---|---|
| `animator.py:1324` | `r[gray > 240] = [255, 255, 255]` | 灰度 >240 的像素被**强制刷成纯白** |
| `video_encoding.py:107` | `frame_buf = np.full((h,w,3), 255)` | 帧缓冲初始化为纯白 |
| `video_encoding.py:116` | `cy, cx = np.where(gray < 240)` | 只有灰度 <240 的像素被当作「内容」去画 |

`SKILL.md:163` 把这条约束写成了铁律：

> **底图硬规则（ink-on-white）**：白底（近白像素引擎会 snap 成白）；灰度 <240 才算墨

### 1.2 这意味着什么

- 米色背景 `#F5F0E8`（灰度 ≈ 240）→ 被刷成纯白，**改了等于没改**
- 深色背景 `#2A3631`（灰度 ≈ 54）→ 整块被当「内容」，会被逐笔描出来，**等于全屏乱涂**
- 所以在 `board_widgets.py` 里换任何色板，最终都会被引擎拉回纯白

**这是本次调研最重要的一句话：改造点在渲染管线，不在绘图素材。**

### 1.3 好消息：架构本身留了门

引擎内部是**逐像素时间遮罩**模型：

```python
# video_encoding.py:107
"""timing holds each pixel's reveal time in seconds (inf = background)."""
```

背景像素的 reveal time 是 `inf`，**永远不会被"画"出来**，只是作为底存在。也就是说引擎并不真正需要"白色背景"，它只是**把白色硬编码成了那个底**。

只要把「底」从常量 255 换成可配置值，深色/暖色主题立刻成立。这是整个方案的支点。

---

## 二、frametell 的样式资产盘点

### 2.1 主题包架构（最值得移植的部分）

`frametell-main/packages/engine/styles/` 下有 5 套完整主题：

| 主题 | 底色 | 线条 | 定位 |
|---|---|---|---|
| `study` | 暖纸 `#FBF8F1` | 干净单描 | 默认 |
| `warm-story` | 暖米`#FBF4E8` | 几乎无抖动，扁平 | 故事/科普 |
| `whiteboard` | 近白 `#FDFDFC` + 斜向光泽 | 抖动 1.2，双描 | 马克笔 |
| `chalkboard` | 黑板绿 `#2A3631` | 抖动 0.95 + 粉笔孔洞滤镜 | 黑板 |
| `tech-dark` | 石墨 `#1B1E21` + 48px 网格 | 几乎无抖动 0.15，线宽 2.4 | 技术 |

每套只有 3 个文件，核心 `style.js` **仅 24–37 行**：

```javascript
window.STYLE = {
  id: 'chalkboard',
  roughScale: 0.95, bowScale: 0.9, sw: 3.6, single: false,   // 线条手感
  palette: { ink, soft, muted, faint, red, redF, orange, ... },  // 统一键名
  background: (stage) => [...].join(','),                        // 任意 CSS
};
```

**风格差异 = 4 个数字 + 一张色表 + 一个背景函数。** 这是极好的抽象。

### 2.2 统一调色板契约（移植的抓手）

所有主题共享**完全相同的键名**：

```
ink  soft  muted  faint  paper
red redF   orange orangeF   green greenF
blue blueF purple purpleF   yellow
inkF softF mutedF faintF
```

含义：
- `ink` = 主线条色；`paper` = 底色
- `xxxF` = 该色**向 paper 混合**的浅填充（深色主题下自动变暗）
- 组件代码只写语义名（`BLUE`/`BLUE_LT`），主题包负责解析成实际色值

frametell 靠 `runtime/look.js` 实现**单片覆盖**：一部片子可在主题之上再改几个色值，不动主题包。

### 2.3 可直接搬走的资产

| 资产 | 位置 | 价值 |
|---|---|---|
| 5 套主题色表 | `styles/*/style.js` | 直接改写成 Python dict |
| 34 个手绘图标 | `runtime/doodles.js` | `person/robot/gear/clock/brain/rocket`… 全部零硬编码色 |
| 文案纪律卡 | `styles/*/GRAMMAR.md` | 每套主题的构图/节奏/禁忌规则 |
| 抖动手感参数 | `roughScale/bowScale/sw/single` | 4 个数字控制"手绘感" |
| **背景纹理配方** | 各 `style.js` 的 `background()` | SVG 噪声滤镜 + 径向渐变 |

### 2.4 license 说明（重要）

frametell 是 **AGPL-3.0-only**。
- ✅ 移植**色值、参数、构图规则、算法思路** → 属于思想/事实，不构成著作权问题
- ⚠️ 直接**复制粘贴其源码文件**（尤其 `doodles.js` 的图标路径数据）→ 会有许可传染风险
- ✅ 稳妥做法：按截图/描述**重新实现**图标与背景，用同样数值，附 `vendor/ATTRIBUTION.md` 说明来源

白板 skill 已有 `vendor/ATTRIBUTION.md`，沿用该模式即可。

---

## 三、优化方案（三条路线）

### 路线 A：背景层换肤（最小改动，立刻见效）

**不动引擎**，在生成 PNG 阶段换底色，渲染前把非白底"压"回去或采用浅色系。

- ✅ 改动量：1 个新文件 + `board_widgets.py` 改 10 行
- ✅ 立刻摆脱"纯白"，可做暖米色/淡蓝灰/淡黄等**浅色主题**
- ❌ 做不了深色（会被引擎当内容）
- ❌ 白底占比校验（`gen_board_images.py:93` 要求 >60%）要跟着调

**适用**：想快速看到变化、只做浅色换肤。

### 路线 B：自研渲染后端，彻底换引擎（推荐）

**放弃 `whiteboard-animator`，自建 PIL 渲染器**，把 frametell 的样式系统搬进来。

核心工作：

1. **主题系统**
   - 新建 `lib/theme.py`：`THEMES = {"whiteboard": {...}, "warm": {...}, "ink": {...}}`
   - 键名与 frametell 对齐（`ink/soft/muted/faint/paper/red/redF/...`）
   - `board_widgets.py` 里所有 `INK/BLUE_LT/YELLOW_LT` 改成查表函数 `C("blueF")`
   - 背景由 `paint_background(style)` 生成（渐变 + 噪点）

2. **手绘线条**
   - 引入 `roughpy`（Python 版 Rough.js，API 几乎一致）或自写抖动算法
   - 参数沿用 frametell 的 `roughScale/bowScale/sw/single`
   - 现有 `d.line/d.rectangle` 换成 sketchy 版本

3. **擦除揭示动画**
   - 保留现有 region 机制（`plan.json` 的 `regions` + `start/end`）
   - 用**蒙版生长**替代引擎的连通域描边：按 region 顺序，逐帧把该 region 的像素从"未画"状态擦到"已画"
   - 文字用现有的 CRAFT 检测或直接按 region 矩形擦出

4. **兼容层**
   - `render_explainer.py` 保留命令行接口，`--style warm|ink|whiteboard`
   - 老项目零改动继续跑（默认 `whiteboard`）

- ✅ 彻底解锁深色/黑板/暖色，风格无上限
- ✅ 不再依赖闭源包，`requirements.txt` 可去掉 83MB 模型（若自写文字擦除）
- ⚠️ 工作量最大：约 800–1200 行新代码
- ⚠️ 需回归测试所有已有项目

**适用**：这是唯一能真正解决"样式单调"的路线。

### 路线 C：混合层（折中，推荐先做）

**保留 `whiteboard-animator` 做擦除动画，但把底图预先烘焙成它能接受的形式。**

关键洞察：引擎只是要"灰度<240 = 内容"。所以——
- **深色主题**：让引擎渲染**纯白底的浅色图形**（把深色反相），再用 ffmpeg/后期把整片**调色**成深色
- **暖色主题**：渲染完在后期叠一层暖色滤镜（LUT / colorbalance）

- ✅ 改动量小（后期处理 + 一个反相工具）
- ✅ 可做深色
- ❌ 文字颜色要反着配（深底浅字→渲染时得给白底黑字，最后反相），逻辑绕
- ❌ 颜色精度受损（反相后再调色，颜色会偏）

**适用**：想低成本试水深色效果。

---

## 四、推荐执行路径

我建议 **A → C → B** 三步走，每步都能独立交付：

| 阶段 | 做什么 | 产出 | 风险 |
|---|---|---|---|
| **第 1 步** | 路线 A：`lib/theme.py` + 背景函数，3 套浅色主题 | 立刻不再纯白 | 极低 |
| **第 2 步** | 路线 C：反相 + 后期调色，验证深色可行性 | `tech-dark`/`chalkboard` 可用 | 中 |
| **第 3 步** | 路线 B：自研渲染后端，移植 roughjs + 34 图标 | 风格无上限 | 高，但有前两步兜底 |

### 第 1 步的具体改动清单

```
新增  lib/theme.py               主题表（whiteboard / warm-paper / dusk）
新增  lib/backgrounds.py         渐变+噪点背景生成
改写  scripts/board_widgets.py   颜色常量 → C("name") 查表
改写  scripts/gen_board_images.py  风格头 + 白底占比阈值随主题变
新增  references/style-themes.md  主题使用说明 + 各自 GRAMMAR
```

---

## 五、各主题的构图纪律（移植自 frametell GRAMMAR.md）

这部分是 frametell 真正的"品味"，比配色更值钱。

### warm-story（推荐给知识科普）
- 一个**隐喻物件**贯穿全片（雪球 / 存钱罐 / 天平 / 树苗 / 沙漏）
- 大色块扁平、几乎无抖动、少描边
- 暖色系 + 一个强调色；**一屏最多三色**
- 大物件、少文字；每元素中文 ≤8 字，正文 ≥36px
- **数字写在物件上**（金额在存钱罐上），不做独立数字卡
- 图表也画成 scenery：增长曲线=山路，时间线=小路
- **不画脸**：需要人物时只画手/背影/剪影
- 节奏：慢而有力，0.6–1.2s 缓入；每 3–6 秒一次可见变化

### tech-dark（推荐给技术/代码讲解）
- 石墨底 + 48px 极淡网格；`ink` 是暖白，`paper` 是浮起面板
- **所有 `*F` 填充都是深色**，方框只是"略亮的板"，绝不做发光块
- **一个强调色**：teal。amber=警告/成本，coral=错误，green=成功。无此含义就不用
- 干净线条：几乎无抖动、单描、线宽 2.4、直角、填充纯平无排线
- **等宽字体讲要点**：函数名/命令/文件名/端口/延迟
- 图=主体；**数字写在图上**（延迟标在箭头旁），不设独立数字卡

### chalkboard
- 深绿黑板 `#2A3631` + 半擦粉笔的涂抹痕迹 + 角落粉尘
- **粉笔孔洞滤镜**：给每个绘制层打洞，才像粉笔不像矢量线
- 粉笔色是浅色：`ink: '#F1ECE1'`，`red: '#F0A3A0'`（粉红粉笔）
- 暗板上的浅色填充会像灯箱发光，**所有填充都贴近板面色**

---

## 六、一个立刻可试的最小验证

在投入大改之前，先花 10 分钟证明路线 B 可行：

```python
# 验证：反相渲染能否让引擎吐出深色视频
# 1) 用现有 whiteboard 流程出一张白底图
# 2) PIL 反相：ImageOps.invert()
# 3) 喂给 animator 渲染
# 4) ffmpeg 再反相回来 → 得到黑底白线的黑板风视频
```

如果这个 4 步跑通，路线 C 立即可用；如果跑通且质量可接受，说明引擎对深色没有根本性阻碍，路线 B 就值得做。

---

## 七、结论

1. **样式单调不是配色问题**，是 `whiteboard_animator` 两处白底硬编码（`gray>240 → 255`、`frame_buf=255`）。
2. **改造点在管线，不在 `board_widgets.py`**。在绘图层换色 100% 无效。
3. **frametell 最值得移植的是样式系统架构**：4 个数字（`roughScale/bowScale/sw/single`）+ 统一 palette 键名 + 可插拔 background，而不是它的具体色值。
4. **引擎架构留了门**：逐像素时间遮罩（`inf = background`）意味着背景本可以任意，把硬编码的 255 参数化即可。
5. **注意 license**：frametell 是 AGPL-3.0，抄思想不抄代码，图标与背景建议重写并记入 `vendor/ATTRIBUTION.md`。
6. **推荐 A → C → B 三步走**，每步可独立交付，第 1 步当天就能看到变化。

---

## 附：关键代码位置索引

```
frametell-main/packages/engine/
  styles/whiteboard/style.js      26 行，近白马克笔（与本 skill 同名，可直接对照）
  styles/warm-story/style.js      25 行，暖色扁平
  styles/chalkboard/style.js      37 行，黑板（含粉笔孔洞滤镜实现）
  styles/tech-dark/style.js       24 行，石墨深色（含网格背景）
  styles/*/GRAMMAR.md每套主题的构图纪律卡
  runtime/core.js:193-203ro() 线条参数装配（roughScale/bowScale/single 的乘算）
  runtime/core.js:215-219texture() 排线纹理叠加
  runtime/core.js:20-33          col() 颜色解析：xxxF 自动向 paper 混合
  runtime/look.js单片 look 覆盖机制
  runtime/doodles.js              34 个手绘图标（零硬编码色）

whiteboard-explainer/
  scripts/board_widgets.py        495 行，PIL 绘图组件库（颜色常量在这里）
  scripts/render_explainer.py:228-231  图片读入 + 强制白底合成
  scripts/gen_board_images.py:93  白底占比 >60% 校验
  SKILL.md:162-164底图 ink-on-white 铁律
```