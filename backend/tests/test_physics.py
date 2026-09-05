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
