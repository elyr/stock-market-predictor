import {
  AfterViewInit, Component, ElementRef, OnDestroy, effect, input, viewChild,
} from '@angular/core';
import {
  BarController, BarElement, CategoryScale, Chart, ChartConfiguration, Filler, Legend, LineController,
  LineElement, LinearScale, PointElement, Tooltip,
} from 'chart.js';

Chart.register(LineController, LineElement, PointElement, BarController, BarElement, CategoryScale,
  LinearScale, Filler, Legend, Tooltip);

/** Thin Chart.js wrapper: re-renders whenever the configuration input changes. */
@Component({
  selector: 'app-chart',
  template: `<div class="chart-box" [style.height.px]="height()">
    <canvas #canvas role="img" [attr.aria-label]="label()"></canvas>
  </div>`,
  styles: `.chart-box { position: relative; width: 100%; }`,
})
export class ChartComponent implements AfterViewInit, OnDestroy {
  readonly config = input.required<ChartConfiguration>();
  readonly height = input(280);
  readonly label = input('Chart');

  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private chart?: Chart;
  private ready = false;

  constructor() {
    effect(() => {
      const config = this.config();
      if (this.ready) this.render(config);
    });
  }

  ngAfterViewInit(): void {
    this.ready = true;
    this.render(this.config());
  }

  private render(config: ChartConfiguration): void {
    this.chart?.destroy();
    if (typeof window === 'undefined' || !this.canvas().nativeElement.getContext) return;
    try {
      this.chart = new Chart(this.canvas().nativeElement, config);
    } catch {
      // Canvas is unavailable (e.g. in unit tests without a canvas implementation)
    }
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }
}

/** Read the current theme tokens so charts match light and dark mode. */
export function themeColors() {
  const style = getComputedStyle(document.documentElement);
  const accentHost = document.querySelector('.theme-crypto, .theme-stocks') ?? document.documentElement;
  const accentStyle = getComputedStyle(accentHost);
  const read = (s: CSSStyleDeclaration, name: string, fallback: string) => s.getPropertyValue(name).trim() || fallback;
  return {
    ink: read(style, '--ink', '#1d2a33'),
    paper: read(style, '--paper', '#f3f5f2'),
    soft: read(style, '--ink-soft', '#4d5b64'),
    faint: read(style, '--ink-faint', '#7b878e'),
    grid: read(style, '--grid', '#d5dcd6'),
    up: read(style, '--up', '#1f7a5c'),
    down: read(style, '--down', '#b23a48'),
    luck: read(style, '--luck', '#e7ebe6'),
    accent: read(accentStyle, '--accent', '#2c5da8'),
    accentWash: read(accentStyle, '--accent-wash', '#e2eaf6'),
  };
}

/**
 * Shared chart styling: thin 2 px lines without dots (a dot appears on hover),
 * bars no wider than 24 px with rounded ends, hairline solid gridlines, a
 * recessive axis, and one tooltip listing every series at the hovered date.
 */
export function baseOptions(yFormat: (v: number) => string) {
  const c = themeColors();
  const font = { family: 'Public Sans' };
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false as const,
    interaction: { mode: 'index' as const, intersect: false },
    elements: {
      line: { borderWidth: 2, tension: 0 },
      point: { radius: 0, hoverRadius: 4, hitRadius: 12 },
      bar: { borderRadius: 4, maxBarThickness: 24 },
    },
    plugins: {
      legend: { labels: { color: c.soft, usePointStyle: true, pointStyle: 'line' as const, boxWidth: 18, padding: 14, font } },
      tooltip: {
        backgroundColor: c.ink, titleColor: c.paper, bodyColor: c.paper, padding: 10, cornerRadius: 6,
        boxPadding: 4, usePointStyle: true, titleFont: { ...font, weight: 'bold' as const }, bodyFont: font,
        callbacks: { label: (ctx: { dataset: { label?: string }; parsed: { y: number | null } }) =>
          `${ctx.dataset.label}: ${ctx.parsed.y == null ? '–' : yFormat(ctx.parsed.y)}` },
      },
    },
    scales: {
      x: { grid: { display: false }, border: { color: c.grid }, ticks: { color: c.faint, maxTicksLimit: 8, font } },
      y: { grid: { color: c.grid, lineWidth: 1 }, border: { display: false },
        ticks: { color: c.faint, padding: 6, callback: (v: string | number) => yFormat(Number(v)), font } },
    },
  };
}
