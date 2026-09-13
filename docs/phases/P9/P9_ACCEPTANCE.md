# P9 Acceptance

## Functional
- [ ] CSL/EPL/LAL historical pipeline remains valid.
- [ ] CFA Cup/UCL/ACL fixture data uses competition-aware identity.
- [ ] league and knockout capability differences are represented.
- [ ] provider health exposes freshness, coverage, error and conflict.
- [ ] duplicate canonical fixture is rejected or merged deterministically.

## Integrity
- [ ] raw provenance retained.
- [ ] `captured_at` and `prediction_timestamp` semantics preserved.
- [ ] no future data enters historical snapshot.
- [ ] provider fallback is auditable.

## Regression
- [ ] P0-P7 tests pass.
- [ ] P8 API/UI contracts pass.
- [ ] frontend build/lint pass.
- [ ] backend pytest pass.

## Release gate
No P9 release if any critical quality rule is fail, any provenance is missing, or any historical evaluation result changes without an explicit dataset/model version change.
