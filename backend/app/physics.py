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

# A bench point is (throttle%, grams, amps, watts).
Point = tuple[float, float, float, float]


@dataclass
class PropCurve:
    """One bench sweep: a motor swinging a specific prop at a specific voltage.

    `test_volts` is the pack voltage the sweep was actually measured at. Vendor
    datasheets state it (iFlight benches 6S motors at 24.0V = 4.0V/cell, not the
    3.7V/cell `NOMINAL_V` assumes), and getting it wrong biases every current —
    and therefore every flight-time — estimate. None means "unknown, fall back
    to the old rated_cells * NOMINAL_V assumption".
    """

    prop: str
    points: list[Point]
    test_volts: float | None = None
    source: str = "seed"          # seed | tmotor-html | iflight-datasheet
    source_url: str = ""
    harvested_at: str = ""

    def rated_volts(self, rated_cells: int) -> float:
        return self.test_volts if self.test_volts else rated_cells * NOMINAL_V


@dataclass
class Motor:
    name: str
    rated_cells: int
    mass_g: float
    curves: list[PropCurve]
    props: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Accept the legacy shape — a bare list of (thr, g, a, w) points — so
        # callers that predate per-prop curves keep working.
        if self.curves and not isinstance(self.curves[0], PropCurve):
            self.curves = [PropCurve(prop="", points=[tuple(p) for p in self.curves])]
        if not self.props:
            self.props = [c.prop for c in self.curves if c.prop]

    def curve_for(self, prop: str | None = None) -> PropCurve:
        """The sweep for `prop`, or the first (default) sweep when unspecified."""
        if prop:
            for c in self.curves:
                if c.prop == prop:
                    return c
            raise KeyError(f"motor '{self.name}' has no curve for prop '{prop}'")
        return self.curves[0]

    @property
    def curve(self) -> list[Point]:
        """Points of the default sweep. Retained for existing callers."""
        return self.curves[0].points


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
                    coax: bool, soc_v: float = NOMINAL_V, iterations: int = 12,
                    prop: str | None = None) -> OperatingPoint:
    """Solve the sagged operating point at a given throttle.

    Fixed-point: guess per-cell voltage -> scale thrust/amps from the bench
    curve (measured at the sweep's own test voltage) -> pack current -> IR sag
    -> new voltage.
    """
    pc = motor.curve_for(prop)
    pts = pc.points
    v_rated = pc.rated_volts(motor.rated_cells)
    ir_pack = pack.ir_mohm_per_cell * pack.cells / 1000.0  # ohms
    v_cell = soc_v
    coax_f = COAX_FACTOR if coax else 1.0

    for _ in range(iterations):
        # current scales ~linearly with voltage at fixed throttle duty
        per_motor_amps = amps(pts, throttle) * (v_cell * pack.cells / v_rated)
        i_total = n_motors * per_motor_amps
        v_pack = soc_v * pack.cells - i_total * ir_pack
        v_cell_new = max(v_pack / pack.cells, CUTOFF_V)
        if abs(v_cell_new - v_cell) < 1e-4:
            v_cell = v_cell_new
            break
        v_cell = v_cell_new

    scale = _voltage_scale(v_cell * pack.cells, v_rated)
    thrust_total = n_motors * thrust_g(pts, throttle) * scale * coax_f
    i_total = n_motors * amps(pts, throttle) * (v_cell * pack.cells / v_rated)
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
    prop: str = ""
    curve_source: str = ""
    test_volts: float | None = None


def simulate(motor: Motor, frame: Frame, pack: Pack, payload: Payload,
             rigging_g: float = BASE_RIGGING_G, prop: str | None = None) -> BuildResult:
    n = frame.motors
    coax = frame.coax
    pc = motor.curve_for(prop)   # raises early on an unknown prop
    auw = n * motor.mass_g + frame.mass_g + pack.mass_g + payload.mass_g + rigging_g
    cell_mismatch = abs(pack.cells - motor.rated_cells)

    # Max thrust / TWR at full charge (4.2V/cell) with sag
    full = operating_point(motor, pack, n, 100.0, coax, soc_v=FULL_V, prop=prop)
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
            pt = operating_point(motor, pack, n, mid, coax, prop=prop)
            if pt.thrust_total_g >= auw:
                hi = mid
            else:
                lo = mid
        hover_thr = hi
        hover_pt = operating_point(motor, pack, n, hover_thr, coax, prop=prop)
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
        ceil_pt = operating_point(motor, pack, n, HOVER_CEILING_PCT, coax, prop=prop)
        carry_g = max(0.0, ceil_pt.thrust_total_g - auw)

    warnings: list[str] = []
    sub250 = auw < 250
    if not can_hover:
        warnings.append("Cannot hover — thrust never exceeds weight. Lighter pack or bigger motors.")
    if pc.test_volts is None:
        warnings.append(
            "Bench voltage for this curve is unknown — assumed 3.7V/cell. "
            "Current and flight time are approximate."
        )
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
        prop=pc.prop, curve_source=pc.source, test_volts=pc.test_volts,
    )
