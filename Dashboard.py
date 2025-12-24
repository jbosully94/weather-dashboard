# Import required libraries
import streamlit as st
import h5py
from datetime import datetime
import plotly.graph_objects as go
import pandas as pd

# Configure the page
st.set_page_config(
    page_title="Weather Dashboard",
    layout="wide"
)

st.title("Weather Data Dashboard")
st.markdown("---")

# Load data from h5 file
# Cached so it doesn't reload every time user interacts with the dashboard
@st.cache_data
def load_data():
    with h5py.File('/Users/james/bme280_data.h5', 'r') as f:
        humidity = f["humidity"][:]
        pressure = f["pressure"][:]
        temperature = f["temperature"][:]
        timestamp = f["timestamp"][:]
    
    # Convert unix timestamps to datetime
    times = [datetime.fromtimestamp(ts) for ts in timestamp]
    
    # Put everything in a dataframe for easier manipulation
    df = pd.DataFrame({
        'time': times,
        'temperature': temperature,
        'humidity': humidity,
        'pressure': pressure
    })
    
    return df

df = load_data()

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