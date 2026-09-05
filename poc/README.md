# Proof of concept

`drone-sim.jsx` is the original single-file React prototype this project grew out of.
It is kept for reference only — it is not wired into the app, not built, and not
maintained. Its physics were replaced wholesale by `backend/app/physics.py`, which
fixes the prototype's largest error source (linear interpolation of thrust curves).
