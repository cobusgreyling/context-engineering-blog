"""
Context Engineering Demo — Adaptive Context Compaction Pipeline
Based on the OpenDev Technical Report (arXiv:2603.05344)

Simulates a multi-turn coding agent session demonstrating:
- 5-stage adaptive context compaction (70% → 80% → 85% → 90% → 99%)
- Tool result optimisation (30,000 tokens → ~100 tokens)
- System reminders to combat instruction fade-out
- Doom-loop detection via fingerprinting
- Dual-memory architecture for bounded thinking

No API key needed — uses simulated LLM responses to demonstrate
the context management mechanics.

Requirements:
    pip install gradio
"""

import hashlib
import json
import random
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Core Data Structures
# ---------------------------------------------------------------------------


class CompactionStage(Enum):
    NOMINAL = "Nominal"
    WARNING = "Stage 1: Warning (70%)"
    OBSERVATION_MASKING = "Stage 2: Observation Masking (80%)"
    FAST_PRUNING = "Stage 2.5: Fast Pruning (85%)"
    AGGRESSIVE_MASKING = "Stage 3: Aggressive Masking (90%)"
    FULL_COMPACTION = "Stage 4: Full Compaction (99%)"


@dataclass
class ToolResult:
    """A single tool execution result in the conversation."""
    tool_name: str
    arguments: dict
    raw_output: str
    raw_tokens: int
    summary: str
    summary_tokens: int
    turn: int
    is_masked: bool = False
    is_pruned: bool = False


@dataclass
class SystemReminder:
    """An injected system reminder."""
    trigger: str
    message: str
    turn: int


@dataclass
class ConversationMessage:
    """A message in the conversation history."""
    role: str  # user, assistant, tool_result, system_reminder
    content: str
    tokens: int
    turn: int
    is_compacted: bool = False


@dataclass
class ContextState:
    """The full state of the context window at any point."""
    max_tokens: int = 128_000
    messages: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    reminders: list = field(default_factory=list)
    compaction_log: list = field(default_factory=list)
    doom_loop_fingerprints: deque = field(default_factory=lambda: deque(maxlen=20))
    nudge_counts: dict = field(default_factory=lambda: {
        "error_recovery": 0,
        "incomplete_todo": 0,
        "exploration_spiral": 0,
    })
    current_turn: int = 0

    @property
    def used_tokens(self) -> int:
        return sum(m.tokens for m in self.messages if not m.is_compacted)

    @property
    def pressure(self) -> float:
        return self.used_tokens / self.max_tokens

    @property
    def stage(self) -> CompactionStage:
        p = self.pressure
        if p >= 0.99:
            return CompactionStage.FULL_COMPACTION
        elif p >= 0.90:
            return CompactionStage.AGGRESSIVE_MASKING
        elif p >= 0.85:
            return CompactionStage.FAST_PRUNING
        elif p >= 0.80:
            return CompactionStage.OBSERVATION_MASKING
        elif p >= 0.70:
            return CompactionStage.WARNING
        return CompactionStage.NOMINAL


# ---------------------------------------------------------------------------
# Simulated Tool Outputs — Realistic coding agent operations
# ---------------------------------------------------------------------------

SIMULATED_TOOLS = {
    "read_file": {
        "files": {
            "src/auth/middleware.ts": {
                "output": lambda: "export class AuthMiddleware {\n" + "\n".join(
                    f"  // Line {i}: Authentication logic for request validation"
                    for i in range(1, 151)
                ) + "\n}\n",
                "lines": 152,
                "chars": 7_840,
            },
            "src/api/routes.ts": {
                "output": lambda: "import { Router } from 'express';\n" + "\n".join(
                    f"  router.get('/api/v1/endpoint{i}', handler{i});"
                    for i in range(1, 201)
                ) + "\nexport default router;\n",
                "lines": 203,
                "chars": 11_200,
            },
            "src/db/schema.prisma": {
                "output": lambda: "\n".join(
                    f"model Table{i} {{\n  id Int @id\n  name String\n  createdAt DateTime\n}}"
                    for i in range(1, 31)
                ),
                "lines": 120,
                "chars": 4_560,
            },
            "tests/auth.test.ts": {
                "output": lambda: "\n".join(
                    f"test('auth case {i}', () => {{ expect(validate(input{i})).toBe(true); }});"
                    for i in range(1, 81)
                ),
                "lines": 80,
                "chars": 5_120,
            },
            "package.json": {
                "output": lambda: json.dumps({
                    "name": "my-app", "version": "2.1.0",
                    "dependencies": {f"pkg-{i}": f"^{i}.0.0" for i in range(1, 25)},
                    "devDependencies": {f"dev-pkg-{i}": f"^{i}.0.0" for i in range(1, 15)},
                }, indent=2),
                "lines": 45,
                "chars": 1_890,
            },
        },
    },
    "text_search": {
        "patterns": {
            "authenticate": {"matches": 23, "files": 8},
            "TODO": {"matches": 47, "files": 15},
            "deprecated": {"matches": 12, "files": 6},
            "error": {"matches": 89, "files": 22},
            "import.*middleware": {"matches": 31, "files": 11},
        },
    },
    "list_files": {
        "directories": {
            "src/": {"items": 47, "dirs": 8, "files": 39},
            "tests/": {"items": 23, "dirs": 3, "files": 20},
            "node_modules/": {"items": 1_247, "dirs": 312, "files": 935},
        },
    },
    "run_command": {
        "commands": {
            "npm test": {
                "output": lambda: "TAP version 14\n" + "\n".join(
                    f"{'ok' if random.random() > 0.1 else 'not ok'} {i} - test case {i}"
                    for i in range(1, 101)
                ) + f"\n\n# tests {100}\n# pass {random.randint(88, 98)}\n# fail {random.randint(2, 12)}",
                "chars": 4_800,
            },
            "npm run build": {
                "output": lambda: "\n".join(
                    f"[{i}/47] Compiling src/module{i}.ts..."
                    for i in range(1, 48)
                ) + "\n\nBuild completed in 12.4s\nOutput: dist/",
                "chars": 2_100,
            },
            "git diff": {
                "output": lambda: "\n".join(
                    f"diff --git a/src/file{i}.ts b/src/file{i}.ts\n"
                    f"--- a/src/file{i}.ts\n+++ b/src/file{i}.ts\n"
                    f"@@ -10,3 +10,5 @@\n-  old line {i}\n+  new line {i}\n+  added line {i}"
                    for i in range(1, 16)
                ),
                "chars": 3_200,
            },
        },
    },
}


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Tool Result Optimisation — Per-tool-type summarisation
# ---------------------------------------------------------------------------


def summarise_tool_result(tool_name: str, args: dict, raw_output: str) -> str:
    """Compress raw tool output to a compact summary."""
    if tool_name == "read_file":
        file_path = args.get("path", "unknown")
        lines = raw_output.count("\n") + 1
        chars = len(raw_output)
        return f"Read file '{file_path}' ({lines} lines, {chars:,} chars)"

    elif tool_name == "text_search":
        pattern = args.get("pattern", "")
        matches = raw_output.count("\n") + 1
        return f"Search '{pattern}' completed ({matches} matches found)"

    elif tool_name == "list_files":
        directory = args.get("path", "")
        items = raw_output.count("\n") + 1
        return f"Listed directory '{directory}' ({items} items)"

    elif tool_name == "run_command":
        cmd = args.get("command", "")
        chars = len(raw_output)
        if "test" in cmd.lower():
            pass_count = raw_output.count("ok ") - raw_output.count("not ok")
            fail_count = raw_output.count("not ok")
            return f"Ran '{cmd}': {pass_count} passed, {fail_count} failed ({chars:,} chars output)"
        return f"Ran '{cmd}' ({chars:,} chars output)"

    elif tool_name == "edit_file":
        file_path = args.get("path", "unknown")
        return f"Edited '{file_path}' successfully"

    return f"Tool '{tool_name}' completed ({len(raw_output):,} chars)"


# ---------------------------------------------------------------------------
# Compaction Engine — 5-stage adaptive pipeline
# ---------------------------------------------------------------------------


def apply_compaction(state: ContextState) -> list[str]:
    """Apply appropriate compaction stage based on context pressure.
    Returns a list of actions taken."""
    actions = []
    stage = state.stage

    if stage == CompactionStage.NOMINAL:
        return actions

    if stage.value.startswith("Stage 1"):
        actions.append(f"[WARNING] Context pressure at {state.pressure:.0%} — monitoring trends")
        state.compaction_log.append({
            "turn": state.current_turn,
            "stage": stage.value,
            "pressure": f"{state.pressure:.1%}",
            "action": "warning_logged",
        })

    if stage in (CompactionStage.OBSERVATION_MASKING, CompactionStage.FAST_PRUNING,
                 CompactionStage.AGGRESSIVE_MASKING, CompactionStage.FULL_COMPACTION):
        # Determine recency window based on stage
        if stage == CompactionStage.OBSERVATION_MASKING:
            protect_recent = 5
        elif stage == CompactionStage.FAST_PRUNING:
            protect_recent = 3
        elif stage == CompactionStage.AGGRESSIVE_MASKING:
            protect_recent = 1
        else:
            protect_recent = 1

        # Mask/prune old tool results
        tool_messages = [m for m in state.messages if m.role == "tool_result" and not m.is_compacted]
        if tool_messages:
            to_compact = tool_messages[:-protect_recent] if protect_recent < len(tool_messages) else []
            tokens_recovered = 0
            for msg in to_compact:
                old_tokens = msg.tokens
                if stage in (CompactionStage.FAST_PRUNING, CompactionStage.FULL_COMPACTION):
                    msg.content = "[pruned]"
                    msg.tokens = 2
                else:
                    msg.content = "[output offloaded — use read_file to recover details]"
                    msg.tokens = 15
                msg.is_compacted = True
                tokens_recovered += old_tokens - msg.tokens

            if tokens_recovered > 0:
                action_type = "pruned" if "Pruning" in stage.value else "masked"
                actions.append(
                    f"[{stage.value.upper()}] {action_type.title()} {len(to_compact)} old tool outputs, "
                    f"recovered ~{tokens_recovered:,} tokens "
                    f"(protected {protect_recent} most recent)"
                )
                state.compaction_log.append({
                    "turn": state.current_turn,
                    "stage": stage.value,
                    "pressure": f"{state.pressure:.1%}",
                    "action": action_type,
                    "items_compacted": len(to_compact),
                    "tokens_recovered": tokens_recovered,
                })

    if stage == CompactionStage.FULL_COMPACTION:
        # Simulate LLM-based summarisation of middle conversation
        middle_messages = [m for m in state.messages if not m.is_compacted and m.role != "tool_result"]
        if len(middle_messages) > 4:
            to_summarise = middle_messages[1:-2]  # Keep first and last 2
            total_tokens = sum(m.tokens for m in to_summarise)
            summary_tokens = max(200, total_tokens // 8)

            for msg in to_summarise:
                msg.is_compacted = True

            summary = ConversationMessage(
                role="assistant",
                content=f"[COMPACTION SUMMARY] Conversation summarised from {len(to_summarise)} messages. "
                        f"Key context preserved: files read, edits made, test results, and current objectives. "
                        f"Full history archived to scratch file.",
                tokens=summary_tokens,
                turn=state.current_turn,
            )
            state.messages.append(summary)

            recovered = total_tokens - summary_tokens
            actions.append(
                f"[FULL COMPACTION] LLM-summarised {len(to_summarise)} messages, "
                f"recovered ~{recovered:,} tokens. History archived."
            )
            state.compaction_log.append({
                "turn": state.current_turn,
                "stage": stage.value,
                "pressure": f"{state.pressure:.1%}",
                "action": "full_compaction",
                "messages_summarised": len(to_summarise),
                "tokens_recovered": recovered,
            })

    return actions


# ---------------------------------------------------------------------------
# System Reminders — Event-driven injection
# ---------------------------------------------------------------------------

REMINDER_TEMPLATES = {
    "error_recovery": (
        "[SYSTEM] The last tool call failed with: {error}. "
        "The file may have changed since you last read it. "
        "Re-read the file and retry your edit with the current content."
    ),
    "incomplete_todo": (
        "[SYSTEM] You have {count} incomplete task(s) remaining: {items}. "
        "Please address these before signalling completion."
    ),
    "exploration_spiral": (
        "[SYSTEM] You have read {count} files consecutively without making any edits. "
        "Consider whether you have enough information to proceed with changes."
    ),
    "doom_loop": (
        "[SYSTEM WARNING] You have called {tool_name} with the same arguments {repeat_count} times. "
        "Try a different approach."
    ),
    "instruction_fadeout": (
        "[SYSTEM] Reminder: Always run tests after editing code. "
        "You have made {edit_count} edits since the last test run."
    ),
}

MAX_NUDGES = {"error_recovery": 3, "incomplete_todo": 2, "exploration_spiral": 2}


def check_and_inject_reminders(state: ContextState, event: dict) -> list[str]:
    """Check conditions and inject reminders. Returns list of injected reminders."""
    injected = []

    # Doom loop detection
    if event.get("tool_call"):
        fp = hashlib.md5(
            json.dumps({"name": event["tool_call"]["name"], "args": event["tool_call"]["args"]},
                       sort_keys=True).encode()
        ).hexdigest()[:12]
        state.doom_loop_fingerprints.append(fp)

        counts = Counter(state.doom_loop_fingerprints)
        max_repeat = max(counts.values()) if counts else 0
        if max_repeat >= 3:
            msg = REMINDER_TEMPLATES["doom_loop"].format(
                tool_name=event["tool_call"]["name"],
                repeat_count=max_repeat,
            )
            state.reminders.append(SystemReminder("doom_loop", msg, state.current_turn))
            state.messages.append(ConversationMessage("system_reminder", msg, estimate_tokens(msg), state.current_turn))
            injected.append(msg)

    # Error recovery
    if event.get("error") and state.nudge_counts["error_recovery"] < MAX_NUDGES["error_recovery"]:
        msg = REMINDER_TEMPLATES["error_recovery"].format(error=event["error"])
        state.reminders.append(SystemReminder("error_recovery", msg, state.current_turn))
        state.messages.append(ConversationMessage("system_reminder", msg, estimate_tokens(msg), state.current_turn))
        state.nudge_counts["error_recovery"] += 1
        injected.append(msg)

    # Exploration spiral
    recent_tools = [tr.tool_name for tr in state.tool_results[-6:]]
    read_count = sum(1 for t in recent_tools if t in ("read_file", "text_search", "list_files"))
    if read_count >= 5 and state.nudge_counts["exploration_spiral"] < MAX_NUDGES["exploration_spiral"]:
        msg = REMINDER_TEMPLATES["exploration_spiral"].format(count=read_count)
        state.reminders.append(SystemReminder("exploration_spiral", msg, state.current_turn))
        state.messages.append(ConversationMessage("system_reminder", msg, estimate_tokens(msg), state.current_turn))
        state.nudge_counts["exploration_spiral"] += 1
        injected.append(msg)

    # Instruction fade-out (edits without tests)
    if event.get("edits_since_test", 0) >= 3:
        msg = REMINDER_TEMPLATES["instruction_fadeout"].format(edit_count=event["edits_since_test"])
        state.reminders.append(SystemReminder("instruction_fadeout", msg, state.current_turn))
        state.messages.append(ConversationMessage("system_reminder", msg, estimate_tokens(msg), state.current_turn))
        injected.append(msg)

    return injected


# ---------------------------------------------------------------------------
# Simulated Agent Turns — Pre-built realistic scenario
# ---------------------------------------------------------------------------

SCENARIO_TURNS = [
    {
        "description": "User asks to fix authentication bug",
        "user_msg": "The login endpoint is returning 401 for valid tokens. Can you investigate and fix it?",
        "agent_action": "I'll start by reading the auth middleware to understand the current implementation.",
        "tool": "read_file",
        "args": {"path": "src/auth/middleware.ts"},
    },
    {
        "description": "Agent reads the routes file",
        "user_msg": None,
        "agent_action": "Let me check the API routes to see how the middleware is applied.",
        "tool": "read_file",
        "args": {"path": "src/api/routes.ts"},
    },
    {
        "description": "Agent searches for authentication references",
        "user_msg": None,
        "agent_action": "Searching for all authentication-related code across the codebase.",
        "tool": "text_search",
        "args": {"pattern": "authenticate"},
    },
    {
        "description": "Agent reads test file",
        "user_msg": None,
        "agent_action": "Let me review the existing auth tests to understand expected behaviour.",
        "tool": "read_file",
        "args": {"path": "tests/auth.test.ts"},
    },
    {
        "description": "Agent reads the database schema",
        "user_msg": None,
        "agent_action": "Checking the database schema for the token/session model.",
        "tool": "read_file",
        "args": {"path": "src/db/schema.prisma"},
    },
    {
        "description": "Agent lists source directory",
        "user_msg": None,
        "agent_action": "Let me see the full source structure to understand the project layout.",
        "tool": "list_files",
        "args": {"path": "src/"},
    },
    {
        "description": "Agent searches for deprecated patterns",
        "user_msg": None,
        "agent_action": "Searching for deprecated code that might affect auth flow.",
        "tool": "text_search",
        "args": {"pattern": "deprecated"},
    },
    {
        "description": "Agent edits the middleware (fix)",
        "user_msg": None,
        "agent_action": "Found the issue: the token validation is comparing against the wrong field. Fixing now.",
        "tool": "edit_file",
        "args": {"path": "src/auth/middleware.ts", "old": "token.userId", "new": "token.sub"},
    },
    {
        "description": "Agent reads middleware again to verify",
        "user_msg": None,
        "agent_action": "Re-reading to verify the edit was applied correctly.",
        "tool": "read_file",
        "args": {"path": "src/auth/middleware.ts"},
    },
    {
        "description": "Agent runs tests",
        "user_msg": None,
        "agent_action": "Running the test suite to verify the fix.",
        "tool": "run_command",
        "args": {"command": "npm test"},
    },
    {
        "description": "Agent edits routes (follow-up fix)",
        "user_msg": "Also update the routes to use the new token format",
        "agent_action": "Updating the routes to use the standardised token format.",
        "tool": "edit_file",
        "args": {"path": "src/api/routes.ts", "old": "req.token", "new": "req.auth.token"},
    },
    {
        "description": "Agent edits routes again (second change)",
        "user_msg": None,
        "agent_action": "Also need to update the error handler in routes.",
        "tool": "edit_file",
        "args": {"path": "src/api/routes.ts", "old": "res.status(401)", "new": "res.status(401).json({ error: 'Unauthorized' })"},
    },
    {
        "description": "Agent edits middleware again (third edit without tests)",
        "user_msg": None,
        "agent_action": "Adding token refresh logic to the middleware.",
        "tool": "edit_file",
        "args": {"path": "src/auth/middleware.ts", "old": "validateToken(token)", "new": "validateAndRefreshToken(token)"},
    },
    {
        "description": "Agent reads package.json",
        "user_msg": None,
        "agent_action": "Checking package.json for the JWT library version.",
        "tool": "read_file",
        "args": {"path": "package.json"},
    },
    {
        "description": "Agent searches for error patterns",
        "user_msg": None,
        "agent_action": "Searching for error handling patterns across the codebase.",
        "tool": "text_search",
        "args": {"pattern": "error"},
    },
    {
        "description": "Agent runs build",
        "user_msg": None,
        "agent_action": "Building the project to check for compilation errors.",
        "tool": "run_command",
        "args": {"command": "npm run build"},
    },
    {
        "description": "Agent reads middleware (duplicate — doom loop trigger)",
        "user_msg": None,
        "agent_action": "Let me re-read the middleware to check something.",
        "tool": "read_file",
        "args": {"path": "src/auth/middleware.ts"},
    },
    {
        "description": "Agent reads middleware again (doom loop continues)",
        "user_msg": None,
        "agent_action": "Reading middleware once more to verify the token flow.",
        "tool": "read_file",
        "args": {"path": "src/auth/middleware.ts"},
    },
    {
        "description": "Agent checks git diff",
        "user_msg": None,
        "agent_action": "Let me review all changes made so far.",
        "tool": "run_command",
        "args": {"command": "git diff"},
    },
    {
        "description": "Agent runs tests again",
        "user_msg": None,
        "agent_action": "Running final test suite to confirm everything passes.",
        "tool": "run_command",
        "args": {"command": "npm test"},
    },
]


def simulate_tool_execution(tool_name: str, args: dict) -> str:
    """Generate realistic tool output."""
    if tool_name == "read_file":
        file_info = SIMULATED_TOOLS["read_file"]["files"].get(args.get("path", ""))
        if file_info:
            return file_info["output"]()
        return f"Error: File '{args.get('path', '')}' not found"

    elif tool_name == "text_search":
        pattern = args.get("pattern", "")
        match_info = SIMULATED_TOOLS["text_search"]["patterns"].get(pattern, {"matches": 5, "files": 2})
        lines = [f"src/file{i}.ts:{random.randint(1,200)}: match for '{pattern}'" for i in range(1, match_info["matches"] + 1)]
        return "\n".join(lines)

    elif tool_name == "list_files":
        dir_info = SIMULATED_TOOLS["list_files"]["directories"].get(args.get("path", ""), {"items": 15})
        entries = [f"{'dir' if i % 5 == 0 else 'file'}_{i}.ts" for i in range(1, dir_info["items"] + 1)]
        return "\n".join(entries)

    elif tool_name == "run_command":
        cmd_info = SIMULATED_TOOLS["run_command"]["commands"].get(args.get("command", ""))
        if cmd_info:
            return cmd_info["output"]()
        return f"$ {args.get('command', '')}\nCommand completed successfully."

    elif tool_name == "edit_file":
        return f"Successfully edited {args.get('path', 'file')}: replaced '{args.get('old', '')}' with '{args.get('new', '')}'"

    return "Tool executed successfully."


# ---------------------------------------------------------------------------
# Main Simulation Engine
# ---------------------------------------------------------------------------


class ContextSimulation:
    """Runs the full context engineering simulation."""

    def __init__(self, max_tokens: int = 128_000):
        self.state = ContextState(max_tokens=max_tokens)
        self.turn_log = []
        self.edits_since_test = 0

        # Add system prompt
        system_prompt = (
            "You are an expert coding assistant. Follow these rules:\n"
            "1. Always read files before editing them.\n"
            "2. Run tests after making changes.\n"
            "3. Complete all tasks before stopping.\n"
            "4. If an edit fails, re-read the file and retry.\n"
        )
        self.state.messages.append(
            ConversationMessage("system", system_prompt, estimate_tokens(system_prompt), 0)
        )

    def execute_turn(self, turn_index: int) -> dict:
        """Execute a single turn and return the full state."""
        if turn_index >= len(SCENARIO_TURNS):
            return None

        turn = SCENARIO_TURNS[turn_index]
        self.state.current_turn = turn_index + 1
        result = {
            "turn": self.state.current_turn,
            "description": turn["description"],
            "tool": turn["tool"],
            "args": turn["args"],
            "compaction_actions": [],
            "reminders_injected": [],
            "pressure_before": self.state.pressure,
            "stage_before": self.state.stage.value,
        }

        # Add user message if present
        if turn.get("user_msg"):
            msg = turn["user_msg"]
            self.state.messages.append(
                ConversationMessage("user", msg, estimate_tokens(msg), self.state.current_turn)
            )

        # Add agent reasoning
        agent_msg = turn["agent_action"]
        self.state.messages.append(
            ConversationMessage("assistant", agent_msg, estimate_tokens(agent_msg), self.state.current_turn)
        )

        # Phase 0: Context compaction check
        compaction_actions = apply_compaction(self.state)
        result["compaction_actions"] = compaction_actions

        # Execute tool
        raw_output = simulate_tool_execution(turn["tool"], turn["args"])
        raw_tokens = estimate_tokens(raw_output)
        summary = summarise_tool_result(turn["tool"], turn["args"], raw_output)
        summary_tokens = estimate_tokens(summary)

        tool_result = ToolResult(
            tool_name=turn["tool"],
            arguments=turn["args"],
            raw_output=raw_output,
            raw_tokens=raw_tokens,
            summary=summary,
            summary_tokens=summary_tokens,
            turn=self.state.current_turn,
        )
        self.state.tool_results.append(tool_result)

        # Add to conversation — use summary in context, not raw output
        self.state.messages.append(
            ConversationMessage("tool_result", summary, summary_tokens, self.state.current_turn)
        )
        result["raw_tokens"] = raw_tokens
        result["summary_tokens"] = summary_tokens
        result["summary"] = summary
        result["tokens_saved"] = raw_tokens - summary_tokens

        # Track edits since test
        if turn["tool"] == "edit_file":
            self.edits_since_test += 1
        elif turn["tool"] == "run_command" and "test" in turn["args"].get("command", ""):
            self.edits_since_test = 0

        # Check for system reminders
        event = {
            "tool_call": {"name": turn["tool"], "args": turn["args"]},
            "edits_since_test": self.edits_since_test,
        }
        if "Error" in raw_output or "not found" in raw_output:
            event["error"] = "File not found or tool execution failed"

        reminders = check_and_inject_reminders(self.state, event)
        result["reminders_injected"] = reminders

        # Final state
        result["pressure_after"] = self.state.pressure
        result["stage_after"] = self.state.stage.value
        result["total_tokens"] = self.state.used_tokens
        result["total_messages"] = len([m for m in self.state.messages if not m.is_compacted])

        self.turn_log.append(result)
        return result


# ---------------------------------------------------------------------------
# Gradio Interface
# ---------------------------------------------------------------------------

import gradio as gr

sim = None


def reset_simulation(context_size: int):
    """Reset the simulation with a given context window size."""
    global sim
    sim = ContextSimulation(max_tokens=context_size)
    return (
        format_dashboard(None),
        format_timeline([]),
        format_compaction_log([]),
        format_token_budget(sim.state),
        0,
    )


def step_forward(turn_counter: int):
    """Execute the next turn."""
    global sim
    if sim is None:
        sim = ContextSimulation()

    result = sim.execute_turn(int(turn_counter))
    if result is None:
        return (
            format_dashboard({"turn": "Done", "description": "All 20 turns completed."}),
            format_timeline(sim.turn_log),
            format_compaction_log(sim.state.compaction_log),
            format_token_budget(sim.state),
            turn_counter,
        )

    return (
        format_dashboard(result),
        format_timeline(sim.turn_log),
        format_compaction_log(sim.state.compaction_log),
        format_token_budget(sim.state),
        turn_counter + 1,
    )


def run_all():
    """Run all 20 turns at once."""
    global sim
    sim = ContextSimulation()

    for i in range(len(SCENARIO_TURNS)):
        sim.execute_turn(i)

    last = sim.turn_log[-1] if sim.turn_log else None
    return (
        format_dashboard(last),
        format_timeline(sim.turn_log),
        format_compaction_log(sim.state.compaction_log),
        format_token_budget(sim.state),
        len(SCENARIO_TURNS),
    )


def format_dashboard(result: dict) -> str:
    """Format the current turn dashboard."""
    if result is None:
        return "Press 'Step' to begin the simulation or 'Run All' to see all 20 turns."

    lines = [f"## Turn {result.get('turn', '?')}: {result.get('description', '')}"]

    if result.get("tool"):
        lines.append(f"\n**Tool:** `{result['tool']}` | **Args:** `{json.dumps(result.get('args', {}))}`")

    if result.get("summary"):
        lines.append(f"\n**Optimised Result:** {result['summary']}")

    if result.get("tokens_saved"):
        lines.append(f"**Token Savings:** {result['raw_tokens']:,} raw -> {result['summary_tokens']:,} summary "
                      f"(**{result['tokens_saved']:,} tokens saved**, "
                      f"{result['tokens_saved']/max(1,result['raw_tokens']):.0%} reduction)")

    if result.get("compaction_actions"):
        lines.append("\n**Compaction:**")
        for action in result["compaction_actions"]:
            lines.append(f"- {action}")

    if result.get("reminders_injected"):
        lines.append("\n**System Reminders Injected:**")
        for reminder in result["reminders_injected"]:
            lines.append(f"- {reminder}")

    pressure = result.get("pressure_after", 0)
    bar_filled = int(pressure * 30)
    bar_empty = 30 - bar_filled
    colour = "red" if pressure > 0.85 else "orange" if pressure > 0.70 else "green"
    lines.append(f"\n**Context Pressure:** `[{'#' * bar_filled}{'.' * bar_empty}]` {pressure:.1%} | "
                 f"**Stage:** {result.get('stage_after', 'Nominal')}")

    return "\n".join(lines)


def format_timeline(turn_log: list) -> str:
    """Format the full timeline of turns."""
    if not turn_log:
        return "No turns executed yet."

    lines = ["| Turn | Tool | Raw Tokens | Summary Tokens | Saved | Pressure | Stage |",
             "|------|------|-----------|---------------|-------|----------|-------|"]

    for t in turn_log:
        saved_pct = f"{t.get('tokens_saved', 0)/max(1, t.get('raw_tokens', 1)):.0%}" if t.get("raw_tokens") else "-"
        lines.append(
            f"| {t['turn']} | `{t['tool']}` | {t.get('raw_tokens', '-'):,} | "
            f"{t.get('summary_tokens', '-'):,} | {saved_pct} | "
            f"{t.get('pressure_after', 0):.1%} | {t.get('stage_after', '-')} |"
        )

    total_raw = sum(t.get("raw_tokens", 0) for t in turn_log)
    total_summary = sum(t.get("summary_tokens", 0) for t in turn_log)
    total_saved = total_raw - total_summary
    lines.append(f"\n**Totals:** {total_raw:,} raw tokens -> {total_summary:,} in context "
                 f"(**{total_saved:,} tokens saved overall**, {total_saved/max(1,total_raw):.0%} reduction)")

    return "\n".join(lines)


def format_compaction_log(log: list) -> str:
    """Format the compaction event log."""
    if not log:
        return "No compaction events yet. Context pressure is below 70%."

    lines = ["| Turn | Stage | Pressure | Action | Details |",
             "|------|-------|----------|--------|---------|"]
    for entry in log:
        details = ""
        if entry.get("items_compacted"):
            details = f"{entry['items_compacted']} items, ~{entry.get('tokens_recovered', 0):,} tokens recovered"
        elif entry.get("messages_summarised"):
            details = f"{entry['messages_summarised']} messages summarised"
        else:
            details = "Monitoring"
        lines.append(
            f"| {entry['turn']} | {entry['stage']} | {entry['pressure']} | "
            f"{entry['action']} | {details} |"
        )

    reminders_by_type = {}
    if sim:
        for r in sim.state.reminders:
            reminders_by_type.setdefault(r.trigger, []).append(r.turn)
    if reminders_by_type:
        lines.append("\n**System Reminders Fired:**")
        for trigger, turns in reminders_by_type.items():
            lines.append(f"- **{trigger}**: fired at turn(s) {', '.join(str(t) for t in turns)}")

    return "\n".join(lines)


def format_token_budget(state: ContextState) -> str:
    """Format the token budget visualisation."""
    total = state.max_tokens
    used = state.used_tokens
    free = total - used
    pressure = state.pressure

    # Category breakdown
    system_tokens = sum(m.tokens for m in state.messages if m.role == "system" and not m.is_compacted)
    user_tokens = sum(m.tokens for m in state.messages if m.role == "user" and not m.is_compacted)
    assistant_tokens = sum(m.tokens for m in state.messages if m.role == "assistant" and not m.is_compacted)
    tool_tokens = sum(m.tokens for m in state.messages if m.role == "tool_result" and not m.is_compacted)
    reminder_tokens = sum(m.tokens for m in state.messages if m.role == "system_reminder" and not m.is_compacted)
    compacted_count = sum(1 for m in state.messages if m.is_compacted)

    lines = [
        "### Token Budget Breakdown",
        f"**Window:** {total:,} tokens | **Used:** {used:,} | **Free:** {free:,} | **Pressure:** {pressure:.1%}",
        "",
        "| Category | Tokens | % of Used |",
        "|----------|--------|-----------|",
        f"| System Prompt | {system_tokens:,} | {system_tokens/max(1,used):.1%} |",
        f"| User Messages | {user_tokens:,} | {user_tokens/max(1,used):.1%} |",
        f"| Assistant (reasoning) | {assistant_tokens:,} | {assistant_tokens/max(1,used):.1%} |",
        f"| Tool Results (optimised) | {tool_tokens:,} | {tool_tokens/max(1,used):.1%} |",
        f"| System Reminders | {reminder_tokens:,} | {reminder_tokens/max(1,used):.1%} |",
        f"\n**Compacted messages:** {compacted_count} | **Active messages:** {len(state.messages) - compacted_count}",
    ]

    # What-if comparison
    if state.tool_results:
        raw_total = sum(tr.raw_tokens for tr in state.tool_results)
        summary_total = sum(tr.summary_tokens for tr in state.tool_results)
        hypothetical_pressure = (used - summary_total + raw_total) / total
        lines.append(f"\n### Without Tool Result Optimisation")
        lines.append(
            f"Tool results would use **{raw_total:,} tokens** instead of {summary_total:,} "
            f"({raw_total - summary_total:,} extra tokens)"
        )
        lines.append(f"Context pressure would be **{hypothetical_pressure:.1%}** instead of {pressure:.1%}")
        if hypothetical_pressure > 0.99:
            lines.append("**The context window would have overflowed!**")
        elif hypothetical_pressure > 0.85:
            lines.append("**Full compaction would have been triggered, losing conversation detail.**")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Build UI
# ---------------------------------------------------------------------------

with gr.Blocks(title="Context Engineering Demo") as demo:
    gr.Markdown("""
    # Context Engineering: Adaptive Compaction Pipeline
    ### Based on the OpenDev Technical Report (arXiv:2603.05344)

    This demo simulates a **20-turn coding agent session** (fixing an authentication bug) and shows
    how context engineering keeps the agent effective over long conversations:

    - **Tool Result Optimisation** — raw outputs (thousands of tokens) compressed to compact summaries (~15 tokens)
    - **5-Stage Adaptive Compaction** — progressively reclaims context as pressure rises (70% -> 80% -> 85% -> 90% -> 99%)
    - **System Reminders** — event-driven nudges injected when the agent drifts (exploration spirals, doom loops, instruction fade-out)
    - **Doom-Loop Detection** — fingerprints repeated identical tool calls and intervenes

    **Step through one turn at a time** to watch context pressure build, or **Run All** to see the full session.
    """)

    turn_counter = gr.State(value=0)

    with gr.Row():
        context_size = gr.Slider(
            minimum=8_000, maximum=200_000, value=128_000, step=1_000,
            label="Context Window Size (tokens)",
            info="Smaller windows trigger compaction sooner — try 16,000 to see all stages activate",
        )
        step_btn = gr.Button("Step (Next Turn)", variant="primary", scale=1)
        run_all_btn = gr.Button("Run All 20 Turns", variant="secondary", scale=1)
        reset_btn = gr.Button("Reset", scale=1)

    with gr.Row():
        with gr.Column(scale=2):
            dashboard = gr.Markdown(
                value="Press **Step** to begin or **Run All** to see the full simulation.",
                label="Current Turn",
            )

        with gr.Column(scale=1):
            token_budget = gr.Markdown(value="", label="Token Budget")

    with gr.Tabs():
        with gr.TabItem("Timeline"):
            timeline = gr.Markdown(value="No turns executed yet.", label="Turn Timeline")

        with gr.TabItem("Compaction & Reminders Log"):
            compaction_log = gr.Markdown(value="No compaction events yet.", label="Compaction Log")

    # Wire up controls
    step_btn.click(
        step_forward,
        inputs=[turn_counter],
        outputs=[dashboard, timeline, compaction_log, token_budget, turn_counter],
    )
    run_all_btn.click(
        run_all,
        outputs=[dashboard, timeline, compaction_log, token_budget, turn_counter],
    )
    reset_btn.click(
        reset_simulation,
        inputs=[context_size],
        outputs=[dashboard, timeline, compaction_log, token_budget, turn_counter],
    )


if __name__ == "__main__":
    demo.launch()
