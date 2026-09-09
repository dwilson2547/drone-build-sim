"""Physics engine tests."""

import math

from app.physics import (
    C_AMPS, C_GRAMS, C_WATTS, Frame, Motor, Pack, Payload,
    NOMINAL_V, operating_point, simulate, thrust_g, _shaped_interp,
)

# Idealized motor whose bench curve is exactly quadratic/cubic in throttle,
# at 4S: thrust = 0.04 * t^2 grams, amps = 0.002 * t^2, watts = 0.0003 * t^3.
def make_ideal_motor(rated_cells=4, mass_g=10.0):
    curve = []
    for t in (10, 25, 50, 75, 100):
        curve.append((t, 0.04 * t * t, 0.002 * t * t, 0.0003 * t ** 3))
    return Motor("ideal", rated_cells, mass_g, curve, [])


def make_pack(cells=4, mah=1300, mass_g=150, ir=0.0):
    return Pack("test", cells, mah, mass_g, "lipo", ir)


QUAD = Frame("quad", 50.0, 4, False, "freestyle")
P0 = Payload("none", 0.0)


def test_shaped_interp_exact_on_quadratic_thrust():
    m = make_ideal_motor()
    for t in (10, 33, 47, 62, 88, 100):
        assert math.isclose(thrust_g(m.curve, t), 0.04 * t * t, rel_tol=1e-9)


def test_shaped_interp_exact_on_cubic_watts():
    m = make_ideal_motor()
    for t in (10, 40, 65, 100):
        assert math.isclose(_shaped_interp(m.curve, t, C_WATTS, 3.0), 0.0003 * t ** 3, rel_tol=1e-9)


def test_linear_interp_would_be_wrong_but_shaped_is_right():
    m = make_ideal_motor()
    # midpoint of 25..50: linear gives (25+100)/2=62.5g, quadratic truth is 56.25g
    assert math.isclose(thrust_g(m.curve, 37.5), 0.04 * 37.5 ** 2, rel_tol=1e-9)


def test_zero_ir_gives_rated_voltage():
    m = make_ideal_motor()
    p = make_pack(ir=0.0)
    pt = operating_point(m, p, 4, 50.0, coax=False)
    assert math.isclose(pt.voltage_per_cell, NOMINAL_V, rel_tol=1e-3)


def test_sag_reduces_thrust_and_voltage():
    m = make_ideal_motor()
    stiff = operating_point(m, make_pack(ir=0.0), 4, 80.0, coax=False)
    saggy = operating_point(m, make_pack(ir=30.0), 4, 80.0, coax=False)
    assert saggy.voltage_per_cell < stiff.voltage_per_cell
    assert saggy.thrust_total_g < stiff.thrust_total_g


def test_hover_solves_and_heavier_means_higher_throttle():
    m = make_ideal_motor()
    light = simulate(m, QUAD, make_pack(mass_g=100), P0)
    heavy = simulate(m, QUAD, make_pack(mass_g=400), P0)
    assert light.can_hover and heavy.can_hover
    assert heavy.hover_throttle > light.hover_throttle


def test_cannot_hover_detected():
    weak = Motor("weak", 4, 10.0, [(100, 50, 5, 70)], [])
    r = simulate(weak, QUAD, make_pack(mass_g=900), P0)
    assert not r.can_hover
    assert r.hover_throttle is None
    assert any("Cannot hover" in w for w in r.warnings)


def test_coax_reduces_thrust():
    m = make_ideal_motor()
    y6 = Frame("y6", 50.0, 6, True, "sub250")
    flat_pt = operating_point(m, make_pack(), 6, 60.0, coax=False)
    coax_pt = operating_point(m, make_pack(), 6, 60.0, coax=True)
    assert coax_pt.thrust_total_g < flat_pt.thrust_total_g
    assert math.isclose(coax_pt.thrust_total_g / flat_pt.thrust_total_g, 0.8, rel_tol=0.02)


def test_flight_time_uses_hover_current():
    m = make_ideal_motor()
    r = simulate(m, QUAD, make_pack(mah=1000), P0)
    assert r.can_hover
    # time = usable Ah / hover A * 60
    expected = (1.0 * 0.80) / r.hover_current_a * 60
    assert math.isclose(r.flight_min, expected, rel_tol=1e-6)


def test_sub250_flag_and_warning():
    m = make_ideal_motor()
    light = simulate(m, Frame("y6", 40, 6, True, "sub250"), make_pack(mass_g=30), P0)
    assert light.sub250
    heavy_motor = Motor("brick", 4, 80.0, make_ideal_motor().curve, [])
    heavy = simulate(heavy_motor, Frame("y6", 100, 6, True, "sub250"), make_pack(mass_g=300), P0)
    assert not heavy.sub250
    assert any("250g" in w for w in heavy.warnings)


def test_voltage_scaling_between_cell_counts():
    m = make_ideal_motor(rated_cells=4)
    # same motor on 3S: thrust at full throttle should be ~(3/4)^2 of 4S
    p3 = operating_point(m, make_pack(cells=3), 4, 100.0, coax=False)
    p4 = operating_point(m, make_pack(cells=4), 4, 100.0, coax=False)
    assert math.isclose(p3.thrust_total_g / p4.thrust_total_g, (3 / 4) ** 2, rel_tol=0.01)


def test_cell_mismatch_warning():
    m = make_ideal_motor(rated_cells=4)
    r = simulate(m, QUAD, make_pack(cells=6), P0)
    assert r.cell_mismatch == 2
    assert any("rated voltage" in w for w in r.warnings)


# --- per-prop curves and explicit bench voltage -----------------------------

from app.physics import PropCurve  # noqa: E402


def _pts(k):
    return [(t, k * t * t, 0.002 * t * t, 0.0003 * t ** 3) for t in (25, 50, 75, 100)]


def make_multiprop_motor():
    return Motor("multi", 6, 30.0, [
        PropCurve(prop='5"', points=_pts(0.04), test_volts=24.0),
        PropCurve(prop='6"', points=_pts(0.06), test_volts=24.0),
    ])


def test_curve_for_selects_by_prop():
    m = make_multiprop_motor()
    assert thrust_g(m.curve_for('5"').points, 100) < thrust_g(m.curve_for('6"').points, 100)


def test_curve_for_defaults_to_first_curve():
    m = make_multiprop_motor()
    assert m.curve_for().prop == '5"'
    assert m.curve == m.curve_for('5"').points


def test_unknown_prop_raises():
    import pytest
    with pytest.raises(KeyError):
        make_multiprop_motor().curve_for('99"')


def test_bigger_prop_lifts_more_in_a_full_sim():
    m = make_multiprop_motor()
    small = simulate(m, QUAD, make_pack(cells=6), P0, prop='5"')
    big = simulate(m, QUAD, make_pack(cells=6), P0, prop='6"')
    assert big.max_thrust_g > small.max_thrust_g
    assert big.prop == '6"'


def test_legacy_bare_curve_is_still_accepted():
    """Callers predating per-prop curves pass a plain list of points."""
    m = Motor("legacy", 4, 10.0, _pts(0.04), [])
    assert len(m.curves) == 1
    assert isinstance(m.curves[0], PropCurve)
    assert m.curves[0].test_volts is None
    assert math.isclose(thrust_g(m.curve, 50), 0.04 * 50 * 50, rel_tol=1e-9)


def test_stated_bench_voltage_changes_current_estimate():
    """A 6S motor benched at 24.0V is not the same as one assumed at 3.7V/cell.

    Assuming 22.2V where the sweep actually ran at 24.0V inflates every current
    by ~8%, which lands directly on flight time.
    """
    pts = _pts(0.04)
    stated = Motor("stated", 6, 30.0, [PropCurve('5"', pts, test_volts=24.0)])
    assumed = Motor("assumed", 6, 30.0, [PropCurve('5"', pts, test_volts=None)])
    pack = make_pack(cells=6, ir=0.0)

    a_stated = operating_point(stated, pack, 4, 70.0, coax=False).current_total_a
    a_assumed = operating_point(assumed, pack, 4, 70.0, coax=False).current_total_a

    assert a_stated < a_assumed
    assert math.isclose(a_stated / a_assumed, (6 * NOMINAL_V) / 24.0, rel_tol=1e-6)


def test_unknown_bench_voltage_warns():
    m = Motor("assumed", 4, 10.0, _pts(0.04), [])
    r = simulate(m, QUAD, make_pack(), P0)
    assert any("Bench voltage" in w for w in r.warnings)

    known = Motor("known", 4, 10.0, [PropCurve('5"', _pts(0.04), test_volts=14.8)])
    r2 = simulate(known, QUAD, make_pack(), P0)
    assert not any("Bench voltage" in w for w in r2.warnings)
