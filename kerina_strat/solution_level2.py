import math
import json
import sys

KBASE   = 0.0005
KDRAG   = 0.0000000015
GRAVITY = 9.8


def fuel_used(vi, vf, dist):
    avg = (vi + vf) / 2
    return (KBASE + KDRAG * avg ** 2) * dist


def solve(level_file: str, output_file: str):
    with open(level_file) as f:
        data = json.load(f)

    car  = data["car"]
    race = data["race"]
    track = data["track"]["segments"]

    MAX_SPEED   = car["max_speed_m/s"]
    ACCEL       = car["accel_m/se2"]
    BRAKE       = car["brake_m/se2"]
    TANK        = car["fuel_tank_capacity_l"]
    INIT_FUEL   = car["initial_fuel_l"]
    LAPS        = race["laps"]
    BASE_PIT    = race["base_pit_stop_time_s"]
    REFUEL_RATE = race["pit_refuel_rate_l/s"]
    SOFT_CAP    = race["fuel_soft_cap_limit_l"]

    # ── Best tyre for current weather ─────────────────────────────
    tyre_props = data["tyres"]["properties"]
    weather_condition = data["weather"]["conditions"][0]["condition"]
    multiplier_key    = f"{weather_condition}_friction_multiplier"

    best_tyre_id  = None
    best_friction = -1
    best_compound = None
    for tyre_set in data["available_sets"]:
        compound = tyre_set["compound"]
        props    = tyre_props[compound]
        friction = props["base_friction"] * props[multiplier_key]
        if friction > best_friction:
            best_friction = friction
            best_tyre_id  = tyre_set["ids"][0]
            best_compound = compound

    print(f"Best tyre: {best_compound} (id={best_tyre_id}), friction={best_friction:.4f}")

    # ── Corner max speeds ─────────────────────────────────────────
    corner_max = {}
    for seg in track:
        if seg["type"] == "corner":
            corner_max[seg["id"]] = math.sqrt(best_friction * GRAVITY * seg["radius_m"])

    # ── Next corner speed from a given track index ────────────────
    def next_corner_spd(idx):
        for j in range(idx + 1, len(track)):
            if track[j]["type"] == "corner":
                return corner_max[track[j]["id"]]
        for s in track:
            if s["type"] == "corner":
                return corner_max[s["id"]]
        return 0

    # ── Simulate one lap fuel consumption ─────────────────────────
    def sim_lap_fuel(entry_spd, target_speed=MAX_SPEED):
        fuel = 0.0
        spd  = entry_spd
        for i, seg in enumerate(track):
            L = seg["length_m"]
            if seg["type"] == "straight":
                nc    = next_corner_spd(i)
                tgt   = min(target_speed, MAX_SPEED)
                # Acceleration
                a_dist = max(0, min((tgt**2 - spd**2) / (2*ACCEL), L)) if tgt > spd else 0
                vf_a   = min(tgt, math.sqrt(spd**2 + 2*ACCEL*a_dist))
                # Braking
                b_dist = max(0, min((vf_a**2 - nc**2) / (2*BRAKE), L - a_dist))
                # Cruise
                c_dist = max(0, L - a_dist - b_dist)

                fuel += fuel_used(spd, vf_a, a_dist)
                fuel += fuel_used(vf_a, vf_a, c_dist)
                fuel += fuel_used(vf_a, nc,   b_dist)
                spd = nc
            else:
                c = corner_max[seg["id"]]
                fuel += fuel_used(c, c, L)
                spd = c
        return fuel, spd

    # ── Compute per-lap fuel costs ────────────────────────────────
    lap1_fuel, lap1_exit = sim_lap_fuel(0,         MAX_SPEED)
    lapN_fuel, _         = sim_lap_fuel(lap1_exit, MAX_SPEED)
    fuel_per_lap = [lap1_fuel] + [lapN_fuel] * (LAPS - 1)
    total_fuel   = sum(fuel_per_lap)

    print(f"Fuel per lap: {lapN_fuel:.4f}L  |  Total: {total_fuel:.2f}L  |  Soft cap: {SOFT_CAP}L")

    # ── Pit stop schedule: minimum stops, maximum tank life ───────
    # Only pit when we cannot complete the next lap on current fuel.
    fuel = INIT_FUEL
    pits = {}   # lap_number -> refuel_amount

    for lap_idx in range(LAPS):
        lap_num = lap_idx + 1
        fuel   -= fuel_per_lap[lap_idx]
        laps_remaining = LAPS - lap_num
        if laps_remaining == 0:
            break

        next_lap_cost = fuel_per_lap[lap_idx + 1]

        if fuel < next_lap_cost:
            # Refuel just enough to finish, capped at tank size
            future_needed = sum(fuel_per_lap[lap_num:])
            shortfall     = future_needed - fuel
            refuel = min(shortfall + 2.0, TANK - fuel)   # 2L safety buffer
            refuel = max(0, round(refuel, 2))
            fuel  += refuel
            pits[lap_num] = refuel
            print(f"  Pit after lap {lap_num}: refuel {refuel}L  →  tank={fuel:.2f}L")

    print(f"Fuel at finish: {fuel:.2f}L")
    fuel_bonus = -1000000 * (1 - total_fuel / SOFT_CAP) ** 2 + 1000000
    print(f"Fuel bonus (est.): {fuel_bonus:.0f}")
    total_pit_time = sum(BASE_PIT + r / REFUEL_RATE for r in pits.values())
    print(f"Total pit overhead: {total_pit_time:.1f}s  |  Stops: {list(pits.keys())}")

    # ── Straight decisions ────────────────────────────────────────
    straight_info = {}
    for i, seg in enumerate(track):
        if seg["type"] != "straight":
            continue
        nc         = next_corner_spd(i)
        brake_dist = (MAX_SPEED**2 - nc**2) / (2 * BRAKE)
        brake_dist = min(brake_dist, seg["length_m"] - 1)
        brake_dist = max(brake_dist, 0)
        straight_info[seg["id"]] = {
            "target": MAX_SPEED,
            "brake":  round(brake_dist, 2)
        }

    # ── Build submission JSON ─────────────────────────────────────
    laps_out = []
    for lap in range(1, LAPS + 1):
        segs_out = []
        for seg in track:
            if seg["type"] == "straight":
                info = straight_info[seg["id"]]
                segs_out.append({
                    "id":                        seg["id"],
                    "type":                      "straight",
                    "target_m/s":                info["target"],
                    "brake_start_m_before_next": info["brake"]
                })
            else:
                segs_out.append({"id": seg["id"], "type": "corner"})

        if lap in pits:
            pit_entry = {
                "enter":               True,
                "fuel_refuel_amount_l": pits[lap]
            }
        else:
            pit_entry = {"enter": False}

        laps_out.append({"lap": lap, "segments": segs_out, "pit": pit_entry})

    submission = {"initial_tyre_id": best_tyre_id, "laps": laps_out}

    with open(output_file, "w") as f:
        json.dump(submission, f, indent=2)

    print(f"\n✅ Submission written to: {output_file}")


if __name__ == "__main__":
    level_file  = sys.argv[1] if len(sys.argv) > 1 else "2.txt"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "submission_level2.txt"
    solve(level_file, output_file)
