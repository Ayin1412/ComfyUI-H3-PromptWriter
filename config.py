"""所有 API / 生成参数的读写。

节点上不再放这些参数，全部收在「🔑 API 设置」面板里，存到：
    <ComfyUI>/user/default/h3_prompt_writer/config.json

优先级：配置文件 > 环境变量 > 内置默认值。
"""

import json
import os
import threading

try:
    import folder_paths
except ImportError:  # pragma: no cover - 脱离 ComfyUI 单跑时
    folder_paths = None

_REL_PATH = os.path.join("default", "h3_prompt_writer", "config.json")
_lock = threading.RLock()

# 键 -> (默认值, 类型, 最小值, 最大值)；类型为 str 时后两个忽略
_SCHEMA = {
    "base_url": ("https://api.openai.com/v1", str, None, None),
    "api_key": ("", str, None, None),
    "model": ("gpt-4o", str, None, None),
    "temperature": (0.7, float, 0.0, 2.0),
    "max_tokens": (4096, int, 256, 32768),
    "timeout": (120, int, 10, 900),
    "retries": (2, int, 0, 5),
    "max_image_side": (1024, int, 256, 2048),
    "image_detail": ("auto", str, None, None),
    "extra_requirements": ("", str, None, None),
}

DEFAULTS = {k: v[0] for k, v in _SCHEMA.items()}

# 环境变量兜底，按顺序取第一个非空的
_ENV = {
    "base_url": ("H3_PROMPT_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE"),
    "api_key": ("H3_PROMPT_API_KEY", "OPENAI_API_KEY"),
    "model": ("H3_PROMPT_MODEL",),
}

IMAGE_DETAILS = ("auto", "low", "high")


def config_path():
    if folder_paths is not None:
        try:
            return os.path.join(folder_paths.get_user_directory(), _REL_PATH)
        except Exception:
            pass
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load():
    """配置文件的原始内容，读不到就是空字典。"""
    path = config_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce(key, value):
    """把任意来源的值转成该键要求的类型，转不动就返回 None（当作没填）。"""
    default, typ, lo, hi = _SCHEMA[key]
    if value is None:
        return None
    if typ is str:
        value = str(value).strip()
        if key == "image_detail" and value not in IMAGE_DETAILS:
            return None
        return value or None
    try:
        value = typ(value)
    except (TypeError, ValueError):
        return None
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _from_env(key):
    for name in _ENV.get(key, ()):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def settings():
    """最终生效的全部参数。"""
    raw = load()
    out = {}
    for key in _SCHEMA:
        value = _coerce(key, raw.get(key))
        if value is None:
            value = _coerce(key, _from_env(key))
        out[key] = DEFAULTS[key] if value is None else value
    return out


def save(patch):
    """局部更新，只认 _SCHEMA 里的键；值为 None 的键保持不动。"""
    if not isinstance(patch, dict):
        return settings()
    with _lock:
        data = load()
        for key, value in patch.items():
            if key not in _SCHEMA or value is None:
                continue
            # 字符串允许显式清空（传空串 = 恢复默认 / 清掉 key）
            coerced = _coerce(key, value)
            data[key] = "" if coerced is None and _SCHEMA[key][1] is str else coerced
            if coerced is None and _SCHEMA[key][1] is not str:
                data.pop(key, None)
        path = config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    return settings()


def public():
    """给设置面板的配置。

    api_key 是原文——面板上有个睁闭眼按钮控制显示，所以前端需要拿到真值。
    这条接口只在 ComfyUI 自己的本地服务上，能访问它的人本来也能读到配置文件。
    """
    data = settings()
    key = str(data.get("api_key") or "")
    data["has_key"] = bool(key)
    data["from_env"] = bool(_from_env("api_key")) and not load().get("api_key")
    data["path"] = config_path()
    return data
