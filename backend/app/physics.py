"""Physics engine for build-sim.

Improvements over the original single-file model:
- Thrust curves interpolate in throttle^2 space (thrust ~ RPM^2), amps in
  throttle^2 space, watts in throttle^3 space — exact for idealized curves and
  much closer to real bench data between sparse points.
- Battery internal-resistance sag model: pack voltage droops under load, which
  reduces thrust and raises hover throttle. The hover point is found with an
  outer bisection on throttle and an inner fixed-point solve for the sagged
  operating point.
- Flight time is computed from the pack current at the sagged hover point,
  not from a fixed nominal-voltage Wh/power estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NOMINAL_V = 3.7       # per-cell nominal (curve reference voltage)
FULL_V = 4.2          # per-cell full charge
CUTOFF_V = 3.3        # per-cell under-load cutoff
USABLE_FRACTION = 0.80  # usable capacity to ~3.5V/cell resting
BASE_RIGGING_G = 22.0   # fc/esc/wiring/rx/straps baseline
COAX_FACTOR = 0.80      # coax stack thrust loss
HOVER_CEILING_PCT = 85.0  # throttle ceiling used for spare-lift calc

# Curve columns
C_THR, C_GRAMS, C_AMPS, C_WATTS = 0, 1, 2, 3


@dataclass
class Motor:
    name: str
    rated_cells: int
    mass_g: float
    curve: list[tuple[float, float, float, float]]  # (thr%, grams, amps, watts) @ rated voltage
    props: list[str] = field(default_factory=list)


@dataclass
class Frame:
    name: str
    mass_g: float
    motors: int
    coax: bool
    frame_class: str  # 'sub250' | 'freestyle' | 'heavy'


@dataclass
class Pack:
    name: str
    cells: int
    mah: float
    mass_g: float
    chemistry: str            # 'lipo' | 'li-ion'
    ir_mohm_per_cell: float   # internal resistance, milliohms per cell


@dataclass
class Payload:
    name: str
    mass_g: float


def _shaped_interp(curve: list[tuple[float, ...]], throttle: float, col: int, exponent: float) -> float:
    """Interpolate `col` against throttle**exponent.

    Thrust and current track ~t^2, power ~t^3, so linear interpolation in the
    shaped domain is far more accurate than raw linear interpolation.
    """
    pts = sorted(curve, key=lambda p: p[C_THR])
    xs = [p[C_THR] ** exponent for p in pts]
    ys = [p[col] for p in pts]
    x = throttle ** exponent
    if x <= xs[0]:
        # scale back from first known point rather than returning it flat
        if xs[0] == 0:
            return ys[0]
        return ys[0] * (x / xs[0])
    if x >= xs[-1]:
        return ys[-1] * (x / xs[-1]) if throttle > pts[-1][C_THR] else ys[-1]
    for i in range(len(pts) - 1):
        if xs[i] <= x <= xs[i + 1]:
            f = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + f * (ys[i + 1] - ys[i])
    return ys[-1]


def thrust_g(curve, throttle) -> float:
    return _shaped_interp(curve, throttle, C_GRAMS, 2.0)


def amps(curve, throttle) -> float:
    return _shaped_interp(curve, throttle, C_AMPS, 2.0)


def watts(curve, throttle) -> float:
    return _shaped_interp(curve, throttle, C_WATTS, 3.0)


def _voltage_scale(v_actual: float, v_rated: float) -> float:
    """Thrust scales ~V^2 for a fixed prop/motor (RPM ~ V, thrust ~ RPM^2)."""
    r = v_actual / v_rated
    return r * r


@dataclass
class OperatingPoint:
    throttle: float
    voltage_per_cell: float
    thrust_total_g: float
    current_total_a: float
    power_total_w: float


def operating_point(motor: Motor, pack: Pack, n_motors: int, throttle: float,
                    coax: bool, soc_v: float = NOMINAL_V, iterations: int = 12) -> OperatingPoint:
    """Solve the sagged operating point at a given throttle.

    Fixed-point: guess per-cell voltage -> scale thrust/amps from the bench
    curve (measured at rated voltage) -> pack current -> IR sag -> new voltage.
    """
    v_rated = motor.rated_cells * NOMINAL_V
    ir_pack = pack.ir_mohm_per_cell * pack.cells / 1000.0  # ohms
    v_cell = soc_v
    coax_f = COAX_FACTOR if coax else 1.0

    for _ in range(iterations):
        scale = _voltage_scale(v_cell * pack.cells, v_rated)
        per_motor_thrust = thrust_g(motor.curve, throttle) * scale
        # current scales ~linearly with voltage at fixed throttle duty
        per_motor_amps = amps(motor.curve, throttle) * (v_cell * pack.cells / v_rated)
        i_total = n_motors * per_motor_amps
        v_pack = soc_v * pack.cells - i_total * ir_pack
        v_cell_new = max(v_pack / pack.cells, CUTOFF_V)
        if abs(v_cell_new - v_cell) < 1e-4:
            v_cell = v_cell_new
            break
        v_cell = v_cell_new

    scale = _voltage_scale(v_cell * pack.cells, v_rated)
    thrust_total = n_motors * thrust_g(motor.curve, throttle) * scale * coax_f
    i_total = n_motors * amps(motor.curve, throttle) * (v_cell * pack.cells / v_rated)
    watts_total = i_total * v_cell * pack.cells
    return OperatingPoint(throttle, v_cell, thrust_total, i_total, watts_total)


@dataclass
class BuildResult:
    auw_g: float
    twr: float
    max_thrust_g: float
    hover_throttle: float | None
    can_hover: bool
    hover_power_w: float
    hover_current_a: float
    hover_v_cell: float
    pack_wh: float
    flight_min: float
    carry_g: float
    n_motors: int
    cell_mismatch: int
    sub250: bool
    frame_class: str
    pack_chemistry: str
    warnings: list[str]


def simulate(motor: Motor, frame: Frame, pack: Pack, payload: Payload,
             rigging_g: float = BASE_RIGGING_G) -> BuildResult:
    n = frame.motors
    coax = frame.coax
    auw = n * motor.mass_g + frame.mass_g + pack.mass_g + payload.mass_g + rigging_g
    cell_mismatch = abs(pack.cells - motor.rated_cells)

    # Max thrust / TWR at full charge (4.2V/cell) with sag
    full = operating_point(motor, pack, n, 100.0, coax, soc_v=FULL_V)
    max_thrust = full.thrust_total_g
    twr = max_thrust / auw

    # Hover: bisection on throttle until total thrust == AUW, at mid-pack voltage
    can_hover = False
    hover_thr = None
    hover_pt = None
    if full.thrust_total_g > auw:
        lo, hi = 1.0, 100.0
        for _ in range(40):
            mid = (lo + hi) / 2
            pt = operating_point(motor, pack, n, mid, coax)
            if pt.thrust_total_g >= auw:
                hi = mid
            else:
                lo = mid
        hover_thr = hi
        hover_pt = operating_point(motor, pack, n, hover_thr, coax)
        can_hover = True

    pack_wh = (pack.mah / 1000.0) * pack.cells * NOMINAL_V
    if can_hover and hover_pt is not None and hover_pt.current_total_a > 0:
        usable_ah = (pack.mah / 1000.0) * USABLE_FRACTION
        flight_min = usable_ah / hover_pt.current_total_a * 60.0
        hover_power = hover_pt.power_total_w
        hover_current = hover_pt.current_total_a
        hover_v_cell = hover_pt.voltage_per_cell
    else:
        flight_min = 0.0
        hover_power = full.power_total_w
        hover_current = full.current_total_a
        hover_v_cell = full.voltage_per_cell

    # Spare lift: extra grams before the sagged hover point hits the ceiling
    carry_g = 0.0
    if can_hover:
        ceil_pt = operating_point(motor, pack, n, HOVER_CEILING_PCT, coax)
        carry_g = max(0.0, ceil_pt.thrust_total_g - auw)

    warnings: list[str] = []
    sub250 = auw < 250
    if not can_hover:
        warnings.append("Cannot hover — thrust never exceeds weight. Lighter pack or bigger motors.")
    if cell_mismatch >= 2:
        warnings.append(
            f"Pack is {cell_mismatch}S off the motor's rated voltage — numbers extrapolated, treat as rough."
        )
    if can_hover and hover_thr is not None and hover_thr > 65:
        warnings.append(
            f"Hover at {hover_thr:.0f}% — mushy, little headroom. Undersized for this weight."
        )
    if twr < 2 and can_hover:
        warnings.append(f"Thrust-to-weight {twr:.1f}:1 — below the 2:1 floor for controllable flight.")
    if not sub250 and frame.frame_class == "sub250":
        warnings.append(f"AUW {auw:.0f}g breaks the 250g limit on a sub-250 frame.")

    return BuildResult(
        auw_g=auw, twr=twr, max_thrust_g=max_thrust,
        hover_throttle=hover_thr, can_hover=can_hover,
        hover_power_w=hover_power, hover_current_a=hover_current,
        hover_v_cell=hover_v_cell, pack_wh=pack_wh, flight_min=flight_min,
        carry_g=carry_g, n_motors=n, cell_mismatch=cell_mismatch,
        sub250=sub250, frame_class=frame.frame_class,
        pack_chemistry=pack.chemistry, warnings=warnings,
    )
