# Whiteboard Explainer 完整流水线

## 总览

```
讲稿（plan.build.json）
  ├─ boards/*.png      ← gen_board_images.py（Agnes）/ PIL 程序化 / 用户图 + make_text_layer.py（文字层）
  ├─ audio/narration/  ← build_narration.py（逐 region 子句 TTS → 分片时长 = 精确 cue）
  └─ plan.json         ← build_narration.py 产出（含 regions start/end）
        │
        ▼
render_explainer.py
  ├─ 每拍：WhiteboardAnimator.render_to_file(element_plan=精确cue) → <sid>.mp4（含音轨）
  └─ concat → 成片 mp4
```

## 白板引擎原理（为什么快且确定）

whiteboard-animator（MIT，CPU-only）：
1. 连通域找墨迹（灰度 <240），CRAFT ONNX 模型标记哪些是文字
2. 按人手习惯排序：容器先于内容、形状先于标签、文字按阅读顺序
3. 每个组件分配绘制时间窗（骨架描边、行走前端、刷笔填充、文字逐词写出）
4. 每像素赋一个显现时刻，流式喂 ffmpeg

无 GPU、无 API key、无训练。渲染耗时 ≈ 视频时长。

## 音画对齐：逐子句 TTS 法

传统整句 TTS 只能整场对齐。本 skill 的方法：

1. 每拍按 region 拆成子句（annotation）
2. 每个子句单独 edge-tts → `<sid>_rNN.mp3` 分片
3. 分片之间垫 gap 秒静音 → concat 成该拍音轨
4. 累加分片真实时长 → 每个 region 的 [start, end] **就是帧级 cue**

子句粒度建议 8–25 字（一句完整语义）；gap 0.35s 保证听感自然。

**尾部窗口 clamp**：最后一个 region 的 end clamp 到音轨实际长度，防止 ffprobe 毫秒级误差触发引擎的 `schedule exceeds cue window`。

## 引擎自动放宽机制

element_plan 窗口装不下绘制量时，`_schedule_elements` 压缩不充分会抛 RuntimeError。render_explainer.py 自动把所有窗口 start/2、end×1.15×N 重试最多 3 次，因此 plan 里 cue 不必留大量余量。

## 渲染参数

| 参数 | 值 |
|---|---|
| quality low/medium/high | 20fps 500k / 24fps 1500k / 24fps 3000k |
| fade_duration | 有 element_plan 时 0.06s（快节奏），无 plan 0.12s |
| 音轨 | ffmpeg mux aac，`-shortest` |
| concat | `-c copy`（分拍参数一致时无损） |

## 成本与速度实测（eclipse-solar，8 拍 110.7s）

- Agnes 生图 3 张：10s（免费）
- PIL 绘图 5 张：<1s
- TTS 14 分片：约 60s（免费，含重试）
- 白板渲染 8 拍 110.7s 视频：64s
- 总计约 2.5 分钟，零 API 成本

## 可选增强（未实施）

- Remotion 叠加字幕/教学卡（复用 story-handdrawn-video 的模板，白板动画 mp4 作底层）
- Gemini `--detect-regions` 自动生成 region plan（引擎自带 CLI 支持，需 GOOGLE_API_KEY）
- matplotlib 生成数据图表 → 白板动画
