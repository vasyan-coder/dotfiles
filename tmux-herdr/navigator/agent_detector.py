"""Detect interactive coding agents attached to tmux panes, using public UI only.

The process table stays in memory; command lines and captured text are never
returned to the caller. No agent transcripts, credentials, or session files are
read. State rules are deliberately conservative and inspired by the public
Herdr Claude/Codex detection manifests (2026-10-11).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections import defaultdict
from typing import Callable, NamedTuple


class Process(NamedTuple):
    pid: int
    ppid: int
    comm: str
    args: str


_LABELS = {
    "blocked": "ждёт вас",
    "working": "работает",
    "idle": "готов",
    "unknown": "неизвестно",
}
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_SPINNER = re.compile(r"^[\u2800-\u28ff\u25d0-\u25d3] ")
_CLAUDE_ACTIVITY = re.compile(
    r"^\s*[*·✢✳✶✻✽]\s+\S.*(?:…|\.\.\.)(?:\s+\(|\s*$)"
)
_CLAUDE_BACKGROUND = re.compile(
    r"^\s*[*·✢✶✻✽]\s+Waiting for [1-9]\d* background agents? to finish\s*$",
    re.I,
)
_CODEX_ACTIVITY = re.compile(
    r"^(?:[•◦]\s+)?[^\s›•◦■✗✓─].* "
    r"\((?:[0-9]+[hm] )*[0-9]+s(?: • .+? to interrupt)?\)(?: · .*)?$"
)
_RESPONSE = re.compile(r"^\s*[•◦■✗✓]\s+")
_QUEUED_INPUT = re.compile(
    r"^\s*•\s+(?:Queued\s+follow-up\s+inputs|Messages\s+to\s+be\s+submitted\s+"
    r"(?:after\s+next\s+tool\s+call|at\s+end\s+of\s+turn))(?:\s|\(|$)",
    re.I,
)
_OPTION = re.compile(r"^\s*[❯›>]?\s*(?:\d+[.)]\s*)?(?:yes|no|accept|decline|allow|trust and continue)\b", re.I)
_PROMPT = re.compile(r"^\s*[❯›]\s*(?:$|[^\u2800-\u28ff])")
_INTERPRETERS = {"node", "nodejs", "bun", "python", "python3", "python3.11", "python3.12", "python3.13"}
_CODEX_NON_INTERACTIVE = {
    "app-server", "app-server-api", "exec", "e", "exec-server", "mcp-server",
    "mcp", "login", "logout", "completion", "debug", "sandbox", "apply",
    "cloud", "features", "review", "help", "update",
}
_CODEX_VALUE_FLAGS = {
    "--model", "-m", "--profile", "-p", "--config", "-c", "--cd", "-C",
    "--sandbox", "-s", "--ask-for-approval", "-a", "--image", "-i",
    "--add-dir", "--enable", "--disable", "--remote", "--session",
}
_CAPTURE_LINES = 32


def _parse_ps(output: str) -> list[Process]:
    processes = []
    for line in output.splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) < 3:
            continue
        try:
            processes.append(Process(int(fields[0]), int(fields[1]), fields[2], fields[3] if len(fields) > 3 else fields[2]))
        except ValueError:
            continue
    return processes


def _read_processes() -> list[Process]:
    try:
        result = subprocess.run(
            ["ps", "-ww", "-axo", "pid=,ppid=,comm=,args="], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return _parse_ps(result.stdout) if result.returncode == 0 else []


def _executable_agent(executable: str) -> str | None:
    name = os.path.basename(executable).lower()
    if name in {"claude", "claude-code"}:
        return "Claude"
    # Claude's native executable is a version number, rather than 'claude'.
    if re.search(r"(?:^|/)claude/versions/\d+\.\d+\.\d+(?:[-+][\w.-]+)?$", executable):
        return "Claude"
    if name == "codex" or re.fullmatch(r"codex-(?:aarch64|x86_64|arm64).+", name):
        return "Codex"
    if name == "gemini":
        return "Gemini"
    if name == "opencode":
        return "OpenCode"
    if name in {"aider", "aider-chat"}:
        return "Aider"
    return None


def _launch(process: Process) -> tuple[str, list[str]] | None:
    try:
        argv = shlex.split(process.args)
    except ValueError:
        argv = process.args.split()
    if not argv:
        argv = [process.comm]
    agent = _executable_agent(argv[0]) or _executable_agent(process.comm)
    if agent:
        return agent, argv[1:]
    # Recognize real JS entrypoints, never shell arguments merely naming an agent.
    interpreter = os.path.basename(argv[0]).lower()
    if interpreter not in _INTERPRETERS and not re.fullmatch(r"python3\.\d+", interpreter):
        return None
    for index, argument in enumerate(argv[1:4], 1):
        normalized = argument.replace("\\", "/")
        if re.search(r"(?:^|/)(?:@anthropic-ai/)?claude-code/(?:cli|bin/claude)\.(?:js|mjs|cjs)$", normalized):
            return "Claude", argv[index + 1:]
        if re.search(r"(?:^|/)(?:@openai/)?codex/bin/codex\.js$", normalized):
            return "Codex", argv[index + 1:]
        if re.search(r"(?:^|/)@google/gemini-cli/(?:dist/)?index\.js$", normalized):
            return "Gemini", argv[index + 1:]
        if argument == "-m" and index + 1 < len(argv) and argv[index + 1] == "aider":
            return "Aider", argv[index + 2:]
        if os.path.basename(argument).lower() in {"aider", "aider-chat"}:
            return "Aider", argv[index + 1:]
        if not argument.startswith("-"):
            break
    return None


def _first_positional(arguments: list[str], value_flags: set[str]) -> str | None:
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item == "--":
            return None  # Everything after '--' is an explicit prompt.
        if item in value_flags:
            index += 2
        elif item.startswith("-"):
            index += 1
        else:
            return item.lower()
    return None


def _interactive(agent: str, arguments: list[str]) -> bool:
    if any(item in {"--help", "-h", "--version", "-V"} for item in arguments):
        return False
    if agent == "Claude":
        headless = {"-p", "--print", "--output-format", "--input-format", "--sdk-url"}
        if any(item.split("=", 1)[0] in headless or (item.startswith("-p") and not item.startswith("--")) for item in arguments):
            return False
        return _first_positional(arguments, {"--model", "--permission-mode", "--resume", "-r", "--session-id", "--settings", "--add-dir", "--agent"}) not in {"auth", "doctor", "install", "mcp", "plugin", "setup-token", "update", "upgrade"}
    if agent == "Codex":
        return _first_positional(arguments, _CODEX_VALUE_FLAGS) not in _CODEX_NON_INTERACTIVE
    if agent == "Gemini":
        return not any(item.split("=", 1)[0] in {"-p", "--prompt", "--output-format"} for item in arguments)
    if agent == "OpenCode":
        return _first_positional(arguments, {"--model", "-m", "--agent", "--port", "--hostname"}) not in {"run", "serve", "web", "mcp", "auth", "upgrade", "export", "import", "stats"}
    if agent == "Aider":
        return not any(item.split("=", 1)[0] in {"-m", "--message", "--message-file", "--apply", "--apply-clipboard"} for item in arguments)
    return False


def _clean_lines(screen: str) -> list[str]:
    return [line.rstrip() for line in _ANSI.sub("", screen).replace("\r", "").splitlines() if line.strip()]


def _prompt(line: str) -> bool:
    return bool(_PROMPT.match(line)) and not _OPTION.match(line)


def _live_region(lines: list[str]) -> list[str]:
    """Discard prior turns above a visible current input marker when possible."""
    markers = [index for index, line in enumerate(lines) if _prompt(line)]
    return lines[markers[-1] + 1:] if markers else lines[-20:]


def _state(agent: str, screen: str, title: str = "") -> str:
    lines = _clean_lines(screen)
    tail = lines[-12:]
    tail_text = "\n".join(tail).lower()
    live = " ".join(_live_region(lines)).lower()
    recent = " ".join(lines[-20:]).lower()
    if agent == "Codex" and "action required" in title.lower():
        return "blocked"
    # Only current controls count: an old permission request above the current
    # input is history, even if it remains on the visible terminal screen.
    cancel = "esc to cancel" in live
    if cancel and re.search(r"enter\s+to\s+(?:confirm|select)", live):
        return "blocked"
    if any(hint in live for hint in ("press enter to confirm or esc to cancel", "enter to submit answer", "enter to submit all", "allow command?")):
        return "blocked"
    if cancel and ("do you want to proceed?" in live or "requests your input" in live):
        return "blocked"
    if ("folder access" in recent and "trust this folder?" in recent
            and ("trust and continue" in recent or "enter continue" in recent)
            and not any(_prompt(line) for line in lines[-4:])):
        return "blocked"
    if "do you trust the contents of this directory?" in recent and not any(_prompt(line) for line in lines[-4:]):
        return "blocked"
    if ("[y/n]" in live or "yes (y)" in live) and not any(_prompt(line) for line in lines[-3:]):
        return "blocked"

    # A permission dialog can appear before an application updates its OSC
    # title. Its current controls take precedence over a lingering spinner.
    if agent == "Claude" and _SPINNER.match(title):
        return "working"
    if agent == "Codex" and re.search(r"(?:^| )[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏](?: |$)", title):
        return "working"

    if "showing detailed transcript" in tail_text or ("q to quit" in tail_text and "pgup/pgdn" in tail_text):
        return "unknown"
    if agent == "Claude":
        for line in tail:
            if _CLAUDE_ACTIVITY.match(line) or _CLAUDE_BACKGROUND.match(line):
                return "working"
            if re.match(r"^\s*[⏸⏵].*esc to interrupt(?:\s|·|$)", line, re.I):
                return "working"
        for index, line in enumerate(tail):
            if re.match(r"^\s*⎿\s+Running(?:…|\.\.\.|\s|$)", line) and not any(re.match(r"^\s*(?:⏺|[✻✳✽])\s", newer) for newer in tail[index + 1:]):
                return "working"
        if title.startswith("✳ "):
            return "idle"
    if agent == "Codex":
        for index, line in enumerate(tail):
            if _CODEX_ACTIVITY.match(line) and "reconnect failed" not in line.lower():
                if not any(_RESPONSE.match(newer) and not _QUEUED_INPUT.match(newer) for newer in tail[index + 1:]):
                    return "working"
    if any(_prompt(line) for line in lines[-4:]):
        return "idle"
    return "unknown"


def detect_agents(panes: list[dict], tmux_call: Callable[[list[str]], str]) -> list[dict]:
    """Return one row per interactive agent kind in each pane.

    Rows retain the input pane metadata and add ``agent``, ``pid``, ``state``
    and ``status_label``. ``pane_title`` and ``pane_height`` are optional. When
    height is known, the bottom 32 visible rows are captured. If those rows are
    empty, the visible viewport is used, so a newly started UI near the top is
    still detected. Terminal scrollback is never read. Unknown state means that
    an agent process exists but its current UI has no dependable state marker.
    ``tmux_call`` must return command output as text and may raise on failure.
    """
    active_panes = []
    for pane in panes:
        if str(pane.get("pane_dead", "0")) in {"1", "True", "true"}:
            continue
        try:
            root_pid = int(pane["pane_pid"])
        except (KeyError, ValueError, TypeError):
            continue
        if root_pid > 0:
            active_panes.append((pane, root_pid))
    if not active_panes:
        return []
    processes = _read_processes()
    by_pid = {process.pid: process for process in processes}
    children: dict[int, list[int]] = defaultdict(list)
    for process in processes:
        children[process.ppid].append(process.pid)
    rows = []
    for pane, root_pid in active_panes:
        pending = [(root_pid, 0)]
        seen: set[int] = set()
        candidates: dict[str, tuple[int, int]] = {}
        while pending:
            pid, depth = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            process = by_pid.get(pid)
            if process is not None:
                launch = _launch(process)
                if launch and _interactive(*launch):
                    agent, _ = launch
                    # npm wrappers and the native child represent one agent.
                    if agent not in candidates or depth > candidates[agent][1]:
                        candidates[agent] = (pid, depth)
            pending.extend((child, depth + 1) for child in children.get(pid, []))
        if not candidates:
            continue
        try:
            args = ["capture-pane", "-p", "-t", str(pane["pane_id"])]
            try:
                height = int(pane.get("pane_height", 0))
            except (ValueError, TypeError):
                height = 0
            if height > 0:
                args += ["-S", str(max(0, height - _CAPTURE_LINES)), "-E", str(height - 1)]
            screen = tmux_call(args)
            if height > _CAPTURE_LINES and not screen.strip():
                screen = tmux_call(["capture-pane", "-p", "-t", str(pane["pane_id"])])
        except Exception:
            screen = ""
        for agent, (pid, _depth) in sorted(candidates.items()):
            state = _state(agent, screen, str(pane.get("pane_title", "")))
            rows.append(dict(pane, agent=agent, pid=pid, state=state, status_label=_LABELS[state]))
    return rows
