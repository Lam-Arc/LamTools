"""Algorithmic scoring of all three modes."""
import json

WEIGHTS = {"low": (3, 4, 3), "high": (1, 5, 4), "max": (0, 5, 5)}

datasets = {
    "low": {"mode": "low", "candidates": [
        {"name": "Vanilla HTML+CSS+JS + localStorage", "cost": 5, "quality": 2, "upgrade": 2},
        {"name": "Alpine.js CDN + localStorage", "cost": 4, "quality": 3, "upgrade": 3},
        {"name": "Vue 3 CDN + localStorage", "cost": 3, "quality": 4, "upgrade": 4},
        {"name": "React CDN + localStorage", "cost": 2, "quality": 4, "upgrade": 3},
    ]},
    "high": {"mode": "high", "candidates": [
        {"name": "Vanilla JS + localStorage", "cost": 4, "quality": 2, "upgrade": 2},
        {"name": "Vue 3 CDN + localStorage", "cost": 4, "quality": 4, "upgrade": 4},
        {"name": "React CDN + localStorage", "cost": 3, "quality": 4, "upgrade": 4},
        {"name": "HTML + IndexedDB", "cost": 2, "quality": 3, "upgrade": 3},
    ]},
    "max": {"mode": "max", "candidates": [
        {"name": "React + Express + SQLite", "cost": 3, "quality": 5, "upgrade": 5},
        {"name": "Vue 3 + Express + SQLite", "cost": 3, "quality": 4, "upgrade": 4},
        {"name": "Vanilla JS + IndexedDB", "cost": 5, "quality": 2, "upgrade": 1},
        {"name": "Next.js + SQLite", "cost": 2, "quality": 4, "upgrade": 3},
    ]},
}

print("=" * 60)
print("ALGORITHMIC SCORING RESULTS")
print("=" * 60)

for mode_name, data in datasets.items():
    cw, qw, uw = WEIGHTS[mode_name]
    formula = f"(5-cost)*{cw} + quality*{qw} + upgrade*{uw}"
    print(f"\n── {mode_name.upper()} — formula: {formula} ──")

    for c in data["candidates"]:
        cost_contrib = (5 - c["cost"]) * cw
        qual_contrib = c["quality"] * qw
        upg_contrib = c["upgrade"] * uw
        c["score"] = cost_contrib + qual_contrib + upg_contrib

    data["candidates"].sort(key=lambda x: x["score"], reverse=True)

    for i, c in enumerate(data["candidates"]):
        marker = "  WINNER" if i == 0 else ""
        gap = f" ({data['candidates'][0]['score'] - c['score']} pts behind)" if i > 0 else ""
        print(f"  {c['score']:3d}  cost={c['cost']} qual={c['quality']} upg={c['upgrade']}  {c['name']}{marker}{gap}")

    if len(data["candidates"]) > 1:
        print(f"  Gap: {data['candidates'][0]['score'] - data['candidates'][1]['score']} pts")

print(f"\n{'=' * 60}")
print("SUMMARY")
print(f"{'=' * 60}")
for mode_name, data in datasets.items():
    w = data["candidates"][0]
    w2 = data["candidates"][1] if len(data["candidates"]) > 1 else None
    r2 = f", runner-up: {w2['name']} ({w2['score']})" if w2 else ""
    print(f"  {mode_name.upper()}: {w['name']} ({w['score']}){r2}")
