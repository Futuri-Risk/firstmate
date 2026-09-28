# ACP adapters (`acp:<agent>`)

One reference for the whole `acp:` family - any agent ACPx itself declares, launched through FirstMate's worker console - with `acp:zcode` (zcode-acp 0.43.3) the verified member.
Verified 2026-09-27 for crewmate/scout work only, through the contract suites `../../../tests/fm-acpx-worker.test.py` (real FirstMate wrapper, real ACPx, an external peer) and `../../../tests/fm-zcode-bridge.test.py` (the real pinned ZCode ACP bridge; only the paid vendor app-server substituted), both run by `../../../tests/fm-fleet-cloud.test.sh` inside the pinned-dependency Fleet contract tests lane, plus a live stdio probe of the ZCode ACP server on this machine (initialize, `session/new`, one real model turn returning `stopReason: end_turn`).
A secondmate or primary is out of scope BY DESIGN, not by a verification gap: `../../../bin/fm-spawn.sh` carries the boundary comment "ACPx is a worker harness; it is deliberately not a primary/Secondmate backend" and refuses a secondmate launch outright, `../../../docs/supervision-protocols/` carries no ACPx protocol, and the control plane refuses a secondmate relaunch before stopping anything.
Cross-harness provider and credential identity is owned by `references/common/model-and-effort.md`.

## Operating facts

| Fact | Value |
|---|---|
| Harness value | `acp:<agent>`, a family grammar rather than one name. The agent part must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`; `fm_acpx_harness_valid` in `../../../bin/fm-acpx-lib.sh` owns the check, spawn preflight (`error: invalid ACP agent name`), the control plane, and teardown all refuse a malformed value, and `../../../bin/fm-dispatch-resolve.sh` carries the same regex in its `verified()` rule so a dispatch profile cannot name an invalid agent either. |
| Launch | `FM_HOME=<home> python3 <bin>/fm-acpx-worker.py --task <id> --agent <agent> --gen <busy-gen> --cwd <worktree> --brief <file> [--model <model>] [--effort <effort>]`, the template in `../../../bin/fm-spawn.sh`; the busy generation is armed through `fm-busy-event.sh` exactly like claude/opencode/pi/omp, and preflight also refuses when `acpx` or `python3` is missing from `PATH`. |
| Session | One named ACPx session per task, `fm-<task>-<sha256(<home> NUL <worktree>)[:16]>`: both prompts of one console ride one provider conversation, a relaunch after close resumes it, and a session whose cwd is not exactly the task worktree is refused. |
| Busy state | Semantic `acpx-bridge`: every apply runs `../../../bin/fm-busy-event.sh` with `--source acpx-bridge` and the armed generation, and `../../../bin/fm-busy-lib.sh` maps every `acp:*` value to the `acpx-bridge` adapter plus the shared `fm-spawn fm-interrupt fm-recovery` trusts. |
| Turn end | `state/<task>.turn-ended` is touched after EVERY prompt, success or failure, and an ACP turn ending never marks a FirstMate task complete - the worker contract suite pins that no `done:` status is ever written. |
| Interrupt | Protocol-native. The control plane delivers `C-c` once (ack source `none`, no clear key; a recorded `acp:<agent>` resolves to the `acpx` family for these tables); the console's SIGINT handler converts it into `acpx cancel --session`, and a cancelled turn ends busy `idle` with event `cancelled` rather than `prompt-failed`. |
| Exit | `/exit` at the worker's own `❯ ` prompt ends the console loop and its finally-block closes the named session; teardown closes the same session through `fm_acpx_close_task` and preserves the task when the close fails (`error: ACP session could not be closed; preserving task work`). |
| Permissions | Fail-closed: every acpx invocation carries `--non-interactive-permissions fail`, so an unattended approval request fails the turn instead of parking it; grants live only in the private home's `config/acpx-permission-policy.json` (see "Permission posture"). |
| Kinds | Crewmate and scout ONLY. Spawn refuses a secondmate with `error: ACPx workers cannot supervise a Secondmate; use OpenCode`; the control plane refuses a secondmate relaunch before stopping the running agent; there is no primary surface at all. |
| Model | `--model` reaches acpx only when set and not `default`; the worker does not re-validate it against the agent's advertised models, so pin only an id the registry is known to advertise (see "The verified member: acp:zcode"). |
| Effort | Checked against the live server at connect: applied through `acpx set` only when the session's advertised `acpx.config_options` (option id `thought_level`, `reasoning_effort`, or `effort`) lists the requested value, otherwise the launch refuses (`ACP server does not advertise the requested effort`); omitted entirely when absent or `default`. |
| Process identity | `fm_acpx_pid_matches` in `../../../bin/fm-acpx-lib.sh`: argv[0] a python interpreter, argv[1] the same file as the real `fm-acpx-worker.py` (`-ef`, so a same-named copy never matches). No process is claimed from a substring in a prompt or an unrelated Python command, and an unreadable argv is unknown, never proof that a process died. |
| Marker | None. The family publishes no environment marker, `../../../bin/fm-harness.sh` carries no acpx arm, and the `acp:` template is excluded from spawn's foreign-marker `env -u` wrap - identity is the recorded `harness=` plus the structural pid rule above, so no inherited marker can claim or shadow it. |

## Agent declaration

ACPx owns the agent catalog; FirstMate never launches an app-server itself.
The worker invokes `acpx <agent>` with the bare agent name as its positional argument, so an agent is dispatchable only after ACPx's `agents.NAME.argv` config names its executable.
On this machine `~/.acpx/config.json` declares `agents.zcode.argv = ["zcode-acp-server"]`; both contract suites write the same shape into the test home's `.acpx/config.json` to pin their external peer, which is also the proof that the catalog resolves through `$HOME/.acpx/config.json`.
The worker docstring's division of ownership is the rule to keep: ACPx owns protocol and provider sessions; FirstMate owns tasks and its inbox.

## Worker console lifecycle

The console is one Python process over one ACPx session, serialized per task by `state/<task>.acpx-owner.lock`.
On attach it runs `sessions ensure` for the named session - with `--resume-session <id>` when the saved binding records a closed provider session - then verifies the shown session's cwd is exactly the task worktree (`ACPx returned an ancestor or different worktree session`), refuses a resume that changed provider identity (`resume changed provider identity; preserved binding requires recovery`), and cancels a provider turn still marked running before taking over.
Every later acpx call and control verb re-validates first: task metadata must still record `harness=acp:<agent>` and the same worktree, the busy generation must match (`stale ACP worker generation; refusing to touch its replacement`), and a saved binding must match agent and worktree.
The generation guard is pinned by contract - a stale worker is refused before any provider contact at all.

A prompt runs `acpx prompt --session <name> --file -` with the text on stdin, in a child of its own session so a pane interrupt reaches the worker rather than the provider.
JSON events stream to the console's stdout, `stopReason` is captured from the result object, and busy progress refreshes at most once per second.
The child is never abandoned: a stuck prompt is cancelled, then terminated, then killed, and stderr lands in the private `state/<task>.acpx-stderr` (opened `O_NOFOLLOW`, mode 0600).
Failure is loud and preserving: a nonzero exit or a missing `stopReason` sets busy `unknown` with event `prompt-failed` and appends `blocked: ACP prompt failed or requested unattended approval; inspect ACPx and the private task error log. Worktree preserved.` to the task status; a clean return, including a cancelled one, sets busy `idle`.
After the launch brief the console reads follow-ups at its own `❯ ` prompt until `/exit` or EOF, and close always runs.

## Permission posture

Every acpx invocation - prompts and control verbs alike - carries the fixed flags `--cwd <worktree> --format json --json-strict --non-interactive-permissions fail --ttl 300`.
`--json-strict` plus the worker's own parse means a malformed control answer is a refusal (`ACPx returned invalid control output`), never a guessed state.
`--non-interactive-permissions fail` is the default posture: with no policy file, ACPx keeps its read-only approval default and an unattended write request fails the turn through the `blocked:` status line above rather than approving anything silently.
The only grant surface is the private home's `config/acpx-permission-policy.json`; when that file exists the worker adds `--permission-policy <path>`, and it stays per-home and out of the repo.

## Crewmate and scout only

The boundary is code, not guidance.
`../../../bin/fm-spawn.sh` refuses `--secondmate` on any `acp:*` value, under the header comment that ACPx is deliberately not a primary/secondmate backend.
`../../../bin/fm-control-lib.sh` refuses a secondmate relaunch target BEFORE stopping the running agent, and `../../../bin/fm-teardown.sh` runs its ACP session close only for non-secondmate kinds.
A secondmate is a firstmate primary in its own home and needs a primary supervision protocol; `../../../docs/supervision-protocols/` carries none for ACPx, and none is planned on this path.
Crewmates and scouts are the verified kinds: the contract suites exercise exactly that journey - launch brief, follow-up, cancel, resume-after-close - end to end.

## Model and effort

`../../../bin/fm-spawn.sh` applies `--model` and `--effort` to `acp:*` with no vocabulary filter of its own; enforcement is the worker's, against the live server.
A model set to anything but `default` passes through to acpx unvalidated - dispatch profiles may carry one (`../../../tests/fm-dispatch-resolve.test.sh` resolves `--harness 'acp:zcode' --model 'glm-5.3'` eligible under provider `zai`), but nothing checks it against the agent's advertised catalog, so only a verified id may be pinned.
Effort is stricter than the shared record-and-omit contract because ACPx can interrogate the live server: at connect the worker reads the session's advertised `acpx.config_options`, looks for the option whose id is `thought_level`, `reasoning_effort`, or `effort`, applies the request through `acpx set` only when that option lists the value, and otherwise refuses the launch outright - an unsupported effort fails loudly instead of being silently dropped.
Read the contract forward the same way: for an agent known to advertise no effort option, record the request and omit the flag rather than pass one the worker must refuse.
When no effort is requested, or the value is `default`, nothing is set at all.

## Detection and process identity

`../../../bin/fm-harness.sh` detection does not cover this family: there is no marker to test and no TUI command name to match, and the file carries no acpx arm (a grep over it returns zero matches).
The router's rule that a new adapter's verified marker and command name must land in `fm-harness.sh` is satisfied here by landing neither: spawn writes the harness value into `state/<id>.meta`, and every later verb - control, relaunch, teardown - re-reads that exact recorded value and validates the grammar, never inferring the harness from a model or provider.
Liveness is structural: `../../../bin/fm-agent-process-lib.sh` classifies a process an agent only when `fm_acpx_pid_matches` proves argv[1] is the real `fm-acpx-worker.py` beside the lib, so an unrelated Python pane can never claim ACP identity and an unreadable `/proc/<pid>/cmdline` reads unknown rather than dead.

## The verified member: `acp:zcode`

zcode-acp 0.43.3 is installed globally (npm `-g`); both `zcode-acp` and `zcode-acp-server` are on `PATH`, auth already works through `~/.zcode/credentials.json` (FirstMate manages no credential for it), and ACPx launches the stdio server - `agents.zcode.argv = ["zcode-acp-server"]` - which needs no TTY, unlike the interactive `zcode-acp` TUI.
A live stdio probe on 2026-09-27 ran the same shape end to end (`zcode-acp server`): initialize, `session/new`, one real model turn, `stopReason: end_turn`, reply `PONG`.
The live registry advertises exactly one model (`GLM-5.3`) and no verified effort option, so the record-and-omit rule applies and neither `--model` nor `--effort` may be pinned for `acp:zcode` without verifying the exact accepted value first.
The bridge contract is pinned in CI: the evidence lane builds zcode-acp at `6552c7d30554c72e6f69faacbff34d94366d9651` into a checksummed runtime, the Fleet contract tests lane unpacks it and points `FM_TEST_ZCODE_ENTRY` at its `dist` entry, and `../../../tests/fm-zcode-bridge.test.py` substitutes only the vendor app-server - `../../../tests/assets/fm-zcode-app-server.cjs`, a protocol fixture with no provider key, network call, workspace edit, or model inference.
Those tests prove the real bridge preserves the worktree (`session/create` carries the exact worktree path as `workspacePath`), rides both turns on one materialized vendor session, and reopens that same vendor conversation (`session/resume`) after close.
The sibling suite `../../../tests/fm-acpx-worker.test.py` pins the worker contract itself: two prompts share one provider session without completing the task, a closed session resumes the exact provider conversation, a stale generation is refused before provider contact, and a cancel releases a waiting turn with the worktree's uncommitted file intact.

### Launch-environment prerequisite (verified in-fleet 2026-09-28)

The zcode backend dies at first prompt - every turn fails with `zcode create failed: zcode backend reader exited (backend dead)`, and the failed session record then drifts its provider id on every retry so the named session must be discarded and re-ensured - whenever the launch environment carries no ZCode provider variables.
The backend headless boot needs `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE` + `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE`; the bridge derives both from its resolved entry only when that entry is the real `.cjs` (`builtinProviderEnv` rejects a shell shim), and a terminal launched outside the ZCode desktop app has none in its ambient environment.
Sessions launched from a shell that inherited the desktop app's `ZCODE_*` environment work, which is why stdio probes and CI-adjacent shells can pass while a fleet pane fails deterministically.
The machine-level fix (verified by an in-fleet scout run 2026-09-28: spawn, real tool-bearing turn, status protocol, report, clean teardown) is `ZCODE_BIN=/opt/ZCode/resources/glm/zcode.cjs` exported in the interactive shell profile: the bridge honors `ZCODE_BIN` before PATH discovery, the `.cjs` entry passes the derivation test, and the adjacent `provider/zcode-builtin.json` plus `~/.zcode/v2/provider_config.json` supply both variables.
A dispatch environment without that export is not a verified `acp:zcode` launch site; re-probe with a one-word prompt round trip before dispatching real work from a new seat.
