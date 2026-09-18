"""Parts library.

Motors are loaded from `data/motors.json` (see MOTORS below). Frames, packs and
payloads are still hand-maintained literals — no vendor publishes them in a form
worth scraping. IR, max_a and rigging_g are typical values for the archetype,
flagged ⚠ unverified inline; refine with measured values over time.
"""

import json
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"

# The motor library is data, not code: regenerated from vendor datasheets by
# tools/harvest_tmotor.py and committed as JSON. Hand-seeded entries (the FPV
# sizes no vendor publishes an HTML table for) live in the same file with
# "source": "seed" and survive a re-harvest.
MOTORS = json.loads((DATA_DIR / "motors.json").read_text(encoding="utf-8"))


# rigging_g = FC + ESC(s) + wiring + RX + straps for the class of build this frame is used for.
# ⚠ unverified — generic archetypes, not weighed hardware. Measured-AUW actuals logged against
# a saved build are the direct check on these; replace with weighed values as they come in.
FRAMES = [
    {"id": "reliant_y6", "name": "Reliant Y6 (sub250)", "mass_g": 42, "motors": 6, "coax": True, "frame_class": "sub250", "rigging_g": 22},
    {"id": "tinyy6_std", "name": 'Generic 3.5" Y6', "mass_g": 55, "motors": 6, "coax": True, "frame_class": "sub250", "rigging_g": 22},
    {"id": "freestyle3", "name": '3" freestyle', "mass_g": 38, "motors": 4, "coax": False, "frame_class": "sub250", "rigging_g": 22},
    {"id": "cruiser45", "name": '4.5" cruiser (sub250)', "mass_g": 48, "motors": 4, "coax": False, "frame_class": "sub250", "rigging_g": 25},
    {"id": "freestyle5", "name": '5" freestyle', "mass_g": 95, "motors": 4, "coax": False, "frame_class": "freestyle", "rigging_g": 45},
    {"id": "y6_450", "name": "F450 Y6 (heavy lift)", "mass_g": 480, "motors": 6, "coax": True, "frame_class": "heavy", "rigging_g": 160},
]

# li-ion: higher IR (~35 mΩ/cell 18650, ~20 mΩ 21700); lipo: ~5-8 mΩ/cell
# max_a = continuous discharge rating of the whole pack. ⚠ unverified — generic archetypes
# (li-ion from typical cell ratings x parallel count, lipo from typical C ratings). None = unknown,
# which disables the pack-current warnings rather than guessing.
PACKS = [
    {"id": "liion_3s_p2", "name": "3S2P 18650 Li-ion (~5000)", "cells": 3, "mah": 5000, "mass_g": 280, "chemistry": "li-ion", "ir_mohm_per_cell": 17.5, "max_a": 20},
    {"id": "liion_4s_p1", "name": "4S1P 21700 Li-ion (~4000)", "cells": 4, "mah": 4000, "mass_g": 260, "chemistry": "li-ion", "ir_mohm_per_cell": 20.0, "max_a": 30},
    {"id": "lipo_4s_650", "name": "4S 650mAh LiPo", "cells": 4, "mah": 650, "mass_g": 68, "chemistry": "lipo", "ir_mohm_per_cell": 12.0, "max_a": 45},
    {"id": "lipo_4s_1300", "name": "4S 1300mAh LiPo", "cells": 4, "mah": 1300, "mass_g": 158, "chemistry": "lipo", "ir_mohm_per_cell": 7.0, "max_a": 100},
    {"id": "lipo_6s_1050", "name": "6S 1050mAh LiPo", "cells": 6, "mah": 1050, "mass_g": 190, "chemistry": "lipo", "ir_mohm_per_cell": 8.0, "max_a": 100},
    {"id": "lipo_6s_5000", "name": "6S 5000mAh LiPo", "cells": 6, "mah": 5000, "mass_g": 720, "chemistry": "lipo", "ir_mohm_per_cell": 4.0, "max_a": 125},
]

PAYLOADS = [
    {"id": "none", "name": "None", "mass_g": 0},
    {"id": "analog", "name": "Analog cam+VTX", "mass_g": 12},
    {"id": "digital", "name": "Digital (O3/HDZero)", "mass_g": 32},
    {"id": "gopro", "name": "GoPro / naked cam", "mass_g": 30},
    {"id": "lr_kit", "name": "GPS + LR gear", "mass_g": 18},
]
