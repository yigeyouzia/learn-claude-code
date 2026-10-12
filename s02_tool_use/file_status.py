#!/usr/bin/env python3
"""
s02_tool_use.py - Tools

The agent loop from s01 does not change. This lesson adds four tools
and a dispatch map:

    +----------+      +-------+      +--------------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch            |
    |  prompt  |      |       |      | bash       -> run_bash   |
    +----------+      +---+---+      | read_file  -> run_read   |
                          ^          | write_file -> run_write  |
                          |          | edit_file  -> run_edit   |
                          +----------+ glob       -> run_glob   |
                          tool_result+--------------------------+

  + run_read / run_write / run_edit / run_glob
  + TOOL_HANDLERS instead of a hard-coded run_bash call
  + safe_path to keep file tools inside the workspace

Key insight: the loop stays the same; only tool registration and dispatch grow.
"""

import os
import subprocess
from pathlib import Path

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

ENVIRONMENT_PROMPT = (
    "Windows: the bash tool runs through cmd.exe; use cmd.exe syntax, not Unix "
    "Bash or PowerShell syntax, and prefer dedicated file tools for file operations"
    if os.name == "nt"
    else "Unix-like: the bash tool runs the system shell"
)

SYSTEM = (
    f"You are a coding agent at {WORKDIR}. Environment: {ENVIRONMENT_PROMPT}. "
    "Use tools to solve tasks. Act, don't explain."
)


# -- From s01 (unchanged) --

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, errors="replace",
                           timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


# -- New in s02: four tools --

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str) -> str:  # 接收路径通配模式，如 **/*.py；返回路径列表组成的字符串
    import glob as g  # 导入标准库 glob，起别名 g；后面用 g.glob(...) 查找匹配路径
    try:  # 尝试查找与整理结果；本段抛出的普通异常会交给下面的 except
        matches = sorted({  # {} 是集合推导式，先去重；sorted 按字符串顺序排序并返回列表
            match for match in g.glob(  # 遍历 glob 返回的路径字符串，把满足后面 if 条件的 match 留下
                pattern, root_dir=WORKDIR, recursive=True)  # 相对模式从工作目录查找；允许 ** 跨多层目录匹配
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR)  # / 拼接路径；resolve 解析 .. 和符号链接；只保留解析后位于工作区内的结果
        })  # 结束集合推导式和排序调用；matches 是已过滤、去重并排序的路径列表
        shown = matches[:200]  # 切片复制前 200 条到新列表；限制展示数量，不限制 glob 的搜索量
        if len(matches) > 200:  # 如果完整结果超过 200 条，需要说明展示内容被截断
            shown.append("... (more matches omitted; narrow the pattern)")  # 在展示列表末尾加提示，建议缩小匹配范围
        return "\n".join(shown) if shown else "(no matches)"  # 列表非空时用换行拼接路径；空列表返回无匹配提示
    except Exception as e:  # 捕获 try 中传播出来的普通异常，用变量 e 取得异常信息
        return f"Error: {e}"  # 把异常转为字符串工具结果，交回 Agent；不在这里重新抛出

import json


def run_file_stats(path: str) -> str:
    """统计 UTF-8 文本文件的行数、字符数和原始字节数。"""
    try:
        if not isinstance(path, str):  # 类型提示不会自动检查参数
            return "Error: path must be a string"

        file_path = safe_path(path)  # 复用工作区路径检查
        raw = file_path.read_bytes()  # 一次读取，得到 bytes
        text = raw.decode("utf-8")  # 解码为文本，保留原始换行

        stats = {
            "path": path,
            "lines": len(text.splitlines()),  # 空文件为 0 行
            "characters": len(text),  # 包括空格和换行字符
            "bytes": len(raw),  # 实际读取的字节数
        }

        return json.dumps(stats, ensure_ascii=False)  # 返回 JSON 字符串

    except Exception as e:
        # 文件不存在、路径越界、读取或解码失败等
        return f"Error: {e}"

# -- New in s02: tool definitions (one tool in s01, five in s02) --

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern; ** matches recursively.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    # file status
    {
        "name": "file_stats",
        "description": (
            "统计工作区内 UTF-8 文本文件的行数、字符数和字节数。"
            "需要文件统计信息时使用此工具。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对于工作目录的文件路径",
                },
            },
            "required": ["path"],
        },
    }
]

# -- New in s02: dispatch map (replaces s01's hard-coded run_bash call) --

TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob, "file_stats": run_file_stats,
}


# -- The agent loop keeps the same shape as s01; only dispatch changes --
# s01: output = run_bash(block.input["command"])
# s02: output = TOOL_HANDLERS[block.name](**block.input)

def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]
        if not tool_calls:
            return

        results = []
        for block in tool_calls:
            print(f"\033[33m> {block.name}\033[0m")
            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"Unknown: {block.name}"
            print(str(output)[:200])
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s02: Tool Use - four tools added to s01")
    print("Enter a question, press Enter to send. Type q to quit.\n")

    history = []
    while True:
        try:
            # \001/\002 tell Readline the ANSI escapes have zero display width.
            query = input("\001\033[36m\002s02 >> \001\033[0m\002")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
