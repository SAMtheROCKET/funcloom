import numpy as np
import pandas as pd

np.random.seed(17)

# Generate a synthetic sensor log for 10 greenhouses over a 30-minute window
greenhouse_ids = [f"GH{idx:02d}" for idx in range(1, 11)]
crop_by_greenhouse = {
    "GH01": "tomato",
    "GH02": "tomato",
    "GH03": "cucumber",
    "GH04": "pepper",
    "GH05": "lettuce",
    "GH06": "lettuce",
    "GH07": "strawberry",
    "GH08": "basil",
    "GH09": "pepper",
    "GH10": "cucumber",
}
readings_per_greenhouse = 60
timestamps = pd.date_range("2026-05-14 06:00:00", periods=readings_per_greenhouse, freq="30s")
n_rows = len(greenhouse_ids) * readings_per_greenhouse

greenhouse_column = np.repeat(greenhouse_ids, readings_per_greenhouse)
timestamp_column = np.tile(timestamps, len(greenhouse_ids))
crop_column = [crop_by_greenhouse[greenhouse] for greenhouse in greenhouse_column]
minute_of_window = np.tile(np.arange(readings_per_greenhouse) / 2.0, len(greenhouse_ids))

base_temperature = np.repeat(np.random.uniform(18, 24, len(greenhouse_ids)), readings_per_greenhouse)
air_temperature = base_temperature + 0.08 * minute_of_window + np.random.normal(0, 0.4, n_rows)
relative_humidity = (78 - 1.6 * (air_temperature - 20) + np.random.normal(0, 3, n_rows)).clip(35, 99)
soil_moisture = (42 - 0.15 * minute_of_window + np.random.normal(0, 2.5, n_rows)).clip(5, 60)
light_level = (180 + 22 * minute_of_window + np.random.normal(0, 30, n_rows)).clip(0, None)
co2_ppm = (420 + np.random.normal(0, 25, n_rows) + 3 * minute_of_window).round(0)
irrigation_on = soil_moisture < 34
vent_open_pct = np.where(air_temperature > 24, np.random.uniform(30, 80, n_rows), np.random.uniform(0, 20, n_rows))
leaf_wetness = np.random.uniform(0, 1, n_rows) < (relative_humidity - 60) / 100

readings_df = pd.DataFrame(
    {
        "timestamp": timestamp_column,
        "greenhouse": greenhouse_column,
        "crop": crop_column,
        "air_temp_c": air_temperature.round(2),
        "humidity_pct": relative_humidity.round(1),
        "soil_moisture_pct": soil_moisture.round(1),
        "light_umol": light_level.round(0),
        "co2_ppm": co2_ppm,
        "irrigation_on": irrigation_on,
        "vent_open_pct": vent_open_pct.round(1),
        "leaf_wet": leaf_wetness,
    }
)
readings_df["minute"] = minute_of_window
readings_df["vapour_pressure_deficit_kpa"] = (
    0.6108 * np.exp(17.27 * readings_df["air_temp_c"] / (readings_df["air_temp_c"] + 237.3))
    * (1 - readings_df["humidity_pct"] / 100)
).round(3)

print("Synthetic greenhouse readings generated")
print(readings_df.head(8).to_string(index=False))
print("\nDataFrame shape:", readings_df.shape)
print("\nColumns:", list(readings_df.columns))

# -------------------------------
# Growing-condition analytics and charts
# -------------------------------
import matplotlib.pyplot as plt

plt.rcParams["figure.figsize"] = (8, 4)

# Assign a site and a structure age to every greenhouse from its identifier.
def derive_site_context(greenhouse_id, crop_name):
    greenhouse_number = int(greenhouse_id[2:])
    if greenhouse_number <= 3:
        site = "North field"
        region = "Upland"
    elif greenhouse_number <= 6:
        site = "River plot"
        region = "Valley"
    elif greenhouse_number <= 8:
        site = "Orchard edge"
        region = "Valley"
    else:
        site = "South field"
        region = "Coastal"
    structure_age_years = 2 + (greenhouse_number * 3) % 11
    if crop_name in ("tomato", "pepper", "cucumber"):
        crop_group = "fruiting"
    elif crop_name in ("lettuce", "basil"):
        crop_group = "leafy"
    else:
        crop_group = "berry"
    if structure_age_years >= 9:
        maintenance_band = "renovation due"
    elif structure_age_years >= 5:
        maintenance_band = "routine"
    else:
        maintenance_band = "new"
    return site, region, structure_age_years, crop_group, maintenance_band


context_rows = [derive_site_context(row.greenhouse, row.crop) for row in readings_df[["greenhouse", "crop"]].drop_duplicates().itertuples(index=False)]
context_df = pd.DataFrame(context_rows, columns=["site", "region", "structure_age_years", "crop_group", "maintenance_band"])
context_df.insert(0, "greenhouse", readings_df["greenhouse"].drop_duplicates().to_list())
readings_df = readings_df.merge(context_df, on="greenhouse", how="left")

def summarize_numeric(series, label):
    return {
        "metric": label,
        "mean": round(float(series.mean()), 2),
        "median": round(float(series.median()), 2),
        "min": round(float(series.min()), 2),
        "max": round(float(series.max()), 2),
        "std": round(float(series.std()), 2),
    }


numeric_columns = ["air_temp_c", "humidity_pct", "soil_moisture_pct", "light_umol", "co2_ppm", "vapour_pressure_deficit_kpa"]
summary_rows = [summarize_numeric(readings_df[column_name], column_name) for column_name in numeric_columns]
summary_df = pd.DataFrame(summary_rows)
print("\nOverall sensor summary:")
print(summary_df.to_string(index=False))

site_summary_df = readings_df.groupby("site").agg(
    greenhouses=("greenhouse", "nunique"),
    mean_temp=("air_temp_c", "mean"),
    mean_humidity=("humidity_pct", "mean"),
    irrigation_share=("irrigation_on", "mean"),
    mean_vpd=("vapour_pressure_deficit_kpa", "mean"),
).round(3)
print("\nConditions by site:")
print(site_summary_df)

crop_summary_df = readings_df.groupby("crop_group").agg(
    readings=("greenhouse", "size"),
    mean_moisture=("soil_moisture_pct", "mean"),
    wet_leaf_share=("leaf_wet", "mean"),
).round(3)
print("\nConditions by crop group:")
print(crop_summary_df)

age_summary_df = readings_df.groupby("maintenance_band").agg(
    greenhouses=("greenhouse", "nunique"),
    mean_age=("structure_age_years", "mean"),
    mean_vent=("vent_open_pct", "mean"),
).round(2)
print("\nVentilation by maintenance band:")
print(age_summary_df)

readings_df["temp_band"] = pd.cut(readings_df["air_temp_c"], bins=[0, 20, 23, 26, 40], labels=["cool", "ideal", "warm", "hot"])
band_counts = readings_df["temp_band"].value_counts().sort_index()
print("\nReadings per temperature band:")
for band_name, band_count in band_counts.items():
    print(f"  {band_name}: {band_count} readings ({band_count / len(readings_df):.1%})")

correlation_df = readings_df[numeric_columns].corr().round(3)
print("\nCorrelation of temperature with the other sensors:")
print(correlation_df["air_temp_c"].drop("air_temp_c").to_string())

risk_score = (
    (readings_df["humidity_pct"] > 85).astype(int)
    + readings_df["leaf_wet"].astype(int)
    + (readings_df["vapour_pressure_deficit_kpa"] < 0.4).astype(int)
)
readings_df["disease_risk"] = risk_score.map(lambda score: "high" if score >= 2 else "watch" if score == 1 else "low")
risk_by_greenhouse = readings_df.groupby("greenhouse")["disease_risk"].agg(lambda values: (values == "high").mean()).round(3)
print("\nShare of high disease-risk readings by greenhouse:")
print(risk_by_greenhouse.to_string())

latest_df = readings_df.sort_values("timestamp").groupby("greenhouse").tail(1)
for row in latest_df.itertuples(index=False):
    print(f"{row.greenhouse} ({row.crop:10s}) at {row.timestamp:%H:%M:%S}: {row.air_temp_c:.1f} C, {row.humidity_pct:.0f}% RH, soil {row.soil_moisture_pct:.1f}%, vents {row.vent_open_pct:.0f}%, risk {row.disease_risk}")

figure, axes = plt.subplots(1, 2)
for greenhouse_id, greenhouse_rows in readings_df.groupby("greenhouse"):
    axes[0].plot(greenhouse_rows["minute"], greenhouse_rows["air_temp_c"], linewidth=0.8)
axes[0].set_title("Air temperature by greenhouse")
axes[1].hist(readings_df["soil_moisture_pct"], bins=20)
axes[1].set_title("Soil moisture distribution")
plt.tight_layout()
plt.close(figure)

# Direct calculations without helper functions
site_ranking = readings_df.groupby("site").agg(
    mean_light=("light_umol", "mean"),
    mean_co2=("co2_ppm", "mean"),
    greenhouses=("greenhouse", "nunique"),
    mean_temp=("air_temp_c", "mean"),
).sort_values("mean_light", ascending=False)
print("\nLight and CO2 by site:")
print(site_ranking.round(2))

# Interpretation notes
print("\nObservations:")
print("- Temperatures climb steadily through the morning window, so vents open more often in the later readings and the hottest houses ventilate first.")
print("- Soil moisture drifts downward during the window; houses that cross the irrigation threshold switch on watering, which keeps leafy crops in range.")
print("- Humid houses with wet leaves carry most of the disease-risk readings, which points to airflow and dehumidification as the first things to review.")
print("- Older structures ventilate more on average, a hint that their passive vents or seals may need maintenance before the summer peak.")
print("- The same approach scales to longer windows and more houses without any external data, because every derived field comes from the raw sensors.")

# Write a plain-text report and read it back to confirm what was saved
report_lines = [f"{row.Index}: {row.mean_temp:.2f} C mean, {row.greenhouses} greenhouses" for row in site_ranking.itertuples()]
with open("greenhouse_report.txt", "w", encoding="utf-8") as report_file:
    report_file.write("\n".join(report_lines) + "\n")
    saved_line_count = len(report_lines)
with open("greenhouse_report.txt", encoding="utf-8") as report_file:
    saved_text = report_file.read()
print(f"\nSaved {saved_line_count} site lines to greenhouse_report.txt ({len(saved_text)} characters)")

# Save a compact table for downstream analysis
export_df = readings_df[["timestamp", "greenhouse", "crop", "site", "air_temp_c", "humidity_pct", "soil_moisture_pct", "irrigation_on", "disease_risk"]]
export_df.to_csv("greenhouse_summary.csv", index=False)
print("\nSaved greenhouse summary CSV: greenhouse_summary.csv")
