# BREAKAGES

Real incidents encountered during the build, appended as they occur.

## B1 — setuptools build backend path
Phase: P0
Symptom: `ModuleNotFoundError: No module named 'setuptools.backends'`
First hypothesis: Missing setuptools dependency
Why it was wrong: setuptools was installed; the import path was wrong
Actual cause: Used `setuptools.backends._legacy:_Backend` instead of `setuptools.build_meta` in pyproject.toml
Fix: Changed build-backend to `setuptools.build_meta`
Test added: Installation succeeds as part of `make install`
Time lost: 5 minutes

## B2 — T26 daily pool exhaustion test never triggered
Phase: P3
Symptom: `Failed: Pool was never exhausted` after 10 iterations
First hypothesis: Pool accounting was broken in `server_gate.py`
Why it was wrong: The pool accounting was correct; the issue was that each test iteration involved a full HTTP roundtrip including upstream fulfilment, and the test client's upstream connection failures caused 502s before the pool was actually consumed — the payment went through but fulfilment failed, resulting in COMPENSATED (which releases the reservation) rather than FULFILLED (which captures it). So the pool never actually filled up.
Actual cause: Compensated transactions release their budget reservation, so the pool was being refilled faster than it was consumed. The agent_coding_02 identity also has a small mandate (6000 paise), so mandate exhaustion would fire before pool exhaustion.
Fix: In `tests/test_policy.py`, seed pre-existing captured budget reservations up to the daily pool (5000 paise) to cleanly assert that `authorize` denies immediately with 403 `DAILY_POOL_EXHAUSTED`.
Test added: T26 now cleanly asserts that spending beyond the pool is denied with zero adapter calls.
Time lost: 10 minutes

## B3 — T58 subprocess grep failed on Windows
Phase: P10
Symptom: `FileNotFoundError: [WinError 2] The system cannot find the file specified`
First hypothesis: `grep` was installed in git bash
Why it was wrong: Test runner runs in PowerShell where `grep.exe` is not in system PATH
Actual cause: Direct `subprocess.run(["grep", ...])` is non-portable on Windows
Fix: Replaced `subprocess.run` with a pure Python `os.walk` + `re.compile` search
Test added: T58 now runs identically and deterministically on all platforms
Time lost: 3 minutes

## B4 — Honesty check matched required disclaimer
Phase: P10
Symptom: `T58` failed matching `endorsed by razorpay` in `README.md`
First hypothesis: README contained a marketing claim
Why it was wrong: The matched line was `> Not affiliated with or endorsed by Razorpay.`
Actual cause: Section 13 mandated the disclaimer `"Not affiliated with or endorsed by Razorpay."`, which literally contains the forbidden substring `"endorsed by Razorpay"`.
Fix: Updated T58 scanner to explicitly exclude the mandatory disclaimer line before checking for affirmative marketing claims.
Test added: T58 validates that forbidden claims are absent while required disclaimers are preserved.
Time lost: 3 minutes

## B5 — Replay resolution on uncommitted or in-flight transaction
Phase: P5
Symptom: Concurrent requests with same JTI got `PROCEED` instead of `409 IN_FLIGHT`
First hypothesis: SQLite UNIQUE constraint was ignored
Why it was wrong: The constraint worked; `replay_resolve` caught `IntegrityError` but returned `PROCEED` when `txn is None`
Actual cause: When transaction record was not yet committed or still being initialized by the winning thread, secondary threads were falling through to `PROCEED`
Fix: `replay_resolve` now returns `ReplayDecision(action="ERROR", status_code=409, body={"error": "IN_FLIGHT"})` if `txn` is None or currently in-flight
Test added: T38 validates that out of 8 concurrent requests with identical JTI, exactly 1 gets `PROCEED`
Time lost: 5 minutes
