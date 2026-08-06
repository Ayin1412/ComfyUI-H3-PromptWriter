"""H3 视频提示词撰写（API）节点。

节点上只留 4 样东西：模式、时长、左边的 query 框、右边的 prompt 框。
所有 API 参数都在「🔑 API 设置」面板里，见 config.py。

写提示词是点节点上的「✍️ 生成提示词」按钮触发的：前端把整张图连同
partial_execution_targets 一起提交，ComfyUI 只跑这个节点和它上游的图片节点，
此时 action=generate，节点才会调用 API。

正常运行整个工作流时 action=passthrough，节点不碰 API，直接把右边框里的内容输出。
"""

import re

from . import config
from .h3_guide import build_system_prompt
from .images import frames_to_data_urls
from .modes import MODE_LABELS, MODE_SPEC, mode_code
from .openai_client import build_user_message, complete

_IMAGE_RE = re.compile(r"^image_(\d+)$")
# 模型有时会把结果包在 ```text ... ``` 里，去掉围栏
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)

GENERATE = "generate"


def _collect_images(kwargs, max_side):
    """按 image_1、image_2 … 的编号顺序收集所有帧；一个输入接了 batch 就按帧展开。"""
    numbered = []
    for key, value in kwargs.items():
        m = _IMAGE_RE.match(key)
        if m and value is not None:
            numbered.append((int(m.group(1)), value))
    numbered.sort(key=lambda p: p[0])

    urls = []
    for _, batch in numbered:
        urls.extend(frames_to_data_urls(batch, max_side=max_side))
    return urls


def _check_count(code, n_images):
    spec = MODE_SPEC[code]
    want = spec["images"]
    if want is None:  # Ref2VA 不限张数，但至少要有一张
        if n_images < 1:
            raise ValueError("Ref2VA 模式至少要接 1 张参考图（可以接多个 image 输入，每个输入也能是多图 batch）。")
        return
    if n_images != want:
        names = "、".join(spec["slots"]) if spec["slots"] else "不需要图片"
        raise ValueError(
            f"{code} 模式需要 {want} 张图，现在收到 {n_images} 张（{names}）。"
            "注意一个 image 输入如果接的是多图 batch，会按帧分别计数。"
        )


def _clean(text):
    text = (text or "").strip()
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text


class H3PromptWriter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (MODE_LABELS, {
                    "default": MODE_LABELS[1],
                    "tooltip": "生成模式，决定左边需要接几张图、每张图是什么含义：\n"
                               "T2VA 纯文本，不接图\n"
                               "I2VA 接 1 张，作为首帧\n"
                               "FL2VA 接 2 张，依次是首帧、尾帧\n"
                               "L2VA 接 1 张，作为尾帧\n"
                               "Ref2VA 接任意多张参考图（可继续往下加输入，每个输入还能接多图 batch）",
                }),
                "duration_seconds": ("FLOAT", {
                    "default": 6.0, "min": 1.0, "max": 120.0, "step": 0.5,
                    "tooltip": "目标视频时长（秒），用来对齐首尾帧时间点和镜头切换时间。",
                }),
                "query": ("STRING", {
                    "multiline": True, "dynamicPrompts": False, "default": "",
                    "tooltip": "用大白话写你想要的视频：内容、动作、镜头、台词、氛围、音效。中英文都行。",
                }),
                "result": ("STRING", {
                    "multiline": True, "dynamicPrompts": False, "default": "",
                    "tooltip": "写好的 H3 提示词，可以直接手改；节点输出的就是这里的内容。",
                }),
                # 前端会把这个 widget 隐藏起来。只有点「✍️ 生成提示词」提交的那次任务
                # 会被前端改成 generate，其余情况一律是 passthrough。
                "action": ("STRING", {"default": "passthrough"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    OUTPUT_TOOLTIPS = ("写好的 H3 视频提示词，接到视频节点的正向提示词上",)
    FUNCTION = "write"
    CATEGORY = "MiniMax H3"
    OUTPUT_NODE = True  # 「✍️ 生成提示词」要靠 partial_execution_targets 单独跑这个节点
    DESCRIPTION = "按官方 h3-prompt-writing 规范把想法和参考图写成 H3 视频提示词。运行工作流时不调用 API，只输出框里的内容。"

    @classmethod
    def IS_CHANGED(cls, action="passthrough", **kwargs):
        # 点一次「生成」就要真的重算一次，不吃缓存；正常运行时走默认的按输入缓存。
        if action == GENERATE:
            return float("nan")
        return False

    def write(self, mode, duration_seconds, query, result, action="passthrough", **kwargs):
        if action != GENERATE:
            text = _clean(result)
            if not text:
                print("[H3PromptWriter] 提示词框是空的，输出了空字符串。"
                      "先点节点上的「生成提示词」按钮，或者直接往右边的框里粘一段。")
            return {"ui": {"h3_prompt": [text]}, "result": (text,)}

        if not (query or "").strip():
            raise ValueError("请先在左边的 query 框里写清楚你想要什么样的视频。")

        code = mode_code(mode)
        cfg = config.settings()
        if not cfg["api_key"]:
            raise ValueError("没有找到 API Key。点节点上的「API 设置」按钮填一次即可，"
                             "或者设置环境变量 OPENAI_API_KEY。")

        image_urls = _collect_images(kwargs, cfg["max_image_side"])
        _check_count(code, len(image_urls))

        system = build_system_prompt(code, len(image_urls), duration_seconds,
                                     cfg["extra_requirements"])
        user = build_user_message(
            "Video request from the user (may be written in Chinese; the rewrite must still be "
            f"in English):\n{query.strip()}",
            image_urls,
            detail=cfg["image_detail"],
        )

        raw, _ = complete(
            cfg["base_url"], cfg["api_key"], cfg["model"],
            [{"role": "system", "content": system}, user],
            temperature=cfg["temperature"], max_tokens=cfg["max_tokens"],
            timeout=cfg["timeout"], retries=cfg["retries"],
        )
        text = _clean(raw)
        if not text:
            raise RuntimeError("模型返回内容为空，换个模型或在设置里调高 max_tokens 再试。")

        return {"ui": {"h3_prompt": [text]}, "result": (text,)}


NODE_CLASS_MAPPINGS = {"H3PromptWriter": H3PromptWriter}
NODE_DISPLAY_NAME_MAPPINGS = {"H3PromptWriter": "H3 视频提示词撰写 (API)"}
