# Path C Commitment

**Locked date:** 2026-05-29
**Unlock date:** 2026-08-27 (90 days)

## Rules

1. No parameter changes between locked date and unlock date. No exceptions.
   This includes: PREOPEN_GAP_PCT, EMERGENCY_FLOOR_PCT, AGGREGATE_CB_USD,
   MAX_HOLD_DAYS, take-profit %, BULL-gating logic, signal thresholds,
   universe composition.

2. Bug fixes that don't change strategy behavior are allowed
   (e.g., logging, OAuth handling, dashboard display).

3. At 2026-08-27, evaluation criterion is single and binary:
   v3.0_no_stop strategy total return vs SPY buy-and-hold over the same
   window, net of 5bp/side slippage. Beats SPY = continue conversation.
   Does not = retire the strategy.

4. "Retire the strategy" means: stop running it, do not redesign, do not
   pivot to a new variant. The trading agent infrastructure stays as a
   learning project; the active strategy is shelved.

5. Looking at the dashboard is fine. Tweaking based on what I see is not.
