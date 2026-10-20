from .core import SafetyGate, wall_demo
from .telemetry import SyntheticTelemetry


def demo():
    print("=" * 62)
    print("MIZAN core - honest reference demo")
    print("=" * 62)
    print("\n[1] Interior-point log-barrier (the optimisation wall)")
    print("    Task pulls theta -> 5.0 ; hard wall at theta = 3.0")
    print("    barrier strength t | theta* | distance to wall h(theta)")
    traj = wall_demo()
    for t, th, hv in traj:
        print(f"    {t:>18.1f} | {th:6.4f} | {hv:8.6f}")
    print(f"    boundary ever crossed: {any(hv < 0 for _, _, hv in traj)}   (must be False)")

    print("\n[2] Safety gate on SYNTHETIC telemetry (not a real detector)")
    src, gate = SyntheticTelemetry(), SafetyGate()
    for label in ["sample-input-A", "sample-input-B"]:
        r = gate.evaluate(src.read(label))
        print(f"\n    context = {label!r}  (synthetic, meaning not analysed)")
        for k, v in r.items():
            print(f"      {k:<16}: {v if isinstance(v, bool) else format(v, '.4f')}")
    print("\nDemo complete. Real telemetry is a separate step.")
