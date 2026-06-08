# Import required libraries
import streamlit as st
import h5py
import numpy as np
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
import plotly.graph_objects as go
import pandas as pd
import tempfile
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials

# Configure the page
st.set_page_config(
    page_title="Weather Dashboard",
    layout="wide"
)

st.title("Weather Data Dashboard")
st.markdown("---")

# Load data from Google Drive
# Cached so it doesn't reload every time user interacts with the dashboard
@st.cache_data(ttl=300)
def load_data():
    # connect to drive
    creds_dict = dict(st.secrets["gcp_service_account"])
    scope = ["https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gauth = GoogleAuth()
    gauth.credentials = creds
    drive = GoogleDrive(gauth)

    file_id = "19kQ2Ky97Qx2M_fIpDGBgS-vTEh9EjHlC"
    gfile = drive.CreateFile({"id": file_id})
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        gfile.GetContentFile(tmp.name)
        with h5py.File(tmp.name, 'r') as f:
            humidity = f["humidity"][:]
            pressure = f["pressure"][:]
            temperature = f["temperature"][:]
            timestamp = f["timestamp"][:]
    
    #Convert unix timestamps to local time
    times = [datetime.fromtimestamp(ts) for ts in timestamp]
    tz = ZoneInfo("America/Chicago")
    times = [datetime.fromtimestamp(ts, tz=tz) for ts in timestamp]
    
    # df are easier to deal with.
    df = pd.DataFrame({
        'time': times,
        'temperature': temperature,
        'humidity': humidity,
        'pressure': pressure
    })
    #Dew point calculation using Magnus formula. Meant to be the most accurate.
    a = 17.27
    b = 237.7
    alpha = ((a * df['temperature']) / (b + df['temperature'])) + np.log(df['humidity'] / 100.0)
    df['dew_point'] = (b * alpha) / (a - alpha)
    
    return df

#melbourne weather
@st.cache_data(ttl=300)  # how often to hit the weather data
def get_melbourne_weather():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": -37.81,
        "longitude": 144.96,
        "current": "temperature_2m,relative_humidity_2m,surface_pressure",
        "timezone": "Australia/Melbourne",
    }
    r = requests.get(url, params=params, timeout=10)
    return r.json()["current"]

df = load_data()


# Current conditions
latest = df.iloc[-1]
st.subheader(f"Current conditions ({latest['time'].strftime('%Y-%m-%d %H:%M')})")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Temperature", f"{latest['temperature']:.1f} °C")
col2.metric("Humidity", f"{latest['humidity']:.1f} %")
col3.metric("Pressure", f"{latest['pressure']:.1f} hPa")
col4.metric("Dew Point", f"{latest['dew_point']:.1f} °C")

st.markdown("---")


# Sidebar controls
st.sidebar.header("Controls")

date_range = st.sidebar.date_input(
    "Select Date Range:",
    value=(df['time'].min().date(), df['time'].max().date()),
    min_value=df['time'].min().date(),
    max_value=df['time'].max().date()
)

show_temp = st.sidebar.checkbox("Show Temperature", value=True)
show_humidity = st.sidebar.checkbox("Show Humidity", value=True)
show_dew_point = st.sidebar.checkbox("Show Dew Point", value=True)
show_pressure = st.sidebar.checkbox("Show Pressure", value=True)

# Filter data based on selected date range
filtered_df = df[
    (df['time'].dt.date >= date_range[0]) & 
    (df['time'].dt.date <= date_range[1])
]

st.sidebar.metric("Data Points", len(filtered_df))

# Temperature and Humidity plot (dual y-axis)
if show_temp or show_humidity:
    st.subheader("Temperature & Humidity")
    
    fig_temp_humidity = go.Figure()
    
    # Add temperature on left y-axis
    if show_temp:
        fig_temp_humidity.add_trace(go.Scatter(
            x=filtered_df['time'],
            y=filtered_df['temperature'],
            mode='lines',
            name='Temperature',
            line=dict(color='red', width=2),
            yaxis='y1'
        ))
    
    # Add humidity on right y-axis
    if show_humidity:
        fig_temp_humidity.add_trace(go.Scatter(
            x=filtered_df['time'],
            y=filtered_df['humidity'],
            mode='lines',
            name='Humidity',
            line=dict(color='green', width=2),
            yaxis='y2'
        ))
    
    # Configure the dual axes
# Configure the dual axes
    fig_temp_humidity.update_layout(
        xaxis_title="Time",
        yaxis=dict(
            title=dict(text="Temperature (°C)", font=dict(color='red')),
            tickfont=dict(color='red')
        ),
        yaxis2=dict(
            title=dict(text="Humidity (%)", font=dict(color='green')),
            tickfont=dict(color='green'),
            overlaying='y',
            side='right'
        ),
        hovermode='x unified',
        height=400,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    st.plotly_chart(fig_temp_humidity, width='stretch')
#dew point
if show_dew_point:
    st.subheader("Dew Point")
    
    fig_dew_point = go.Figure()
    
    fig_dew_point.add_trace(go.Scatter(
        x=filtered_df['time'],
        y=filtered_df['dew_point'],
        mode='lines',
        name='Dew Point',
        line=dict(color='blue', width=2)
    ))
    
    # Add the background comfort zones
    fig_dew_point.add_hrect(y0=0, y1=13, line_width=0, fillcolor="green", opacity=0.1)
    fig_dew_point.add_hrect(y0=13, y1=18, line_width=0, fillcolor="yellow", opacity=0.1)
    fig_dew_point.add_hrect(y0=18, y1=30, line_width=0, fillcolor="red", opacity=0.1)
    
    fig_dew_point.update_layout(
        yaxis_title="Dew Point (C)",
        xaxis_title="Time",
        hovermode='x unified',
        height=300
    )
    
    st.plotly_chart(fig_dew_point, width='stretch')
    
    #description
    st.caption("Comfortable: < 13C | Sticky: 13C - 18C | Oppressive: > 18C")


# Pressure plot (separate)
if show_pressure:
    st.subheader("Pressure")
    
    fig_pressure = go.Figure()
    fig_pressure.add_trace(go.Scatter(
        x=filtered_df['time'],
        y=filtered_df['pressure'],
        mode='lines',
        name='Pressure',
        line=dict(color='orange', width=2)
    ))
    
    fig_pressure.update_layout(
        yaxis_title="Pressure (hPa)",
        xaxis_title="Time",
        hovermode='x unified',
        height=300
    )
    
    st.plotly_chart(fig_pressure, width='stretch')

# Optional data table view
if st.checkbox("Show Raw Data"):
    st.dataframe(filtered_df)

#melbourne weather
st.subheader("Meanwhile in Melbourne")
mel = get_melbourne_weather()
mc1, mc2, mc3 = st.columns(3)
mc1.metric("Temperature", f"{mel['temperature_2m']:.1f} °C")
mc2.metric("Humidity", f"{mel['relative_humidity_2m']:.0f} %")
mc3.metric("Pressure", f"{mel['surface_pressure']:.1f} hPa")
