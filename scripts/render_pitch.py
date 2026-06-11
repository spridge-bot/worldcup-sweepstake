#!/usr/bin/env python3
"""Render aerial pitch PNGs with mplsoccer.

Usage: render_pitch.py payload.json out.png "Home Name" "Away Name" [mode]

mode "positions" (default): payload {"home": [{name, shirt, x, y}], "away": [...]}
mode "shots":               payload {"shots": [{player, team, type, xg, x, y, minute}]}

Coordinates are Sofascore/Opta style (0-100). Shot x is the distance from the
goal being attacked, so home shots are drawn at the right goal (100 - x) and
away shots at the left. Needs Python >= 3.10 (run via the .venv-pitch venv).
"""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from mplsoccer import Pitch

BG, LINE = "#0a1f12", "#2a5a3e"
HOME, AWAY = "#36d97c", "#f5c542"


def base_pitch():
    pitch = Pitch(pitch_type="opta", pitch_color=BG, line_color=LINE, linewidth=1.4)
    fig, ax = pitch.draw(figsize=(8, 5.4))
    fig.patch.set_facecolor(BG)
    return pitch, fig, ax


def draw_positions(positions, home, away):
    pitch, fig, ax = base_pitch()
    for side, color in (("home", HOME), ("away", AWAY)):
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
    return fig


SHOT_MARKERS = {"goal": "*", "save": "o", "block": "s", "miss": "X", "post": "P"}


def draw_shots(shots, home, away):
    pitch, fig, ax = base_pitch()
    for s in shots:
        x, y = s.get("x"), s.get("y")
        if x is None or y is None:
            continue
        # x = distance from the attacked goal; home attacks right, away left
        if s["team"] == "home":
            px, py = 100 - x, y
            color = HOME
        else:
            px, py = x, 100 - y
            color = AWAY
        goal = s.get("type") == "goal"
        size = 140 + (s.get("xg") or 0.05) * 900
        pitch.scatter([px], [py], s=size * (1.6 if goal else 1),
                      marker=SHOT_MARKERS.get(s.get("type"), "o"),
                      color=color, edgecolors="#ffffff" if goal else "#04150b",
                      linewidth=1.6 if goal else 1.0, alpha=0.95 if goal else 0.75,
                      ax=ax, zorder=4 if goal else 3)
        if goal and s.get("player"):
            ax.text(px, py - 5, f"{s['player']} {s.get('minute') or ''}'",
                    ha="center", va="center", fontsize=6.5, color="#eef5ef", zorder=5)
    legend = [Line2D([], [], marker="*", color=BG, markerfacecolor="#fff",
                     markersize=11, label="Goal"),
              Line2D([], [], marker="o", color=BG, markerfacecolor="#9ca3af",
                     markersize=8, label="Saved"),
              Line2D([], [], marker="s", color=BG, markerfacecolor="#9ca3af",
                     markersize=7, label="Blocked"),
              Line2D([], [], marker="X", color=BG, markerfacecolor="#9ca3af",
                     markersize=8, label="Off target")]
    ax.legend(handles=legend, loc="lower center", ncol=4, frameon=False,
              fontsize=7, labelcolor="#8fb39d", bbox_to_anchor=(0.5, -0.08))
    ax.set_title(f"{home} (green)   ·   shot map, size = xG   ·   {away} (gold)",
                 color="#8fb39d", fontsize=10, pad=10)
    return fig


def main():
    payload_file, out_path, home, away = sys.argv[1:5]
    mode = sys.argv[5] if len(sys.argv) > 5 else "positions"
    payload = json.loads(open(payload_file).read())
    if mode == "shots":
        fig = draw_shots(payload.get("shots") or [], home, away)
    else:
        fig = draw_positions(payload, home, away)
    fig.savefig(out_path, dpi=115, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


if __name__ == "__main__":
    main()
