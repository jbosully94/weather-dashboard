# weather-dashboard
A little GUI to show weather data from my apartment. 

At my apartment I have a raspberry pi with a BME280. It saves the data into a .h5 file which it regularly pushes to google drive. From there a streamlit application (here) uses the PyDrive2 to access the google drive API where it can download the .h5 file and display its contents using plotly graphs. 

Planned upgrades:
Indoor/outdoor temperature sensors
Lighnting sensor
Photon flux

Live at: https://jamesweather.streamlit.app
