# SimAPI v3 — Spec and Design Document

## The data quality platform for Physical AI

**In plain English**

Labs spend millions collecting robot demonstrations. A person drives a robot arm, or the arm runs in simulation, and every moment is recorded: joint angles, speeds, motor forces, camera timestamps, and commanded actions. AI models are then trained on those recordings.

Some episodes in every dataset can be quietly broken: joints teleport, motors stay pinned at their limits, cameras drift out of sync, or values recorded in degrees are interpreted as radians. The AI learns from those errors, training runs fail for unclear reasons, and teams lose weeks. SimAPI sits between data collection and training. It checks each episode, explains failures with plain labels, and can return a clean dataset. It must never give a fake clean pass. A trusted validation tool is valuable; one that waves bad data through is worse than having no tool.

This document describes the problem, the feature ideas, their effort and priority, what not to build, and a possible path to making SimAPI a company that a top accelerator such as Y Combinator (YC) would fund.

### Terms used in this document

- **Episode:** One full attempt at a task, such as picking up a cup. It is the unit on which robot AI is trained.
- **Signal:** One measured column, such as `joint_1_position`.
- **Torque:** How hard a motor pushes, measured in newton metres (Nm).
- **Profile:** A named set of allowed ranges for one robot.
- **Verdict shape:** The exact JSON structure returned by SimAPI. It is frozen because many callers depend on it.
- **EASY:** One file, with no architecture change, and days rather than weeks of work.
- **HARD:** A new subsystem, endpoint, frontend, or research risk.

## 1. The 100k torque problem

### What it is

SimAPI's core ships default limits so a new user gets some check without configuring anything. These defaults are not robot limits; they are broad “is this number insane?” screens. They are currently so wide that they barely screen anything:

| Signal | Core default | Where |
| --- | --- | --- |
| `joint_torque` | −100,000 to +100,000 Nm | `core/robotics_engine.py`, lines 20–36 (`DEFAULT_ROBOTICS_LIMITS`) |
| `joint_velocity` | −500 to +500 rad/s | Same defaults |
| `joint_acceleration` | −5,000 to +5,000 rad/s² | Same defaults |
| `joint_position` | −4π to +4π rad | Same defaults |
| `end_effector_force` | −50,000 to +50,000 N | Same defaults |
| `joint_torque` in the legacy validator | −100,000 to +100,000 Nm | `core/physics_validator.py`, around line 149; this validator has its own copy |

`core/robotics_engine.py` starts from `DEFAULT_ROBOTICS_LIMITS`, applies defaults to recognized `joint_*` columns, and then applies the caller's configured limits. A user who supplies no profile therefore gets the broad defaults. Nearly anything passes, and the report looks like a real check.

### Why it matters: real-world magnitudes

A Franka Panda arm's strongest joint maxes out at about 87 Nm. A UR5e maxes out at about 150 Nm. 100,000 Nm is roughly fifty times the twisting force of a truck engine; no desk-sized robot arm produces it.

A recording that claims 50,000 Nm of joint torque is physically impossible data. It points to a broken sensor, a unit error, or a corrupted file. SimAPI currently passes it under the broad defaults.

The source document records this five-sample example (`joint_1_torque = 50000`):

```text
RAW (core, no limits): robotics_limit:joint_1_torque passed;
  low=-100000.0, high=100000.0;
  detail="All samples within [-100000, 100000]"

GUARDED (this pack): verdict=failed;
  limits_source=screening_profile;
  profile_guard warning added;
  all 5 rows excluded; training_ready=False
```

Trust in the verdict is SimAPI's main asset. A lab that discovers SimAPI passed 50,000 Nm will have good reason to distrust every later “passed” result. This fix therefore comes before the other features.

### The chosen fix: two layers

#### Layer 1: immediate guard (done in the pack; no core changes)

`core/physical_ai_v2.py` provides `validate_guarded()`, which wraps `check_robotics_limits`:

- Callers who pass explicit limits or a named profile use those limits.
- Callers who pass neither, and do not explicitly opt into raw defaults with `allow_defaults=True`, get the generic `generic_lab_arm` screening profile: torque ±150, velocity ±3.0, acceleration ±25, and position ±2π.
- The wrapper adds a `profile_guard` warning explaining that the limits are screening-only, and caps the result at `warning` with `training_ready=False`.
- Even with `allow_defaults=True`, the result carries the guard warning and `training_ready=False`; defaults do not prove that a dataset matches a particular robot.
- Empty input fails closed. Malformed limits are rejected with an error naming the signal, matching `core/physical_ai.py` behavior.

#### Layer 2: fix the core defaults (Prompt H1)

Tighten the core defaults to torque ±200, velocity ±10, acceleration ±50, and end-effector force ±1000. Add a `robotics_unprofiled_signal` warning whenever a joint signal was checked only against defaults, and cap the verdict at `warning` with `training_ready=False`. Apply the corresponding torque and velocity tightening in `core/physics_validator.py`. Callers with explicit limits must see no behavior change.

Layer 1 protects callers using the wrapper. Layer 2 prevents a misleading clean pass for direct core users who do not use that wrapper.

## 2. Every idea, classified: EASY / HARD / DON'T-BUILD

**Status key:** `DONE-IN-THIS-PACK`, `PROMPT-GIVEN` (in `prompts-hard.md` or the earlier bundle's `prompts.md`), `LATER`, or `DONT-BUILD`.

### 2A. EASY ideas

#### E1. Robot arm profiles — DONE-IN-THIS-PACK

Ready-made realistic limits let a user choose `franka_panda` instead of entering 28 numbers. `core/physical_ai_v2.py` defines `ARM_PROFILES` and `get_profile(name, num_joints)` for `franka_panda` (87 Nm torque class and about 2.175 rad/s), `ur5e` (150 Nm and about 3.14 rad/s), `ur10e`, `xarm7`, `so101` (a small LeRobot servo arm with much lower limits), and `generic_lab_arm` (±150 torque, ±3.0 velocity, ±25 acceleration, and ±2π position).

Each profile is a starting screening profile that must be checked against the robot's URDF or datasheet. Profiles help users complete a first validation quickly. Adding another profile should take about 15 lines.

**YC/business value:** Medium-high. Activation — a user's first successful check — is where developer tools succeed or lose users.

#### E2. Defaults guard — DONE-IN-THIS-PACK

`validate_guarded()` provides the guard described in Section 1. Labs can say that SimAPI never silently passes unprofiled data.

**YC/business value:** High. This is a credibility feature and a direct demonstration of catching what a tool with excessively broad defaults would miss.

#### E3. Jerk checks — DONE-IN-THIS-PACK

`check_jerk()` derives velocity, acceleration, and jerk (the rate of change of acceleration, in rad/s³) by finite differences within each episode, following the repository's time and episode conventions. It flags rows above the configured limit. Smooth motors should not show sudden jerk spikes; logging glitches, collisions, and frame drops can.

This catches a class of corruption that position and velocity checks can miss: data that is in range and self-consistent at each step but has implausibly abrupt changes.

**YC/business value:** Medium. It deepens the check catalogue with a physically meaningful check.

#### E4. Degrees/radians detection — DONE-IN-THIS-PACK

`detect_units()` flags position signals whose maximum absolute value is greater than 2π and at most 360: that is impossible in radians but plausible in degrees. `convert_degrees_to_radians(rows, signals)` returns converted rows without mutating the originals.

This catches the common degrees-versus-radians mix-up. A deeper feature — unit declarations inside profiles — is already described in bundle prompt 1c.

**YC/business value:** Medium-high. It catches a data bug teams may otherwise discover late in a training run.

#### E5. Dataset health score — DONE-IN-THIS-PACK

`dataset_health_score()` turns `core/physical_ai.py` per-episode results into a score from 0 to 100 and a letter band from A to F. The score gives 70% weight to the share of training-ready episodes and 30% to the share of unflagged rows, then reports the main reasons the score is lower.

The score helps managers and dataset buyers compare datasets without reading hundreds of checks. It can also become a badge, leaderboard, CI gate, or pricing surface.

**YC/business value:** High. Scores are easy to share; raw JSON is not.

#### E6. Failure clustering — DONE-IN-THIS-PACK

`cluster_failures()` groups failure dictionaries by `(label/check, signal)` and sorts the clusters. A cluster includes its count, example row indices, and a plain-English name, such as “Value outside its allowed range — `joint_1_torque` × 214.”

Clustering turns thousands of failures into a short list of actions: fix a sensor, re-collect episodes, or review a specific signal. Semantic clustering beyond these rules is later work in the H10 research area; it must not invent structure.

**YC/business value:** Medium-high. This makes SimAPI an analyst as well as a checker.

#### E7. Torque saturation trend per episode — DONE-IN-THIS-PACK

`torque_saturation_trend(rows, signal, limit)` compares the share of samples within 5% of the torque limit in the first and second halves of an episode. A rising share means the motor is straining more as the task continues.

`core/physical_ai.py` already labels episodes where a motor is pinned at its limit for at least 30% of the episode. The trend is an earlier warning that a motor or task may be deteriorating. It is cheap to compute and difficult to spot by eye across hundreds of episodes.

**YC/business value:** Medium on its own; it is a building block for fleet monitoring (H9).

#### E8. Duplicate and near-duplicate episode detection — LATER

Hash each episode's signals to find exact duplicates, then use a cheap fingerprint of downsampled position series to find near-duplicates. A tolerance for the fingerprint needs to be chosen.

Duplicated demonstrations can overweight one motion during training. Exact hashing is straightforward; near-duplicate detection needs about one to two days and a tolerance decision.

**YC/business value:** Medium. This would round out dataset hygiene and be easy to demonstrate on public data.

#### E9. Timestamp monotonicity and gap report — DONE; standalone report is LATER polish

Time must not go backwards or repeat within an episode. Silent sampling gaps should be reported per episode with their counts and worst gap, not only as pass/fail. The core trajectory engine already has `robotics_time_order` and `robotics_sample_gaps` (when `max_time_step` is set); `core/physical_ai.py` labels `time_gap` and `time_disorder`.

A standalone per-episode gap report with the worst gap and a gap histogram remains later polish, estimated at about half a day.

**YC/business value:** Low-medium on its own; it adds depth to the check catalogue.

#### E10. Shareable Markdown report export — LATER

Render a validation report as one clean Markdown file containing the verdict, health score, top failure clusters, worst episodes, limits used, and `limits_source`. It should be easy to paste into GitHub issues, pull requests, Slack, or a paper appendix.

Reports are often discussed in conversations. A shareable artifact makes it easier to answer why data was rejected and spreads SimAPI when results are shared. This is about half a day of rendering work.

**YC/business value:** Medium-high. Shared reports carry evidence along with the product name.

### 2B. HARD ideas

#### H1. Fix the 100k defaults in core — PROMPT-GIVEN (Prompt H1: do this first)

Tighten the core screening defaults to torque ±200, velocity ±10, acceleration ±50, and force ±1000. Add the `robotics_unprofiled_signal` warning to cap results when a joint signal uses defaults. Apply the torque and velocity tightening in `core/physics_validator.py` as well. Explicit-limit callers must remain unchanged.

**YC/business value:** High. Trust is the product.

#### H2. Forward-kinematics consistency via URDF — PROMPT-GIVEN

Parse URDF geometry and compute the expected hand position from joint angles. Fail samples whose reported end-effector position differs. This catches wrong-frame, stale, or mislabeled end-effector data that per-joint checks cannot detect.

**Effort:** One to two weeks for a new suite, URDF geometry parser, and math tests.

**YC/business value:** High. It catches a broad failure mode and provides a distinctive demonstration.

#### H3. Sim-versus-real comparison endpoint — PROMPT-GIVEN

Add `POST /v1/compare/sim-real`: validate both datasets, compare each shared signal's distributions using p5–p95 overlap, flag overlap below 0.5, and compare check pass rates. Return `aligned` or `drift_detected`.

Simulation data can pass physical checks but still be far from real data. This endpoint makes that gap visible to simulation teams.

**Effort:** About one week for the endpoint, pure comparison module, and tests.

**YC/business value:** High. It serves simulation-heavy teams using tools such as Isaac Sim or MuJoCo.

#### H4. Hosted large-recording ingestion, streamed — PROMPT-GIVEN

Upload `.mcap`, `.db3`, rosbag2 `.zip`, LeRobot parquet, or dataset archives to the hosted API. Stream the upload, enforce size limits while receiving it, reuse the existing loaders, avoid whole-file memory spikes, and refuse data above the sample cap rather than truncating it.

**Effort:** One to two weeks for streaming, temporary-file lifecycle, format dispatch, and optional-dependency handling.

**YC/business value:** High. Accepting the recording teams already have removes a major adoption barrier and could support usage-based pricing.

#### H5. Episode viewer: synced video and joint charts — PROMPT-GIVEN

In the existing dashboard design, add an episode page where camera video and joint charts share one timeline. Mark flagged moments, and let a reviewer click a failure cluster or marker to seek both video and charts to that time.

Engineers can understand a failure more easily by watching the event alongside the chart than by reading a row number. The viewer is a potentially strong demonstration and can become part of a team's review habit.

**Effort:** Two to four weeks for frontend work, media handling, and API support.

**YC/business value:** Very high.

#### H6. Hugging Face dataset CI and health badge — PROMPT-GIVEN

Add a reusable GitHub Action or Hugging Face Space integration that validates a LeRobot dataset repository when it changes and publishes the health score and report as a badge or comment on the dataset page.

This places a quality signal where public datasets are shared. It can introduce SimAPI to dataset publishers and buyers.

**Effort:** One to two weeks for integration, authentication, and report rendering.

**YC/business value:** Very high. This is a distribution channel as well as a feature.

#### H7. MCP Streamable HTTP authentication and rate limiting — PROMPT-GIVEN

Secure the MCP server's Streamable HTTP mode with bearer-token authentication that refuses to start without configured keys, per-token request limits, row caps, and upload-based recording validation. Local file paths remain available only in stdio mode.

Hosted AI-client access is useful to teams only if they can run the server safely.

**Effort:** About one week.

**YC/business value:** Medium-high. This opens an emerging distribution channel once HTTP hosting is planned.

#### H8. Vectorize trajectory checks to scale to one million rows — PROMPT-GIVEN

Rewrite `core/robotics_trajectory.py` with vectorized pandas/NumPy operations grouped by episode. Preserve check names, failed indices, and summaries exactly, and benchmark at one million rows. Existing tests are the contract.

Real logs contain millions of rows. Validation that takes an hour will not be used in a pipeline; validation that takes around a minute can be.

**Effort:** One to two weeks, largely to prove equivalent results.

**YC/business value:** Medium-high. Scale is necessary for larger lab customers and reduces hosting costs.

#### H9. Fleet monitoring and motor-drift prediction — PROMPT-GIVEN

Schedule validation of incoming recordings, store per-robot health scores, saturation trends, and failure clusters over time, then alert when a robot's torque trend drifts. For example: “Arm 3's joint 2 is straining 15% more than last month.”

Motor degradation can quietly affect weeks of recordings before a motor fails. Monitoring could become a recurring-revenue product and build a longitudinal robot-data moat.

**Effort:** Four or more weeks for storage, scheduling, alerting, and baselines.

**YC/business value:** Very high, especially after multiple partners request it.

#### H10. Model-in-the-loop: learn which bad episodes hurt training — PROMPT-GIVEN; research-level

Measure how failure labels affect policy performance. Train small proxy models on datasets that differ only in the fraction of episodes with one failure type, then estimate the performance change per contamination level with confidence intervals. Use the results to propose impact-weighted health scoring.

Labs need to know whether failures such as frozen sensors or timestamp errors cause measurable training harm, so they can spend limited re-collection budgets where they matter most.

**Effort:** One to three months of research, with GPU budget and careful experimental design. The work should happen after design partners can supply training runs.

**YC/business value:** Potentially company-defining, but high risk.

#### H11. Learned anomaly-detection checks — LATER

Train anomaly models on validated-good episodes to flag data that appears wrong in ways no current rule describes.

An unexplained ML rejection would undermine SimAPI's trust asset. The dimensional engine documents the limit: self-consistent but wrong data cannot be detected from outputs alone. Add learned checks only after collecting enough real failure examples, with explanations and evidence attached.

**YC/business value:** Medium; defer this work.

### 2C. DON'T-BUILD list

| Idea | Why not |
| --- | --- |
| Video understanding that judges a grasp from camera footage | This is a different company, involving vision models, GPU infrastructure, and labeling. SimAPI's strength is cheap, deterministic signal checks with evidence. Video understanding would also raise the cost of each check. |
| Training robot models for customers | The model-training market is crowded and capital-intensive. SimAPI would compete with its own customers instead of supplying clean data. |
| World models or simulation generation | This is research-lab territory with well-funded competitors. SimAPI validates simulation data; generating it requires a different team and budget. |

**Rule of thumb:** If an idea does not make a verdict more trustworthy, a dataset more usable, or SimAPI present where data changes hands, it does not ship.

## 3. The wedge: how this could become a YC-level company

### Pick one beachhead

Start with the LeRobot/Hugging Face community and university labs running Franka arms. These teams already share public data, so H6 could reach them without an enterprise sales cycle. University Franka labs encounter data-quality problems weekly and publish their work; their students may bring SimAPI into later jobs. The SO-101 and LeRobot hobbyist-to-research pipeline offers a growth path from today's $300 arm builder to tomorrow's lab hire.

The deliberately excluded beachheads are large robotics companies, with long sales cycles and custom requirements, and consumer/food robotics, which have different data and buyers. This exclusion was directed on 2026-11-11.

### The sequence

1. **Ship H1 and deploy this pack.** Establish trust in the verdict and deliver the easy wins.
2. **Recruit design partners, not just users.** Recruit five to ten teams from the beachhead. A design partner provides real recordings, joins a weekly call, and tells SimAPI when it is wrong. In exchange, they receive free, permanent access and influence over the roadmap.
3. **Collect evidence that customers need the product:**
   - Real recordings validated, including count and total size in GB; close the gap with the first real `.mcap` or `.db3` run.
   - Weekly active teams validating at least one dataset per week for four weeks.
   - A specific story such as “Lab X found N bad episodes in a dataset they were about to train on.”
   - Letters of intent or paid pilots; even $200 per month from a lab is stronger evidence than 1,000 free signups.
   - Failure saves logged with customer permission, for testimonials.
4. **Then build H4, H5, and H6** to remove friction and improve distribution. Build H9 after two or three partners request monitoring. Do H10 after traction, using partners' training runs.

### The data moat

Checks can be copied; a labeled library of real failure examples cannot be bought off the shelf. With consent, each validation can contribute anonymized examples of real teleports, saturation curves, synchronization offsets, robot models, and tasks. Over time, that data could improve default profiles, support learned checks (H11), and ground training-impact research (H10).

Contributions must be opt-in and anonymized. Keep robot and task metadata only; do not store raw customer recordings or video by default. The moat must be earned through trust.

### Honest scorecard (November 2026)

| Dimension | Status in the source specification |
| --- | --- |
| Core engine: checks, verdicts, and evidence | Real and working |
| Physical-AI layer: episodes, labels, and clean export | Built in the bundle and this pack; not yet deployed |
| Trust fix for 100k defaults | Guarded in this pack; the core fix is specified as H1 but not yet applied |
| Real-recording proof (`.mcap`/`.db3` end to end) | Not yet done; the largest gap |
| Paying users/design partners | None yet; work for the next 90 days |
| Distribution | MCP is an early move; the H6 Hugging Face badge is not yet built |

YC does not fund feature lists. It funds a team with growing evidence that a specific group of people needs the product. Each feature above should increase trust, remove adoption friction, or produce that evidence.

## 4. Deploy map

| File | Destination | Notes |
| --- | --- | --- |
| `physical_ai_v2.py` (this pack) | `core/physical_ai_v2.py` | Lives next to `core/physical_ai.py` and imports `check_robotics_limits` through `core.robotics_validation`, with the same sibling fallback as `physical_ai.py`. It should not change anything else. |
| `SPEC.md` (this pack) | Repository root or `docs/` | Design reference; not runtime code. |
| `prompts-hard.md` (this pack) | With the founders or in `docs/` | Paste one prompt at a time into Codex or Claude Code in the repo. Start with H1. |
| `physical_ai.py` (earlier bundle) | `core/physical_ai.py` | Already mapped in the bundle README. `physical_ai_v2.py` builds on its shapes. |
| `simapi_mcp.py` (earlier bundle) | Repository root | H7 hardens its HTTP mode; the module itself is otherwise unchanged. |
| `ftc_frc.py` (earlier bundle) | `core/ftc_frc.py` | The school-robotics line is separate from the Physical AI beachhead. |
| `dashboard_extras.js` (earlier bundle) | Beside the existing dashboard | H5 supersedes this add-on later with the full episode viewer. |

### Order of operations

1. Deploy `physical_ai.py` and `physical_ai_v2.py` to `core/`.
2. Run Prompt H1.
3. Run one real `.mcap` or `.db3` recording end to end and record what breaks.
4. Only then choose the next H prompt, and name the design partner whose needs justify it.

## Execution update (2026-11-12)

This update records work completed after the source specification was written.

| Required step | Current status |
| --- | --- |
| Deploy `physical_ai.py` and `physical_ai_v2.py` into `core/` | Complete; both modules are in `core/` on `main`. |
| Run H1 | Complete; the tightened screening defaults and unprofiled-signal warning are merged. |
| Run one real `.mcap`/`.db3` end to end and record breakages | Complete for one licensed public ROS 2 MCAP. See [the run report](real-recording-run.md). The loader fix is merged; validation still fails on the `t` epoch-timestamp semantic bound, and the default 100 MiB upload limit rejects the raw file. |
| Choose the next H prompt and name a design partner | Pending a named design partner. The public sample proves the code path but is not a customer or design-partner validation. |

The Python API is not externally deployed. The public health route still reports `python_backend: false`; the repository has no configured Python-service deployment target or GitHub deployment secrets/variables. The API deployment can proceed after a Railway/Render service is connected and configured.
