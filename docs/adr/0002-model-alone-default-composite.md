# 2. The model alone is the default composite

- **Status:** accepted, November 2026

## Context

The ranking score used to be a weighted mix of hand-made component scores
(technical, momentum, volume, and a news sentiment score removed in
[ADR 1](0001-remove-sentiment.md)) with fixed weights 0.25 / 0.35 / 0.20 / 0.10 / 0.10.
Measured on the demo market, whose only signal is a planted short-term
reversal, the momentum score pointed the wrong way (its largest input rewards
yesterday's rise; IC -0.075), the technical score mixed reversal rules (RSI,
Bollinger) with trend rules (MACD, moving averages), and the fixed weights
averaged a positive and a negative signal into an IC of 0.009.

## Decision

The default composite is the return model's score alone (`ranking_config.weights`:
model 1.0, the rest 0). The model sees the picks behind the hand-made scores as
features and learns from history which way each points and how much it is worth.
The component scores are still computed and shown as plain-language
explanations, and experiments can give them weight again. The model score is
shown as a percentile (0-100) because probabilities for relative returns
cluster near 50%.

## Consequences

- Changing the default model (`ml_config.model`) also means revisiting the
  ranking weights in `config/config.yaml`.
- The composite is still a weighted average over the components that exist,
  renormalised, so a component missing before training does not drag scores down.
- Details: `docs/design/analysis.md`, section 7.
