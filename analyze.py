"""
analyze.py
==========
Loads the sample bond universe + treasury curve, computes YTM, duration,
convexity, and spreads (G-spread, Z-spread) for every bond, then ranks
bonds within each rating bucket by relative value.

This is the "so what" step: it turns the math in bond_pricing.py into the
kind of view a credit salesperson pulls up before a morning call -- which
names look cheap or rich vs. their peers, right now.

Run:
    python analyze.py

Outputs:
    - a results table printed to console
    - results/bond_analysis.csv  (full metrics for every bond)
    - results/price_yield_curve.png  (convexity illustration for one bond)
"""

import csv
import os
from bond_pricing import (
    TreasuryCurve, bond_price, ytm_from_price,
    modified_duration, convexity, g_spread, z_spread,
)

OUT_DIR = "results"


def load_curve(path: str) -> TreasuryCurve:
    maturities, yields = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            maturities.append(float(row["maturity_years"]))
            yields.append(float(row["yield"]))
    return TreasuryCurve(maturities, yields)


def load_bonds(path: str):
    with open(path) as f:
        return list(csv.DictReader(f))


def analyze_bonds(bonds, curve: TreasuryCurve):
    results = []
    for b in bonds:
        face = 100.0
        coupon = float(b["coupon_rate"])
        maturity = float(b["years_to_maturity"])
        price = float(b["price"])

        ytm = ytm_from_price(face, coupon, maturity, price)
        mod_dur = modified_duration(face, coupon, maturity, ytm)
        conv = convexity(face, coupon, maturity, ytm)
        g_spd = g_spread(ytm, curve, maturity)
        z_spd = z_spread(face, coupon, maturity, price, curve)

        results.append({
            **b,
            "ytm_pct": round(ytm * 100, 3),
            "mod_duration": round(mod_dur, 2),
            "convexity": round(conv, 2),
            "g_spread_bps": round(g_spd, 1),
            "z_spread_bps": round(z_spd, 1),
        })
    return results


def rank_relative_value(results):
    """
    Within each (sector, rating) bucket, rank bonds by Z-spread descending.
    The widest-spread bond in a peer group is trading "cheap" (you're paid
    more for the same credit risk) -- the narrowest is trading "rich".

    This is a simplification of real relative-value work (real desks also
    adjust for liquidity, issue size, covenants, and curve position) but it
    captures the core logic: same rating + same sector + similar maturity
    should trade at similar spreads. Deviations are the trade idea.
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in results:
        buckets[(r["sector"], r["rating"])].append(r)

    for key, group in buckets.items():
        group.sort(key=lambda r: r["z_spread_bps"], reverse=True)
        for i, r in enumerate(group):
            if i == 0:
                r["relative_value"] = "CHEAPEST in peer group"
            elif i == len(group) - 1:
                r["relative_value"] = "RICHEST in peer group"
            else:
                r["relative_value"] = "in line with peers"
    return results


def print_report(results):
    header = f'{"ID":<6}{"Issuer":<24}{"Sector":<12}{"Rtg":<5}{"YTM%":>7}{"ModDur":>8}{"Conv":>7}{"Gspd":>7}{"Zspd":>7}  Relative Value'
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda r: (r["sector"], r["rating"])):
        print(f'{r["bond_id"]:<6}{r["issuer"]:<24}{r["sector"]:<12}{r["rating"]:<5}'
              f'{r["ytm_pct"]:>7}{r["mod_duration"]:>8}{r["convexity"]:>7}'
              f'{r["g_spread_bps"]:>7}{r["z_spread_bps"]:>7}  {r["relative_value"]}')


def save_csv(results, path):
    fieldnames = list(results[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def plot_price_yield_curve(bond, out_path):
    """
    Plots price vs. yield for one bond across a range of yields, to make
    convexity visible: the curve bends upward, it isn't a straight line.
    A tangent line at the current yield (the duration-only estimate) is
    also drawn so you can SEE the gap between the linear approximation and
    the true (convex) price -- that gap IS convexity.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    face = 100.0
    coupon = float(bond["coupon_rate"])
    maturity = float(bond["years_to_maturity"])
    ytm0 = float(bond["ytm_pct"]) / 100
    mod_dur = float(bond["mod_duration"])
    price0 = bond_price(face, coupon, maturity, ytm0)

    yields = np.linspace(ytm0 - 0.03, ytm0 + 0.03, 100)
    prices = [bond_price(face, coupon, maturity, y) for y in yields]

    # Duration-only linear approximation: %price change = -ModDur * delta_yield
    tangent = [price0 * (1 - mod_dur * (y - ytm0)) for y in yields]

    plt.figure(figsize=(8, 5))
    plt.plot(yields * 100, prices, label="Actual price (true convex relationship)", linewidth=2)
    plt.plot(yields * 100, tangent, label="Duration-only estimate (straight line)",
              linestyle="--", color="darkorange")
    plt.axvline(ytm0 * 100, color="gray", linestyle=":", linewidth=1)
    plt.scatter([ytm0 * 100], [price0], color="black", zorder=5, label="Current yield/price")
    plt.title(f'Price vs. Yield -- {bond["issuer"]} ({bond["bond_id"]})\n'
              f'Why convexity matters: duration alone under/overstates the price move')
    plt.xlabel("Yield (%)")
    plt.ylabel("Price")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    curve = load_curve("treasury_curve.csv")
    bonds = load_bonds("sample_bonds.csv")

    results = analyze_bonds(bonds, curve)
    results = rank_relative_value(results)

    print_report(results)

    csv_path = os.path.join(OUT_DIR, "bond_analysis.csv")
    save_csv(results, csv_path)
    print(f"\nSaved full metrics to {csv_path}")

    # Pick the bond with the highest convexity value for the illustration --
    # usually the longest-duration bond, which makes the curvature most visible.
    illustration_bond = max(results, key=lambda r: r["mod_duration"])
    png_path = os.path.join(OUT_DIR, "price_yield_curve.png")
    plot_price_yield_curve(illustration_bond, png_path)
    print(f"Saved price/yield convexity chart to {png_path}")


if __name__ == "__main__":
    main()
