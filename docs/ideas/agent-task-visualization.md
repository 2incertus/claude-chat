# Agent Task Visualization

Brainstorming doc for showing subagent activity in the claude-chat PWA.

## Feature Concept

Claude Code's Agent tool spawns subagents to handle work in parallel or sequentially. Today, the claude-chat PWA shows the raw tmux output -- you see status lines like `Agent(description)` appearing as tool calls, but there is no structured representation of what agents are running, what they are doing, or how they relate to each other.

How agents work in Claude Code:
- The main Claude session can invoke the **Agent tool**, passing a task description. This spawns a subagent that runs independently.
- Each agent invocation has: a description (what was asked), a status (running, completed, failed), and output (its final result or error).
- Agents can spawn their own subagents, creating a **nested tree** of work. A code refactoring task might spawn 5 file-editing agents, one of which spawns 2 more to handle complex files.
- Multiple agents can run **in parallel** -- Claude Code uses this to search multiple directories, edit multiple files, or research multiple topics simultaneously.
- In the tmux pane, agent activity appears as status lines (`Agent(description)` tool calls followed by indented `tool_result` output). The nesting and parallelism are not visually obvious from raw output.

The goal: give the user a clear, at-a-glance view of what agents are doing, how they relate, and whether they succeeded -- without requiring them to parse raw tmux output.

## Questions to Explore

1. **Where should agents appear in the UI?**
   a) Inline in the chat feed (like current command-result cards)
   b) In a separate collapsible panel/drawer accessible from the header
   c) As a floating overlay that can be toggled on/off
   d) In a dedicated tab alongside the main chat

2. **How should agent status be represented visually?**
   a) Color-coded dots (green=done, yellow=running, red=failed) -- matching the existing session status dot pattern
   b) Animated spinner for running, checkmark/X for completed/failed
   c) Progress bar showing estimated completion
   d) Pulsing border or glow effect on the agent card

3. **How deep should nesting display go?**
   a) Flat list only -- show all agents at the same level regardless of who spawned them
   b) One level of nesting (parent + direct children)
   c) Full tree with indentation, no depth limit
   d) Full tree but auto-collapse anything deeper than 2 levels

4. **Should agent output stream live or only appear on completion?**
   a) Live stream -- show each line as it appears in the agent's work (like watching a terminal)
   b) Completion only -- show nothing until the agent finishes, then show the result
   c) Hybrid -- show a brief live status line (e.g., "Reading 3 files...") but full output only on completion
   d) User-configurable per session

5. **How should 5+ parallel agents be handled without overwhelming the UI?**
   a) Show a summary card ("5 agents running") that expands to individual cards on tap
   b) Stack them vertically with compact one-line cards (name + status dot only)
   c) Horizontal scrollable pill bar showing agent names, tap to expand one
   d) Show the first 3 inline, with a "+N more" overflow indicator

6. **Should completed agents auto-collapse?**
   a) Yes, always collapse when done -- keep the feed clean
   b) Collapse after a short delay (e.g., 3 seconds) so the user can see the result
   c) Collapse only if there are 3+ completed agents visible
   d) Never auto-collapse -- let the user manage it
   e) Collapse only successful agents; keep failed agents expanded

7. **How should agent output be visually distinguished from the main Claude conversation?**
   a) Different background color (e.g., slightly tinted cards)
   b) Left border accent color unique to agents
   c) Indented with a vertical line connector (tree style)
   d) Same styling as command-result cards but with an agent icon/badge
   e) Monospace font for agent output vs proportional for main conversation

8. **Should users be able to interact with individual agents?**
   a) View only -- no interaction, agents are autonomous
   b) Allow canceling a running agent (sends interrupt)
   c) Allow sending a message/instruction to a specific running agent
   d) Allow re-running a failed agent

9. **Should token usage / cost be displayed per agent?**
   a) No -- too noisy, overall session cost is enough
   b) Show token count per agent in a subtle footer
   c) Show cost per agent only on tap/expand
   d) Show aggregate cost for the agent tree (parent + all children)

10. **How should the agent tree relate to the main chat scroll position?**
    a) Agents are rendered inline at the position where they were spawned -- scrolling the chat scrolls past them
    b) Agents float in a sticky section that stays visible while the main chat scrolls
    c) A small floating badge shows "3 agents running" and tapping it scrolls to or opens the agent view
    d) Agents are completely separate from chat scroll -- accessed via a dedicated button/tab

## Rough Mockup Concepts

### A. Inline Expansion Cards

This approach extends the existing command-result card pattern that already works in the app. Agent invocations render as collapsible cards directly in the chat feed, right where Claude spawned them.

```
[ Claude message: "I'll search for that pattern across the codebase." ]

+--------------------------------------------------+
| > Agent: Search src/ for auth patterns    [done]  |
|   +----------------------------------------------+
|   | > Grep(pattern="auth", path="src/")  [done]  |
|   | > Read("src/auth/middleware.ts")      [done]  |
|   +----------------------------------------------+
|   Result: Found 3 auth middleware files...        |
+--------------------------------------------------+

+--------------------------------------------------+
| > Agent: Search tests/ for auth coverage  [done]  |
|   Result: 2 test files cover auth...              |
+--------------------------------------------------+

[ Claude message: "Here's what I found..." ]
```

**Pros:** Familiar pattern (users already understand command-result cards). Natural reading order -- agents appear where they were invoked. No new navigation concepts. Works well on mobile since cards are full-width.

**Cons:** Can push the main conversation far apart when many agents run. Deep nesting (3+ levels) becomes hard to read with indentation alone. Parallel agents may visually imply sequence.

### B. Sidebar / Drawer with Agent Tree

A dedicated panel slides in from the right (or bottom on mobile) showing the full agent tree. The main chat feed shows a compact inline indicator ("3 agents working...") and the drawer provides the detailed view.

```
Main Chat:                          Drawer (slide from right):
+---------------------+            +-------------------------+
| Claude: "Let me     |            | Agent Tree              |
| refactor those       |  [tap -->] | +-- Refactor auth  [ok] |
| files..."            |            |   +-- Edit middleware   |
|                      |            |   +-- Edit routes       |
| [3 agents running]   |            |   +-- Update tests [!!] |
|                      |            | +-- Update docs    [ok] |
| Claude: "Done,       |            | +-- Run linter    [...] |
| here's the summary." |            +-------------------------+
+---------------------+
```

**Pros:** Keeps the main chat feed clean and readable. Tree visualization makes parent-child relationships obvious. Can show the full tree at any time regardless of chat scroll position. Good for complex multi-agent tasks with deep nesting.

**Cons:** Requires new navigation (drawer/panel concept). On small phone screens, the drawer may cover the entire chat. Users might not discover it without guidance. Disconnects agent context from where it was invoked in the conversation.

### C. Tabbed View (Main Chat + Agent Tabs)

The chat screen header gets a tab bar. The default tab is "Chat" (current behavior). When agents spawn, an "Agents" tab appears with a badge count. Each top-level agent group could optionally get its own tab.

```
+--------------------------------------------------+
| < Back    Session Name          [Chat] [Agents 3] |
+--------------------------------------------------+

(When "Agents" tab is selected:)

+--------------------------------------------------+
| Refactor auth module                    [running] |
| Started 12s ago                                   |
|                                                   |
|   Edit src/auth/middleware.ts           [done]    |
|   Edit src/auth/routes.ts               [done]    |
|   Update tests/auth.test.ts             [failed]  |
|     Error: Test assertion mismatch                |
|                                                   |
| Update documentation                   [done]     |
|   3 files updated                                 |
|                                                   |
| Run linter                              [running] |
|   Checking 47 files...                            |
+--------------------------------------------------+
```

**Pros:** Full screen devoted to agent status -- no compromise on space. Clean separation of concerns (conversation vs. agent work). Badge count on tab gives at-a-glance awareness. Familiar mobile pattern (tabs).

**Cons:** Context switching between tabs is friction. Users might miss agent completion if they are on the other tab. Duplicates some information (agent results appear in chat AND agent tab). Tab bar takes vertical space from the header area.
