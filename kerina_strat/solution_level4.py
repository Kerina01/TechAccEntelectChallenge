import math
import json
import sys

KBASE      = 0.0005
KDRAG      = 0.0000000015
GRAVITY    = 9.8
K_STRAIGHT = 0.0000166
K_BRAKING  = 0.0398
K_CORNER   = 0.000265
MAX_SPEED  = 90.0
BLOWOUT_SAFETY = 0.90   # pit when tyre reaches this degradation level


# ── Weather helpers ───────────────────────────────────────────────

def build_timeline(conditions):
    tl, t = [], 0.0
    for w in conditions:
        tl.append((t, t + w["duration_s"], w))
        t += w["duration_s"]
    return tl, t

def get_weather_at(race_time, timeline, cycle_len):
    t_mod = race_time % cycle_len
    for start, end, w in timeline:
        if start <= t_mod < end:
            return w
    return timeline[-1][2]


# ── Tyre helpers ──────────────────────────────────────────────────

# Best tyre per condition (by effective friction when fresh):
# dry:        Soft > Medium > Hard > Wet > Intermediate
# cold:       Soft > Medium > Hard > Wet > Intermediate
# light_rain: Soft > Wet > Medium > Hard > Intermediate
# heavy_rain: Wet > Soft > Medium > Intermediate > Hard
TYRE_PREFERENCE = {
    "dry":        ["Soft", "Medium", "Hard", "Wet", "Intermediate"],
    "cold":       ["Soft", "Medium", "Hard", "Wet", "Intermediate"],
    "light_rain": ["Wet", "Soft", "Medium", "Hard", "Intermediate"],
    "heavy_rain": ["Wet", "Intermediate", "Soft", "Medium", "Hard"],
}

def get_friction_key(condition):
    return f"{condition}_friction_multiplier"

def tyre_friction(compound, props, cond, degradation):
    mk = get_friction_key(cond)
    return (props["base_friction"] - degradation) * props[mk]

def best_available_tyre(cond, current_id, inventory, tyre_props, exclude_current=True):
    """Return tyre_id of best available tyre for condition."""
    prefs = TYRE_PREFERENCE[cond]
    for compound in prefs:
        candidates = [
            (tid, deg)
            for tid, (tc, deg) in inventory.items()
            if tc == compound
            and deg < BLOWOUT_SAFETY
            and (tid != current_id or not exclude_current)
        ]
        if candidates:
            return min(candidates, key=lambda x: x[1])[0]   # freshest of this compound
    # Fallback: any non-blown tyre
    for tid, (tc, deg) in inventory.items():
        if deg < BLOWOUT_SAFETY and (tid != current_id or not exclude_current):
            return tid
    return current_id


# ── Lap simulation ────────────────────────────────────────────────

def sim_lap(entry_spd, compound, cond, accel_eff, brake_eff, deg_so_far, tyre_props_data, track):
    props    = tyre_props_data[compound]
    deg_rate = props[f"{cond}_degradation"]
    friction = (props["base_friction"] - deg_so_far) * props[get_friction_key(cond)]
    if friction <= 0:
        return None   # tyre blown

    cs = {s["id"]: math.sqrt(friction * GRAVITY * s["radius_m"])
          for s in track if s["type"] == "corner"}

    def nc(idx):
        for j in range(idx + 1, len(track)):
            if track[j]["type"] == "corner":
                return cs[track[j]["id"]]
        return cs[next(s["id"] for s in track if s["type"] == "corner")]

    time = 0.0; fuel = 0.0; spd = entry_spd; deg = 0.0; straights = {}

    for i, seg in enumerate(track):
        L = seg["length_m"]
        if seg["type"] == "straight":
            n   = nc(i)
            tgt = MAX_SPEED
            a   = max(0.0, min((tgt**2 - spd**2) / (2 * accel_eff), L)) if tgt > spd else 0.0
            va  = min(tgt, math.sqrt(spd**2 + 2 * accel_eff * a))
            b   = max(0.0, min((va**2 - n**2) / (2 * brake_eff), L - a))
            c   = max(0.0, L - a - b)

            time += (va - spd) / accel_eff if va > spd else 0.0
            time += c / va                  if va > 0  else 0.0
            time += (va - n)  / brake_eff  if va > n  else 0.0

            fuel += (KBASE + KDRAG * ((spd + va) / 2) ** 2) * a
            fuel += (KBASE + KDRAG * va ** 2)              * c
            fuel += (KBASE + KDRAG * ((va + n) / 2) ** 2) * b

            deg += deg_rate * (a + c) * K_STRAIGHT
            deg += ((va / 100) ** 2 - (n / 100) ** 2) * K_BRAKING * deg_rate

            straights[seg["id"]] = {
                "target_m/s":                MAX_SPEED,
                "brake_start_m_before_next": round(b, 2)
            }
            spd = n
        else:
            c_spd = cs[seg["id"]]
            time += L / c_spd
            fuel += (KBASE + KDRAG * c_spd ** 2) * L
            deg  += K_CORNER * (c_spd ** 2 / seg["radius_m"]) * deg_rate
            spd   = c_spd

    return time, fuel, spd, deg, straights


# ── Main solver ───────────────────────────────────────────────────

def solve(level_file: str, output_file: str):
    with open(level_file) as f:
        data = json.load(f)

    car   = data["car"]
    race  = data["race"]
    track = data["track"]["segments"]

    TANK        = car["fuel_tank_capacity_l"]
    INIT_FUEL   = car["initial_fuel_l"]
    LAPS        = race["laps"]
    BASE_PIT    = race["base_pit_stop_time_s"]
    TYRE_SWAP   = race["pit_tyre_swap_time_s"]
    REFUEL_RATE = race["pit_refuel_rate_l/s"]
    SOFT_CAP    = race["fuel_soft_cap_limit_l"]

    tyre_props_data = data["tyres"]["properties"]
    conditions = data["weather"]["conditions"]
    timeline, cycle_len = build_timeline(conditions)

    # Build tyre inventory: id -> (compound, degradation)
    inventory = {}
    for ts in data["available_sets"]:
        for tid in ts["ids"]:
            inventory[tid] = (ts["compound"], 0.0)

    # Starting tyre: best for initial weather condition
    start_cond = next(w["condition"] for w in conditions
                      if w["id"] == race["starting_weather_condition_id"])
    current_tyre_id = best_available_tyre(start_cond, None, inventory, tyre_props_data, exclude_current=False)
    print(f"Start: {inventory[current_tyre_id][0]} (id={current_tyre_id}) for '{start_cond}'")

    race_time  = 0.0
    fuel       = INIT_FUEL
    entry_spd  = 0.0
    total_fuel = 0.0
    total_deg  = 0.0
    pits       = {}
    lap_data   = []

    for lap in range(1, LAPS + 1):
        w         = get_weather_at(race_time, timeline, cycle_len)
        cond      = w["condition"]
        compound, deg_so_far = inventory[current_tyre_id]

        result = sim_lap(entry_spd, compound, cond,
                         10.0 * w["acceleration_multiplier"],
                         20.0 * w["deceleration_multiplier"],
                         deg_so_far, tyre_props_data, track)

        lap_time, lap_fuel, exit_spd, lap_deg, straights = result

        inventory[current_tyre_id] = (compound, deg_so_far + lap_deg)
        fuel       -= lap_fuel
        total_fuel += lap_fuel
        race_time  += lap_time
        entry_spd   = exit_spd
        total_deg  += lap_deg
        new_deg     = inventory[current_tyre_id][1]
        laps_left   = LAPS - lap

        lap_data.append((lap, straights, current_tyre_id))

        if laps_left == 0:
            break

        nw    = get_weather_at(race_time, timeline, cycle_len)
        ncond = nw["condition"]

        # ── Decide if pit needed ──────────────────────────────────
        need_tyre_change = new_deg >= BLOWOUT_SAFETY
        next_res = sim_lap(exit_spd, compound, ncond,
                           10.0 * nw["acceleration_multiplier"],
                           20.0 * nw["deceleration_multiplier"],
                           new_deg, tyre_props_data, track)
        need_fuel = (next_res is None) or (fuel < next_res[1])

        pit_entry = {}
        if need_tyre_change or need_fuel:
            # Tyre change
            if need_tyre_change:
                new_tyre_id = best_available_tyre(ncond, current_tyre_id, inventory, tyre_props_data)
                if new_tyre_id != current_tyre_id:
                    pit_entry["tyre_change_set_id"] = new_tyre_id
                    current_tyre_id = new_tyre_id
                    compound = inventory[current_tyre_id][0]

            # Fuel
            avg_per_lap   = total_fuel / lap
            future_needed = avg_per_lap * laps_left
            shortfall     = future_needed - fuel
            refuel = max(0.0, min(shortfall + 2.0, TANK - fuel))
            refuel = round(refuel, 2)
            if refuel > 0:
                pit_entry["fuel_refuel_amount_l"] = refuel
                fuel += refuel

            if pit_entry:
                pit_entry["enter"] = True
                pits[lap] = pit_entry

                tyre_info = f" tyre→{current_tyre_id}({compound})" if "tyre_change_set_id" in pit_entry else ""
                fuel_info = f" fuel+{refuel}L" if refuel > 0 else ""
                print(f"  Pit lap {lap:2d}: {cond:12s}  deg={new_deg*100:.1f}%{tyre_info}{fuel_info}")

    print(f"\nRace time:   {race_time:.1f}s")
    print(f"Total fuel:  {total_fuel:.2f}L  (cap: {SOFT_CAP}L)")
    print(f"Total deg:   {total_deg:.4f}")
    fb = -1_000_000 * (1 - total_fuel / SOFT_CAP) ** 2 + 1_000_000
    tb = 100_000 * total_deg
    print(f"Fuel bonus:  {fb:.0f}")
    print(f"Tyre bonus:  {tb:.0f}")
    print(f"Combined:    {fb + tb:.0f}")
    print(f"Pit stops ({len(pits)}): {list(pits.keys())}")

    # ── Build submission ──────────────────────────────────────────
    initial_tyre_id = lap_data[0][2]

    laps_out = []
    for lap_num, straights, _ in lap_data:
        segs_out = []
        for seg in track:
            if seg["type"] == "straight":
                s = straights[seg["id"]]
                segs_out.append({
                    "id":                        seg["id"],
                    "type":                      "straight",
                    "target_m/s":                s["target_m/s"],
                    "brake_start_m_before_next": s["brake_start_m_before_next"]
                })
            else:
                segs_out.append({"id": seg["id"], "type": "corner"})

        if lap_num in pits:
            pit_entry = dict(pits[lap_num])
        else:
            pit_entry = {"enter": False}

        laps_out.append({"lap": lap_num, "segments": segs_out, "pit": pit_entry})

    submission = {"initial_tyre_id": initial_tyre_id, "laps": laps_out}
    with open(output_file, "w") as f:
        json.dump(submission, f, indent=2)
    print(f"\n✅ Submission written to: {output_file}")


if __name__ == "__main__":
    level_file  = sys.argv[1] if len(sys.argv) > 1 else "4.txt"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "submission_level4.txt"
    solve(level_file, output_file)
