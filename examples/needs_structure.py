"""An intentionally simple script to inventory before future extraction."""

distance_samples_m_list = [10.0, 15.0, 20.0]
elapsed_time_s_float = 5.0
vehicle_speeds_mps_list = [
    distance_m_float / elapsed_time_s_float
    for distance_m_float in distance_samples_m_list
]


def summarize(x):
    return {"count": len(x), "maximum": max(x)}


if __name__ == "__main__":
    print(summarize(vehicle_speeds_mps_list))
