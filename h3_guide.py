"""按官方 h3-prompt-writing skill 拼系统提示词。

references/ 下的两份指南直接取自 MiniMax-AI/MiniMax-H3 仓库的 skills/h3-prompt-writing/references，
原样带在节点包里，不做改写；这里只负责把它们塞进 system prompt，再补上本次任务的模式、时长和图片编号约定。
"""

import os

from .modes import MODE_SPEC

_REF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "references")
_cache = {}


def _read(name):
    if name not in _cache:
        path = os.path.join(_REF_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                _cache[name] = f.read()
        except OSError as e:
            raise RuntimeError(f"读不到参考文档 {path}：{e}") from e
    return _cache[name]


def _fmt_seconds(duration):
    """时长统一写成两位小数，指南里的 S.SS 就是这个格式。"""
    return f"{float(duration):.2f}"


def _picture_rules(code, n_images, duration):
    """告诉模型这次挂了几张图、每张图对应哪个 <Picture N>。"""
    secs = _fmt_seconds(duration)
    if code == "T2VA":
        return "No reference image is provided. Build the entire timeline from the user request."
    if code == "I2VA":
        return (
            "One reference image is attached. It is <Picture 1>, the actual first frame of the "
            "target video at 0.00 seconds, belonging to [Shot 1]."
        )
    if code == "FL2VA":
        return (
            "Two reference images are attached, in order. The first attached image is <Picture 1>, "
            f"the first frame at the 0.00-second mark. The second attached image is <Picture 2>, the "
            f"last frame at the {secs}-second mark."
        )
    if code == "L2VA":
        return (
            "One reference image is attached. It is <Picture 1>, the last frame of the target video "
            f"at the {secs}-second mark, belonging to the final [Shot N]. It is NOT the first frame."
        )
    # Ref2VA
    labels = ", ".join(f"<Picture {i}>" for i in range(1, max(n_images, 1) + 1))
    return (
        f"{n_images} reference image(s) are attached, in order: {labels} (the first attached image is "
        "<Picture 1>, the second is <Picture 2>, and so on). Only image references exist in this task: "
        "do not invent <Video N> or <Audio N> labels. Define a <Subject N> for every piece of reusable "
        "visible content, and keep a standalone <Picture N> entry only when that image itself anchors a "
        "concrete frame or the shot planning."
    )


def _output_contract(code):
    """要求模型只吐最终 prompt，别加解释和代码围栏。"""
    if code == "Ref2VA":
        fields = (
            "subject_definitions, summary, retention_analysis, detailed_description, "
            "overall_soundscape, non_diegetic_music"
        )
        head = "Follow the six-section full-reference format"
    else:
        fields = "integrated_multimodal_description, overall_soundscape, non_diegetic_music"
        head = "Follow the base-mode final prompt structure"
        if code in ("I2VA", "FL2VA", "L2VA"):
            head += " (the alignment instruction line first, then one blank line, then the fields)"
    return (
        f"{head}. Emit exactly these sections in this order: {fields}.\n"
        "Output ONLY the final prompt text. No markdown code fences, no headings, no preamble, no "
        "explanation, no translation notes, and no commentary before or after it."
    )


def build_system_prompt(code, n_images, duration, extra_requirements=""):
    """拼出发给模型的 system prompt。"""
    spec = MODE_SPEC[code]
    guides = [("base-en.txt", _read("base-en.txt"))]
    if code == "Ref2VA":
        guides.append(("ref-en.txt", _read("ref-en.txt")))

    parts = [
        "You are a MiniMax H3 video prompt writer. You rewrite a user's video request into an H3 "
        "generation prompt, strictly following the official guides below.",
        "",
    ]
    for name, text in guides:
        parts += [f"<guide name=\"{name}\">", text.strip(), "</guide>", ""]

    parts += [
        "## This task",
        f"- Input mode: {code}.",
        f"- Target video duration: {_fmt_seconds(duration)} seconds. Every cut timestamp must be "
        "strictly increasing and fall inside this duration, and the timeline must fill it.",
        f"- Reference images: {_picture_rules(code, n_images, duration)}",
        "- Read the attached images yourself: derive the visual style, subject appearance, clothing, "
        "colors, key props, lighting, and spatial layout from what is actually visible, and keep them "
        "consistent with the description you write.",
        "- Write the rewrite in English. Keep dialogue, lyrics, and text visible in the scene in their "
        "original language, verbatim, inside the formats the guide specifies.",
        "",
        "## Output",
        _output_contract(code),
    ]

    if spec["images"] == 0:
        parts.append("Do not reference any picture label, since no image is attached.")

    extra = (extra_requirements or "").strip()
    if extra:
        parts += ["", "## Extra requirements from the user (these win over defaults, "
                  "but never over the guide's format rules)", extra]

    return "\n".join(parts)
