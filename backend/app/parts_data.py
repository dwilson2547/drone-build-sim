"""Seed parts library, ported from the original drone-sim.jsx.

Thrust curves are per-motor at the rated cell count, from published bench
tests / listing charts. IR values are typical per-cell internal resistance
for the chemistry/format — refine with measured values over time.
"""

MOTORS = [
    {
        "id": "0802_19000kv", "name": "0802 19000KV (whoop)", "rated_cells": 1, "mass_g": 3.2,
        "props": ["31mm"],
        "curve": [(25, 3, 0.35, 1.1), (50, 8, 1.1, 4.1), (75, 16, 2.6, 9.6), (100, 26, 4.8, 17.8)],
    },
    {
        "id": "1404_4600kv", "name": "1404 4600KV", "rated_cells": 4, "mass_g": 9.5,
        "props": ['3"', '3.5"'],
        "curve": [(25, 38, 0.7, 8), (50, 95, 2.4, 36), (75, 180, 6.0, 89), (100, 310, 12.5, 185)],
    },
    {
        "id": "1404_3000kv", "name": "1404 3000KV (LR)", "rated_cells": 4, "mass_g": 9.5,
        "props": ['4"', '4.5"'],
        "curve": [(25, 34, 0.5, 6), (50, 85, 1.8, 27), (75, 165, 4.6, 68), (100, 275, 9.2, 136)],
    },
    {
        "id": "1804_2450kv", "name": "1804 2450KV", "rated_cells": 4, "mass_g": 12,
        "props": ['4"', '4.5"'],
        "curve": [(25, 92, 0.85, 10), (50, 230, 3.0, 44), (75, 470, 7.6, 112), (100, 780, 15.0, 222)],
    },
    {
        "id": "2004_1800kv", "name": "2004 1800KV", "rated_cells": 6, "mass_g": 15,
        "props": ['5"'],
        "curve": [(25, 130, 1.2, 26), (50, 320, 4.2, 93), (75, 640, 10.5, 233), (100, 1050, 21.0, 466)],
    },
    {
        "id": "2207_1750kv", "name": "2207 1750KV (freestyle)", "rated_cells": 6, "mass_g": 32,
        "props": ['5"'],
        "curve": [(25, 195, 1.9, 40), (50, 480, 6.5, 144), (75, 980, 16.0, 355), (100, 1700, 34.0, 755)],
    },
    {
        "id": "3115_900kv", "name": "3115 900KV (GF1050)", "rated_cells": 6, "mass_g": 95,
        "props": ['10"'],
        "curve": [(25, 580, 3.2, 78), (50, 1420, 11.4, 300), (70, 2500, 28, 710), (100, 4080, 62.7, 1600)],
    },
]

FRAMES = [
    {"id": "reliant_y6", "name": "Reliant Y6 (sub250)", "mass_g": 42, "motors": 6, "coax": True, "frame_class": "sub250"},
    {"id": "tinyy6_std", "name": 'Generic 3.5" Y6', "mass_g": 55, "motors": 6, "coax": True, "frame_class": "sub250"},
    {"id": "freestyle3", "name": '3" freestyle', "mass_g": 38, "motors": 4, "coax": False, "frame_class": "sub250"},
    {"id": "cruiser45", "name": '4.5" cruiser (sub250)', "mass_g": 48, "motors": 4, "coax": False, "frame_class": "sub250"},
    {"id": "freestyle5", "name": '5" freestyle', "mass_g": 95, "motors": 4, "coax": False, "frame_class": "freestyle"},
    {"id": "y6_450", "name": "F450 Y6 (heavy lift)", "mass_g": 480, "motors": 6, "coax": True, "frame_class": "heavy"},
]

PACKS = [
    # li-ion: higher IR (~35 mΩ/cell 18650, ~20 mΩ 21700); lipo: ~5-8 mΩ/cell
    {"id": "liion_3s_p2", "name": "3S2P 18650 Li-ion (~5000)", "cells": 3, "mah": 5000, "mass_g": 280, "chemistry": "li-ion", "ir_mohm_per_cell": 17.5},
    {"id": "liion_4s_p1", "name": "4S1P 21700 Li-ion (~4000)", "cells": 4, "mah": 4000, "mass_g": 260, "chemistry": "li-ion", "ir_mohm_per_cell": 20.0},
    {"id": "lipo_4s_650", "name": "4S 650mAh LiPo", "cells": 4, "mah": 650, "mass_g": 68, "chemistry": "lipo", "ir_mohm_per_cell": 12.0},
    {"id": "lipo_4s_1300", "name": "4S 1300mAh LiPo", "cells": 4, "mah": 1300, "mass_g": 158, "chemistry": "lipo", "ir_mohm_per_cell": 7.0},
    {"id": "lipo_6s_1050", "name": "6S 1050mAh LiPo", "cells": 6, "mah": 1050, "mass_g": 190, "chemistry": "lipo", "ir_mohm_per_cell": 8.0},
    {"id": "lipo_6s_5000", "name": "6S 5000mAh LiPo", "cells": 6, "mah": 5000, "mass_g": 720, "chemistry": "lipo", "ir_mohm_per_cell": 4.0},
]

PAYLOADS = [
    {"id": "none", "name": "None", "mass_g": 0},
    {"id": "analog", "name": "Analog cam+VTX", "mass_g": 12},
    {"id": "digital", "name": "Digital (O3/HDZero)", "mass_g": 32},
    {"id": "gopro", "name": "GoPro / naked cam", "mass_g": 30},
    {"id": "lr_kit", "name": "GPS + LR gear", "mass_g": 18},
]
