from __future__ import annotations

"""Sinh SVG chart từ results/summary.csv cho báo cáo benchmark."""

import argparse
import csv
from pathlib import Path


def _read_summary(path: Path) -> list[dict[str, float]]:
    """Đọc summary.csv và ép các giá trị số về float."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = []
        for row in csv.DictReader(fh):
            rows.append({key: float(value) for key, value in row.items()})
        return rows


def _scale(value: float, source_min: float, source_max: float, target_min: float, target_max: float) -> float:
    """Ánh xạ giá trị dữ liệu sang tọa độ SVG."""
    if source_max == source_min:
        return (target_min + target_max) / 2
    ratio = (value - source_min) / (source_max - source_min)
    return target_min + ratio * (target_max - target_min)


def _svg_shell(width: int, height: int, title: str, body: str) -> str:
    """Bọc phần thân chart trong khung SVG dùng chung."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">
  <rect width="100%" height="100%" fill="#0a0c10"/>
  <text x="28" y="34" fill="#e8eaf0" font-family="Arial, sans-serif" font-size="20" font-weight="700">{title}</text>
{body}
</svg>
"""


def render_rto_line(rows: list[dict[str, float]], output: Path) -> None:
    """Vẽ line chart Mean/Median/P99 RTO."""
    width, height = 900, 460
    left, right, top, bottom = 76, 32, 66, 64
    intervals = [row["interval_min"] for row in rows]
    values = [value for row in rows for value in (row["mean_s"], row["median_s"], row["p99_s"])]
    min_x, max_x = min(intervals), max(intervals)
    max_y = max(values) * 1.15 if values else 1.0

    def x(interval: float) -> float:
        return _scale(interval, min_x, max_x, left, width - right)

    def y(value: float) -> float:
        return _scale(value, 0, max_y, height - bottom, top)

    grid = []
    for tick in range(6):
        gy = _scale(tick, 0, 5, height - bottom, top)
        label = max_y * tick / 5
        grid.append(f'  <line x1="{left}" y1="{gy:.1f}" x2="{width-right}" y2="{gy:.1f}" stroke="#1e2330"/>')
        grid.append(f'  <text x="24" y="{gy+4:.1f}" fill="#8a90a0" font-family="Arial" font-size="12">{label:.2f}s</text>')
    for interval in intervals:
        gx = x(interval)
        grid.append(f'  <text x="{gx-10:.1f}" y="{height-28}" fill="#8a90a0" font-family="Arial" font-size="12">{interval:g}</text>')

    series = [
        ("mean_s", "#00ff88", "Mean"),
        ("median_s", "#4da6ff", "Median"),
        ("p99_s", "#ffaa00", "P99"),
    ]
    lines = []
    for index, (field, color, label) in enumerate(series):
        points = " ".join(f'{x(row["interval_min"]):.1f},{y(row[field]):.1f}' for row in rows)
        lines.append(f'  <polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"/>')
        for row in rows:
            lines.append(f'  <circle cx="{x(row["interval_min"]):.1f}" cy="{y(row[field]):.1f}" r="4" fill="{color}"/>')
        lines.append(f'  <rect x="{width-210}" y="{82 + index*24}" width="12" height="12" fill="{color}"/>')
        lines.append(f'  <text x="{width-190}" y="{93 + index*24}" fill="#d8dbe3" font-family="Arial" font-size="13">{label}</text>')

    body = "\n".join(
        [
            *grid,
            f'  <line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#4a5060"/>',
            f'  <line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#4a5060"/>',
            '  <text x="390" y="434" fill="#d8dbe3" font-family="Arial" font-size="13">Checkpoint interval (minutes)</text>',
            '  <text x="18" y="238" fill="#d8dbe3" font-family="Arial" font-size="13" transform="rotate(-90 18 238)">Recovery time</text>',
            *lines,
        ]
    )
    output.write_text(_svg_shell(width, height, "RTO vs Checkpoint Interval", body), encoding="utf-8")


def render_cost_bars(rows: list[dict[str, float]], output: Path) -> None:
    """Vẽ stacked bar cho I/O, CPU và communication cost."""
    width, height = 900, 460
    left, right, top, bottom = 76, 34, 66, 64
    totals = [row["io_cost"] + row["cpu_cost"] + row["comm_cost"] for row in rows]
    max_total = max(totals) * 1.15 if totals else 1.0
    bar_width = min(86, (width - left - right) / max(1, len(rows)) * 0.58)
    gap = (width - left - right) / max(1, len(rows))

    parts = [("io_cost", "#4da6ff", "IO"), ("cpu_cost", "#00ff88", "CPU"), ("comm_cost", "#ffaa00", "Comm")]
    elements = []
    for tick in range(6):
        gy = _scale(tick, 0, 5, height - bottom, top)
        label = max_total * tick / 5
        elements.append(f'  <line x1="{left}" y1="{gy:.1f}" x2="{width-right}" y2="{gy:.1f}" stroke="#1e2330"/>')
        elements.append(f'  <text x="22" y="{gy+4:.1f}" fill="#8a90a0" font-family="Arial" font-size="12">{label:.0f}</text>')

    for idx, row in enumerate(rows):
        x0 = left + idx * gap + (gap - bar_width) / 2
        baseline = height - bottom
        for field, color, _label in parts:
            bar_h = (row[field] / max_total) * (height - bottom - top)
            y0 = baseline - bar_h
            elements.append(f'  <rect x="{x0:.1f}" y="{y0:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" fill="{color}"/>')
            baseline = y0
        elements.append(f'  <text x="{x0+bar_width/2-8:.1f}" y="{height-28}" fill="#8a90a0" font-family="Arial" font-size="12">{row["interval_min"]:g}</text>')

    for index, (_field, color, label) in enumerate(parts):
        elements.append(f'  <rect x="{width-210}" y="{82 + index*24}" width="12" height="12" fill="{color}"/>')
        elements.append(f'  <text x="{width-190}" y="{93 + index*24}" fill="#d8dbe3" font-family="Arial" font-size="13">{label}</text>')

    body = "\n".join(
        [
            *elements,
            f'  <line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#4a5060"/>',
            f'  <line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#4a5060"/>',
            '  <text x="390" y="434" fill="#d8dbe3" font-family="Arial" font-size="13">Checkpoint interval (minutes)</text>',
            '  <text x="20" y="238" fill="#d8dbe3" font-family="Arial" font-size="13" transform="rotate(-90 20 238)">Estimated cost units</text>',
        ]
    )
    output.write_text(_svg_shell(width, height, "Cost Breakdown by Interval", body), encoding="utf-8")


def render_heatmap(rows: list[dict[str, float]], output: Path) -> None:
    """Vẽ heatmap nhỏ cho Median/Mean/P99 RTO."""
    width, height = 820, 360
    left, top = 110, 72
    cell_w, cell_h = 86, 42
    max_value = max((row["p99_s"] for row in rows), default=1.0)
    min_value = min((row["median_s"] for row in rows), default=0.0)
    metrics = [("median_s", "Median"), ("mean_s", "Mean"), ("p99_s", "P99")]
    elements = []
    for yidx, (_field, label) in enumerate(metrics):
        y0 = top + yidx * cell_h
        elements.append(f'  <text x="34" y="{y0+26}" fill="#d8dbe3" font-family="Arial" font-size="13">{label}</text>')
    for xidx, row in enumerate(rows):
        x0 = left + xidx * cell_w
        elements.append(f'  <text x="{x0+28}" y="56" fill="#8a90a0" font-family="Arial" font-size="12">{row["interval_min"]:g}m</text>')
        for yidx, (field, _label) in enumerate(metrics):
            value = row[field]
            ratio = _scale(value, min_value, max_value, 0.18, 1.0)
            red = int(255 * ratio)
            green = int(255 * (1 - ratio) * 0.75 + 80)
            color = f"#{red:02x}{green:02x}55"
            y0 = top + yidx * cell_h
            elements.append(f'  <rect x="{x0}" y="{y0}" width="{cell_w-8}" height="{cell_h-8}" rx="4" fill="{color}"/>')
            elements.append(f'  <text x="{x0+18}" y="{y0+23}" fill="#0a0c10" font-family="Arial" font-size="12" font-weight="700">{value:.3f}s</text>')
    elements.append('  <text x="310" y="312" fill="#d8dbe3" font-family="Arial" font-size="13">Lower values are greener; higher tail latency is warmer.</text>')
    output.write_text(_svg_shell(width, height, "RTO Metric Heatmap", "\n".join(elements)), encoding="utf-8")


def generate_charts(summary_path: Path, output_dir: Path) -> list[Path]:
    """Sinh toàn bộ SVG chart từ summary hiện có."""
    rows = _read_summary(summary_path)
    if not rows:
        raise ValueError(f"no rows found in {summary_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        output_dir / "rto_vs_interval.svg",
        output_dir / "cost_breakdown.svg",
        output_dir / "rto_heatmap.svg",
    ]
    render_rto_line(rows, outputs[0])
    render_cost_bars(rows, outputs[1])
    render_heatmap(rows, outputs[2])
    return outputs


def main() -> None:
    """Entry point CLI để regenerate chart artifact."""
    parser = argparse.ArgumentParser(description="Generate SVG charts from benchmark summary.csv.")
    parser.add_argument("--summary", type=Path, default=Path("results/summary.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/charts"))
    args = parser.parse_args()
    for output in generate_charts(args.summary, args.output_dir):
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
