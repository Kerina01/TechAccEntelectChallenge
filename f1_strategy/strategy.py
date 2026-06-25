def build_basic_strategy(level):
    race = level["race"]
    track = level["track"]

    laps = []

    for lap_number in range(1, race["laps"] + 1):
        segments = []

        for segment in track["segments"]:
            if segment["type"] == "straight":
                segments.append({
                    "id": segment["id"],
                    "type": "straight",
                    "target_m/s": 50,
                    "brake_start_m_before_next": 200
                })
            else:
                segments.append({
                    "id": segment["id"],
                    "type": "corner"
                })

        laps.append({
            "lap": lap_number,
            "segments": segments,
            "pit": {
                "enter": False
            }
        })

    return {
        "initial_tyre_id": level["tyres"][0]["id"],
        "laps": laps
    }