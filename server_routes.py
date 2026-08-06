"""提示词库和 API 设置的 HTTP 接口，注册在 ComfyUI 自带的 PromptServer 上。

前端（web/h3_prompt_writer.js）通过这些接口读写 user/default/h3_prompt_writer/ 下的两个 json。
"""

import asyncio
import time

from aiohttp import web
from server import PromptServer

from . import config, library, openai_client

routes = PromptServer.instance.routes


async def _json_body(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@routes.get("/h3_prompt/prompts")
async def list_prompts(request):
    return web.json_response({"items": library.load_all()})


@routes.post("/h3_prompt/save")
async def save_prompt(request):
    data = await _json_body(request)
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return web.json_response({"error": "内容不能为空"}, status=400)
    item = library.add(
        text,
        name=str(data.get("name") or ""),
        tags=str(data.get("tags") or ""),
        mode=str(data.get("mode") or ""),
        query=str(data.get("query") or ""),
        model=config.settings()["model"],
    )
    # 顺手在 output/h3_prompts/ 下留一份 txt，方便直接拿去用
    path = library.export_txt(text, item["name"], item.get("mode", ""), item.get("query", ""))
    return web.json_response({"item": item, "path": path})


@routes.post("/h3_prompt/update")
async def update_prompt(request):
    data = await _json_body(request)
    item_id = data.get("id")
    if not item_id:
        return web.json_response({"error": "缺少 id"}, status=400)
    item = library.update(item_id, name=data.get("name"), text=data.get("text"),
                          tags=data.get("tags"))
    if item is None:
        return web.json_response({"error": "记录不存在"}, status=404)
    return web.json_response({"item": item})


@routes.post("/h3_prompt/delete")
async def delete_prompt(request):
    data = await _json_body(request)
    if not library.delete(data.get("id")):
        return web.json_response({"error": "记录不存在"}, status=404)
    return web.json_response({"ok": True})


@routes.get("/h3_prompt/config")
async def get_config(request):
    return web.json_response(config.public())


@routes.post("/h3_prompt/config")
async def set_config(request):
    # 不传的键保持原值；api_key 传空串 = 清空
    config.save(await _json_body(request))
    return web.json_response(config.public())


def _conn(data):
    """面板上还没保存的值优先，缺了就退回已保存的配置。"""
    saved = config.settings()
    return (
        str(data.get("base_url") or "").strip() or saved["base_url"],
        str(data.get("api_key") or "").strip() or saved["api_key"],
        str(data.get("model") or "").strip() or saved["model"],
        int(data.get("timeout") or saved["timeout"]),
    )


@routes.post("/h3_prompt/models")
async def fetch_models(request):
    """拉一遍接口的可用模型列表，给面板上的「获取模型」按钮用。"""
    base_url, api_key, _, timeout = _conn(await _json_body(request))
    try:
        items = await asyncio.to_thread(
            openai_client.list_models, base_url, api_key, min(timeout, 60))
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"items": items, "url": openai_client.models_url(base_url)})


@routes.post("/h3_prompt/test")
async def test_connection(request):
    """发一句最短的对话，确认地址 / key / 模型这条链路是通的。"""
    base_url, api_key, model, timeout = _conn(await _json_body(request))
    if not api_key:
        return web.json_response({"error": "还没填 API Key"}, status=400)
    if not model:
        return web.json_response({"error": "还没填模型名"}, status=400)

    started = time.perf_counter()
    try:
        reply, _ = await asyncio.to_thread(
            openai_client.complete,
            base_url, api_key, model,
            [{"role": "user", "content": "Reply with exactly: OK"}],
            0.0, 16, min(timeout, 60), 0,
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({
        "ok": True,
        "model": model,
        "ms": int((time.perf_counter() - started) * 1000),
        "reply": reply.strip()[:80],
    })
