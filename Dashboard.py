import inspect
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
WINDOWS = {"24 h": 1, "3 days": 3, "7 days": 7, "30 days": 30, "All": None}
COLOURS = {
    "temperature": "#eb6834",
    "dew_point": "#1baf7a",
    "humidity": "#6250d6",
    "pressure": "#008300",
    "rain_chance": "#2a78d6",
    "melbourne": "#2a78d6",
}
# Mid-grey at low opacity reads as a light grid on both light and dark themes
GRID = "rgba(128, 128, 128, 0.2)"
# Metric sparklines only exist in newer Streamlit versions
SPARKLINES = "chart_data" in inspect.signature(st.metric).parameters

st.set_page_config(page_title="Home Weather", layout="wide")


# ---------- Data ----------

def to_local(ts):
    return pd.to_datetime(ts, unit="s", utc=True).tz_convert(TZ)


def read_forecast(f):
    # Older files have no forecast group, and a new one can be empty
    if "forecast/timestamp" not in f:
        return pd.DataFrame(columns=["time", "rain_chance", "change_3h", "sensor_hours"])
    g = f["forecast"]
    fc = pd.DataFrame({
        "time": to_local(g["timestamp"][:]),
        "rain_chance": g["rain_chance"][:],
        "change_3h": g["change_3h"][:],
        "sensor_hours": g["sensor_hours"][:],
    })
    return fc.sort_values("time", ignore_index=True)


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
                "time": to_local(f["timestamp"][:]),
                "temperature": f["temperature"][:],
                "humidity": f["humidity"][:],
                "pressure": f["pressure"][:],
            })
            fc = read_forecast(f)

    # Dew point, Magnus formula
    a, b = 17.27, 237.7
    alpha = a * df["temperature"] / (b + df["temperature"]) + np.log(df["humidity"] / 100)
    df["dew_point"] = b * alpha / (a - alpha)
    # The Pi has no real-time clock, so rows can arrive out of order after a reboot
    return df.sort_values("time", ignore_index=True), fc


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
    return pd.DataFrame({"time": to_local(h["time"]), "temperature": h["temperature_2m"]})


# ---------- Wording ----------

def comfort(dew_point):
    if dew_point < 13:
        return "comfortable"
    if dew_point < 18:
        return "sticky"
    return "oppressive"


def verdict(pct):
    if pct < 15:
        return "Unlikely"
    if pct < 35:
        return "Possible"
    if pct < 60:
        return "Likely"
    return "Very likely"


def trend(change):
    if change > 1:
        word = "↑ Rising"
    elif change < -1:
        word = "↓ Falling"
    else:
        word = "→ Steady"
    return f"{word} ({change:+.1f} hPa in 3 h)"


# ---------- Chart helpers ----------

def fade(hex_colour, alpha):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def line(x, y, name, colour, unit, **kw):
    # One colour per variable everywhere; hover shows units to one decimal place
    return go.Scatter(
        x=x, y=y, name=name, mode="lines",
        line=dict(color=colour, width=2, shape="spline"),
        hovertemplate=f"{name}: %{{y:.1f}}{unit}<extra></extra>",
        **kw,
    )


def style(fig, height):
    # Transparent backgrounds let the Streamlit theme show through in light and dark mode
    fig.update_layout(
        height=height,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    # automargin stops the tight margins from clipping tick labels
    for update in (fig.update_xaxes, fig.update_yaxes):
        update(showgrid=True, gridcolor=GRID, griddash="solid", zeroline=False, automargin=True)
    return fig


def show(fig):
    st.plotly_chart(fig, width="stretch", theme="streamlit")


# ---------- Charts ----------

def rain_chart(fc):
    fig = go.Figure(line(
        fc["time"], fc["rain_chance"] * 100, "Rain chance", COLOURS["rain_chance"], "%",
        fill="tozeroy", fillcolor=fade(COLOURS["rain_chance"], 0.15),
    ))
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    return style(fig, 220)


def stacked_chart(view):
    # One shared time axis, so zooming one panel zooms all
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.5, 0.25, 0.25],
        subplot_titles=("Temperature and dew point (°C)", "Humidity (%)", "Pressure (hPa)"),
    )
    t = view["time"]
    fig.add_trace(line(t, view["temperature"], "Temperature", COLOURS["temperature"], " °C"), row=1, col=1)
    # Shading between the two lines shows how dry the air is
    fig.add_trace(line(t, view["dew_point"], "Dew point", COLOURS["dew_point"], " °C",
                       fill="tonexty", fillcolor=fade(COLOURS["dew_point"], 0.12)), row=1, col=1)
    fig.add_trace(line(t, view["humidity"], "Humidity", COLOURS["humidity"], "%"), row=2, col=1)
    fig.add_trace(line(t, view["pressure"], "Pressure", COLOURS["pressure"], " hPa"), row=3, col=1)
    fig.update_layout(showlegend=False)
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1)
    return style(fig, 750)


def melbourne_chart(home, mel):
    series = [("Chicago (home)", home, COLOURS["temperature"]), ("Melbourne", mel, COLOURS["melbourne"])]
    fig = go.Figure([line(d["time"], d["temperature"], name, colour, " °C") for name, d, colour in series])

    # Label each line just past its right end. The time axis is stretched a little so the
    # labels fit inside the tight margins. The higher line's label sits slightly above its
    # end and the lower one's slightly below, so the two never collide.
    ends = [d.dropna().iloc[-1] for _, d, _ in series]
    for (name, _, colour), end, other in zip(series, ends, ends[::-1]):
        above = end["temperature"] >= other["temperature"]
        fig.add_annotation(
            x=end["time"], y=end["temperature"], text=name, showarrow=False,
            font=dict(color=colour), xanchor="left", xshift=4,
            yanchor="bottom" if above else "top",
        )
    first, last = home["time"].iloc[0], max(e["time"] for e in ends)
    fig.update_xaxes(range=[first, last + (last - first) * 0.12])
    fig.update_layout(yaxis_title="Temperature (°C)",
                      legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom"))
    return style(fig, 350)


# ---------- Page sections ----------

def header(df, now):
    last = df["time"].iloc[-1]
    minutes = int((now - last).total_seconds() // 60)
    st.title("Home Weather", anchor=False)
    st.caption(f"Last reading {last:%a %d %b, %H:%M} ({minutes} min ago)")
    # The sensor once died for a month without anyone noticing
    if minutes > 10:
        st.warning(f"Sensor offline since {last:%a %d %b, %H:%M}")


def now_row(df):
    latest = df.iloc[-1]
    prev = df.set_index("time").asof(latest["time"] - pd.Timedelta(hours=3))
    spark = df[df["time"] >= latest["time"] - pd.Timedelta(hours=24)].resample("1h", on="time").mean()

    tiles = [
        ("Temperature", "temperature", " °C", "off"),
        ("Humidity", "humidity", "%", "off"),
        (f"Dew point ({comfort(latest['dew_point'])})", "dew_point", " °C", "off"),
        ("Pressure", "pressure", " hPa", "normal"),
    ]
    for col, (label, name, unit, delta_colour) in zip(st.columns(4), tiles):
        extra = {"chart_data": spark[name].dropna().round(1).tolist()} if SPARKLINES else {}
        col.metric(label, f"{latest[name]:.1f}{unit}", f"{latest[name] - prev[name]:+.1f}{unit}",
                   delta_color=delta_colour, border=True, **extra)

    today = df[df["time"].dt.date == latest["time"].date()]
    hi = today.loc[today["temperature"].idxmax()]
    lo = today.loc[today["temperature"].idxmin()]
    st.caption(
        f"Changes are against 3 hours ago. Today's high {hi['temperature']:.1f} °C at {hi['time']:%H:%M}, "
        f"low {lo['temperature']:.1f} °C at {lo['time']:%H:%M}."
    )


def rain_card(fc, start):
    with st.container(border=True):
        st.subheader("Rain outlook", anchor=False)
        if fc.empty:
            st.write("Forecast not available yet")
            return

        latest = fc.iloc[-1]
        # Round once so the verdict always matches the number shown
        pct = round(latest["rain_chance"] * 100)
        left, right = st.columns([1, 2], vertical_alignment="center")
        with left:
            st.metric("Chance of rain", f"{pct}%")
            st.markdown(f"**{verdict(pct)}**")
            st.markdown(trend(latest["change_3h"]))
        with right:
            show(rain_chart(fc[fc["time"] >= start]))

        note = "Chance of rain in the next 6 hours, predicted change in barometric pressure."
        if latest["sensor_hours"] < 25:
            note += " (partly using Open-Meteo pressure while the sensor builds up history)"
        st.caption(note)


def window_view(df, start, choice):
    view = df[df["time"] >= start]
    # Long windows are averaged hourly so the charts stay quick
    if choice in ("30 days", "All"):
        view = view.resample("1h", on="time").mean().reset_index()
    return view


def melbourne(df, start, now):
    st.subheader("Melbourne v Chicago", anchor=False)
    mel = load_melbourne()
    mel = mel[(mel["time"] >= start) & (mel["time"] <= now)]
    home = df[df["time"] >= start].resample("1h", on="time")["temperature"].mean().reset_index()
    st.caption(
        f"It's {now.tz_convert('Australia/Melbourne'):%a %H:%M} in Melbourne "
        f"and {mel['temperature'].iloc[-1]:.1f} °C."
    )
    show(melbourne_chart(home, mel))


# Reruns just this part every 5 minutes; the cached loaders still decide when Drive is hit
@st.fragment(run_every="5min")
def page():
    df, fc = load_data()
    now = pd.Timestamp.now(tz=TZ)

    # The window selector sits below the rain card but drives it too, so read its value up front
    choice = st.session_state.get("window") or "3 days"
    days = WINDOWS[choice]
    start = df["time"].iloc[-1] - pd.Timedelta(days=days) if days else df["time"].iloc[0]

    header(df, now)
    now_row(df)
    rain_card(fc, start)

    st.divider()
    st.segmented_control("Window", list(WINDOWS), default="3 days", key="window")
    show(stacked_chart(window_view(df, start, choice)))

    melbourne(df, start, now)

    with st.expander("Raw data"):
        st.dataframe(df[df["time"] >= start], hide_index=True)


page()
