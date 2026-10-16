#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""autofix_boxes.py — 自动为未归属组件生成兜底 box 并写回 plan.build.json / plan.json

规则:上半页(y<50%)的未归属组件 → 并入该场景第一个 region;下半页 → 并入最后一个 region。
每个 region 收到的所有补框,合并为一个尽量小的外接框(加 12px 余量)追加为该 region 的多 box。
用法: python autofix_boxes.py plan.build.json   (会同步重建 plan.json 的调用方自行处理)
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from whiteboard_animator import WhiteboardAnimator


def boxes_of(region, sw, sh):
    raw = region.get("box")
    items = raw if isinstance(raw, list) and raw and isinstance(raw[0], (list, dict)) else [raw]
    out = []
    for b in items:
        if isinstance(b, dict):
            b = [b["ymin"], b["xmin"], b["ymax"], b["xmax"]]
        ymin, xmin, ymax, xmax = [int(v) for v in b]
        out.append((xmin / 1000 * sw, ymin / 1000 * sh, xmax / 1000 * sw, ymax / 1000 * sh))
    return out


def main() -> int:
    plan_path = Path(sys.argv[1]).resolve()
    root = plan_path.parent
    an = WhiteboardAnimator(fade_duration=0.06)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    total_fixed = 0
    for scene in plan["scenes"]:
        img = np.array(Image.open(root / scene["image"]).convert("RGB"))
        small = an._enforce_white_bg(an._downscale(img))
        comps = an._find_components(small)
        sw, sh = small.shape[1], small.shape[0]
        regions = scene.get("regions", [])
        if not regions:
            continue
        boxes = []
        for r in regions:
            boxes.extend(boxes_of(r, sw, sh))
        lost = []
        for c in comps:
            x0, y0, x1, y1 = c["left"], c["top"], c["right"], c["bottom"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            area = max((x1 - x0) * (y1 - y0), 1)
            owned = False
            for bx0, by0, bx1, by1 in boxes:
                if bx0 <= cx <= bx1 and by0 <= cy <= by1:
                    owned = True
                    break
                inter = (max(0, min(x1, bx1) - max(x0, bx0)) * max(0, min(y1, by1) - max(y0, by0)))
                if inter / area >= 0.25:
                    owned = True
                    break
            if not owned:
                lost.append((x0, y0, x1, y1))
        if not lost:
            continue
        top = [c for c in lost if (c[1] + c[3]) / 2 < sh / 2]
        bot = [c for c in lost if (c[1] + c[3]) / 2 >= sh / 2]
        for group, target in ((top, regions[0]), (bot, regions[-1])):
            if not group:
                continue
            ux0 = max(0, int(min(c[0] for c in group)) - 12)
            uy0 = max(0, int(min(c[1] for c in group)) - 12)
            ux1 = min(sw - 1, int(max(c[2] for c in group)) + 12)
            uy1 = min(sh - 1, int(max(c[3] for c in group)) + 12)
            box = [round(uy0 / sh * 1000), round(ux0 / sw * 1000),
                   round(uy1 / sh * 1000), round(ux1 / sw * 1000)]
            cur = target.get("box")
            items = cur if isinstance(cur, list) and cur and isinstance(cur[0], list) else [cur]
            items.append(box)
            target["box"] = items
            total_fixed += len(group)
            print(f"  {scene['id']}: 补框 -> {target['label']} (+{len(group)} 组件)")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"autofix 完成，共处理 {total_fixed} 个组件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
