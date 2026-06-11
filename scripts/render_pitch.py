#!/usr/bin/env python3
"""Render an aerial average-positions pitch with mplsoccer.

Usage: render_pitch.py positions.json out.png "Home Name" "Away Name"

positions.json: {"home": [{"name", "shirt", "x", "y"}, ...], "away": [...]}
Coordinates are Sofascore/Opta style (0-100 along both axes, attacking right).
Needs Python >= 3.10 (run via the .venv-pitch venv; see sofascore_live.py).
"""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mplsoccer import Pitch


def main():
    pos_file, out_path, home, away = sys.argv[1:5]
    positions = json.loads(open(pos_file).read())

    pitch = Pitch(pitch_type="opta", pitch_color="#0a1f12", line_color="#2a5a3e",
                  linewidth=1.4)
    fig, ax = pitch.draw(figsize=(8, 5.4))
    fig.patch.set_facecolor("#0a1f12")
    for side, color in (("home", "#36d97c"), ("away", "#f5c542")):
        for p in positions.get(side, []):
            x, y = p["x"], p["y"]
            if side == "away":            # mirror so the teams face each other
                x, y = 100 - x, 100 - y
            pitch.scatter([x], [y], s=300, color=color, edgecolors="#04150b",
                          linewidth=1.4, ax=ax, zorder=3)
            if p.get("shirt"):
                ax.text(x, y, str(p["shirt"]), ha="center", va="center",
                        fontsize=7.5, fontweight="bold", color="#04150b", zorder=4)
            ax.text(x, y - 4.4, (p.get("name") or "").split(" ")[-1][:11],
                    ha="center", va="center", fontsize=6, color="#eef5ef", zorder=4)
    ax.set_title(f"{home} (green)     ·     average positions     ·     {away} (gold)",
                 color="#8fb39d", fontsize=10, pad=10)
    fig.savefig(out_path, dpi=115, bbox_inches="tight", facecolor="#0a1f12")
    plt.close(fig)


if __name__ == "__main__":
    main()
