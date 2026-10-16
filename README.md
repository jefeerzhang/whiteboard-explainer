# whiteboard-explainer

白板讲解动画 skill。把讲解稿变成「真手绘过程」视频——图形一笔笔描出、文字逐笔写出、讲到哪画到哪（帧级音画对齐）。

> 本 skill 是**像素级笔画绘制**——帧帧确定、本地零成本、可秒级重渲，且支持"一图逐元素生长"的单画布模式（数学推导/流程图 友好）。

## 快速开始-安装使用

```bash
在workbuddy，codex, claude code，直接命令要求安装skill:https://github.com/liangdabiao/whiteboard-explainer
```

安装后，技能会在 workbuddy,Claude Code 、codex 中按学科关键词自动激活，也可手动调用。

例如： 利用 whiteboard-explainer skill 帮忙制作一个视频：  解释日全食

❯ whiteboard-explainer  ：英文教学制作  deepmind的故事

---

## Demo视频演示

B站demo演示： https://www.bilibili.com/video/BV1z4YW6UEER/

![](动画.gif)

 
## 它能做什么 / 不能做什么

**能**：
- 一拍一图的 slide 模式，适合步骤讲解、产品介绍、教学课程。
- 一张大图逐元素生长的「单画布模式」，适合数学推导 / 流程图 / 知识图谱。
- 元素级 cue 对齐（"讲到哪画到哪"，旁白→绘制 帧级同步）。
- 中文 / 英文 / 任意语种旁白（edge-tts）。
- 跨平台（macOS / Windows / Linux）。

**不能 / 注意**：
- 真人物 / 照片 / 复杂场景 → 用真人视频或别的 skill，白板风不合适。
- 8K / 超高清 → 引擎最大输出 1280 长边；要高清请在 final concat 步骤自己 upscale。
- Agnes 是付费 API（虽然免费档便宜），不放 key 时用 PIL 程序化绘制。

## 文件结构

```
whiteboard-explainer/
├─ SKILL.md                     # 入口文档（AI agent 用这一份当系统 prompt）
├─ README.md                    # 你现在读的（人类开发者用这一份）
├─ LICENSE                      # MIT
├─ requirements.txt             # pip 依赖清单
├─ .gitignore
├─ assets/
│  └─ fonts/
│     ├─ MaShanZheng-Regular.ttf   # 毛笔字（OFL，差异化设计）
│     └─ OFL-MaShanZheng.txt       # 字体授权
├─ scripts/
│  ├─ setup.sh / setup.ps1     # 一键安装
│  ├─ self_test.py              # 自检（CRAFT/渲染/cue 对齐三关）
│  ├─ build_narration.py        # 子句 TTS + 精确 cue
│  ├─ render_explainer.py       # 主渲染
│  ├─ make_text_layer.py        # PIL 确定性中文文字层
│  ├─ gen_board_images.py       # Agnes 白板生图
│  ├─ gen_tts.py                # 复用脚本（旁白批量生成）
│  └─ slice_from_lrc.py         # 复用脚本（按 LRC 切片音频）
├─ lib/
│  └─ lib_agnes.py              # Agnes HTTP 客户端（带重试）
├─ vendor/
│  └─ ATTRIBUTION.md            # 第三方依赖归属（引擎/模型来源与许可）
├─ references/
│  ├─ pipeline.md               # 完整流水线（含踩坑记录）
│  └─ region-plan-guide.md      # plan.build.json 写法详解
└─ templates/
   ├─ region-plan.example.json  # 抄改起点
   └─ chart-recipes/
      └─ eclipse.py             # PIL 程序化绘制示范（影锥/轨道倾角/五阶段）
```

## 依赖与安装位置

| 依赖 | 类型 | 必须？ | 在哪 |
|---|---|---|---|
| `whiteboard-animator` | pip 包 | ✅ | PyPI `==0.1.1`（自带 CRAFT 模型，setup 自动安装） |
| `onnxruntime` | pip 包 | ✅ | PyPI |
| `edge-tts` | pip 包 | ✅ | PyPI |
| `Pillow` / `numpy` | pip 包 | ✅ | PyPI |
| `ffmpeg` / `ffprobe` | 系统二进制 | ✅ | PATH（setup 会检测） |
| `AGNES_API_KEY` | Agnes API 凭证 | 可选 | `.env` 或环境变量 |

`.env` 寻找顺序：cwd → 父目录 → `~/.env` → `~/.workbuddy/.env`，找不到则硬报错（不会静默失败）。

详见 [`references/pipeline.md`](references/pipeline.md)。

## 协议

- **skill 本身**：MIT（见 `LICENSE`）
- **whiteboard-animator**：MIT（上游 [masihsultani/whiteboard-animator](https://github.com/masihsultani/whiteboard-animator)）
- **MaShanZheng-Regular.ttf**：SIL Open Font License 1.1（见 `assets/fonts/OFL-MaShanZheng.txt`）
- **CRAFT 模型**（craft.onnx）：Naver Clova AI Research，非商业用途

第三方归属与具体出处见 [`vendor/ATTRIBUTION.md`](vendor/ATTRIBUTION.md)。

## 致谢

- whiteboard-animator 引擎来自 [masihsultani/whiteboard-animator](https://github.com/masihsultani/whiteboard-animator) （MIT）
- 中文毛笔字体 [Ma Shan Zheng](https://fonts.google.com/specimen/Ma+Shan+Zheng) by Neural Reasoning
- 文字检测 [CRAFT](https://github.com/clovaai/CRAFT-pytorch) by Clova AI
- linuxdo 社区支持 ： https://linux.do