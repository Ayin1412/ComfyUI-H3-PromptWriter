"""五种 H3 生成模式的定义。前端（web/h3_prompt_writer.js）里有一份同样的表，改这里记得同步改那边。"""

# 下拉里显示的完整文案；前面的英文代号是真正的模式标识（用空格切一下就能拿到）。
MODE_LABELS = [
    "T2VA 纯文本",
    "I2VA 首帧",
    "FL2VA 首尾帧",
    "L2VA 尾帧",
    "Ref2VA 多图参考",
]

# images: 该模式需要的图片张数；None 表示不限张数（Ref2VA）。
MODE_SPEC = {
    "T2VA": {"images": 0, "slots": []},
    "I2VA": {"images": 1, "slots": ["首帧 <Picture 1>"]},
    "FL2VA": {"images": 2, "slots": ["首帧 <Picture 1>", "尾帧 <Picture 2>"]},
    "L2VA": {"images": 1, "slots": ["尾帧 <Picture 1>"]},
    "Ref2VA": {"images": None, "slots": None},
}


def mode_code(label):
    """把下拉里的 "FL2VA 首尾帧" 还原成 "FL2VA"。"""
    code = str(label or "").strip().split()[0] if str(label or "").strip() else ""
    return code if code in MODE_SPEC else "T2VA"
