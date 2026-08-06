"""写好的 H3 提示词的持久化存储。

放在 ComfyUI 的 user 目录下，更新 / 重装本节点不会丢：
    <ComfyUI>/user/default/h3_prompt_writer/prompts.json

每条记录：
    {"id": str, "name": str, "text": str, "mode": str, "query": str, "model": str,
     "tags": str, "created": float, "updated": float}
"""

import json
import os
import re
import threading
import time
import uuid

try:
    import folder_paths
except ImportError:  # pragma: no cover
    folder_paths = None

_REL_PATH = os.path.join("default", "h3_prompt_writer", "prompts.json")

# 读改写不是原子的，多个请求同时进来会互相覆盖，用一把锁串起来。
_lock = threading.RLock()

_FIELDS = ("mode", "query", "model", "tags")


def library_path():
    if folder_paths is not None:
        try:
            return os.path.join(folder_paths.get_user_directory(), _REL_PATH)
        except Exception:
            pass
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.json")


def auto_name(text):
    """没起名字时，用正文里第一行有内容的前 28 个字符凑一个。"""
    for line in (text or "").splitlines():
        line = line.strip()
        # 跳过 "integrated_multimodal_description:" 这种纯字段名开头
        if line and not line.endswith(":"):
            return line[:28] + ("…" if len(line) > 28 else "")
    return time.strftime("H3 提示词 %Y-%m-%d %H:%M:%S")


def _normalize(item):
    if not isinstance(item, dict):
        return None
    text = item.get("text")
    if not isinstance(text, str):
        return None
    now = time.time()
    out = {
        "id": str(item.get("id") or uuid.uuid4().hex),
        "name": str(item.get("name") or "").strip() or auto_name(text),
        "text": text,
        "created": float(item.get("created") or now),
        "updated": float(item.get("updated") or item.get("created") or now),
    }
    for field in _FIELDS:
        out[field] = str(item.get(field) or "")
    return out


def load_all():
    """全部记录，按更新时间倒序。"""
    path = library_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    items = [n for n in (_normalize(i) for i in data) if n]
    items.sort(key=lambda i: i["updated"], reverse=True)
    return items


def _write_all(items):
    path = library_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def add(text, name="", **meta):
    """新增一条；正文完全相同的记录只更新时间戳和元信息，不重复写入。"""
    if not isinstance(text, str) or not text.strip():
        return None
    meta = {k: str(meta.get(k) or "") for k in _FIELDS}
    with _lock:
        items = load_all()
        for item in items:
            if item["text"] == text:
                item["updated"] = time.time()
                if str(name or "").strip():
                    item["name"] = name.strip()
                for key, value in meta.items():
                    if value:
                        item[key] = value
                _write_all(items)
                return item
        now = time.time()
        item = {
            "id": uuid.uuid4().hex,
            "name": str(name or "").strip() or auto_name(text),
            "text": text,
            "created": now,
            "updated": now,
            **meta,
        }
        items.insert(0, item)
        _write_all(items)
        return item


def update(item_id, name=None, text=None, tags=None):
    with _lock:
        items = load_all()
        for item in items:
            if item["id"] == item_id:
                if name is not None:
                    item["name"] = str(name).strip() or item["name"]
                if text is not None:
                    item["text"] = str(text)
                if tags is not None:
                    item["tags"] = str(tags).strip()
                item["updated"] = time.time()
                _write_all(items)
                return item
        return None


def delete(item_id):
    with _lock:
        items = load_all()
        kept = [i for i in items if i["id"] != item_id]
        if len(kept) == len(items):
            return False
        _write_all(kept)
        return True


def export_txt(text, name="", mode="", query=""):
    """入库的同时在 output/h3_prompts/ 下另存一份 txt，返回路径；失败返回空串。"""
    if folder_paths is None:
        return ""
    try:
        out_dir = os.path.join(folder_paths.get_output_directory(), "h3_prompts")
        os.makedirs(out_dir, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(name or "")).strip(" .") or "h3_prompt"
        path = os.path.join(out_dir, f"{time.strftime('%Y%m%d-%H%M%S')}_{safe[:40]}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# mode: {mode}\n# query: {(query or '').strip()}\n\n{text}\n")
        return path
    except OSError as e:
        print(f"[H3PromptWriter] 导出 txt 失败：{e}")
        return ""
