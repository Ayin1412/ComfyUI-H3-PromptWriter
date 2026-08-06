"""ComfyUI-H3-PromptWriter — 调 API 按 MiniMax H3 官方规范写视频提示词的节点。"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 注册 HTTP 接口。即使注册失败（例如单测环境里没有 server 模块），节点本身也要能正常加载。
try:
    from . import server_routes  # noqa: F401
except Exception as e:  # pragma: no cover
    print(f"[H3PromptWriter] 提示词库 / API 设置接口注册失败，面板将不可用: {e}")

# 前端扩展：按模式自动增删图片输入 + 结果回填 + 保存/提示词库/API 设置按钮。
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
