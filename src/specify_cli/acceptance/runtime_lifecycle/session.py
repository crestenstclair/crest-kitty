"""The process-lifecycle-v1 runtime-session provider (port of runtime-session.ts).

Bounded lifecycle: start -> ordered progress markers -> exact completion
markers in declared order -> completion-to-exit grace -> normal exit with the
required code -> no owned process or descendant remains. Persistent lifecycles
(interactive-persistent, service-persistent, background-owned) treat the
completion markers as readiness and require the declared
``owned-process-signal-v1`` controller teardown to cleanly stop the session;
readiness and teardown are reported separately.

Six timeout budgets bound every stage (startupTimeoutMs, progressSilenceMs,
completionTimeoutMs, completionToExitGraceMs, teardownGraceMs, hardTimeoutMs)
with the failure-stage vocabulary startup / progress_silence / completion /
completion_to_exit / teardown / hard_limit. All diagnostics, evidence, and
termination actions are JSON-safe dicts; environment values never appear in
results.

Deviation from the TS reference: ``subprocess.Popen`` either raises (mapped to
``runtime_spawn_failed``) or has spawned, so Node's late 'error'/'spawn'
events and the pre-spawn startup-timeout branch have no analogue here.
"""

from __future__ import annotations

import codecs
import contextlib
import os
import signal as signal_module
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from specify_cli.acceptance.deterministic.model import ResolvedValidation
from specify_cli.acceptance.deterministic.process_runner import (
    ProcessExecutionRequest,
    ProcessResult,
    ProcessSpawnError,
)
from specify_cli.acceptance.runtime_lifecycle.capabilities import (
    RuntimeHostCapabilityRegistry,
    create_default_runtime_host_capabilities,
)
from specify_cli.acceptance.runtime_lifecycle.interactions import RuntimeInteractionProviderRequest
from specify_cli.acceptance.runtime_lifecycle.launcher import RuntimeLaunchRequest, ScriptRuntimeProcessLauncher
from specify_cli.acceptance.runtime_lifecycle.process_tree import OwnedProcessTree
from specify_cli.acceptance.runtime_lifecycle.registry import (
    RuntimeInteractionProviderRegistry,
    create_default_runtime_interaction_registry,
)

PROCESS_LIFECYCLE_RUNTIME_PROVIDER = "process-lifecycle-v1"
OWNED_PROCESS_SIGNAL_TEARDOWN_PROVIDER = "owned-process-signal-v1"

_POLL_INTERVAL_S = 0.01
_TREE_POLL_INTERVAL_MS = 40
_READ_CHUNK_BYTES = 65536


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _diag(code: str, message: str, path: str | None = None) -> dict[str, str]:
    payload = {"severity": "error", "code": code, "message": message}
    if path is not None:
        payload["path"] = path
    return payload


def _occurrence_positions(haystack: str, needle: str) -> list[int]:
    positions: list[int] = []
    offset = 0
    while offset <= len(haystack) - len(needle):
        found = haystack.find(needle, offset)
        if found < 0:
            break
        positions.append(found)
        offset = found + max(1, len(needle))
    return positions


@dataclass
class _Capture:
    chunks: list[bytes] = field(default_factory=list)
    bytes: int = 0
    truncated: bool = False
    text: str = ""
    decoder: Any = field(default_factory=lambda: codecs.getincrementaldecoder("utf-8")(errors="replace"))

    def full_text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")


@dataclass
class _MarkerState:
    declaration: dict[str, Any]
    phase: str  # "progress" | "completion"
    declaration_index: int
    occurrences: list[dict[str, int]] = field(default_factory=list)


@dataclass
class _InteractionState:
    declaration: dict[str, Any]
    result: dict[str, Any]
    thread: threading.Thread | None = None
    started: bool = False
    settled: bool = False


@dataclass
class _Failure:
    diagnostic: dict[str, str]
    timeout_stage: str | None = None
    output_limit: str | None = None


def _marker_observation(state: _MarkerState) -> dict[str, Any]:
    declaration = state.declaration
    if state.phase == "progress":
        expected: dict[str, int] = {"minimumCount": declaration["minimumCount"]}
        passed = len(state.occurrences) >= declaration["minimumCount"]
    else:
        expected = {"exactCount": declaration["exactCount"]}
        passed = len(state.occurrences) == declaration["exactCount"]
    return {
        "id": declaration["id"],
        "phase": state.phase,
        "stream": declaration["stream"],
        "contains": declaration["contains"],
        "expected": expected,
        "observedCount": len(state.occurrences),
        "passed": passed,
        "occurrences": [dict(occurrence) for occurrence in state.occurrences],
    }


def _marker_count_diagnostics(states: list[_MarkerState]) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    for state in states:
        observed = len(state.occurrences)
        marker_id = state.declaration["id"]
        if state.phase == "progress":
            expected = state.declaration["minimumCount"]
            if observed < expected:
                diagnostics.append(
                    _diag(
                        "runtime_progress_marker_missing",
                        f"Progress marker '{marker_id}' occurred {observed} time(s); at least {expected} required.",
                        f"proof.progress.{marker_id}",
                    )
                )
        else:
            expected = state.declaration["exactCount"]
            if observed == 0:
                diagnostics.append(
                    _diag(
                        "required_marker_missing",
                        f"Completion marker '{marker_id}' did not occur; exactly {expected} required.",
                        f"proof.completion.{marker_id}",
                    )
                )
            elif observed != expected:
                diagnostics.append(
                    _diag(
                        "required_marker_count_mismatch",
                        f"Completion marker '{marker_id}' occurred {observed} time(s); exactly {expected} required.",
                        f"proof.completion.{marker_id}",
                    )
                )
    return diagnostics


def _marker_order_diagnostics(states: list[_MarkerState]) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    completion = [state for state in states if state.phase == "completion"]
    for index in range(1, len(completion)):
        previous = completion[index - 1].occurrences[0] if completion[index - 1].occurrences else None
        current = completion[index].occurrences[0] if completion[index].occurrences else None
        if previous and current and current["sequence"] <= previous["sequence"]:
            diagnostics.append(
                _diag(
                    "required_marker_out_of_order",
                    f"Completion marker '{completion[index].declaration['id']}' was observed before "
                    f"'{completion[index - 1].declaration['id']}'.",
                    f"proof.completion.{completion[index].declaration['id']}",
                )
            )
    return diagnostics


def _completion_satisfied(states: list[_MarkerState]) -> bool:
    return all(
        len(state.occurrences) == state.declaration["exactCount"] for state in states if state.phase == "completion"
    )


def _first_occurrence_elapsed(state: _MarkerState | None) -> int | None:
    if state and state.occurrences:
        return state.occurrences[0]["elapsedMs"]
    return None


def _synthetic_process(request: ProcessExecutionRequest, cause: str, code: str | None = None) -> ProcessResult:
    return ProcessResult(
        command=list(request.command),
        working_directory=request.working_directory,
        limits=request.limits,
        duration_ms=0,
        termination="spawn_error",
        exit_code=None,
        signal=None,
        timed_out=False,
        output_limit_exceeded=[],
        spawn_error=ProcessSpawnError(message=cause, code=code),
    )


def _signal_name(signum: int) -> str:
    try:
        return signal_module.Signals(signum).name
    except ValueError:
        return f"SIG{signum}"


def _interaction_evidence_diagnostics(state: _InteractionState, session_id: str) -> list[dict[str, str]]:
    """Evidence-vs-declaration checks once structured evidence exists."""
    declaration = state.declaration
    result = state.result
    evidence = result["evidence"]
    diagnostics: list[dict[str, str]] = []
    if evidence["sessionId"] != session_id:
        diagnostics.append(
            _diag(
                "runtime_interaction_session_mismatch",
                f"Interaction '{declaration['id']}' reported session '{evidence['sessionId']}' instead of '{session_id}'.",
            )
        )
    if evidence["actionId"] != declaration["id"]:
        diagnostics.append(
            _diag(
                "runtime_interaction_action_mismatch",
                f"Interaction evidence action '{evidence['actionId']}' does not match '{declaration['id']}'.",
            )
        )
    if not evidence["attempted"]:
        diagnostics.append(_diag("runtime_interaction_not_attempted", f"Interaction '{declaration['id']}' was not attempted."))
    if not evidence["reachedSeam"]:
        diagnostics.append(
            _diag("runtime_interaction_seam_not_reached", f"Interaction '{declaration['id']}' did not reach the declared production seam.")
        )
    opening = result.get("openingObservedAtMs")
    closing = result.get("closingObservedAtMs")
    delivered = evidence["deliveredAtMs"]
    outside_window = opening is not None and closing is not None and (delivered < opening or delivered >= closing)
    if outside_window:
        diagnostics.append(
            _diag(
                "runtime_interaction_timing_mismatch",
                f"Interaction '{declaration['id']}' was delivered at {delivered} ms outside the required "
                f"[{opening}, {closing}) ms window.",
            )
        )
    invoked = result.get("invokedAtMs")
    if not outside_window and invoked is not None and delivered < invoked:
        diagnostics.append(
            _diag(
                "runtime_interaction_timing_mismatch",
                f"Interaction '{declaration['id']}' reported delivery at {delivered} ms before its provider was invoked at {invoked} ms.",
            )
        )
    counts: dict[str, int] = {}
    for assertion in evidence["assertions"]:
        counts[assertion["id"]] = counts.get(assertion["id"], 0) + 1
        if not assertion["passed"]:
            diagnostics.append(
                _diag("runtime_interaction_assertion_failed", f"Interaction assertion '{assertion['id']}' failed for '{declaration['id']}'.")
            )
    for required in declaration["requiredAssertions"]:
        count = counts.get(required, 0)
        if count != 1:
            diagnostics.append(
                _diag(
                    "runtime_interaction_assertion_missing",
                    f"Interaction '{declaration['id']}' requires exactly one '{required}' assertion; observed {count}.",
                )
            )
    return diagnostics


def _finalize_interaction(state: _InteractionState, session_id: str, markers_by_id: dict[str, _MarkerState]) -> None:
    declaration = state.declaration
    result = state.result
    opening = _first_occurrence_elapsed(markers_by_id.get(declaration["opensAfter"]))
    closing = _first_occurrence_elapsed(markers_by_id.get(declaration["closesBefore"]))
    if opening is not None:
        result["openingObservedAtMs"] = opening
    if closing is not None:
        result["closingObservedAtMs"] = closing
    if opening is None:
        result["diagnostics"].append(
            _diag(
                "runtime_interaction_opening_milestone_missing",
                f"Interaction '{declaration['id']}' opening milestone '{declaration['opensAfter']}' was not observed.",
            )
        )
    if closing is None:
        result["diagnostics"].append(
            _diag(
                "runtime_interaction_closing_milestone_missing",
                f"Interaction '{declaration['id']}' closing milestone '{declaration['closesBefore']}' was not observed.",
            )
        )
    if not result.get("evidence"):
        if not result["diagnostics"]:
            result["diagnostics"].append(
                _diag("runtime_interaction_evidence_missing", f"Interaction '{declaration['id']}' returned no structured evidence.")
            )
        result["status"] = "failed"
        return
    result["diagnostics"].extend(_interaction_evidence_diagnostics(state, session_id))
    result["status"] = "passed" if not result["diagnostics"] else "failed"


@dataclass(frozen=True)
class RuntimeSessionProviderResult:
    """What the acceptance service consumes: a process record and JSON-safe session evidence."""

    process: ProcessResult
    runtime_session: dict[str, Any]


class ProcessLifecycleRuntimeProvider:
    """Supervises one declared runtime session against its full lifecycle contract."""

    id = PROCESS_LIFECYCLE_RUNTIME_PROVIDER

    def __init__(
        self,
        *,
        launcher: Any | None = None,
        interactions: RuntimeInteractionProviderRegistry | None = None,
        capabilities: RuntimeHostCapabilityRegistry | None = None,
        process_tree_factory: Any | None = None,
    ) -> None:
        self._launcher = launcher if launcher is not None else ScriptRuntimeProcessLauncher()
        self._interactions = interactions if interactions is not None else create_default_runtime_interaction_registry()
        self._capabilities = capabilities if capabilities is not None else create_default_runtime_host_capabilities()
        if self._launcher.pty_available:
            self._capabilities.add("stdio:pty")
        self._tree_factory = process_tree_factory or OwnedProcessTree

    def run(self, *, check: ResolvedValidation, request: ProcessExecutionRequest) -> RuntimeSessionProviderResult:
        proof = check.proof or {}
        gap = self._capability_gap(proof, request)
        if gap is not None:
            return gap
        return _LifecycleSession(self, proof, request).run()

    def _capability_gap(self, proof: dict[str, Any], request: ProcessExecutionRequest) -> RuntimeSessionProviderResult | None:
        required = [*proof.get("requiredCapabilities", []), "stdio:pty" if proof.get("stdioMode") == "pty" else "stdio:pipe"]
        missing = self._capabilities.missing(required)
        if not missing:
            return None
        joined = ", ".join(missing)
        gap = _diag(
            "BLOCKING_REQUIRED_PROOF_GAP",
            f"Applicable runtime proof '{proof.get('entryPoint')}' requires unavailable host capability: {joined}.",
            "proof.requiredCapabilities",
        )
        return RuntimeSessionProviderResult(
            process=_synthetic_process(request, f"Runtime host capability unavailable: {joined}", "RUNTIME_CAPABILITY_UNAVAILABLE"),
            runtime_session={"provider": self.id, "status": "failed", "proof": proof, "diagnostics": [gap]},
        )


class _LifecycleSession:
    """One bounded supervision run; all mutable state lives here."""

    def __init__(self, provider: ProcessLifecycleRuntimeProvider, proof: dict[str, Any], request: ProcessExecutionRequest) -> None:
        self._provider_id = provider.id
        self._launcher = provider._launcher
        self._interactions_registry = provider._interactions
        self._tree_factory = provider._tree_factory
        self._proof = proof
        self._request = request
        self._timeouts: dict[str, int] = proof["timeouts"]
        self._bounded = proof["lifecycle"] == "bounded"
        self._session_id = str(uuid.uuid4())
        self._started_epoch_ms = _epoch_ms()
        self._lock = threading.Lock()
        self._stdout = _Capture()
        self._stderr = _Capture()
        self._capture_done: dict[str, threading.Event] = {"stdout": threading.Event(), "stderr": threading.Event()}
        progress = proof["progress"]
        self._marker_states = [
            *(_MarkerState(declaration=marker, phase="progress", declaration_index=index) for index, marker in enumerate(progress)),
            *(
                _MarkerState(declaration=marker, phase="completion", declaration_index=len(progress) + index)
                for index, marker in enumerate(proof["completion"])
            ),
        ]
        self._markers_by_id = {state.declaration["id"]: state for state in self._marker_states}
        self._marker_sequence = 0
        self._last_output_epoch_ms = self._started_epoch_ms
        self._output_failure: _Failure | None = None
        self._interaction_states = [
            _InteractionState(
                declaration=declaration,
                result={
                    "id": declaration["id"],
                    "provider": declaration["provider"],
                    "opensAfter": declaration["opensAfter"],
                    "closesBefore": declaration["closesBefore"],
                    "status": "failed",
                    "diagnostics": [],
                },
            )
            for declaration in proof["interactions"]
        ]
        self._proc: Any = None
        self._tree: OwnedProcessTree | None = None
        self._parent_exited = False
        self._exit_code: int | None = None
        self._signal: str | None = None
        self._failure: _Failure | None = None
        self._startup_observed_ms: int | None = None
        self._completion_observed_ms: int | None = None
        self._teardown_attempted = False
        self._teardown_started_ms: int | None = None
        self._teardown_completed_ms: int | None = None
        self._teardown_passed = self._bounded
        self._termination_actions: list[dict[str, Any]] = []
        self._last_tree_poll_ms = 0

    # ---- lifecycle -----------------------------------------------------------

    def run(self) -> RuntimeSessionProviderResult:
        spawn_failure = self._launch()
        if spawn_failure is not None:
            return spawn_failure
        self._start_capture_threads()
        self._loop()
        self._await_interactions()
        for state in self._interaction_states:
            _finalize_interaction(state, self._session_id, self._markers_by_id)
        diagnostics = self._collect_diagnostics()
        self._cleanup(diagnostics)
        tree_evidence = self._tree_evidence(diagnostics)
        return self._result(diagnostics, tree_evidence)

    def _launch(self) -> RuntimeSessionProviderResult | None:
        try:
            self._proc = self._launcher.launch(
                RuntimeLaunchRequest(argv=list(self._request.command), cwd=self._request.working_directory, stdio_mode=self._proof["stdioMode"])
            )
        except Exception as cause:
            message = str(cause) or type(cause).__name__
            failure = _diag("runtime_spawn_failed", f"Could not start runtime session: {message}")
            return RuntimeSessionProviderResult(
                process=_synthetic_process(self._request, message),
                runtime_session={"provider": self._provider_id, "status": "failed", "proof": self._proof, "diagnostics": [failure]},
            )
        self._tree = self._tree_factory(self._proc.pid, self._started_epoch_ms)
        return None

    def _loop(self) -> None:
        while self._failure is None:
            now = _epoch_ms()
            duration = now - self._started_epoch_ms
            self._poll_process_state()
            self._poll_tree(now)
            self._start_eligible_interactions()
            self._observe_milestones(duration)
            self._failure = self._stage_failure(duration, now)
            if self._failure is not None:
                break
            self._settle_unstarted_interactions()
            if self._teardown_due():
                self._attempt_teardown()
                if self._failure is not None:
                    break
            if self._exit_ready():
                break
            if self._failure is not None:
                break
            time.sleep(_POLL_INTERVAL_S)

    # ---- process observation -------------------------------------------------

    def _poll_process_state(self) -> None:
        returncode = self._proc.poll()
        if returncode is None or self._parent_exited:
            return
        self._parent_exited = True
        if returncode < 0:
            self._signal = _signal_name(-returncode)
            self._exit_code = None
        else:
            self._exit_code = returncode
        if self._tree is not None:
            self._tree.record_parent_exit()

    def _poll_tree(self, now: int) -> None:
        if self._tree is not None and now - self._last_tree_poll_ms >= _TREE_POLL_INTERVAL_MS:
            self._tree.snapshot()
            self._last_tree_poll_ms = now

    def _child_closed(self) -> bool:
        return self._parent_exited and self._capture_done["stdout"].is_set() and self._capture_done["stderr"].is_set()

    # ---- output capture and marker scanning ----------------------------------

    def _start_capture_threads(self) -> None:
        specs = (
            ("stdout", self._proc.stdout, self._stdout, self._request.limits.stdout_bytes),
            ("stderr", self._proc.stderr, self._stderr, self._request.limits.stderr_bytes),
        )
        for stream, raw, state, maximum in specs:
            if raw is None:
                self._capture_done[stream].set()
                continue
            thread = threading.Thread(target=self._drain, args=(stream, raw, state, maximum), daemon=True)
            thread.start()

    def _drain(self, stream: str, raw: Any, state: _Capture, maximum: int) -> None:
        fd = raw.fileno()
        while True:
            try:
                chunk = os.read(fd, _READ_CHUNK_BYTES)
            except OSError:
                break
            if not chunk:
                break
            self._capture(stream, state, maximum, chunk)
        with contextlib.suppress(Exception):
            raw.close()
        self._capture_done[stream].set()

    def _capture(self, stream: str, state: _Capture, maximum: int, chunk: bytes) -> None:
        with self._lock:
            self._last_output_epoch_ms = _epoch_ms()
            remaining = max(0, maximum - state.bytes)
            if remaining > 0:
                retained = chunk[:remaining]
                state.chunks.append(retained)
                state.bytes += len(retained)
                state.text += state.decoder.decode(retained)
                self._scan_markers(stream, state.text)
            if len(chunk) > remaining and self._output_failure is None:
                state.truncated = True
                self._output_failure = _Failure(
                    _diag("runtime_output_limit", f"Runtime session exceeded its {stream} capture limit."), output_limit=stream
                )

    def _scan_markers(self, stream: str, text: str) -> None:
        candidates: list[tuple[int, int, _MarkerState]] = []
        for state in self._marker_states:
            if state.declaration["stream"] != stream:
                continue
            positions = _occurrence_positions(text, state.declaration["contains"])
            candidates.extend((offset, state.declaration_index, state) for offset in positions[len(state.occurrences):])
        candidates.sort(key=lambda entry: (entry[0], entry[1]))
        now = _epoch_ms() - self._started_epoch_ms
        for offset, _, state in candidates:
            state.occurrences.append({"elapsedMs": now, "offset": offset, "sequence": self._marker_sequence})
            self._marker_sequence += 1

    def _observe_milestones(self, duration: int) -> None:
        with self._lock:
            if self._startup_observed_ms is None:
                for marker in self._proof["progress"]:
                    first = _first_occurrence_elapsed(self._markers_by_id.get(marker["id"]))
                    if first is not None:
                        self._startup_observed_ms = first
                        break
            if self._completion_observed_ms is None and _completion_satisfied(self._marker_states):
                self._completion_observed_ms = duration

    # ---- failure stages ------------------------------------------------------

    def _stage_failure(self, duration: int, now: int) -> _Failure | None:
        timeouts = self._timeouts
        if self._output_failure is not None:
            return self._output_failure
        if self._startup_observed_ms is None and duration >= timeouts["startupTimeoutMs"]:
            return _Failure(
                _diag("runtime_startup_timeout", f"Runtime emitted no declared progress within {timeouts['startupTimeoutMs']} ms."),
                timeout_stage="startup",
            )
        if self._completion_observed_ms is None and now - self._last_output_epoch_ms >= timeouts["progressSilenceMs"]:
            return _Failure(
                _diag(
                    "runtime_progress_silence_timeout",
                    f"Runtime produced no output for {timeouts['progressSilenceMs']} ms before completion.",
                ),
                timeout_stage="progress_silence",
            )
        if self._completion_observed_ms is None and duration >= timeouts["completionTimeoutMs"]:
            return _Failure(
                _diag(
                    "runtime_completion_timeout",
                    f"Runtime did not reach its declared success condition within {timeouts['completionTimeoutMs']} ms.",
                ),
                timeout_stage="completion",
            )
        if duration >= timeouts["hardTimeoutMs"]:
            return _Failure(
                _diag("runtime_hard_timeout", f"Runtime exceeded its {timeouts['hardTimeoutMs']} ms hard limit."),
                timeout_stage="hard_limit",
            )
        if self._child_closed() and self._completion_observed_ms is None:
            return _Failure(
                _diag("exit_before_required_completion", "Runtime parent exited before every required completion marker was observed.")
            )
        if (
            self._bounded
            and self._completion_observed_ms is not None
            and not self._parent_exited
            and duration - self._completion_observed_ms >= timeouts["completionToExitGraceMs"]
        ):
            return _Failure(
                _diag(
                    "success_reported_but_process_resident",
                    f"Runtime reported terminal success but remained resident beyond its "
                    f"{timeouts['completionToExitGraceMs']} ms completion-to-exit grace.",
                ),
                timeout_stage="completion_to_exit",
            )
        return None

    # ---- interactions --------------------------------------------------------

    def _start_eligible_interactions(self) -> None:
        for state in self._interaction_states:
            if state.started:
                continue
            with self._lock:
                opening = _first_occurrence_elapsed(self._markers_by_id.get(state.declaration["opensAfter"]))
                closing = _first_occurrence_elapsed(self._markers_by_id.get(state.declaration["closesBefore"]))
                milestones = [_marker_observation(marker) for marker in self._marker_states]
            if opening is None:
                continue
            state.started = True
            if closing is not None:
                state.result["diagnostics"].append(
                    _diag(
                        "runtime_interaction_timing_mismatch",
                        f"Interaction '{state.declaration['id']}' could not be invoked because its window closed at "
                        f"{closing} ms before dispatch.",
                    )
                )
                state.result["completedAtMs"] = self._elapsed()
                state.settled = True
                continue
            state.result["invokedAtMs"] = self._elapsed()
            provider = self._interactions_registry.get(state.declaration["provider"])
            if provider is None:
                state.result["diagnostics"].append(
                    _diag(
                        "runtime_interaction_provider_unsupported",
                        f"No runtime interaction provider is registered for '{state.declaration['provider']}'.",
                    )
                )
                state.result["completedAtMs"] = self._elapsed()
                state.settled = True
                continue
            state.thread = threading.Thread(target=self._invoke_interaction, args=(state, provider, milestones), daemon=True)
            state.thread.start()

    def _invoke_interaction(self, state: _InteractionState, provider: Any, milestones: list[dict[str, Any]]) -> None:
        try:
            evidence = provider.invoke(
                RuntimeInteractionProviderRequest(
                    session_id=self._session_id,
                    session_started_at_epoch_ms=self._started_epoch_ms,
                    action=state.declaration,
                    cwd=self._request.working_directory,
                    limits=self._request.limits,
                    milestones=milestones,
                )
            )
            state.result["evidence"] = evidence
        except Exception as cause:
            state.result["diagnostics"].append(
                _diag(
                    "runtime_interaction_provider_failed",
                    f"Interaction provider '{state.declaration['provider']}' failed: {str(cause) or type(cause).__name__}",
                )
            )
        finally:
            state.result["completedAtMs"] = self._elapsed()
            state.settled = True

    def _settle_unstarted_interactions(self) -> None:
        if not self._child_closed():
            return
        for state in self._interaction_states:
            if not state.started:
                state.settled = True

    def _all_interactions_settled(self) -> bool:
        return all(state.settled for state in self._interaction_states)

    def _await_interactions(self) -> None:
        timeout_s = max(1, self._timeouts["teardownGraceMs"]) / 1000
        for state in self._interaction_states:
            if state.thread is not None:
                state.thread.join(timeout_s)

    # ---- teardown and exit ---------------------------------------------------

    def _teardown_due(self) -> bool:
        return (
            not self._bounded
            and self._completion_observed_ms is not None
            and self._all_interactions_settled()
            and not self._teardown_attempted
        )

    def _attempt_teardown(self) -> None:
        self._teardown_attempted = True
        self._teardown_started_ms = self._elapsed()
        teardown = self._proof.get("teardown")
        provider_name = teardown.get("provider") if teardown else None
        if provider_name != OWNED_PROCESS_SIGNAL_TEARDOWN_PROVIDER:
            self._failure = _Failure(
                _diag(
                    "runtime_teardown_provider_unsupported",
                    f"Runtime teardown provider '{provider_name or 'missing'}' is not supported by '{self._provider_id}'.",
                )
            )
            return
        if (teardown.get("request") or {}).get("signal") != "SIGTERM":
            self._failure = _Failure(
                _diag("runtime_teardown_request_malformed", "owned-process-signal-v1 teardown requires request.signal to be 'SIGTERM'.")
            )
            return
        if self._tree is None:
            self._failure = _Failure(
                _diag("runtime_teardown_unavailable", "Runtime controller could not establish an owned process tree for teardown.")
            )
            return
        remaining = self._tree.terminate(self._timeouts["teardownGraceMs"], self._termination_actions)
        with contextlib.suppress(Exception):
            self._proc.wait(timeout=2)
        self._teardown_completed_ms = self._elapsed()
        self._teardown_passed = not remaining
        if remaining:
            self._failure = _Failure(
                _diag("runtime_teardown_incomplete", f"Controller teardown left owned process IDs resident: {', '.join(map(str, remaining))}."),
                timeout_stage="teardown",
            )

    def _exit_ready(self) -> bool:
        if self._failure is not None or not self._parent_exited or self._completion_observed_ms is None:
            return False
        if not self._all_interactions_settled():
            return False
        remaining = self._tree.snapshot() if self._tree is not None else []
        if self._proof["requireNoDescendants"] and remaining:
            descendants = [pid for pid in remaining if pid != self._proc.pid]
            if descendants or self._proc.pid in remaining:
                self._failure = _Failure(
                    _diag(
                        "owned_descendant_resident",
                        f"Runtime parent exited while owned process IDs remained resident: {', '.join(map(str, remaining))}.",
                    )
                )
            return False
        return self._child_closed() and (self._bounded or self._teardown_attempted)

    # ---- results -------------------------------------------------------------

    def _collect_diagnostics(self) -> list[dict[str, str]]:
        diagnostics: list[dict[str, str]] = []
        if self._failure is not None:
            diagnostics.append(self._failure.diagnostic)
        diagnostics.extend(_marker_count_diagnostics(self._marker_states))
        diagnostics.extend(_marker_order_diagnostics(self._marker_states))
        for state in self._interaction_states:
            diagnostics.extend(state.result["diagnostics"])
        if self._parent_exited and self._exit_code != self._proof["requireExitCode"]:
            exit_text = "none" if self._exit_code is None else str(self._exit_code)
            diagnostics.append(
                _diag("runtime_exit_code_mismatch", f"Runtime exit code was {exit_text}; expected {self._proof['requireExitCode']}.")
            )
        if self._signal and self._failure is None:
            diagnostics.append(_diag("runtime_unexpected_signal", f"Runtime terminated by signal {self._signal}."))
        return diagnostics

    def _cleanup(self, diagnostics: list[dict[str, str]]) -> None:
        if self._tree is not None and (self._failure is not None or diagnostics):
            remaining = self._tree.terminate(self._timeouts["teardownGraceMs"], self._termination_actions)
            with contextlib.suppress(Exception):
                self._proc.wait(timeout=2)
            if remaining:
                diagnostics.append(
                    _diag("runtime_cleanup_incomplete", f"Runtime cleanup could not terminate owned process IDs: {', '.join(map(str, remaining))}.")
                )
        if self._tree is not None and self._tree.errors:
            diagnostics.append(
                _diag(
                    "runtime_process_tree_observation_failed",
                    f"Could not fully observe the owned process tree: {'; '.join(self._tree.errors)}",
                )
            )

    def _tree_evidence(self, diagnostics: list[dict[str, str]]) -> dict[str, Any]:
        if self._tree is not None:
            evidence = self._tree.evidence()
        else:
            evidence = {
                "parentPid": None,
                "processGroupId": None,
                "observedPids": [],
                "observedDescendantPids": [],
                "remainingPids": [],
                "noOwnedProcessesRemain": True,
            }
        if (
            self._proof["requireNoDescendants"]
            and not evidence["noOwnedProcessesRemain"]
            and not any(entry["code"] == "runtime_cleanup_incomplete" for entry in diagnostics)
        ):
            diagnostics.append(
                _diag("runtime_cleanup_incomplete", f"Owned process IDs remain resident: {', '.join(map(str, evidence['remainingPids']))}.")
            )
        return evidence

    def _elapsed(self) -> int:
        return _epoch_ms() - self._started_epoch_ms

    def _result(self, diagnostics: list[dict[str, str]], tree_evidence: dict[str, Any]) -> RuntimeSessionProviderResult:
        with self._lock:
            milestones = [_marker_observation(state) for state in self._marker_states]
        evidence: dict[str, Any] = {
            "sessionId": self._session_id,
            "provider": self._provider_id,
            "proof": self._proof,
            "argv": list(self._request.command),
            "cwd": self._request.working_directory,
            "durationMs": self._elapsed(),
            "milestones": milestones,
            "interactions": [state.result for state in self._interaction_states],
            "processTree": tree_evidence,
            "terminationActions": self._termination_actions,
            "teardown": self._teardown_evidence(),
        }
        if self._startup_observed_ms is not None:
            evidence["startupObservedAtMs"] = self._startup_observed_ms
        if self._completion_observed_ms is not None:
            evidence["completionObservedAtMs"] = self._completion_observed_ms
        if self._failure is not None and self._failure.timeout_stage:
            evidence["timeoutStage"] = self._failure.timeout_stage
        return RuntimeSessionProviderResult(
            process=self._process_result(),
            runtime_session={
                "provider": self._provider_id,
                "status": "passed" if not diagnostics else "failed",
                "proof": self._proof,
                "evidence": evidence,
                "diagnostics": diagnostics,
            },
        )

    def _teardown_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"required": not self._bounded}
        teardown = self._proof.get("teardown")
        if teardown:
            payload["provider"] = teardown["provider"]
        if self._teardown_started_ms is not None:
            payload["startedAtMs"] = self._teardown_started_ms
        if self._teardown_completed_ms is not None:
            payload["completedAtMs"] = self._teardown_completed_ms
        payload["passed"] = self._teardown_passed
        return payload

    def _process_result(self) -> ProcessResult:
        timeout_stage = self._failure.timeout_stage if self._failure is not None else None
        output_limit = self._failure.output_limit if self._failure is not None else None
        if timeout_stage:
            termination = "timed_out"
        elif output_limit:
            termination = "output_limit"
        elif self._signal:
            termination = "signaled"
        else:
            termination = "exited"
        return ProcessResult(
            command=list(self._request.command),
            working_directory=self._request.working_directory,
            limits=self._request.limits,
            duration_ms=self._elapsed(),
            termination=termination,
            exit_code=self._exit_code,
            signal=self._signal,
            timed_out=timeout_stage is not None,
            output_limit_exceeded=[output_limit] if output_limit else [],
            spawn_error=None,
            stdout=self._stdout.full_text(),
            stderr=self._stderr.full_text(),
            stdout_truncated=self._stdout.truncated,
            stderr_truncated=self._stderr.truncated,
        )
