import math
import json
import sys

def solve(level_file: str, output_file: str):
    with open(level_file) as f:
        data = json.load(f)

    car   = data["car"]
    race  = data["race"]
    track = data["track"]["segments"]

    MAX_SPEED = car["max_speed_m/s"]
    ACCEL     = car["accel_m/se2"]
    BRAKE     = car["brake_m/se2"]
    GRAVITY   = 9.8
    LAPS      = race["laps"]

    # ── Pick best tyre for dry conditions ─────────────────────────
    # Level 1: no degradation, just want highest friction for dry weather
    tyre_props   = data["tyres"]["properties"]
    available    = data["available_sets"]
    weather_cond = "dry"  # Level 1 is always dry

    multiplier_key = f"{weather_cond}_friction_multiplier"

    best_tyre_id      = None
    best_tyre_friction = -1

    for tyre_set in available:
        compound = tyre_set["compound"]
        props    = tyre_props[compound]
        friction = props["base_friction"] * props[multiplier_key]
        print(f"  {compound}: base={props['base_friction']} × {props[multiplier_key]} = {friction:.4f}")
        if friction > best_tyre_friction:
            best_tyre_friction = friction
            best_tyre_id       = tyre_set["ids"][0]
            best_compound      = compound

    print(f"\n✅ Best tyre: {best_compound} (id={best_tyre_id}), friction={best_tyre_friction:.4f}")

    # ── Max corner speeds ──────────────────────────────────────────
    corner_max = {}
    print("\n=== Corner max speeds ===")
    for seg in track:
        if seg["type"] == "corner":
            spd = math.sqrt(best_tyre_friction * GRAVITY * seg["radius_m"])
            corner_max[seg["id"]] = spd
            print(f"  Corner {seg['id']:2d} (r={seg['radius_m']}m): {spd:.2f} m/s")

    # ── Straight decisions ─────────────────────────────────────────
    straight_info = {}
    print("\n=== Straight decisions ===")
    for i, seg in enumerate(track):
        if seg["type"] != "straight":
            continue

        # Find the next corner after this straight
        next_corner_speed = None
        for j in range(i + 1, len(track)):
            if track[j]["type"] == "corner":
                next_corner_speed = corner_max[track[j]["id"]]
                break

        # Wrap-around: last straight on track → first corner of next lap
        if next_corner_speed is None:
            for s in track:
                if s["type"] == "corner":
                    next_corner_speed = corner_max[s["id"]]
                    break

        target = MAX_SPEED

        # Braking distance: d = (v_entry² - v_exit²) / (2 × brake)
        brake_dist = (target ** 2 - next_corner_speed ** 2) / (2 * BRAKE)
        brake_dist = min(brake_dist, seg["length_m"] - 1)
        brake_dist = max(brake_dist, 0)
        brake_dist = round(brake_dist, 2)

        straight_info[seg["id"]] = {
            "target": target,
            "brake":  brake_dist,
            "next_corner_spd": next_corner_speed
        }
        print(f"  Straight {seg['id']:2d}: target={target} m/s  "
              f"brake={brake_dist}m before end  "
              f"(→ {next_corner_speed:.2f} m/s for next corner)")

    # ── Build submission JSON ──────────────────────────────────────
    laps_out = []
    for lap in range(1, LAPS + 1):
        segs_out = []
        for seg in track:
            if seg["type"] == "straight":
                info = straight_info[seg["id"]]
                segs_out.append({
                    "id":                       seg["id"],
                    "type":                     "straight",
                    "target_m/s":               info["target"],
                    "brake_start_m_before_next": info["brake"]
                })
            else:
                segs_out.append({"id": seg["id"], "type": "corner"})

        laps_out.append({
            "lap":      lap,
            "segments": segs_out,
            "pit":      {"enter": False}
        })

    submission = {"initial_tyre_id": best_tyre_id, "laps": laps_out}

    with open(output_file, "w") as f:
        json.dump(submission, f, indent=2)

    print(f"\n✅ Submission written to: {output_file}")


if __name__ == "__main__":
    level_file  = sys.argv[1] if len(sys.argv) > 1 else "1.txt"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "submission_level1.txt"
    solve(level_file, output_file)
