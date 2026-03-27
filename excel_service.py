import os
import threading
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


file_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "source_data",
    "Vessel_Device_Installation_Tracker NV.xlsx",
)
column_names = [
    "Vessel Name/ ID",
    "Spec",
    "Devices",
    "Installation Status",
    "Date of Installation",
    "Savings/year (fuel efficiency)",
    "Savings/year (Maitenance)",
    "Co2 savings ton/year",
]


df = pd.DataFrame()
list_df = pd.DataFrame()
summary_df = pd.DataFrame()
summary2_df = pd.DataFrame()
summary3_df = pd.DataFrame()
summary4_df = pd.DataFrame()
summary_raw = pd.DataFrame()
listvessel_df = pd.DataFrame()
listdevice_df = pd.DataFrame()
vessel_devices = pd.DataFrame()

initiative_desc_map = {}
kpis = []
kpis_section = []
vessels10 = {"names": [], "values": []}
donutdev = {
    "labels": ["IWTM P10", "EFMS", "MGPS", "LED", "Nautilus Log", "Shore Generator"],
    "values": [216, 289, 400, 320, 80, 50],
}

_excel_data_loaded = False
_excel_data_lock = threading.Lock()


# --- Fuel Consumption Data (Monthly) ---
fuel_data = {
    "months": ["Janvier", "Fevrier", "Mars", "April", "Mai", "Juin", "Juillet", "Aout"],
    "DEFIANCE": [53.26, 101.05, 134.43, 157.72, 164.31, 148.86, 146.98, 114.46],
    "PRINCIPLE": [194.55, 111.68, 206.97, 152.42, 162.69, 176.43, 194.75, 143.17],
    "PRIME": [119.5, 155.3, 198.36, 150.38, 179.65, 179.63, 154.3, 166.73],
    "PRELUDE": [125.3, 136.7, 164.0, 110.0, 124.7, 155.8, 140.9, 85.8],
}

goal_data = {
    "months": ["Janvier", "Fevrier", "Mars", "April", "Mai", "Juin", "Juillet", "Aout"],
    "AVERAGE": [123.1525, 126.1825, 175.94, 142.63, 157.8375, 165.18, 159.2325, 127.54],
    "GOAL": [104.679625, 100.946, 123.158, 114.104, 126.27, 132.144, 127.386, 114.786],
}

# Latest values (last element of each list)
fuel_latest = fuel_data["DEFIANCE"][-1]
avg_latest = goal_data["AVERAGE"][-1]
goal_latest = goal_data["GOAL"][-1]

# --- Oil lub and CW Water Data (Monthly) ---
oil_data = {
    "weeks": ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6", "Week 7", "Week 8"],
    "OIL_WATER": [87.5, 54, 50.5, 55, 46, 35, 31, 28.1],
    "PPM_2um": [91, 79, 56, 53, 29, 17, 16, 9.8],
}

cw_data = {
    "weeks": ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6", "Week 7", "Week 8"],
    "CONDUCTIVITY": [94, 84, 79, 87, 72, 82, 65, 31.2],
    "GOAL": [25, 25, 25, 25, 25, 25, 25, 25],
}

oil_latest = 100 - oil_data["OIL_WATER"][-1]
ppm_latest = 100 - oil_data["PPM_2um"][-1]
cond_latest = 100 - cw_data["CONDUCTIVITY"][-1]


def _num(i, j):
    v = pd.to_numeric(summary_raw.iat[i, j], errors="coerce")
    return 0 if pd.isna(v) else float(v)


def load_excel_data():
    global df, list_df, summary_df, summary2_df, summary3_df, summary4_df
    global summary_raw, initiative_desc_map, kpis, kpis_section
    global listvessel_df, listdevice_df, vessel_devices, vessels10

    df = pd.read_excel(file_path, engine="openpyxl", names=column_names, skiprows=7, usecols="B:I")
    list_df = pd.read_excel(file_path, engine="openpyxl", sheet_name="Tracker", skiprows=6, nrows=470, usecols="B:J")

    summary_df = pd.read_excel(file_path, engine="openpyxl", sheet_name="Summary", skiprows=0, nrows=18, usecols="A:F")
    summary2_df = pd.read_excel(file_path, engine="openpyxl", sheet_name="Summary", skiprows=15, nrows=3, usecols="B:C")
    summary3_df = pd.read_excel(file_path, engine="openpyxl", sheet_name="Summary", skiprows=0, nrows=4, usecols="I:K")
    summary4_df = pd.read_excel(file_path, engine="openpyxl", sheet_name="Summary", skiprows=1, nrows=17, usecols="Y:Z")

    initiative_desc_map = dict(zip(summary4_df.iloc[:, 0], summary4_df.iloc[:, 1]))

    summary_raw = pd.read_excel(file_path, engine="openpyxl", sheet_name="Summary", header=None)

    kpi_devices_raw = int(_num(24, 2))
    kpi_gain_raw = _num(4, 9) * 100
    kpi_co2_raw = _num(23, 2)

    kpi_devices = int(round(kpi_devices_raw))
    kpi_gain = round(kpi_gain_raw, 2)
    kpi_co2 = round(kpi_co2_raw, 0)

    kpis = [
        {"title": "Initiatives", "value": kpi_devices, "suffix": "", "back": ["8 initiatives certified", "9 initiatives on POC"]},
        {"title": "2025 Fuel Gain", "value": kpi_gain, "suffix": "%", "back": ["Scope 1 Only. Goal 2026:", "20% Fuel savings"]},
        {"title": "CO₂ Savings", "value": kpi_co2, "suffix": " t", "back": ["Expected savings", "based on fuel savings"]},
    ]

    kpi_tfc_raw = _num(6, 9)
    kpi_vessels_raw = _num(7, 9)
    kpi_update_raw = _num(3, 9) * 90

    kpi_tfc = int(round(kpi_tfc_raw))
    kpi_vessels = int(round(kpi_vessels_raw))
    kpi_update = int(round(kpi_update_raw))

    kpis_section = [
        {"title": "Last 12 months TFC", "value": kpi_tfc, "suffix": " t"},
        {"title": "Number of Vessels", "value": kpi_vessels, "suffix": ""},
        {"title": "Updated Info", "value": kpi_update, "suffix": "%"},
    ]

    listvessel_df = pd.read_excel(file_path, engine="openpyxl", sheet_name="Summary", skiprows=26, nrows=72, usecols="A")
    listdevice_df = pd.read_excel(file_path, engine="openpyxl", sheet_name="Summary", skiprows=1, nrows=17, usecols="A")

    vessels_of_interest = df[
        df["Vessel Name/ ID"].astype(str).str.contains(
            "Britoil|ENA Habitat|BOS|Lewek Hydra|Nautical Aisia|Nautical Anisha|Paragon Sentinel",
            na=False,
        )
    ]

    vessel_devices = vessels_of_interest[
        [
            "Vessel Name/ ID",
            "Devices",
            "Installation Status",
            "Savings/year (fuel efficiency)",
            "Savings/year (Maitenance)",
            "Co2 savings ton/year",
        ]
    ]

    vessel_devices["Savings/year (fuel efficiency)"] = pd.to_numeric(vessel_devices["Savings/year (fuel efficiency)"], errors="coerce")
    vessel_devices["Savings/year (Maitenance)"] = pd.to_numeric(vessel_devices["Savings/year (Maitenance)"], errors="coerce")
    vessel_devices["Co2 savings ton/year"] = pd.to_numeric(vessel_devices["Co2 savings ton/year"], errors="coerce")

    vessel_devices["Total Savings"] = (
        vessel_devices["Savings/year (fuel efficiency)"].fillna(0)
        + vessel_devices["Savings/year (Maitenance)"].fillna(0)
        + vessel_devices["Co2 savings ton/year"].fillna(0)
    )

    top_vessels = vessel_devices.groupby("Vessel Name/ ID")["Total Savings"].sum().nlargest(10).reset_index()
    plt.figure(figsize=(10, 6))
    plt.bar(top_vessels["Vessel Name/ ID"], top_vessels["Total Savings"], color="blue")
    plt.xlabel("Vessel Name")
    plt.ylabel("Total Savings")
    plt.title("Top 10 Vessels with Best Performance")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("static/top_vessels_chart.png")
    plt.close()

    vessels10r = summary_raw.loc[98:107, 0].dropna().astype(str).tolist()
    savings10r = pd.to_numeric(summary_raw.loc[98:107, 1], errors="coerce").fillna(0).tolist()
    vessels10 = {"names": vessels10r, "values": savings10r}


def ensure_excel_data_loaded():
    global _excel_data_loaded
    if _excel_data_loaded:
        return
    with _excel_data_lock:
        if _excel_data_loaded:
            return
        load_excel_data()
        _excel_data_loaded = True


def get_vessel_summary(vessel_name):
    ensure_excel_data_loaded()

    start_idx = list_df[list_df.iloc[:, 1] == vessel_name].index
    if len(start_idx) == 0:
        return None

    start = start_idx[0]
    end = start + 1

    while end < len(list_df) and pd.isna(list_df.iloc[end, 0]):
        end += 1

    summary_bis_df = list_df.iloc[start:end].copy()
    return summary_bis_df


def get_device_summary(device_name):
    ensure_excel_data_loaded()

    filtered_df = list_df[
        (list_df.iloc[:, 3] == device_name)
        & (list_df.iloc[:, 4].isin(["Done", "In Process"]))
    ].copy()

    vessel_names = []
    for idx in filtered_df.index:
        vessel_name = None
        search_idx = idx
        while search_idx >= 0:
            val = list_df.iloc[search_idx, 1]
            if pd.notna(val):
                vessel_name = val
                break
            search_idx -= 1
        vessel_names.append(vessel_name)

    filtered_df.insert(0, "Vessel Name", vessel_names)

    return filtered_df[
        [
            "Vessel Name",
            filtered_df.columns[4],
            filtered_df.columns[5],
            filtered_df.columns[6],
            filtered_df.columns[7],
            filtered_df.columns[8],
            filtered_df.columns[9],
        ]
    ]
