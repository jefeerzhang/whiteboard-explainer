# 第三方依赖归属（Third-party attribution）

本 skill 运行时依赖以下第三方组件，均为开源，但**不随 skill 包分发源码**——由 `scripts/setup.sh` / `setup.ps1` 在安装时通过 pip 从 PyPI 自动获取。

## whiteboard-animator（白板手绘引擎）

- **用途**：像素级白板手绘动画渲染引擎（连通域检测 + CRAFT 文字识别 + 逐笔绘制）
- **上游**：https://github.com/masihsultani/whiteboard-animator
- **作者**：Masih Sultani
- **PyPI**：`whiteboard-animator==0.1.1`（MIT License）
- **获取方式**：setup 时 `pip install whiteboard-animator==0.1.1`（见 `requirements.txt`）

## CRAFT 文字检测模型（craft.onnx）

- **用途**：文字区域检测（区分「文字逐字写出」vs「图形描边」）
- **上游**：https://github.com/clovaai/CRAFT-pytorch （Clova AI Research）
- **来源**：`whiteboard_animator/models/craft.onnx`，是 CRAFT-pytorch `craft_mlt_25k` 权重的 ONNX 导出
- **体积**：约 83MB，随 `whiteboard-animator` pip 包自动下载，**不随本 skill 分发**
- **许可**：Clova AI Research 条款，**非商业用途**。商业部署请替换为商用授权的 OCR 模型。

## 为什么源码不再 vendor 进 skill

早期版本把整个 whiteboard-animator 源码 + 83MB 模型 vendor 进 `vendor/`，导致 skill 包体积约 90MB，不符合 skill 体积规范。现改为：skill 只声明 `whiteboard-animator==0.1.1`，引擎与模型在用户首次 setup 时由 pip 从 PyPI 拉取。引擎源码与 PyPI 0.1.1 已做逐字节 diff 校验，零差异，行为完全一致。
