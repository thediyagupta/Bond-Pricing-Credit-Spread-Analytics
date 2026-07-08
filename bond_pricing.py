"""
bond_pricing.py
================
Core bond-math library: price, yield-to-maturity, duration, convexity,
and credit spreads (G-spread and Z-spread).

Everything here is built from first principles (no QuantLib, no black-box
finance libraries) on purpose -- the goal of this project is to make you
understand *why* each number is what it is, since that's what you'll be
expected to reason about on a credit sales desk.

All bonds are assumed to be plain-vanilla, fixed-coupon, non-callable
bonds unless stated otherwise. That's a deliberate simplification --
callable bonds need option-adjusted spread (OAS), which requires an
interest-rate model and is out of scope for a one-week foundation build.
See the README for how OAS relates to Z-spread conceptually.
"""

from dataclasses import dataclass
from typing import List, Tuple


# ---------------------------------------------------------------------------
# 1. CASH FLOWS
# ---------------------------------------------------------------------------

def generate_cashflows(face: float, coupon_rate: float, years_to_maturity: float,
                        freq: int = 2) -> List[Tuple[float, float]]:
    """
    Build the bond's cash flow schedule.

    Returns a list of (time_in_years, cashflow_amount) tuples.
    Every period pays a coupon; the final period also repays face value.

    face            : face / par value, e.g. 100
    coupon_rate     : ANNUAL coupon rate as a decimal, e.g. 0.05 for 5%
    years_to_maturity: time to maturity in years, e.g. 7.5
    freq            : coupon payments per year (2 = semi-annual, the market convention
                       for most USD and INR corporate bonds)
    """
    n_periods = round(years_to_maturity * freq)
    coupon_payment = face * coupon_rate / freq

    cashflows = []
    for i in range(1, n_periods + 1):
        t = i / freq
        cf = coupon_payment
        if i == n_periods:
            cf += face  # principal repaid with the last coupon
        cashflows.append((t, cf))
    return cashflows


# ---------------------------------------------------------------------------
# 2. PRICING (present value of cash flows)
# ---------------------------------------------------------------------------

def bond_price(face: float, coupon_rate: float, years_to_maturity: float,
               ytm: float, freq: int = 2) -> float:
    """
    Price a bond given its yield-to-maturity (YTM).

    This is just a discounted cash flow: every coupon and the principal
    are discounted back to today at a single flat rate (the YTM), compounded
    at the coupon frequency. This is the "clean price" (no accrued interest).

    ytm : ANNUAL yield as a decimal, e.g. 0.06 for 6%
    """
    cashflows = generate_cashflows(face, coupon_rate, years_to_maturity, freq)
    periodic_rate = ytm / freq

    price = 0.0
    for t, cf in cashflows:
        n = t * freq  # which period number this cash flow falls in
        price += cf / (1 + periodic_rate) ** n
    return price


def ytm_from_price(face: float, coupon_rate: float, years_to_maturity: float,
                    price: float, freq: int = 2, tol: float = 1e-8) -> float:
    """
    Back out YTM from a given market price using bisection search.

    Why bisection instead of a closed-form formula: there is no closed-form
    solution for YTM (it's the root of a polynomial), so every real pricing
    system solves it numerically. Bisection is the simplest reliable method
    to understand -- Newton's method converges faster but can be unstable
    for extreme inputs, which matters less for a learning tool than clarity.
    """
    lo, hi = -0.5, 2.0  # search between -50% and +200% yield -- generous bounds
    for _ in range(200):
        mid = (lo + hi) / 2
        implied_price = bond_price(face, coupon_rate, years_to_maturity, mid, freq)
        if abs(implied_price - price) < tol:
            return mid
        # price and yield move in opposite directions
        if implied_price > price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# 3. DURATION & CONVEXITY (interest-rate risk measures)
# ---------------------------------------------------------------------------

def macaulay_duration(face: float, coupon_rate: float, years_to_maturity: float,
                       ytm: float, freq: int = 2) -> float:
    """
    Macaulay duration: the weighted-average time (in years) until you get
    your money back, where each cash flow's weight is its share of the
    bond's present value.

    Intuition: a zero-coupon bond's Macaulay duration equals its maturity
    (you get 100% of your cash back at one point in time). A coupon bond's
    duration is always LESS than its maturity, because you get some cash
    back earlier via coupons.
    """
    cashflows = generate_cashflows(face, coupon_rate, years_to_maturity, freq)
    periodic_rate = ytm / freq
    price = bond_price(face, coupon_rate, years_to_maturity, ytm, freq)

    weighted_time = 0.0
    for t, cf in cashflows:
        n = t * freq
        pv = cf / (1 + periodic_rate) ** n
        weighted_time += t * pv
    return weighted_time / price


def modified_duration(face: float, coupon_rate: float, years_to_maturity: float,
                       ytm: float, freq: int = 2) -> float:
    """
    Modified duration: the % price change for a 1% (100bp) change in yield.
    This is the number a salesperson actually quotes -- "this bond has
    5.2 years of duration" means a 100bp yield move moves the price ~5.2%.

    Formula: ModDur = MacDur / (1 + ytm/freq)
    """
    mac_dur = macaulay_duration(face, coupon_rate, years_to_maturity, ytm, freq)
    return mac_dur / (1 + ytm / freq)


def convexity(face: float, coupon_rate: float, years_to_maturity: float,
              ytm: float, freq: int = 2) -> float:
    """
    Convexity: measures how much duration ITSELF changes as yields move --
    i.e. the curvature of the price/yield relationship.

    Why it matters: duration alone is a straight-line (linear) approximation
    of price sensitivity. Real bond prices curve -- they rise more than
    duration predicts when yields fall, and fall less than duration predicts
    when yields rise. Positive convexity is a feature buyers like; it's why,
    all else equal, higher-convexity bonds trade at a slight premium
    (lower yield) versus lower-convexity bonds of the same duration.

    Computed here numerically (bump yield up and down, see how duration /
    price responds) rather than via the closed-form formula, because the
    numerical approach is easier to build intuition for and generalizes to
    bonds with unusual cash flow patterns.
    """
    bump = 0.0001  # 1 basis point
    price_base = bond_price(face, coupon_rate, years_to_maturity, ytm, freq)
    price_up = bond_price(face, coupon_rate, years_to_maturity, ytm + bump, freq)
    price_down = bond_price(face, coupon_rate, years_to_maturity, ytm - bump, freq)

    # Second derivative of price w.r.t. yield, normalized by price
    conv = (price_up + price_down - 2 * price_base) / (price_base * bump ** 2)
    return conv


# ---------------------------------------------------------------------------
# 4. TREASURY / BENCHMARK CURVE (for spread calculations)
# ---------------------------------------------------------------------------

@dataclass
class TreasuryCurve:
    """A simple par-yield curve, e.g. {1: 0.048, 2: 0.045, 5: 0.043, 10: 0.044, 30: 0.046}"""
    maturities: List[float]
    yields: List[float]

    def yield_at(self, maturity: float) -> float:
        """Linearly interpolate the curve to get a yield at any maturity."""
        pts = sorted(zip(self.maturities, self.yields))
        if maturity <= pts[0][0]:
            return pts[0][1]
        if maturity >= pts[-1][0]:
            return pts[-1][1]
        for (m1, y1), (m2, y2) in zip(pts, pts[1:]):
            if m1 <= maturity <= m2:
                weight = (maturity - m1) / (m2 - m1)
                return y1 + weight * (y2 - y1)
        return pts[-1][1]

    def discount_factor(self, t: float) -> float:
        """Discount factor at time t using the interpolated zero-ish curve
        (treated as continuously-compounding for simplicity in Z-spread calc)."""
        y = self.yield_at(t)
        return 1 / (1 + y) ** t


# ---------------------------------------------------------------------------
# 5. SPREADS -- the vocabulary you'll actually use on the desk
# ---------------------------------------------------------------------------

def g_spread(bond_ytm: float, curve: TreasuryCurve, years_to_maturity: float) -> float:
    """
    G-spread: the simplest, most-quoted spread measure.
    Bond's YTM minus the interpolated government-bond yield at the SAME
    maturity. Expressed in basis points (bps) by convention.

    Use case: "quick and dirty" relative value -- how much extra yield am
    I getting for taking on this issuer's credit risk vs. the risk-free rate?
    Limitation: uses a single YTM number, so it ignores the *shape* of the
    curve and doesn't account for how cash flows are spread through time.
    """
    tsy_yield = curve.yield_at(years_to_maturity)
    return (bond_ytm - tsy_yield) * 10000  # in bps


def z_spread(face: float, coupon_rate: float, years_to_maturity: float,
             price: float, curve: TreasuryCurve, freq: int = 2,
             tol: float = 1e-6) -> float:
    """
    Z-spread ("zero-volatility spread"): the constant spread that, when
    added to EVERY point on the government zero curve, makes the present
    value of the bond's cash flows equal to its market price.

    Why it's better than G-spread: G-spread only looks at one point on the
    curve (the bond's maturity). Z-spread discounts each individual cash
    flow at that cash flow's OWN maturity point on the curve, then finds
    the single spread that reconciles the whole cash flow schedule to the
    market price. This matters more for longer-dated, higher-coupon bonds
    where a lot of value arrives well before final maturity.

    OAS (option-adjusted spread) note: for a plain bullet bond with no
    embedded call/put option, OAS == Z-spread. OAS only diverges from
    Z-spread when the bond is callable/putable, because OAS strips out the
    value of that embedded option using an interest-rate model (binomial
    tree / Monte Carlo). We don't model that here -- see README.
    """
    cashflows = generate_cashflows(face, coupon_rate, years_to_maturity, freq)

    def price_given_spread(spread: float) -> float:
        pv = 0.0
        for t, cf in cashflows:
            curve_yield = curve.yield_at(t)
            discount_rate = curve_yield + spread
            pv += cf / (1 + discount_rate) ** t
        return pv

    # bisection search over spread, same logic as ytm_from_price
    lo, hi = -0.10, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        implied_price = price_given_spread(mid)
        if abs(implied_price - price) < tol:
            return mid * 10000  # bps
        if implied_price > price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 * 10000
