import os
import tempfile

import h5py
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials

TZ = "America/Chicago"
FILE_ID = "19kQ2Ky97Qx2M_fIpDGBgS-vTEh9EjHlC"

st.set_page_config(page_title="Home Weather", layout="wide")


@st.cache_data(ttl=300)
def load_data():
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        dict(st.secrets["gcp_service_account"]),
        ["https://www.googleapis.com/auth/drive"],
    )
    gauth = GoogleAuth()
    gauth.credentials = creds
    drive = GoogleDrive(gauth)

    # Temp folder is deleted afterwards, so old downloads don't pile up
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "weather.h5")
        drive.CreateFile({"id": FILE_ID}).GetContentFile(path)
        with h5py.File(path, "r") as f:
            df = pd.DataFrame({
                "time": pd.to_datetime(f["timestamp"][:], unit="s", utc=True).tz_convert(TZ),
                "temperature": f["temperature"][:],
                "humidity": f["humidity"][:],
                "pressure": f["pressure"][:],
            })

    # Dew point, Magnus formula
    a, b = 17.27, 237.7
    alpha = a * df["temperature"] / (b + df["temperature"]) + np.log(df["humidity"] / 100)
    df["dew_point"] = b * alpha / (a - alpha)
    return df.sort_values("time", ignore_index=True)


@st.cache_data(ttl=900)
def load_melbourne():
    # Unix timestamps avoid DST clashes when converting to Chicago time
    h = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": -37.81,
            "longitude": 144.96,
            "hourly": "temperature_2m",
            "past_days": 92,
            "forecast_days": 1,
            "timeformat": "unixtime",
        },
        timeout=10,
    ).json()["hourly"]
    return pd.DataFrame({
        "time": pd.to_datetime(h["time"], unit="s", utc=True).tz_convert(TZ),
        "temperature": h["temperature_2m"],
    })


def comfort(dew_point):
    if dew_point < 13:
        return "comfortable"
    if dew_point < 18:
        return "sticky"
    return "oppressive"


df = load_data()
latest = df.iloc[-1]
prev = df.set_index("time").asof(latest["time"] - pd.Timedelta(hours=3))
now = pd.Timestamp.now(tz=TZ)
minutes_ago = int((now - latest["time"]).total_seconds() // 60)

st.title("Home Weather")
st.caption(f"Last reading {latest['time']:%a %d %b, %H:%M} ({minutes_ago} min ago)")


# Current conditions, with change over the last 3 hours
def change(col, unit):
    return f"{latest[col] - prev[col]:+.1f} {unit}"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Temperature", f"{latest['temperature']:.1f} °C", change("temperature", "°C"), delta_color="off")
c2.metric("Humidity", f"{latest['humidity']:.0f} %", change("humidity", "%"), delta_color="off")
c3.metric(f"Dew point ({comfort(latest['dew_point'])})", f"{latest['dew_point']:.1f} °C",
          change("dew_point", "°C"), delta_color="off")
c4.metric("Pressure", f"{latest['pressure']:.1f} hPa", change("pressure", "hPa"))

today = df[df["time"].dt.date == latest["time"].date()]
hi = today.loc[today["temperature"].idxmax()]
lo = today.loc[today["temperature"].idxmin()]
st.caption(
    f"Changes are against 3 hours ago. Today's high {hi['temperature']:.1f} °C at {hi['time']:%H:%M}, "
    f"low {lo['temperature']:.1f} °C at {lo['time']:%H:%M}."
)

st.divider()


# Time window
windows = {"24 h": 1, "3 days": 3, "7 days": 7, "30 days": 30, "All": None}
choice = st.segmented_control("Window", list(windows), default="3 days") or "3 days"
days = windows[choice]
start = latest["time"] - pd.Timedelta(days=days) if days else df["time"].iloc[0]
view = df[df["time"] >= start]

# Long windows are averaged hourly so the charts stay quick
if choice in ("30 days", "All"):
    view = view.resample("1h", on="time").mean().reset_index()


# Stacked charts on one shared time axis, so zooming one zooms all
fig = make_subplots(
    rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
    row_heights=[0.5, 0.25, 0.25],
    subplot_titles=("Temperature and dew point (°C)", "Humidity (%)", "Pressure (hPa)"),
)
fig.add_trace(go.Scatter(x=view["time"], y=view["temperature"], name="Temperature",
                         line=dict(color="#d62728", width=2)), row=1, col=1)
# Shading between the two lines shows how dry the air is
fig.add_trace(go.Scatter(x=view["time"], y=view["dew_point"], name="Dew point",
                         line=dict(color="#1f77b4", width=2),
                         fill="tonexty", fillcolor="rgba(31,119,180,0.12)"), row=1, col=1)
fig.add_trace(go.Scatter(x=view["time"], y=view["humidity"], name="Humidity",
                         line=dict(color="#2ca02c", width=2)), row=2, col=1)
fig.add_trace(go.Scatter(x=view["time"], y=view["pressure"], name="Pressure",
                         line=dict(color="#ff7f0e", width=2)), row=3, col=1)
fig.update_layout(height=750, hovermode="x unified", showlegend=False)
fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1)
st.plotly_chart(fig, width="stretch")


# Melbourne v Chicago over the same window
st.subheader("Melbourne v Chicago")
mel = load_melbourne()
mel = mel[(mel["time"] >= start) & (mel["time"] <= now)]
home = df[df["time"] >= start].resample("1h", on="time")["temperature"].mean()
st.caption(
    f"It's {now.tz_convert('Australia/Melbourne'):%a %H:%M} in Melbourne "
    f"and {mel['temperature'].iloc[-1]:.1f} °C."
)

fig_mel = go.Figure()
fig_mel.add_trace(go.Scatter(x=home.index, y=home.values, name="Chicago (home)",
                             line=dict(color="#d62728", width=2)))
fig_mel.add_trace(go.Scatter(x=mel["time"], y=mel["temperature"], name="Melbourne",
                             line=dict(color="#9467bd", width=2)))
fig_mel.update_layout(height=350, hovermode="x unified", yaxis_title="Temperature (°C)",
                      legend=dict(orientation="h", y=1.1, x=0))
st.plotly_chart(fig_mel, width="stretch")


with st.expander("Raw data"):
    st.dataframe(df[df["time"] >= start], hide_index=True)
