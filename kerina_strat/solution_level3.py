import math
import json
import sys

KBASE   = 0.0005
KDRAG   = 0.0000000015
GRAVITY = 9.8


# ── Weather helpers ───────────────────────────────────────────────────────────

def build_weather_timeline(conditions):
    timeline = []
    t = 0.0
    for w in conditions:
        timeline.append((t, t + w["duration_s"], w))
        t += w["duration_s"]
    return timeline, t  # timeline, cycle_length

def get_weather_at(race_time, timeline, cycle_len):
    t_mod = race_time % cycle_len
    for start, end, w in timeline:
        if start <= t_mod < end:
            return w
    return timeline[-1][2]

def cond_key(condition_str):
    """Map condition string to tyre multiplier key."""
    return condition_str  # keys match: "dry", "cold", "light_rain", "heavy_rain"


# ── Track / physics helpers ───────────────────────────────────────────────────

def build_corner_speeds(track, friction):
    return {s["id"]: math.sqrt(friction * GRAVITY * s["radius_m"])
            for s in track if s["type"] == "corner"}

def next_corner_spd(idx, track, corner_speeds):
    for j in range(idx + 1, len(track)):
        if track[j]["type"] == "corner":
            return corner_speeds[track[j]["id"]]
    for s in track:
        if s["type"] == "corner":
            return corner_speeds[s["id"]]
    return 0.0

def fuel_used(vi, vf, dist):
    avg = (vi + vf) / 2
    return (KBASE + KDRAG * avg ** 2) * dist

def sim_lap(entry_spd, track, friction, accel_eff, brake_eff):
    """Simulate one lap. Returns (lap_time, fuel_consumed, exit_speed, straight_decisions)."""
    corner_speeds = build_corner_speeds(track, friction)
    lap_time = 0.0
    lap_fuel = 0.0
    spd      = entry_spd
    straights = {}  # seg_id -> {target, brake_dist}

    for i, seg in enumerate(track):
        L = seg["length_m"]

        if seg["type"] == "straight":
            nc  = next_corner_spd(i, track, corner_speeds)
            tgt = 90.0  # MAX_SPEED

            # Acceleration phase
            a_dist = max(0.0, min((tgt**2 - spd**2) / (2 * accel_eff), L)) if tgt > spd else 0.0
            vf_a   = min(tgt, math.sqrt(spd**2 + 2 * accel_eff * a_dist))

            # Braking phase
            b_dist = max(0.0, min((vf_a**2 - nc**2) / (2 * brake_eff), L - a_dist))

            # Cruise phase
            c_dist = max(0.0, L - a_dist - b_dist)

            # Time
            lap_time += (vf_a - spd)  / accel_eff if vf_a > spd else 0.0
            lap_time += c_dist / vf_a  if vf_a > 0 else 0.0
            lap_time += (vf_a - nc)   / brake_eff if vf_a > nc else 0.0

            # Fuel
            lap_fuel += fuel_used(spd,  vf_a, a_dist)
            lap_fuel += fuel_used(vf_a, vf_a, c_dist)
            lap_fuel += fuel_used(vf_a, nc,   b_dist)

            straights[seg["id"]] = {
                "target_m/s":                round(tgt, 2),
                "brake_start_m_before_next": round(b_dist, 2)
            }
            spd = nc

        else:
            c = corner_speeds[seg["id"]]
            lap_time += L / c
            lap_fuel += fuel_used(c, c, L)
            spd = c

    return lap_time, lap_fuel, spd, straights


# ── Main solver ───────────────────────────────────────────────────────────────

def solve(level_file: str, output_file: str):
    with open(level_file) as f:
        data = json.load(f)

    car   = data["car"]
    race  = data["race"]
    track = data["track"]["segments"]

    MAX_SPEED   = car["max_speed_m/s"]
    TANK        = car["fuel_tank_capacity_l"]
    INIT_FUEL   = car["initial_fuel_l"]
    LAPS        = race["laps"]
    BASE_PIT    = race["base_pit_stop_time_s"]
    REFUEL_RATE = race["pit_refuel_rate_l/s"]
    SOFT_CAP    = race["fuel_soft_cap_limit_l"]

    # Weather setup
    conditions = data["weather"]["conditions"]
    timeline, cycle_len = build_weather_timeline(conditions)

    # ── Pick best tyre per weather condition ──────────────────────
    tyre_props = data["tyres"]["properties"]

    def best_tyre_for_cond(cond_str):
        mk = f"{cond_str}_friction_multiplier"
        best_id, best_f, best_c = None, -1, None
        for ts in data["available_sets"]:
            compound = ts["compound"]
            props    = tyre_props[compound]
            f = props["base_friction"] * props[mk]
            if f > best_f:
                best_f = f; best_id = ts["ids"][0]; best_c = compound
        return best_id, best_f, best_c

    print("=== Best tyre per weather ===")
    for w in conditions:
        tid, tf, tc = best_tyre_for_cond(w["condition"])
        print(f"  {w['condition']:12s}: {tc:12s} (id={tid}) friction={tf:.4f}")

    # Level 3: Soft wins in every condition — no tyre changes needed
    initial_tyre_id = data["available_sets"][0]["ids"][0]  # Soft
    print(f"\nUsing Soft tyres (id={initial_tyre_id}) for full race — no tyre changes")

    # ── Simulate race lap by lap ──────────────────────────────────
    race_time  = 0.0
    fuel       = INIT_FUEL
    entry_spd  = 0.0
    total_fuel = 0.0
    pits       = {}   # lap_num -> refuel_amount
    lap_data   = []   # (lap_num, straights_dict, cond)

    for lap in range(1, LAPS + 1):
        w         = get_weather_at(race_time, timeline, cycle_len)
        cond      = w["condition"]
        mk        = f"{cond}_friction_multiplier"
        friction  = tyre_props["Soft"]["base_friction"] * tyre_props["Soft"][mk]
        accel_eff = 10.0 * w["acceleration_multiplier"]
        brake_eff = 20.0 * w["deceleration_multiplier"]

        lap_time, lap_fuel, exit_spd, straights = sim_lap(
            entry_spd, track, friction, accel_eff, brake_eff
        )

        fuel       -= lap_fuel
        total_fuel += lap_fuel
        race_time  += lap_time
        entry_spd   = exit_spd

        lap_data.append((lap, straights, cond))

        laps_left = LAPS - lap
        if laps_left == 0:
            break

        # Check if we can start the next lap
        nw         = get_weather_at(race_time, timeline, cycle_len)
        nmk        = f"{nw['condition']}_friction_multiplier"
        nfriction  = tyre_props["Soft"]["base_friction"] * tyre_props["Soft"][nmk]
        naccel_eff = 10.0 * nw["acceleration_multiplier"]
        nbrake_eff = 20.0 * nw["deceleration_multiplier"]
        _, next_cost, _, _ = sim_lap(exit_spd, track, nfriction, naccel_eff, nbrake_eff)

        if fuel < next_cost:
            avg_per_lap   = total_fuel / lap
            future_needed = avg_per_lap * laps_left
            shortfall     = future_needed - fuel
            refuel        = min(shortfall + 2.0, TANK - fuel)
            refuel        = max(0.0, round(refuel, 2))
            fuel         += refuel
            pits[lap]     = refuel
            print(f"  Pit after lap {lap:2d}: {cond:12s}  refuel={refuel:.2f}L  tank→{fuel:.1f}L")

    print(f"\nRace time:    {race_time:.1f}s")
    print(f"Total fuel:   {total_fuel:.2f}L  (cap: {SOFT_CAP}L)")
    fuel_bonus = -1_000_000 * (1 - total_fuel / SOFT_CAP) ** 2 + 1_000_000
    print(f"Fuel bonus:   {fuel_bonus:.0f}")
    print(f"Pit stops:    {list(pits.keys())}  ({len(pits)} stops)")
    pit_overhead = sum(BASE_PIT + r / REFUEL_RATE for r in pits.values())
    print(f"Pit overhead: {pit_overhead:.1f}s")

    # ── Build submission JSON ─────────────────────────────────────
    laps_out = []
    for lap_num, straights, cond in lap_data:
        segs_out = []
        for seg in track:
            if seg["type"] == "straight":
                s = straights[seg["id"]]
                segs_out.append({
                    "id":   seg["id"],
                    "type": "straight",
                    "target_m/s":                s["target_m/s"],
                    "brake_start_m_before_next": s["brake_start_m_before_next"]
                })
            else:
                segs_out.append({"id": seg["id"], "type": "corner"})

        if lap_num in pits:
            pit_entry = {"enter": True, "fuel_refuel_amount_l": pits[lap_num]}
        else:
            pit_entry = {"enter": False}

        laps_out.append({"lap": lap_num, "segments": segs_out, "pit": pit_entry})

    submission = {"initial_tyre_id": initial_tyre_id, "laps": laps_out}
    with open(output_file, "w") as f:
        json.dump(submission, f, indent=2)

    print(f"\n✅ Submission written to: {output_file}")


if __name__ == "__main__":
    level_file  = sys.argv[1] if len(sys.argv) > 1 else "3.txt"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "submission_level3.txt"
    solve(level_file, output_file)
