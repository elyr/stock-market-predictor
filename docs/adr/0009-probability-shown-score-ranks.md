# 9. Show calibrated probabilities, but rank on the raw score

- **Status:** accepted, November 2026

## Context

A displayed probability should mean what it says, so model output is calibrated.
But a calibrator with a negative slope would reverse the order of the assets.

## Decision

Probabilities are calibrated and shown, never used to rank. Ranking uses the
model's raw score. The score is shown as a percentile (0-100) because
probabilities for relative returns cluster near 50%.

## Consequences

- Calibration cannot reorder assets.
- Tests check that calibration does not worsen the Brier score.
