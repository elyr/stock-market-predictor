/**
 * Builds docs/presentation/Ledger.pptx: what Ledger is, how it works and what it is for.
 *
 *   cd docs/presentation && npm ci && npm run build
 *
 * This script is the source of the deck. When the project changes in a way the
 * deck describes (features, model, results, stack, workflow), edit the CONTENT
 * below, bump UPDATED, rebuild, and commit both this file and Ledger.pptx.
 * See "Presentation" in AGENTS.md.
 */
const path = require("path");
const pptxgen = require("pptxgenjs");

const UPDATED = "November 2026";

// Palette taken from the app: slate ink, graph-paper neutrals, the logo's mint,
// green and crimson for outperformance and underperformance, cobalt for stocks
// and violet for crypto.
const COL = {
  ink: "1D2A33", soft: "4D5B64", faint: "7B878E", paper: "F3F5F2", card: "FFFFFF",
  grid: "D5DCD6", mint: "7FD1AE", up: "1F7A5C", down: "B23A48", stocks: "2C5DA8", crypto: "6B4BC2",
  railInk: "C9D3D8",
};
const FONT = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
pres.title = "Ledger: ranking stocks and crypto, honestly";
pres.subject = "What Ledger is, how it works and what it is for";
pres.author = "Ledger project";
pres.theme = { headFontFace: FONT, bodyFontFace: FONT };

// ------------------------------------------------------------------ layouts

pres.defineSlideMaster({
  title: "DARK",
  background: { color: COL.ink },
  objects: [
    { text: { text: `Ledger · ${UPDATED}`, options: { x: 0.5, y: 5.15, w: 5, h: 0.3, fontFace: FONT, fontSize: 10, color: COL.faint, margin: 0 } } },
  ],
});

pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: COL.paper },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9, h: 0.75, fontFace: FONT, fontSize: 30, bold: true, color: COL.ink, margin: 0, valign: "top", align: "left" }, text: "" } },
    { text: { text: "Ledger", options: { x: 0.5, y: 5.2, w: 2, h: 0.25, fontFace: FONT, fontSize: 10, color: COL.faint, margin: 0 } } },
  ],
  slideNumber: { x: 9.0, y: 5.2, w: 0.5, h: 0.25, fontFace: FONT, fontSize: 10, color: COL.faint, align: "right" },
});

// ------------------------------------------------------------------ helpers

function card(slide, x, y, w, h, fill = COL.card) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: COL.grid, width: 0.75 },
  });
}

/** The deck's motif: a small filled circle with a number or letter in it. */
function badge(slide, x, y, label, color, size = 0.42) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: size, h: size, fill: { color }, line: { color } });
  slide.addText(label, {
    x, y, w: size, h: size, align: "center", valign: "middle", fontFace: FONT, fontSize: 13, bold: true,
    color: "FFFFFF", margin: 0, isTextBox: true,
  });
}

function text(slide, value, opts) {
  slide.addText(value, { fontFace: FONT, color: COL.ink, margin: 0, isTextBox: true, valign: "top", ...opts });
}

function content(title, section) {
  const slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  slide.addText(title, { placeholder: "title" });
  return slide;
}

// ------------------------------------------------------------------ 1. title

pres.addSection({ title: "Introduction" });
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Introduction" });
  // Logo: the app's rising line on ruled paper
  s.addShape(pres.shapes.LINE, { x: 0.5, y: 1.05, w: 0.8, h: 0, line: { color: "3B4851", width: 1 } });
  s.addShape(pres.shapes.LINE, { x: 0.5, y: 1.25, w: 0.8, h: 0, line: { color: "3B4851", width: 1 } });
  s.addShape(pres.shapes.LINE, { x: 0.5, y: 1.45, w: 0.8, h: 0, line: { color: "3B4851", width: 1 } });
  s.addShape(pres.shapes.LINE, { x: 0.55, y: 1.2, w: 0.7, h: 0.32, flipV: true, line: { color: COL.mint, width: 3 } });
  text(s, "Ledger", { x: 0.5, y: 1.75, w: 9, h: 0.9, fontSize: 48, bold: true, color: "FFFFFF" });
  text(s, "A personal research assistant for stocks and crypto, honest about what can be predicted", {
    x: 0.5, y: 2.7, w: 7.5, h: 0.9, fontSize: 20, color: COL.railInk });
  text(s, "For a non-expert investor, and an end-to-end MLOps learning project", {
    x: 0.5, y: 3.75, w: 7.5, h: 0.4, fontSize: 14, italic: true, color: COL.mint });
  s.addNotes("Ledger ranks stocks and crypto by how likely each is to beat the others over the next few days. "
    + "Its distinguishing feature is honesty: every number comes with how much evidence supports it. "
    + "It is also a vehicle for learning the full MLOps and platform stack.");
}

// ------------------------------------------------------------------ 2. goals

{
  const s = content("Two goals, one project", "Introduction");
  const goals = [
    ["1", COL.stocks, "A personal research assistant",
      "For a non-expert: a weekly brief in plain sentences, your portfolio and its risks, "
      + "rankings and price ranges, and a plain verdict on whether any of it beats luck."],
    ["2", COL.crypto, "A real MLOps platform to learn on",
      "Build what a production ML system needs end to end: training, a model registry, jobs, "
      + "monitoring, Kubernetes, GitOps, CI/CD, backups."],
  ];
  goals.forEach(([n, color, head, body], i) => {
    const x = 0.5 + i * 4.6;
    card(s, x, 1.3, 4.4, 2.6);
    badge(s, x + 0.3, 1.6, n, color);
    text(s, head, { x: x + 0.3, y: 2.2, w: 3.8, h: 0.45, fontSize: 18, bold: true });
    text(s, body, { x: x + 0.3, y: 2.7, w: 3.8, h: 1.1, fontSize: 14, color: COL.soft });
  });
  text(s, "Not financial advice: short-term returns are mostly noise, and the app is built to say so.", {
    x: 0.5, y: 4.25, w: 9, h: 0.4, fontSize: 14, italic: true, color: COL.soft });
  s.addNotes("The first goal is the product; the second is the reason the project exists in this form. "
    + "Every component maps to a skill used in production ML teams.");
}

// ------------------------------------------------------------------ 3. the app

pres.addSection({ title: "What it does" });
{
  const s = content("Two dashboards, three questions", "What it does");
  text(s, "US stocks and crypto each get the same pages, with their own data and models.", {
    x: 0.5, y: 1.0, w: 9, h: 0.35, fontSize: 14, color: COL.soft });
  const groups = [
    ["Today", COL.up, [["Weekly brief", "Your week in plain sentences"], ["Outlook", "Ranking, picks, reasons"],
      ["Long-term", "The month ahead"], ["My portfolio", "Your trades, gains, risk"],
      ["Next 3 days", "Price range, 7 times in 10"], ["Forecast", "Ranges: day, 3 days, week"],
      ["Volatility", "How big the swings will be"], ["Alerts", "Unusual moves, twice a day"]]],
    ["Is it working?", COL.stocks, [["Track record", "Live picks, scored later"], ["Backtest", "Replayed on past prices"],
      ["Predicted vs actual", "Which inputs carry signal"]]],
    ["Improve it", COL.crypto, [["Experiments", "Compare settings fairly"], ["Models", "Versions; pin or roll back"]]],
  ];
  // Today has eight pages: a wide card with two columns; the other two groups share the rest
  const frames = [{ x: 0.5, w: 4.4, cols: 2 }, { x: 5.05, w: 2.15, cols: 1 }, { x: 7.35, w: 2.15, cols: 1 }];
  groups.forEach(([head, color, pages], i) => {
    const { x, w, cols } = frames[i];
    card(s, x, 1.45, w, 3.6);
    badge(s, x + 0.2, 1.62, String(i + 1), color, 0.38);
    text(s, head, { x: x + 0.66, y: 1.66, w: w - 0.72, h: 0.35, fontSize: 15, bold: true });
    const perColumn = Math.ceil(pages.length / cols);
    pages.forEach(([name, what], j) => {
      const column = Math.floor(j / perColumn), row = j % perColumn;
      const colWidth = (w - 0.4) / cols;
      text(s, [
        { text: name, options: { bold: true, fontSize: 13, breakLine: true } },
        { text: what, options: { fontSize: 11, color: COL.soft } },
      ], { x: x + 0.2 + column * colWidth, y: 2.2 + row * 0.68, w: colWidth - 0.1, h: 0.62 });
    });
  });
  s.addNotes("The menu is grouped by the question each page answers. Every figure has a small question-mark help tooltip.");
}

// ------------------------------------------------------------------ 4. how to use it

{
  const s = content("How to use it", "What it does");
  text(s, "A simple routine. Most weeks, the right answer is to do nothing.", {
    x: 0.5, y: 1.0, w: 9, h: 0.35, fontSize: 14, color: COL.soft });
  const steps = [
    ["Every week", "Read the weekly brief", "What happened, how your portfolio did, and what to do, in plain sentences."],
    ["When you trade", "Record it", "Add each buy and sell in My portfolio to see gains against simply buying the market."],
    ["When warned", "Fix the risk", "A position too big, a sector too heavy, risk rising: the app says so in plain words."],
    ["Before deciding", "Look at the ranges", "Outlook, Next 3 days and Long-term give rankings and likely price ranges, never certainties."],
    ["Every month", "Check the record", "If the track record does not beat luck, follow the risk advice, not the picks."],
  ];
  const w = 1.66, gap = 0.17;
  steps.forEach(([when, head, body], i) => {
    const x = 0.5 + i * (w + gap);
    card(s, x, 1.5, w, 2.95, i === 0 ? "E3F1EA" : COL.card);
    badge(s, x + 0.2, 1.7, String(i + 1), i === 0 ? COL.up : COL.ink, 0.38);
    text(s, when.toUpperCase(), { x: x + 0.2, y: 2.2, w: w - 0.35, h: 0.25, fontSize: 9, bold: true, color: COL.soft, charSpacing: 1 });
    text(s, head, { x: x + 0.2, y: 2.45, w: w - 0.35, h: 0.55, fontSize: 15, bold: true });
    text(s, body, { x: x + 0.2, y: 3.05, w: w - 0.35, h: 1.35, fontSize: 11.5, color: COL.soft });
  });
  text(s, "Start with ./run.sh on simulated prices to learn the pages, then ./run.sh --live. Every ? explains a term.", {
    x: 0.5, y: 4.6, w: 9, h: 0.35, fontSize: 12, italic: true, color: COL.soft });
  s.addNotes("The app is built so that a non-expert can follow it without knowing the jargon. "
    + "The risk warnings are the most reliable part; the rankings are only worth following once the track record shows real skill.");
}

// ------------------------------------------------------------------ 5. pipeline

pres.addSection({ title: "How it works" });
{
  const s = content("From prices to picks", "How it works");
  const steps = [
    ["Prices", "Daily prices and volumes from Yahoo Finance, with Coinbase and Alpha Vantage as fallbacks (or a simulated market)"],
    ["Features", "Ten well-known effects, each ranked against the other assets that day"],
    ["Model", "A ridge regression learns what each effect is worth, on dates before the test period"],
    ["Score", "Assets ranked 0 to 100, with a calibrated chance to beat the field"],
    ["Portfolio", "Top picks, at most three per sector, calmer assets weighted more"],
  ];
  const w = 1.66, gap = 0.17;
  steps.forEach(([head, body], i) => {
    const x = 0.5 + i * (w + gap);
    card(s, x, 1.35, w, 2.75, i === 2 ? "E2EAF6" : COL.card);
    badge(s, x + 0.2, 1.55, String(i + 1), i === 2 ? COL.stocks : COL.ink, 0.38);
    text(s, head, { x: x + 0.2, y: 2.05, w: w - 0.35, h: 0.35, fontSize: 16, bold: true });
    text(s, body, { x: x + 0.2, y: 2.45, w: w - 0.35, h: 1.55, fontSize: 12, color: COL.soft });
    if (i < steps.length - 1) {
      s.addShape(pres.shapes.LINE, {
        x: x + w + 0.01, y: 2.72, w: gap - 0.02, h: 0, line: { color: COL.faint, width: 1.25, endArrowType: "triangle" },
      });
    }
  });
  text(s, "Retrained at every analysis, on demand or on a schedule. Stocks and crypto never share a model.", {
    x: 0.5, y: 4.35, w: 9, h: 0.5, fontSize: 13, color: COL.soft });
  s.addNotes("The key choice is comparing assets with each other on the same day, rather than predicting each price on its own: "
    + "the market's overall move is shared by every asset, so no single asset's history can predict it.");
}

// ------------------------------------------------------------------ 6. features

{
  const s = content("Ten effects with a reason to work", "How it works");
  const rows = [
    ["Short-term reversal", "Yesterday's and last week's moves tend to partly reverse"],
    ["12-month momentum", "Longer trends continue (crypto: 30 and 90 days)"],
    ["Low volatility, low beta", "Calmer assets do better than their risk suggests"],
    ["Stretched price", "Far above or below the 20-day average tends to pull back"],
    ["52-week high", "Prices near their yearly high tend to keep climbing"],
    ["Lottery returns", "Assets with sudden jumps tend to disappoint"],
    ["Volume shocks", "Quiet moves reverse more than moves on heavy volume"],
  ];
  const table = [
    [{ text: "Effect", options: { bold: true, color: COL.soft } }, { text: "Why it might predict the next week", options: { bold: true, color: COL.soft } }],
    ...rows.map(([a, b]) => [{ text: a, options: { bold: true } }, b]),
  ];
  s.addTable(table, {
    x: 0.5, y: 1.2, w: 5.9, colW: [2.1, 3.8], fontFace: FONT, fontSize: 12, color: COL.ink,
    border: { type: "solid", pt: 0.75, color: COL.grid }, fill: { color: COL.card }, rowH: 0.42, valign: "middle", margin: 0.06,
  });
  card(s, 6.7, 1.2, 2.8, 3.36, "E2EAF6");
  text(s, "Ranked every day", { x: 6.95, y: 1.4, w: 2.4, h: 0.35, fontSize: 16, bold: true });
  text(s, "Each input becomes its rank among the assets that day. Calm and turbulent periods become comparable and outliers harmless.", {
    x: 6.95, y: 1.8, w: 2.35, h: 1.3, fontSize: 12, color: COL.soft });
  text(s, "Learned from history", { x: 6.95, y: 3.05, w: 2.4, h: 0.35, fontSize: 16, bold: true });
  text(s, "The ridge regression finds each effect's weight and direction from history.", {
    x: 6.95, y: 3.45, w: 2.35, h: 0.9, fontSize: 12, color: COL.soft });
  s.addNotes("These are documented effects from the finance literature, not dozens of overlapping indicators. "
    + "The model, not a human, decides how much each is worth.");
}

// ------------------------------------------------------------------ 7. honesty

pres.addSection({ title: "Measuring honestly" });
{
  const s = content("Is it better than luck?", "Measuring honestly");
  const items = [
    ["IC", COL.stocks, "Rank IC", "Correlation between the predicted order and what actually happened. 0 is no skill; 0.02 to 0.05 is good in practice."],
    ["t", COL.up, "t-statistic", "Above about 2 the result is unlikely to be luck. The app turns it into a verdict: luck, some evidence, strong evidence."],
    ["F", COL.crypto, "No peeking at the future", "Tests use only later dates, with a gap so no training label overlaps them."],
    ["L", COL.down, "A locked period", "Experiments never see the most recent days. A winner is checked there once."],
  ];
  items.forEach(([b, color, head, body], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.5 + col * 4.6, y = 1.25 + row * 1.75;
    card(s, x, y, 4.4, 1.55);
    badge(s, x + 0.25, y + 0.25, b, color);
    text(s, head, { x: x + 0.85, y: y + 0.27, w: 3.35, h: 0.35, fontSize: 16, bold: true });
    text(s, body, { x: x + 0.85, y: y + 0.68, w: 3.35, h: 0.8, fontSize: 12, color: COL.soft });
  });
  s.addNotes("Every result is shown with its uncertainty. The live track record scores each analysis after its horizon, "
    + "so nothing can be adjusted afterwards.");
}

// ------------------------------------------------------------------ 8. results

{
  const s = content("What changed when the model was rebuilt", "Measuring honestly");
  s.addChart(pres.charts.BAR, [{
    name: "Out-of-sample rank IC",
    // Bar charts draw the first category at the bottom: listed bottom to top
    labels: ["Cross-sectional model", "Momentum score alone", "Earlier composite score"],
    values: [0.076, -0.053, 0.009],
  }], {
    x: 0.5, y: 1.15, w: 5.4, h: 3.6, barDir: "bar",
    chartColors: [COL.stocks], invertedColors: [COL.down],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "+0.000;-0.000;0", dataLabelColor: COL.ink,
    dataLabelFontFace: "+mn-lt", dataLabelFontSize: 12,
    catAxisLabelColor: COL.soft, catAxisLabelFontFace: "+mn-lt", catAxisLabelFontSize: 12, catAxisLabelPos: "low",
    valAxisLabelColor: COL.faint, valAxisLabelFontFace: "+mn-lt", valAxisLabelFontSize: 10, valAxisLabelFormatCode: "0.00",
    valAxisMinVal: -0.08, valAxisMaxVal: 0.1, valGridLine: { color: COL.grid, size: 0.5 }, catGridLine: { style: "none" },
    showLegend: false, showTitle: true, title: "Rank IC on the demo market (higher is better)",
    titleColor: COL.ink, titleFontFace: "+mn-lt", titleFontSize: 13,
  });
  card(s, 6.2, 1.15, 3.3, 3.6);
  text(s, [{ text: "+39 bp", options: { fontSize: 36, bold: true, color: COL.up, breakLine: true } },
    { text: "per week after costs in the backtest (t\u00a0=\u00a03.2)", options: { fontSize: 12, color: COL.soft } }],
  { x: 6.45, y: 1.35, w: 2.85, h: 1.2 });
  text(s, "Caveat", { x: 6.45, y: 2.75, w: 2.85, h: 0.3, fontSize: 14, bold: true });
  text(s, "The demo market has one planted signal. Real large-cap stocks are much harder: an IC of 0.02 to 0.04 would be a good result.", {
    x: 6.45, y: 3.1, w: 2.85, h: 1.5, fontSize: 12, color: COL.soft });
  s.addNotes("The earlier score averaged hand-made rules, one of which pointed the wrong way, so it cancelled out. "
    + "The rebuilt model reaches the maximum the demo market allows, and finds nothing on a market without a signal.");
}

// ------------------------------------------------------------------ 9. ranges

{
  const s = content("Where prices may be, not where they will be", "Measuring honestly");
  text(s, "Nobody can say tomorrow's price. How far it is likely to move can be forecast, and checked.", {
    x: 0.5, y: 1.05, w: 9, h: 0.35, fontSize: 14, color: COL.soft });
  // A range bar like the Forecast page
  const bx = 0.8, by = 2.05, bw = 5.2;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: bx, y: by, w: bw, h: 0.42, rectRadius: 0.06, fill: { color: "CADAF2" }, line: { color: "CADAF2" } });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: bx + 1.45, y: by, w: 2.3, h: 0.42, rectRadius: 0.06, fill: { color: COL.stocks }, line: { color: COL.stocks } });
  s.addShape(pres.shapes.LINE, { x: bx + bw / 2, y: by - 0.15, w: 0, h: 0.72, line: { color: COL.ink, width: 2 } });
  text(s, "Today's price", { x: bx + bw / 2 - 0.8, y: by + 0.65, w: 1.6, h: 0.3, fontSize: 12, align: "center", color: COL.ink });
  text(s, "Dark: half the time", { x: bx + 1.45, y: by - 0.45, w: 2.3, h: 0.3, fontSize: 12, align: "center", color: COL.stocks, bold: true });
  text(s, "Whole bar: 9 times in 10", { x: bx, y: by + 1.05, w: bw, h: 0.3, fontSize: 12, color: COL.soft });
  text(s, "Built from each asset's volatility and the size of past moves, centred on today's price. "
    + "A 70% range for the next 3 days sits between the two. Every range is scored once its window has passed.",
  { x: 0.5, y: 3.55, w: 5.8, h: 0.9, fontSize: 13, color: COL.soft });
  card(s, 6.7, 1.55, 2.8, 2.9);
  text(s, [{ text: "≈ 90%", options: { fontSize: 36, bold: true, color: COL.up, breakLine: true } },
    { text: "of the wide ranges should hold. The app shows the real share, and an alert fires if it drops below 80%.", options: { fontSize: 12, color: COL.soft } }],
  { x: 6.95, y: 1.75, w: 2.35, h: 2.5 });
  s.addNotes("Volatility is far more predictable than direction, which is why the Forecast and Volatility pages are the most reliable parts of the app.");
}

// ------------------------------------------------------------------ 10. architecture

pres.addSection({ title: "The platform" });
{
  const s = content("How it is built", "The platform");
  const layers = [
    ["Web app", "Angular: two dashboards, help on every term", "E2EAF6"],
    ["Server", "FastAPI API, plus background workers that run the analyses", COL.card],
    ["Data and models", "PostgreSQL for history; MLflow for every model version", COL.card],
    ["Prices", "Yahoo Finance, with Coinbase and Alpha Vantage as fallbacks", COL.card],
  ];
  const w = 2.1, gap = 0.2;
  layers.forEach(([head, body, fill], i) => {
    const x = 0.5 + i * (w + gap);
    card(s, x, 1.3, w, 1.85, fill);
    text(s, head, { x: x + 0.2, y: 1.5, w: w - 0.4, h: 0.4, fontSize: 16, bold: true });
    text(s, body, { x: x + 0.2, y: 1.95, w: w - 0.4, h: 1.1, fontSize: 12.5, color: COL.soft });
    if (i < layers.length - 1) {
      s.addShape(pres.shapes.LINE, { x: x + w + 0.02, y: 2.22, w: gap - 0.04, h: 0,
        line: { color: COL.faint, width: 1.25, endArrowType: "triangle", beginArrowType: "triangle" } });
    }
  });
  card(s, 0.5, 3.45, 9, 1.2, "1F2A30");
  const base = [
    ["Runs anywhere", "One command locally, or on Kubernetes with GitOps"],
    ["Watched", "Prometheus and Grafana track the service, the data and the model's skill"],
    ["Checked", "Every change is tested, scanned and deployed in CI before it reaches main"],
  ];
  base.forEach(([head, body], i) => {
    const x = 0.75 + i * 2.95;
    text(s, [{ text: head, options: { bold: true, fontSize: 14, color: "FFFFFF", breakLine: true } },
      { text: body, options: { fontSize: 11.5, color: COL.railInk } }], { x, y: 3.65, w: 2.7, h: 0.9 });
  });
  s.addNotes("Details of each component, the CI pipeline and the Kubernetes setup are in docs/ARCHITECTURE.md and docs/KUBERNETES.md.");
}

// ------------------------------------------------------------------ 11. run it

{
  const s = content("Try it", "The platform");
  const cmds = [
    ["./run.sh", "Demo mode: a simulated market, nothing to configure"],
    ["./run.sh --live", "Real prices from Yahoo Finance, kept in a separate database"],
    ["./kube.sh --live", "The full platform on a local Kubernetes cluster, with monitoring"],
  ];
  cmds.forEach(([cmd, what], i) => {
    const y = 1.25 + i * 1.05;
    card(s, 0.5, y, 9, 0.85);
    text(s, cmd, { x: 0.75, y: y + 0.22, w: 3.0, h: 0.4, fontSize: 18, bold: true, fontFace: "Courier New", color: COL.stocks });
    text(s, what, { x: 3.9, y: y + 0.25, w: 5.4, h: 0.4, fontSize: 14, color: COL.soft });
  });
  text(s, "Both scripts fetch the latest main, install what is missing, and open the app in the browser.", {
    x: 0.5, y: 4.5, w: 9, h: 0.4, fontSize: 13, italic: true, color: COL.soft });
  s.addNotes("Demo results say nothing about real markets: the simulated market has one planted signal to check the model against.");
}

// ------------------------------------------------------------------ 12. close

pres.addSection({ title: "Conclusion" });
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Conclusion" });
  text(s, "Honest by design", { x: 0.5, y: 0.55, w: 9, h: 0.7, fontSize: 32, bold: true, color: "FFFFFF" });
  const points = [
    ["Limits", "Weekly returns are mostly noise. Expect modest skill on real stocks, and judge it on the live track record over months, not days."],
    ["Next", "Months of live track record, a champion and challenger model, more data than prices (fundamentals, earnings dates), and safe hosting behind a login."],
  ];
  points.forEach(([head, body], i) => {
    const y = 1.55 + i * 1.5;
    badge(s, 0.5, y, i === 0 ? "!" : "→", i === 0 ? COL.down : COL.up);
    text(s, head, { x: 1.15, y: y + 0.02, w: 8, h: 0.4, fontSize: 18, bold: true, color: "FFFFFF" });
    text(s, body, { x: 1.15, y: y + 0.45, w: 8.2, h: 0.8, fontSize: 14, color: COL.railInk });
  });
  text(s, "github.com/elyr/stock-market-predictor · Research tool, not financial advice", {
    x: 0.5, y: 4.65, w: 9, h: 0.3, fontSize: 12, color: COL.mint });
  s.addNotes("The value of the project is in the honesty of its measurements and in the platform around the model.");
}

pres.writeFile({ fileName: path.join(__dirname, "Ledger.pptx") }).then((file) => console.log(`Wrote ${file}`));
