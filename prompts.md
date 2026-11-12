SimAPI prompts — copy-paste fixes and features
How to use this file: each prompt is ready to paste into an AI coding
assistant (Claude Code, Codex, Cursor...) working inside the simapi repo.
Don't edit the prompt text — the file names, line numbers and acceptance
criteria are the important part. Run the repo tests after each one.
Plain words: "acceptance criteria" = how you know the job is actually done.

Part 1 — Fix-it prompts (problems found in the code)
1a. Robotics fast path — stop running 4 engines for a robot question
The problem: In api/server.py, _validate_core (line ~857), a
simulation_type=robotics request runs the dimensional engine, the
robotics engine (line ~891), the legacy physics validator, AND APIE.
Three of those are general-simulation machinery the robotics user never
asked for, and their opinions get merged into the robotics verdict.
Slow, and confusing to explain.
Prompt:
In api/server.py, look at _validate_core and the robotics branch
(req.simulation_type == SimulationType.ROBOTICS).

Change the flow for robotics requests so that:
1. The robotics engine (ROBOTICS_ENGINE.validate) runs FIRST and its
   result is the source of truth for status / training_ready /
   exclusions in the response — the same way the dimensional engine is
   the source of truth for non-robotics requests today.
2. The dimensional engine and APIE only run for a robotics request when
   the caller opts in with a new boolean request field `run_general`
   (default False). The legacy physics block must never change a
   robotics verdict (keep it, clearly labelled as comparison-only).
3. Non-robotics requests must behave exactly as they do today.

Then measure: add a small benchmark script (or extend benchmark/) that
validates the same robotics payload before/after (use git stash to get
the "before" number) and prints median latency for both. Print the
results in your summary.

Rules: do not change the response JSON field names. Do not touch
core/robotics_engine.py or core/robotics_trajectory.py.
Acceptance criteria:
Robotics response verdict comes only from the robotics engine unless run_general: true.
Same robotics payload returns the same robotics_checks / exclusions as before the change.
pytest tests/test_robotics_*.py tests/test_api.py passes.
Benchmark shows before/after median latency numbers in the summary.

1b. Wide default limits — warn loudly or require a profile
The problem: core/robotics_engine.py, DEFAULT_ROBOTICS_LIMITS
(line ~20): joint_torque ±100,000, joint_velocity ±500, joint_position
±4π. These are "is this number insane?" screens, not robot limits — but
nothing in a report tells the user that. With no profile, almost
anything passes and the user thinks their data was really checked.
Prompt:
In core/robotics_engine.py, DEFAULT_ROBOTICS_LIMITS are extremely wide
screening values. Today a validation run that used them is
indistinguishable from a run that used the robot's real limits.

Change the robotics report so that:
1. robotics_summary gains "limits_source": "profile" when the caller
   supplied limits for every recognised joint signal present, "mixed"
   when they supplied some, "defaults" when they supplied none.
2. When limits_source is "defaults" or "mixed", add a top-level
   warning entry to the report: "screening defaults used for
   <signals> — supply a profile (or import a URDF) for real limits",
   naming the signals that fell back to defaults.
3. Do NOT change any verdict logic — a value that passed before still
   passes. This is honesty labelling, not new checks.

Also add the same warning text to the CLI output path in sdk-node if
it prints report summaries.
Acceptance criteria:
Run with no limits → report shows limits_source: "defaults" + the warning.
Run with a full profile → limits_source: "profile", no warning.
All existing tests in tests/test_robotics_engine.py still pass; add one new test for each of the three limits_source values.

1c. Units in the profile — kill the degrees/radians footgun
The problem: Today the rule is "your limits must be in the same
units as your data" — pure honour system. Degrees vs radians is the #1
way robot data gets silently ruined (a limit of 1.57 rad means nothing
if the data is in degrees). The dimensional engine already converts
units for general data; the robotics path does not.
Prompt:
Add unit declarations to robotics profiles and convert on the way in.

1. A profile / robotics_limits payload may now include a sibling field
   "units": {"joint_1_position": "deg", "joint_1_velocity": "deg/s",
   "joint_1_torque": "Nm"}. Supported position units: rad, deg.
   Supported velocity units: rad/s, deg/s. Torque: Nm only (no-op).
2. In the robotics path (start from where _validate_core calls
   ROBOTICS_ENGINE.validate in api/server.py, and the shared code in
   core/robotics_engine.py), when units are declared, convert the
   affected data columns AND the matching limits to radians before any
   check runs. The report's robotics_evidence must show the converted
   (radian) values, and robotics_summary must record
   "unit_conversions": {"joint_1_position": "deg->rad"}.
3. If a units entry names a signal that is not in the data, fail the
   request with the same error shape used for other bad requests
   (see api/errors.py) — do not silently ignore it.
4. No units declared -> behaviour exactly as today.

Also accept the units field in the CLI profile file format used by
sdk-node, converting with the same rules (share the conversion helper —
put it in core/ so both paths use one implementation).
Acceptance criteria:
Data in degrees with units: {joint_1_position: "deg"} and limits in radians gives the SAME verdict and exclusions as the equivalent all-radians data.
Evidence values are in radians; summary lists the conversion.
New tests: deg→rad equivalence test, unknown-signal units error test.
All existing robotics tests still pass.

1d. Vectorize the trajectory checker — same answers, much faster
The problem: core/robotics_trajectory.py loops in Python over
every pair of rows for every joint column (see the pair loops around
lines ~60–125). Fine at the current 10,000-sample API cap; it will
crawl on real robot logs (a 100 Hz arm makes 10,000 samples in
100 seconds).
Prompt:
Rewrite the internals of core/robotics_trajectory.py
(analyze_trajectories) using pandas/numpy vectorised operations
grouped by episode, instead of Python loops over row pairs.

Hard requirements:
1. IDENTICAL results: the same checks, same check names, same failed
   indices, same summary — the existing tests are the contract.
   tests/test_robotics_trajectory.py must pass UNCHANGED, including
   the Python/hosted parity test.
2. Keep the public function signature and return shape.
3. Episodes must never be compared across boundaries (group first).
4. Add a benchmark: generate a 200,000-row, 6-joint synthetic episode
   locally, time old vs new implementation, and report the speedup in
   your summary (keep the generator script out of the repo or under
   benchmark/).
Acceptance criteria:
pytest tests/test_robotics_trajectory.py passes with zero test changes.
Benchmark shows a real speedup number (expect >10x) on 200k rows.
No new dependencies.

1e. One name for motor push: _effort vs _torque
The problem: ROS recordings come through the loaders
(integrations/ros2_loader.py, integrations/lerobot_loader.py) with
signals named joint_N_effort, while API/CSV users write
joint_N_torque. Same physical thing, two names — so a torque limit
silently doesn't apply to recording data, and a user has to know which
name their source used.
Prompt:
Unify effort/torque naming in the robotics path.

1. In core/robotics_engine.py (and the key normalisation in
   core/robotics_trajectory.py), treat a column ending in "_effort"
   as the same signal as the matching "_torque" column for limit
   lookup: if the caller configured joint_1_torque limits and the data
   has joint_1_effort, apply the limits to the effort column.
2. Reports and evidence must show the ORIGINAL column name from the
   data (don't rename the user's data) — only the limit lookup is
   aliased.
3. If BOTH joint_1_effort and joint_1_torque exist in the same data,
   check both against the limits and note the alias in the summary.
4. Update the loader docstrings in integrations/ros2_loader.py and
   the MCP/CLI docs that currently tell users to rename their limits.
Acceptance criteria:
A ROS-style row set with joint_1_effort: 95 and a configured joint_1_torque: [-70, 70] limit FAILS the limit check (before this change it passed silently).
Evidence shows joint_1_effort as the signal name.
New test in tests/test_robotics_engine.py covering the alias; all existing tests pass.

1f. Physical AI in the API report — stream sync + failure labels
The problem: The API report says pass/fail. Physical AI teams
(labs training robot AIs on episodes) need two more things SimAPI
doesn't give them today: (1) WHY an episode failed, in a fixed label
vocabulary, and (2) whether the camera/state/action clocks agree —
a sync problem teaches an AI wrong cause-and-effect while every value
still looks "in range". Reference implementations of both exist in
this bundle's physical_ai.py (episode_quality,
check_stream_sync) — port the ideas, don't reinvent them.
Prompt:
Add Physical-AI reporting to the API, reusing bundle file
physical_ai.py as the reference:

1. Add core/physical_ai.py (from the bundle) to the repo and wire it
   into api/server.py: when a robotics validation request includes
   multiple episodes, the response gains "episode_quality": the
   per-episode verdicts and failure_labels exactly as episode_quality()
   returns them. Fixed label vocabulary only (FAILURE_LABELS) — do not
   invent new labels in the API layer.
2. Add a new endpoint POST /v1/streams/sync accepting
   {"streams": {"camera": [timestamps...], "state": [...], ...},
    "tolerance_seconds": 0.05}
   and returning check_stream_sync()'s result unchanged.
3. The plain /v1/validate response shape for existing callers must not
   change: episode_quality is an ADDED field, nothing renamed/removed.
Acceptance criteria:
Multi-episode robotics request → response contains episode_quality with per-episode labels matching physical_ai.py output on the same data.
/v1/streams/sync: streams offset by +0.2s fail at tolerance 0.05; aligned streams pass.
tests/test_api.py passes; add API tests for both additions.

1g. Ship the FTC/FRC profile as a built-in
The problem: SimAPI's robotics checks only recognise arm-style
columns today, so a school robotics team (FTC/FRC) has to rename
columns and hand-write limits before anything works. This bundle's
ftc_frc.py has the school-robot logic (power range, encoder velocity
agreement, battery sag, gyro unwrap, odometry jumps).
Prompt:
Make the FTC/FRC checks a built-in profile, using bundle file
ftc_frc.py as the reference implementation.

1. Add core/ftc_frc.py (from the bundle) to the repo.
2. In the CLI (sdk-node) and the playground (web/), add a built-in
   profile named "ftc" (and an alias "frc") that: maps common FTC
   column names to the checker, uses FTC_DEFAULT_LIMITS unless the
   user overrides them, and routes validation to validate_ftc_log
   instead of the arm checker.
   Example that must work:  simapi validate drive-log.csv --profile ftc
3. The playground profile picker gains "FTC / FRC (school robotics)"
   in its list; selecting it shows the FTC limits, editable.
4. Do not change the arm ("robotics") profile behaviour in any way.
Acceptance criteria:
The example CLI command validates a sample FTC CSV (power/encoder/battery/heading columns) and flags a power value of 1.4.
A heading wrap +179 → −179 in the sample log is NOT flagged.
Existing CLI/playground behaviour for arm profiles unchanged; add a test with a small FTC fixture log.

Part 2 — Large Codex prompts — the hard stuff
These are BIG jobs: multi-file, architectural. They are written for
OpenAI Codex or a coding agent that can hold a whole plan. Each one
has the full context, the plan, the files it may and may NOT touch,
and a definition of done. Paste ONE at a time. Do not run two at once —
they touch overlapping files.

2a. Forward-kinematics consistency suite
CONTEXT — read this first.
SimAPI is a validation service for simulation / robotics data: callers
POST tables of numeric samples (one row = one moment, one column = one
signal) and get back a machine-readable verdict (status,
training_ready, per-check results, excluded rows, evidence) used to
stop bad data from training an AI or moving a robot.
Key files:
- api/server.py — FastAPI app; _validate_core is the main pipeline;
  for simulation_type=robotics it merges ROBOTICS_ENGINE.validate(...).
- core/robotics_engine.py — the robotics engine. It is COMPOSABLE:
  RoboticsValidationEngine holds a list of check "suites". A suite is
  any object matching the RoboticsCheckSuite protocol (a `name` and
  `run(context) -> RoboticsSuiteResult{checks, excluded, summary}`).
  Today two suites ship: SignalLimitsSuite (range checks) and
  TrajectorySuite (motion checks, in core/robotics_trajectory.py).
  The file's own docstring says dynamics/contact/sensor suites are
  meant to be added WITHOUT growing one big function.
- core/robotics_validation.py — thin backward-compatible wrapper.
- URDF import already exists on the CLI/playground side: it reads a
  robot description (XML: joints with limits, links with geometry)
  and maps joint names to signal names like joint_shoulder_position.

GOAL
Add a third suite, KinematicsSuite: use the URDF link geometry to
compute where the end-effector (hand) SHOULD be from the joint
angles (forward kinematics, "FK"), and fail samples where the
reported end-effector position disagrees beyond a tolerance.
This catches a whole class of lies the current suites cannot: every
individual value can be in range and self-consistent per-joint, while
the hand position column is simply wrong (bad sensor, wrong frame,
stale data).

PLAN
1. URDF geometry parsing: extend the existing URDF import code path
   (find it — CLI/playground side) with a parser that also returns,
   per joint: parent link, child link, origin (xyz + rpy), axis.
   Support revolute and prismatic joints; treat continuous joints as
   revolute. Fixed joints contribute their origin transform only.
2. FK computation (numpy): given a dict of joint values for one
   sample, walk the chain base->tip multiplying 4x4 transforms
   (origin * rotation-about-axis(angle) for revolute, origin *
   translation-along-axis(d) for prismatic). Return the tip position
   (x, y, z). Pure function, no engine imports — put it in a new file
   core/kinematics.py with the URDF geometry parser.
3. The suite: KinematicsSuite(urdf_geometry, joint_signal_map,
   tolerance_m). For each sample that has all mapped joint position
   columns AND reported end-effector columns (accept
   end_effector_x/y/z and end_effector_position_x/y/z), compute FK
   and compare Euclidean distance to the reported position.
   - distance > tolerance -> failed check
     "robotics_kinematics:end_effector_position", sample excluded,
     evidence carries computed vs reported position and the distance.
   - samples missing any needed column: skip silently (NOT a failure
     — FK is opt-in by supplying a URDF; absence of hand data in a
     joint-only log is normal).
   - no URDF supplied: suite is not constructed at all.
4. Wiring: RoboticsValidationEngine gains an optional suites argument
   path so _validate_core / check_robotics_limits can add
   KinematicsSuite when the request includes a URDF (accept the URDF
   as an XML string field "urdf_xml" on the validate request, parse
   once per request). Existing callers see zero change.
5. Tests with a simple 2-link planar arm (link lengths 1.0 and 1.0,
   both revolute about Z): hand-compute the expected tip position for
   at least 3 angle pairs (e.g. (0,0)->(2,0); (90deg,0)->(0,2);
   (0,90deg)->(1,1)) in the test itself, do not just snapshot the
   implementation's output.

FILES YOU MAY TOUCH
- core/kinematics.py (NEW)
- core/robotics_engine.py (add the suite class + optional wiring only)
- core/robotics_validation.py (pass-through optional arg only)
- api/server.py (accept urdf_xml, construct the suite — small change)
- the existing URDF import module (extend the parser; keep its
  current outputs identical)
- tests/test_robotics_kinematics.py (NEW)

FILES YOU MUST NOT TOUCH
- core/robotics_trajectory.py, core/dimensional/*, core/apie.py,
  core/physics_validator.py — no changes, not even formatting.
- The two existing suites' code and check names.

CONSTRAINTS
- Do NOT change the report verdict shape: same top-level fields, same
  check-name style ("robotics_<family>:<signal>"), exclusions and
  evidence in the existing formats.
- Radians everywhere internally; URDF is radians — do not add unit
  conversion in this task.
- numpy only; no new dependencies.
- All existing tests keep passing: pytest tests/ (robotics tests in
  particular) with zero modifications to existing test files.

DEFINITION OF DONE
- The 2-link arm tests pass, including one sample whose reported hand
  position is wrong by > tolerance and is excluded with evidence
  showing computed vs reported positions.
- A request without urdf_xml produces byte-identical robotics output
  to before the change.
- pytest tests/ green. Summary lists files changed and the FK maths
  used (transform order) in 5 lines or fewer.

2b. Hosted recording ingestion — .bag / .mcap / .db3 upload
CONTEXT — read this first.
SimAPI is a hosted validation API (FastAPI, api/server.py) plus local
tools. The hosted API today accepts only tabular numeric data (JSON
rows / CSV) with these limits: max 10,000 samples per request;
recording imports exist ONLY locally — integrations/ros2_loader.py
handles ROS 2 rosbag2 (.db3 folders) and integrations/lerobot_loader.py
handles LeRobot parquet datasets; both feed the same deterministic
robotics engine (core/robotics_engine.py via
core/robotics_validation.check_robotics_limits). ROS 1 .bag and
.mcap JointState reading exists in the CLI-side ingestion code
(rosbags-based; BZ2/LZ4/Zstd). api/errors.py defines the error shapes
the API returns; follow them. Recording import on the local side
accepts files up to 100 MB and REJECTS a recording whose selected
topic exceeds the sample limit instead of truncating it — keep that
honesty rule.

GOAL
Let hosted API users upload a recording and get the same robotics
validation report as if they had sent the rows: a new endpoint
POST /v1/validate/recording (multipart upload) supporting rosbag2
folders (as .zip), single .db3, .mcap, and LeRobot (single .parquet
or a .zip of a dataset folder), reusing the existing loaders.

PLAN
1. Endpoint + upload handling in api/server.py (or a new router file
   if the codebase has that pattern — check first): stream the upload
   to a temp file in chunks (never hold the whole upload in memory as
   bytes AND parsed rows at the same time); enforce the 100 MB cap
   DURING streaming and abort with the standard error shape when
   exceeded. Clean up temp files in a finally block.
2. Dispatch by content, not just extension: parquet magic bytes ->
   LeRobot path; sqlite magic -> .db3; mcap magic -> mcap reader;
   zip -> inspect entries (rosbag2 folder layout vs LeRobot layout).
   Unknown content -> 4xx with api/errors.py shape naming the
   supported formats.
3. Reuse integrations/ros2_loader.py and integrations/lerobot_loader.py
   for conversion to rows. If a loader loads everything eagerly and
   memory doubles, wrap it so rows are produced once and the raw
   buffer/temp file is released before validation runs. Do not fork
   the loaders' conversion logic into the server.
4. Enforce the 10,000-sample limit on the CONVERTED rows before
   validation: over the limit -> error response that states the
   observed count and the limit (matching how the local importer
   refuses rather than truncates). Topic selection: accept an
   optional form field topic_hint with the same semantics as the
   loaders.
5. Response: the standard validation report, plus
   "recording": {"format": ..., "rows": n, "source_name": ...}.
   robotics_limits / conditions arrive as a JSON form field and are
   parsed/validated exactly like the JSON endpoint does (share the
   parsing code — do not duplicate it).
6. Tests: build tiny synthetic fixtures IN the test (a small parquet
   via pyarrow; a small .db3 via the rosbag2 writer or sqlite fixture
   the existing loader tests use — check tests/ for the established
   pattern and reuse it). Cover: happy path each format, 100 MB cap
   logic (simulate with a lowered cap via settings, do NOT create a
   100 MB file), over-sample-limit rejection, garbage file rejection,
   missing topic.

FILES YOU MAY TOUCH
- api/server.py (endpoint only), api/errors.py (only if a new error
  code is genuinely needed — prefer existing shapes)
- api/config.py / settings (upload cap + temp dir settings)
- integrations/ros2_loader.py, integrations/lerobot_loader.py
  (streaming-friendly wrappers ONLY; conversion output must be
  byte-identical for existing inputs)
- tests/test_api_recordings.py (NEW), docs for the endpoint
  (docs-site/ page if that is where endpoints are documented)

FILES YOU MUST NOT TOUCH
- core/robotics_engine.py, core/robotics_trajectory.py,
  core/robotics_validation.py, core/dimensional/*, core/apie.py.
- The existing /v1/validate endpoints and their response shapes.

CONSTRAINTS
- Do not change the report verdict shape.
- The hosted sample/file limits stay 10,000 samples / 100 MB — same
  numbers, enforced in the new path too.
- Optional deps (rosbags, pyarrow) must stay optional: the server must
  still start and serve tabular validation on a machine without them;
  the recording endpoint returns a clear "not installed" error in
  that case (check how the codebase already handles optional
  features and follow it).
- All existing tests keep passing, unmodified.

DEFINITION OF DONE
- curl example in your summary uploading the synthetic .mcap/.parquet
  fixture and getting a robotics report with the expected verdict.
- New tests green, including cap and rejection cases; pytest tests/
  fully green.
- A short note in the summary: peak-memory approach in 3 lines (what
  is streamed, what is materialised, when the temp file dies).

2c. Sim-vs-real comparison endpoint
CONTEXT — read this first.
SimAPI validates simulation and robotics data (FastAPI in
api/server.py; robotics engine in core/robotics_engine.py, entry
point core/robotics_validation.check_robotics_limits). Physical-AI
teams train robot AIs on a MIX of simulated episodes and real-robot
episodes. Data can pass every physical check and still be useless —
or harmful — for training if the simulated data lives in a totally
different range from the real data (sim joints cruise at 3 rad/s,
real joints never pass 1 rad/s). Today SimAPI validates one dataset
at a time; there is no comparison.

GOAL
A new endpoint POST /v1/compare/sim-real that takes two datasets
(sim rows + real rows, same request/response conventions as
/v1/validate), validates BOTH with the same robotics limits, and
returns a distribution-drift report: per shared signal — range,
mean, std for sim vs real, an overlap score, and a drift flag;
plus check pass-rate comparison per dataset.

PLAN
1. Request model next to ValidateRequest in api/server.py:
   {sim_data, real_data, robotics_limits, conditions} reusing the
   existing row/limit validators — do not write parallel validation
   of limits.
2. Run check_robotics_limits on each dataset (same limits, same
   conditions). Collect per-dataset: verdict, per-check pass/fail,
   excluded count/rate.
3. Distribution comparison (new module core/sim_real.py, pure
   pandas/numpy, no API imports): for every numeric signal present in
   BOTH datasets compute min/max/mean/std per side; overlap = length
   of intersection of the two [p5, p95] ranges divided by the length
   of their union (use percentile ranges, not raw min/max — one
   outlier sample must not dominate); drift_flag when overlap < 0.5.
   Signals present on only one side are listed under
   "signals_only_in_sim" / "signals_only_in_real" (that is itself a
   finding: a signal the sim does not even produce).
4. Velocity/acceleration derived distributions: also compare the
   distributions of finite-difference velocities per joint (reuse the
   approach in core/robotics_trajectory.py conceptually; share code
   if there is a clean helper, otherwise implement in sim_real.py —
   do NOT edit robotics_trajectory.py).
5. Response shape (new top-level object, does not alter /v1/validate):
   {sim: {...validation summary...}, real: {...},
    signals: {name: {sim: {min,max,mean,std}, real: {...},
                     overlap, drift}},
    check_pass_rates: {check_name: {sim: bool, real: bool}},
    verdict: "drift_detected" if any drift_flag or a check passes on
    one side and fails on the other, else "aligned"}
6. Tests: synthetic pair where sim velocities are ~3x real ->
   drift flagged on the velocity distribution with overlap < 0.5;
   identical distributions (same rows both sides) -> verdict
   "aligned", all overlaps ~1.0; a signal missing from sim listed
   correctly; a check that fails only on the real side shows in
   check_pass_rates and flips the verdict.

FILES YOU MAY TOUCH
- core/sim_real.py (NEW)
- api/server.py (endpoint + request model only)
- tests/test_sim_real.py (NEW), docs-site endpoint page

FILES YOU MUST NOT TOUCH
- core/robotics_engine.py, core/robotics_trajectory.py,
  core/robotics_validation.py, core/dimensional/*, core/apie.py,
  and the existing endpoints' behaviour.

CONSTRAINTS
- Do not change the existing report verdict shape anywhere; the
  comparison verdict is a new field of a new endpoint only.
- Deterministic: no LLM/AI calls in this path.
- Percentile method and overlap formula exactly as specified in
  step 3 (tests will assert them).
- All existing tests keep passing, unmodified.

DEFINITION OF DONE
- Both synthetic scenarios in step 6 behave as specified in tests.
- pytest tests/ green; summary shows one example response (trimmed)
  with a drift-flagged signal.

2d. MCP HTTP hosting with auth + rate limiting
CONTEXT — read this first.
The bundle file simapi_mcp.py is a FastMCP server exposing SimAPI's
robotics validator as tools for AI chat clients (validate_robotics_
episode, validate_robotics_csv, validate_recording,
export_clean_episodes, get_default_robotics_limits,
explain_robotics_check). It runs locally over stdio by default
(SIMAPI_MCP_TRANSPORT=stdio) — safe, because only the local user can
reach it. It can also run over streamable-http
(SIMAPI_MCP_TRANSPORT=streamable-http), which is how remote clients
like ChatGPT connect. PROBLEM: in HTTP mode today there is NO auth
and NO rate limiting — anyone who finds the URL can run validations,
and validate_recording takes local file paths, which is dangerous on
a public server.

GOAL
Make the HTTP transport safe to host: bearer-token auth on every
request, per-token rate limiting, and recording-by-upload instead of
local paths in HTTP mode — without changing stdio behaviour at all.

PLAN
1. Config via environment only: SIMAPI_MCP_API_KEYS (comma-separated
   bearer tokens), SIMAPI_MCP_RATE_LIMIT (requests/minute/token,
   default 60), SIMAPI_MCP_MAX_ROWS (per-call row cap, default
   10000, matching the hosted API's sample limit).
2. Auth: when transport is streamable-http, require
   "Authorization: Bearer <token>" on every MCP request; compare with
   hmac.compare_digest; missing/wrong token -> HTTP 401 with a plain
   JSON error body, before any tool runs. If SIMAPI_MCP_API_KEYS is
   unset in HTTP mode, REFUSE TO START with a clear error message —
   never silently run open. Stdio mode: no auth (unchanged), and the
   env vars are ignored.
   Implementation route: FastMCP/mcp SDK middleware or a thin ASGI
   wrapper around the app — check what mcp<2 (the pinned SDK version)
   supports and use the least invasive option; document the choice
   in a comment.
3. Rate limiting: in-memory fixed-window counter per token; over the
   limit -> HTTP 429 with Retry-After. In-memory is fine (single
   process) — note that in one comment.
4. Row cap: the three row-taking tools reject payloads over
   SIMAPI_MCP_MAX_ROWS with a tool error naming the count and cap
   (both transports — this one is just good hygiene).
5. validate_recording in HTTP mode: local filesystem paths are
   DISABLED (tool error explaining why). Add validate_recording_upload
   that accepts base64 content + filename, writes to a temp dir,
   validates, and deletes in a finally block. Stdio mode keeps the
   path-based tool exactly as is.
6. Tests (pytest, using the SDK's test client / httpx against the
   ASGI app — follow the mcp<2 testing pattern): no token -> 401;
   wrong token -> 401; good token -> tools list + a validate call
   succeeds; hammering past a tiny test rate limit -> 429;
   validate_recording with a path in HTTP mode -> tool error;
   upload variant works on a tiny synthetic parquet; stdio-mode test
   from the existing harness still passes untouched.

FILES YOU MAY TOUCH
- simapi_mcp.py (the bundle file; it will live at the repo root or a
  tools/ folder — keep it a single file)
- tests for it (NEW test file next to the existing MCP test harness)
- the MCP README section (auth + env vars documentation)

FILES YOU MUST NOT TOUCH
- Everything under core/, api/, integrations/ — the server wraps the
  engine; this task changes the wrapper only.
- The six tools' names, argument names, or return shapes (except the
  ADDED upload tool and the row-cap error).

CONSTRAINTS
- Do not change any tool's verdict/report shape.
- No new heavy dependencies: stdlib + the already-pinned mcp SDK +
  httpx (test-only) at most.
- Secrets never logged: tokens must not appear in any log line or
  error message.
- Existing stdio tests keep passing, unmodified.

DEFINITION OF DONE
- All step-6 tests green, including the 401/429 cases.
- Server in HTTP mode without SIMAPI_MCP_API_KEYS refuses to start
  (show the error in your summary).
- README documents: how to set keys, the rate-limit behaviour, and
  why path-based recording is stdio-only.