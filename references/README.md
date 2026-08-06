# 第三方内容 / Third-party content

本目录下的三个文件**不是本项目的作品**，原样取自 MiniMax 官方仓库，未作任何改动：

| 文件 | 来源 |
| --- | --- |
| `SKILL.md` | [MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3) · `skills/h3-prompt-writing/SKILL.md` |
| `base-en.txt` | 同上 · `skills/h3-prompt-writing/references/base-en.txt` |
| `ref-en.txt` | 同上 · `skills/h3-prompt-writing/references/ref-en.txt` |

版权归 MiniMax 所有。收录在这里是为了让节点离线可用——它们是发给模型的 system prompt 的主体。
上游仓库在收录时未提供 LICENSE 文件，因此这些文件**不适用本项目根目录的 MIT 协议**；
如果 MiniMax 方面希望移除，提个 issue 即可，我会改成运行时下载。

请以上游仓库的最新版本为准，本目录的副本可能滞后。

---

The three files in this directory are **not part of this project**. They are copied verbatim,
without modification, from [MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3)
(`skills/h3-prompt-writing/`). Copyright belongs to MiniMax. They are vendored so the node works
offline, since they form the bulk of the system prompt sent to the model. The upstream repository
carried no LICENSE file at the time of copying, so these files are **not covered by this project's
MIT license**. If MiniMax would like them removed, please open an issue and they will be replaced
with a runtime download. Refer to the upstream repository for the authoritative, up-to-date version.
