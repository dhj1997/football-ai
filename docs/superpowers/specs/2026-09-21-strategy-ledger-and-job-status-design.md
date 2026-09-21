# Strategy Ledger and Job Status Repair

## Goal

Repair two production reporting defects without changing prediction decisions,
bet execution, or bankroll transactions:

1. activation status must show the actual latest run for each provider job;
2. strategy financial metrics must include every settled paper bet, even when
   its prediction evaluation row is missing.

The repair also corrects strategy drawdown to use the configured account
initial balance and restores four missing evaluation rows from two verified
TheSportsDB results.

## Non-goals

- Do not alter model probabilities, decisions, strategy weights, or quality
  thresholds.
- Do not rewrite settled bets, executions, bankroll transactions, or balances.
- Do not infer an unknown season or final score.
- Do not add a second reporting store or a new scheduler.

## Activation Status

The activation endpoint currently scans the latest 200 job runs globally.
Frequent five-minute jobs can evict daily provider jobs from that window and
make completed work appear as `not_run`.

For each displayed provider operation, read its latest run by job name through
the existing `last_job_run(job_name)` repository method. Preserve the existing
status mapping, details, error, and timestamp fields. The general job-history
endpoint remains unchanged.

## Metric Boundaries

Prediction-quality metrics and financial metrics have different authoritative
sources:

- accuracy, Brier, Log Loss, RPS, calibration, decision counts, and prediction
  sample counts continue to use immutable `fixture_settlements` rows;
- bet count, wins, losses, stake, realized profit, ROI, CLV, Asian-handicap
  outcomes, and drawdown use all immutable settled bets for the requested
  model and simulation competition.

Financial filtering must not depend on membership in `fixture_settlements`.
Apply league and date filters from the bet's frozen `league_key` and
`fixture_date`. Apply a season filter only when the bet carries a season or a
linked settlement provides one; unresolved seasons are excluded rather than
inferred. New bets retain the fixture season when one is available.

Quality gates keep prediction sample requirements from the evaluation rows,
but use the complete financial portfolio for ROI, CLV, and drawdown checks.

## Drawdown Baseline

`_portfolio_metrics` must receive the repository's configured
`initial_balance`. It may fall back to the existing default only for repository
doubles that do not expose this value. Production therefore calculates
drawdown from 5000 rather than the previous hard-coded 1000.

## Historical Reconciliation

The following authoritative TheSportsDB event results were verified before
implementation:

| Event | Fixture | Final score |
|---|---|---|
| `2506194` | Deportivo Alaves vs Villarreal | 1-0 |
| `2494015` | Crystal Palace vs Manchester City | 1-4 |

After a verified MySQL backup, map these responses through the existing
TheSportsDB fixture mapper, validate event ID, teams, `FT` status, and score,
then upsert the two finished fixtures. Run the existing settlement service for
those fixtures. Its prediction-level uniqueness and settled-bet idempotency
must create only the four missing evaluation rows while leaving the existing
four settled bets and all bankroll transactions unchanged.

If any provider value differs from the verified identity or result, stop the
reconciliation without writing data.

## Tests

Add focused regression coverage for:

- a provider job hidden behind more than 200 unrelated runs still appears with
  its real latest status;
- a settled bet without a prediction evaluation is included in financial
  metrics but does not increase prediction-quality sample counts;
- league and date filters apply independently to settled-bet metrics;
- season-filtered metrics exclude bets whose season cannot be proven;
- drawdown uses a non-default repository initial balance;
- repeated historical settlement does not duplicate evaluations, returns, or
  other bankroll transactions.

Run only the directly affected settlement, P1 evaluation, API strategy, and
P15 activation tests, followed by Python compilation and `git diff --check`.

## Deployment Verification

1. Push the reviewed commits to GitHub `main`.
2. Run the production MySQL backup and restore-verification gate.
3. Deploy the tracked `HEAD`, rebuild Web, and restart API/Web services.
4. Verify service health and public HTTP routes.
5. Reconcile the two historical fixtures through the existing services.
6. Verify 47 settled bets are represented in global financial metrics while
   prediction samples are neither duplicated nor fabricated.
7. Verify provider operations show their real latest run instead of `not_run`.
8. Repeat reconciliation and confirm evaluation and transaction counts remain
   unchanged.
