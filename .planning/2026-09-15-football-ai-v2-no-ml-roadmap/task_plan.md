# Football AI v2 Strict No-ML Roadmap

## Goal

Make `docs/Football_AI_v2_no_ML_architecture_plan.md` the only operative roadmap after Round 2 and remove trainable ML/calibration work from all future instructions.

## Decisions

- Keep transparent statistical engines, versioned rule systems, market information, and an explanation-only LLM layer.
- Permit transparent statistical state/parameter estimation for Elo, Poisson, and Dixon-Coles; prohibit generic learned feature-to-outcome mappings.
- Calibration is rule-based only. Platt, Isotonic, temperature fitting, learned weights, stacking, OOF training, and all other fitted calibration are outside v2 no-ML.
- Reuse Round 2 feature snapshots and audit history. Do not create a parallel feature/data system.
- Freeze existing trainable legacy paths; do not extend or promote them. Retirement requires a separate compatibility-safe change.

## Phases

### Phase 1: Reconcile architecture sources
**Status:** complete
- Compare the strict no-ML decision with the old Codex plan, Round 1 audit, and Round 2 report.

### Phase 2: Establish canonical architecture and roadmap
**Status:** complete
- Rewrite the no-ML architecture with boundaries, transition policy, Round 3-8 deliverables, and acceptance gates.

### Phase 3: Retire conflicting future instructions
**Status:** complete
- Mark old plans as historical and replace their executable phase/task/test lists.

### Phase 4: Verify documentation consistency
**Status:** complete
- Scan operative documentation for forbidden future work, run `git diff --check`, and report the new route.

## Scope

- Documentation and planning only.
- No business-code change, dependency change, database migration, commit, push, or deployment.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| `apply_patch` rejected deleting and adding the same architecture file in one patch | 1 | Split planning creation and architecture replacement into separate patches. |
| Skill chunk-read orchestration hit a JavaScript template-string syntax error | 1 | Use fixed commands without embedded PowerShell newline escapes. |
| `session-catchup.py` failed while emitting a Unicode symbol through the GBK console | 1 | Re-run with task-scoped UTF-8 Python output and keep output byte-capped. |
| Completion helper defaulted to the unrelated root `task_plan.md` and this plan used an unsupported status marker | 1 | Pass this plan path explicitly and use the helper's required bold status-marker format. |
