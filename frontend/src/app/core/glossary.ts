/**
 * Definitions shown by the help hints (`<app-hint term="…">`).
 *
 * One place for every definition keeps the wording consistent across pages.
 * Each entry is a short, plain-language explanation of a term, never
 * information the page needs to be understood or an action: per tooltip
 * guidance, what matters must be visible without hovering.
 */
export interface GlossaryEntry {
  term: string;
  text: string;
}

const entries = {
  // ------------------------------------------------------------ ranking
  score: {
    term: 'Score',
    text: "Where the model ranks this asset today, from 0 (worst) to 100 (best) among those analysed. It is a ranking, not a price target.",
  },
  beat: {
    term: 'Chance to beat the field',
    text: "The model's probability that this asset does better than the average of the others over the holding period. Values stay close to 50% because short-term returns are mostly noise; 55% is a strong view.",
  },
  weight: {
    term: 'Weight',
    text: 'Share of the suggested portfolio. Calmer assets get more, so each position carries a similar amount of risk.',
  },
  volatility: {
    term: 'Volatility',
    text: 'How much the price typically swings, as a yearly percentage. 30% means a typical year moves the price by about ±30%.',
  },
  today: {
    term: 'Today',
    text: 'Price change over the last trading day (the last 24 hours for crypto).',
  },
  weekRange: {
    term: 'Next week',
    text: 'Where the price should be at the end of the next week 9 times in 10, based on its volatility and how far prices moved in the past.',
  },
  scoreParts: {
    term: 'Score parts',
    text: 'The model score is what ranks assets. Technical, momentum and volume are simple rule-based readings of the chart, shown for context; by default they do not change the ranking.',
  },
  modelWeighed: {
    term: 'What the model weighed',
    text: "Each line is one input the model uses and how much it pushed this asset's score up (for) or down (against), compared with the other assets today.",
  },
  topFeatures: {
    term: 'Inputs the model leans on most',
    text: 'The inputs with the largest weight in the trained model: the patterns that history says mattered most for ranking.',
  },

  // ------------------------------------------------------------ evidence
  ic: {
    term: 'Rank IC',
    text: 'How well the ranking matched what happened next: the correlation between the predicted order and the actual order of returns, across assets on each date. 0 is no skill, 1 is perfect. In practice 0.02 to 0.05 is good.',
  },
  tStat: {
    term: 't-statistic',
    text: 'How sure we can be that a result is not luck. Above about 2 (or below −2) it is unlikely to be chance; between −2 and 2 it could easily be.',
  },
  luckBand: {
    term: 'Better than luck?',
    text: "The marker is the model's rank IC on dates it never trained on. The shaded band is what a model with no skill would produce 95% of the time; outside it, the result is unlikely to be luck.",
  },
  auc: {
    term: 'AUC',
    text: 'How often the model scores a winner above a loser when you pick one of each at random. 0.5 is a coin flip, 1 is perfect; slightly above 0.5 is typical here.',
  },
  accuracy: {
    term: 'Right calls',
    text: 'Share of unseen cases where the model correctly said whether the asset would beat the field. Compare it with always guessing the same answer.',
  },
  testRows: {
    term: 'Unseen asset-days',
    text: 'One asset on one date, in the recent period kept out of training. More of them makes the measurement more reliable.',
  },
  calibration: {
    term: 'Calibration',
    text: 'Whether the stated chances are honest: of all the times the model said 55%, about 55% should have come true. Points on the dashed line are perfectly honest.',
  },
  excess: {
    term: 'Edge over the field',
    text: 'Return of the picks minus the average return of every asset in the universe over the same period. Positive means the picks did better than buying everything.',
  },
  hitRate: {
    term: 'Hit rate',
    text: 'Share of periods (or picks) that beat the average of the universe. 50% is what a coin flip would give.',
  },
  topBottom: {
    term: 'Top vs bottom',
    text: 'Average return of the best-scored group minus the worst-scored group. A model with skill makes this clearly positive.',
  },
  rightDirection: {
    term: 'Right direction',
    text: 'Share of dates on which this part ranked assets in the right order more often than not (rank IC above 0).',
  },
  staircase: {
    term: 'Score groups',
    text: 'Each date the assets are split into groups from lowest to highest score. With real skill, each group does a little better than the one before it.',
  },
  steady: {
    term: 'Is the skill steady?',
    text: 'Rank IC date by date and its rolling average. Real skill keeps the average above zero; a line drifting to zero means the edge is fading.',
  },

  // ------------------------------------------------------------ backtest
  annualReturn: {
    term: 'Per year',
    text: 'The compounded return turned into a yearly rate, so periods of different length can be compared.',
  },
  sharpe: {
    term: 'Sharpe ratio',
    text: 'Return per unit of risk (yearly return divided by yearly volatility). Higher is better; above 1 is good for a stock strategy.',
  },
  drawdown: {
    term: 'Worst drop',
    text: 'The largest fall from a previous high before recovering. It shows the worst stretch you would have had to sit through.',
  },
  edgePerPeriod: {
    term: 'Edge per period',
    text: 'Average return above the equal-weight universe for each holding period, in basis points (1 bp = 0.01%).',
  },
  costs: {
    term: 'After costs',
    text: 'Each trade is charged a cost (5 basis points each way by default) on the part of the portfolio that changes.',
  },
  backtest: {
    term: 'Backtest',
    text: 'A replay of the strategy on past prices. Each period it retrains only on data available then, picks, holds, and records the outcome, as if it had run live.',
  },

  // ------------------------------------------------------------ experiments and models
  dev: {
    term: 'Development period',
    text: 'The stretch of past dates every experiment is scored on, so experiments can be compared fairly.',
  },
  lockbox: {
    term: 'Locked period',
    text: 'The most recent dates, kept out of every experiment. Check a promising experiment on it once: if the gain disappears there, it was fitted to noise.',
  },
  vsCurrent: {
    term: 'vs. current',
    text: 'Difference in rank IC from the current settings on the same period. Small differences are usually noise.',
  },
  champion: {
    term: 'Champion',
    text: "The model version used for today's analysis. A newly trained version replaces it unless a version is pinned.",
  },
  pinned: {
    term: 'Pinned',
    text: 'Analyses rank with this exact version instead of training a new one, so results stay comparable while you investigate.',
  },
  evidence: {
    term: 'Evidence',
    text: 'A plain verdict from the t-statistic: whether this result could easily be luck or not.',
  },
  codeVersion: {
    term: 'Code',
    text: 'The version of the app that trained this model, so a result can be traced to the exact code.',
  },

  // ------------------------------------------------------------ forecast and volatility
  range50: {
    term: 'Likely range (50%)',
    text: 'The price should end inside this range about half the time. Half the time it will end outside, which is expected.',
  },
  range90: {
    term: 'Wide range (90%)',
    text: 'The price should end inside this range 9 times in 10. Wider means the asset is more turbulent, not that something is wrong.',
  },
  coverage: {
    term: 'Ranges held',
    text: 'How often past ranges actually contained the price once their window had passed. Close to 50% and 90% means the ranges are honest.',
  },
  heldOut: {
    term: 'Held-out check',
    text: 'Coverage measured, when the ranges were fitted, on recent dates that were not used to fit them.',
  },
  volForecast: {
    term: 'Volatility forecast',
    text: 'The expected size of price swings over the coming days, from a model trained on how volatility behaved in the past. Swings are far more predictable than direction.',
  },
  volUp: {
    term: 'Chance it rises',
    text: 'Probability that volatility over the coming days will be higher than it is now.',
  },
  r2: {
    term: 'Variation explained',
    text: 'How much of the differences in future volatility the model accounts for, compared with simply assuming it stays where it is.',
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof entries;
export const GLOSSARY: Record<GlossaryKey, GlossaryEntry> = entries;
