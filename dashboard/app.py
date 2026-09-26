"""
Same Dash pattern as your phishing detector's URL/Email scanner tabs --
now with a login flow, since every API call is behind JWT auth.
"""

import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import requests

API_URL = "https://gps-detect-tracker.fly.dev"

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
app.title = "Location Tracker"


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


app.layout = dbc.Container([
    dcc.Store(id="auth-token", storage_type="memory"),
    dcc.Store(id="username-store", storage_type="memory"),

    html.H2("Consent-Based Location Tracker", className="my-4"),

    html.Div(id="auth-panel", className="mb-2"),
    html.Div(id="auth-status", className="text-danger mb-4"),
    html.Div(id="app-body"),

    dcc.Interval(id="refresh-interval", interval=3000, n_intervals=0),
], fluid=True)


# ---- Auth panel: login/register form, or "logged in as X" ----
@app.callback(
    Output("auth-panel", "children"),
    [Input("auth-token", "data"), Input("username-store", "data")],
)
def render_auth_panel(token, username):
    if token:
        return dbc.Row([
            dbc.Col(html.Div(f"Logged in as {username}"), width="auto"),
            dbc.Col(dbc.Button("Logout", id="logout-btn", size="sm", color="secondary"), width="auto"),
        ], className="align-items-center g-2")

    return dbc.Row([
        dbc.Col(dbc.Input(id="auth-username", placeholder="Username"), width=2),
        dbc.Col(dbc.Input(id="auth-password", placeholder="Password", type="password"), width=2),
        dbc.Col(dbc.Button("Login", id="login-btn", color="primary"), width="auto"),
        dbc.Col(dbc.Button("Register", id="register-btn", color="secondary"), width="auto"),
    ], className="align-items-center g-2")


@app.callback(
    [Output("auth-token", "data"), Output("username-store", "data"), Output("auth-status", "children")],
    [Input("login-btn", "n_clicks"), Input("register-btn", "n_clicks")],
    [State("auth-username", "value"), State("auth-password", "value")],
    prevent_initial_call=True,
)
def handle_auth(login_clicks, register_clicks, username, password):
    triggered = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
    if not username or not password:
        return dash.no_update, dash.no_update, "Username and password required."

    if triggered == "register-btn":
        try:
            resp = requests.post(f"{API_URL}/auth/register", json={"username": username, "password": password})
            if not resp.ok:
                return dash.no_update, dash.no_update, f"Register failed: {resp.json().get('detail', resp.text)}"
        except requests.exceptions.RequestException as e:
            return dash.no_update, dash.no_update, f"Could not reach backend: {e}"
        # registered -- fall through to log in immediately

    try:
        resp = requests.post(f"{API_URL}/auth/login", data={"username": username, "password": password})
        if not resp.ok:
            return dash.no_update, dash.no_update, f"Login failed: {resp.json().get('detail', resp.text)}"
        return resp.json()["access_token"], username, ""
    except requests.exceptions.RequestException as e:
        return dash.no_update, dash.no_update, f"Could not reach backend: {e}"


@app.callback(
    [Output("auth-token", "data", allow_duplicate=True), Output("username-store", "data", allow_duplicate=True)],
    Input("logout-btn", "n_clicks"),
    prevent_initial_call=True,
)
def logout(n_clicks):
    if not n_clicks:
        # The Logout button doesn't exist until AFTER login, so Dash fires
        # this callback once automatically the moment it's first created --
        # that's not a real click. Only treat an actual positive click count
        # as a genuine logout.
        raise dash.exceptions.PreventUpdate
    return None, None


# ---- App body: device picker + tabs, only once logged in ----
@app.callback(Output("app-body", "children"), Input("auth-token", "data"))
def render_app_body(token):
    if not token:
        return html.Div("Log in or register above to view your devices.", className="text-muted mt-4")

    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Label("Select Device"),
                dcc.Dropdown(id="device-dropdown", placeholder="Choose a device"),
            ], width=4),
        ], className="mb-3"),

        dbc.Tabs([
            dbc.Tab(label="Live Map", tab_id="live-map-tab"),
            dbc.Tab(label="Analytics", tab_id="analytics-tab"),
            dbc.Tab(label="Geofences", tab_id="geofences-tab"),
            dbc.Tab(label="Anomalies", tab_id="anomalies-tab"),
            dbc.Tab(label="ETA", tab_id="eta-tab"),
            dbc.Tab(label="Sharing", tab_id="sharing-tab"),
        ], id="tabs", active_tab="live-map-tab", className="mb-3"),

        html.Div(id="tab-content"),
    ])


@app.callback(
    Output("device-dropdown", "options"),
    [Input("refresh-interval", "n_intervals"), Input("auth-token", "data")],
)
def update_device_list(n, token):
    if not token:
        return []
    try:
        resp = requests.get(f"{API_URL}/devices", headers=auth_headers(token))
        if not resp.ok:
            return []
        return [{"label": f"{d['device_name']} ({d['owner_name']})", "value": d["id"]} for d in resp.json()]
    except requests.exceptions.RequestException:
        return []


# ---- Tab switcher ----
@app.callback(Output("tab-content", "children"), Input("tabs", "active_tab"))
def render_tab(active_tab):
    if active_tab == "analytics-tab":
        return html.Div([
            dbc.Row(id="kpi-row", className="mb-4 mt-3"),
            html.H5("Frequently Visited Places (auto-detected)"),
            dcc.Graph(id="frequent-locations-map"),
            html.H5("Trips", className="mt-4"),
            html.Div(id="trips-table"),
        ])
    if active_tab == "geofences-tab":
        return html.Div([
            dbc.Row([
                dbc.Col([html.Label("Zone Name"), dbc.Input(id="geofence-name", placeholder="Home")], width=2),
                dbc.Col([html.Label("Latitude"), dbc.Input(id="geofence-lat", type="number")], width=2),
                dbc.Col([html.Label("Longitude"), dbc.Input(id="geofence-lon", type="number")], width=2),
                dbc.Col([html.Label("Radius (m)"), dbc.Input(id="geofence-radius", type="number", value=150)], width=2),
                dbc.Col([html.Br(), dbc.Button("Use Current Location", id="use-current-loc-btn", color="secondary", size="sm")], width=2),
                dbc.Col([html.Br(), dbc.Button("Add Geofence", id="add-geofence-btn", color="primary")], width=2),
            ], className="mb-2 mt-3 align-items-end"),
            html.Div(id="geofence-add-status", className="text-muted mb-4"),
            html.H5("Defined Geofences"),
            html.Div(id="geofence-list", className="mb-4"),
            html.H5("Entry / Exit Log"),
            html.Div(id="geofence-event-log"),
        ])
    if active_tab == "anomalies-tab":
        return html.Div([
            html.P(
                "Flags physically implausible jumps immediately, and statistically unusual "
                "location/time/speed patterns once there's enough history (20+ pings).",
                className="text-muted mt-3",
            ),
            html.Div(id="anomalies-table"),
        ])
    if active_tab == "eta-tab":
        return html.Div([
            dbc.Row([
                dbc.Col([html.Label("Destination Latitude"), dbc.Input(id="eta-dest-lat", type="number")], width=3),
                dbc.Col([html.Label("Destination Longitude"), dbc.Input(id="eta-dest-lon", type="number")], width=3),
                dbc.Col([html.Br(), dbc.Button("Predict ETA", id="predict-eta-btn", color="primary")], width=2),
            ], className="mb-3 mt-3 align-items-end"),
            html.Div(id="eta-result"),
        ])
    if active_tab == "sharing-tab":
        return html.Div([
            html.P(
                "Manage who can view this device's data. Only the device owner can grant or revoke access.",
                className="text-muted mt-3",
            ),
            dbc.Row([
                dbc.Col([html.Label("Share with (username)"), dbc.Input(id="share-username")], width=3),
                dbc.Col([html.Br(), dbc.Button("Grant Access", id="grant-share-btn", color="primary")], width=2),
            ], className="mb-2 align-items-end"),
            html.Div(id="share-status", className="text-muted mb-3"),
            html.H5("Current Access"),
            html.Div(id="share-list"),
        ])
    return html.Div([
        dcc.Graph(id="live-map"),
        html.Div(id="status-line", className="text-muted mt-2"),
    ])


def kpi_card(title, value, subtitle=""):
    return dbc.Col(dbc.Card(dbc.CardBody([
        html.H6(title, className="text-muted"),
        html.H3(value),
        html.Small(subtitle, className="text-muted"),
    ])), width=2)


# ---- Live Map tab ----
@app.callback(
    [Output("live-map", "figure"), Output("status-line", "children")],
    [Input("device-dropdown", "value"), Input("refresh-interval", "n_intervals")],
    State("auth-token", "data"),
    prevent_initial_call=True,
)
def update_map(device_id, n, token):
    if not device_id or not token:
        return go.Figure(), "Select a device to view its location."

    try:
        resp = requests.get(f"{API_URL}/devices/{device_id}/history", params={"limit": 100}, headers=auth_headers(token))
        if not resp.ok:
            return go.Figure(), f"Error: {resp.json().get('detail', resp.text)}"
        history = resp.json()
    except requests.exceptions.RequestException:
        return go.Figure(), "Could not reach the backend."

    if not history:
        return go.Figure(), "No location data yet -- is sharing ON?"

    history = list(reversed(history))
    lats = [p["latitude"] for p in history]
    lons = [p["longitude"] for p in history]

    fig = go.Figure()
    fig.add_trace(go.Scattermap(
        lat=lats, lon=lons, mode="lines+markers",
        marker=dict(size=6, color="blue"), line=dict(width=2, color="blue"), name="Route",
    ))
    fig.add_trace(go.Scattermap(
        lat=[lats[-1]], lon=[lons[-1]], mode="markers",
        marker=dict(size=14, color="red"), name="Current location",
    ))
    fig.update_layout(
        map=dict(center=dict(lat=lats[-1], lon=lons[-1]), zoom=13, style="open-street-map"),
        margin=dict(l=0, r=0, t=0, b=0), height=600,
    )

    latest = history[-1]
    status = f"Last update: {latest['recorded_at']} | Accuracy: {latest['accuracy']} m | Speed: {latest['speed']} m/s"
    return fig, status


# ---- Analytics tab ----
@app.callback(
    [Output("kpi-row", "children"), Output("frequent-locations-map", "figure"), Output("trips-table", "children")],
    [Input("device-dropdown", "value"), Input("refresh-interval", "n_intervals")],
    State("auth-token", "data"),
    prevent_initial_call=True,
)
def update_analytics(device_id, n, token):
    if not device_id or not token:
        return [], go.Figure(), ""

    try:
        summary_resp = requests.get(f"{API_URL}/devices/{device_id}/analytics/summary", headers=auth_headers(token))
        clusters_resp = requests.get(f"{API_URL}/devices/{device_id}/analytics/frequent-locations", headers=auth_headers(token))
        trips_resp = requests.get(f"{API_URL}/devices/{device_id}/trips", headers=auth_headers(token))
    except requests.exceptions.RequestException:
        return [dbc.Col(html.Div("Could not reach the backend."))], go.Figure(), ""

    if not summary_resp.ok:
        return [dbc.Col(html.Div(summary_resp.json().get("detail", "Error")))], go.Figure(), ""

    summary = summary_resp.json()
    clusters = clusters_resp.json() if clusters_resp.ok else []
    trip_list = trips_resp.json() if trips_resp.ok else []

    kpis = [
        kpi_card("Distance Traveled", f"{summary['total_distance_mi']} mi", f"{summary['total_distance_m']} m"),
        kpi_card("Avg Speed", f"{summary['avg_speed_mps'] or '--'} m/s"),
        kpi_card("Max Speed", f"{summary['max_speed_mps'] or '--'} m/s"),
        kpi_card("Duration Tracked", f"{summary['duration_minutes']} min"),
        kpi_card("Total Pings", summary["num_points"]),
    ]

    fig = go.Figure()
    if clusters and not isinstance(clusters, dict):
        fig.add_trace(go.Scattermap(
            lat=[c["center_lat"] for c in clusters],
            lon=[c["center_lon"] for c in clusters],
            mode="markers+text",
            marker=dict(size=[min(10 + c["num_visits"], 40) for c in clusters], color="purple"),
            text=[f"Visited {c['num_visits']}x" for c in clusters],
            textposition="top center",
            name="Frequent Places",
        ))
        center = clusters[0]
        fig.update_layout(
            map=dict(center=dict(lat=center["center_lat"], lon=center["center_lon"]), zoom=11, style="open-street-map"),
            margin=dict(l=0, r=0, t=0, b=0), height=500,
        )
    else:
        fig.update_layout(title="Not enough data yet to detect frequent places (need more pings clustered in one spot)", height=300)

    if not trip_list or isinstance(trip_list, dict):
        trips_table = html.Div(
            "No discrete trips detected yet (need a 10+ minute gap between pings to separate two trips).",
            className="text-muted",
        )
    else:
        trips_table = dbc.Table([
            html.Thead(html.Tr([
                html.Th("Trip #"), html.Th("Start"), html.Th("End"),
                html.Th("Distance"), html.Th("Avg Speed"), html.Th("Duration"),
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(t["trip_number"]), html.Td(t["start_time"]), html.Td(t["end_time"]),
                    html.Td(f"{t['total_distance_mi']} mi"), html.Td(f"{t['avg_speed_mps'] or '--'} m/s"),
                    html.Td(f"{t['duration_minutes']} min"),
                ]) for t in trip_list
            ]),
        ], bordered=True, size="sm")

    return kpis, fig, trips_table


# ---- Geofences tab ----
@app.callback(
    [Output("geofence-lat", "value"), Output("geofence-lon", "value")],
    Input("use-current-loc-btn", "n_clicks"),
    [State("device-dropdown", "value"), State("auth-token", "data")],
    prevent_initial_call=True,
)
def fill_current_location(n_clicks, device_id, token):
    if not device_id:
        return dash.no_update, dash.no_update
    try:
        resp = requests.get(f"{API_URL}/devices/{device_id}/location", headers=auth_headers(token))
        if not resp.ok:
            return dash.no_update, dash.no_update
        loc = resp.json()
        return loc.get("latitude"), loc.get("longitude")
    except requests.exceptions.RequestException:
        return dash.no_update, dash.no_update


@app.callback(
    Output("geofence-add-status", "children"),
    Input("add-geofence-btn", "n_clicks"),
    [State("device-dropdown", "value"), State("geofence-name", "value"),
     State("geofence-lat", "value"), State("geofence-lon", "value"), State("geofence-radius", "value"),
     State("auth-token", "data")],
    prevent_initial_call=True,
)
def add_geofence(n_clicks, device_id, name, lat, lon, radius, token):
    if not device_id:
        return "Select a device first."
    if not name or lat is None or lon is None:
        return "Name, latitude, and longitude are all required."

    try:
        resp = requests.post(
            f"{API_URL}/geofences",
            json={"device_id": device_id, "name": name, "center_lat": lat, "center_lon": lon, "radius_meters": radius or 150},
            headers=auth_headers(token),
        )
        if resp.ok:
            return f"Added geofence '{name}' ({radius or 150}m radius)."
        return f"Failed: {resp.json().get('detail', resp.text)}"
    except requests.exceptions.RequestException as e:
        return f"Could not reach backend: {e}"


@app.callback(
    [Output("geofence-list", "children"), Output("geofence-event-log", "children")],
    [Input("device-dropdown", "value"), Input("refresh-interval", "n_intervals"), Input("geofence-add-status", "children")],
    State("auth-token", "data"),
    prevent_initial_call=True,
)
def refresh_geofences(device_id, n, add_status, token):
    if not device_id:
        return "Select a device to see its geofences.", ""

    try:
        fences_resp = requests.get(f"{API_URL}/devices/{device_id}/geofences", headers=auth_headers(token))
        events_resp = requests.get(f"{API_URL}/devices/{device_id}/geofence-events", headers=auth_headers(token))
    except requests.exceptions.RequestException:
        return "Could not reach backend.", ""

    fences = fences_resp.json() if fences_resp.ok else []
    events = events_resp.json() if events_resp.ok else []
    fence_by_id = {f["id"]: f["name"] for f in fences}

    if not fences:
        fence_list = html.Div("No geofences defined yet -- add one above.", className="text-muted")
    else:
        fence_list = dbc.Table([
            html.Thead(html.Tr([html.Th("Name"), html.Th("Center"), html.Th("Radius")])),
            html.Tbody([
                html.Tr([html.Td(f["name"]), html.Td(f"{f['center_lat']:.5f}, {f['center_lon']:.5f}"), html.Td(f"{f['radius_meters']} m")])
                for f in fences
            ]),
        ], bordered=True, size="sm")

    if not events:
        event_log = html.Div("No entry/exit events yet.", className="text-muted")
    else:
        event_log = dbc.Table([
            html.Thead(html.Tr([html.Th("Time"), html.Th("Zone"), html.Th("Event")])),
            html.Tbody([
                html.Tr([
                    html.Td(e["occurred_at"]), html.Td(fence_by_id.get(e["geofence_id"], "?")),
                    html.Td(html.Span(e["event_type"], style={"color": "green" if e["event_type"] == "ENTERED" else "crimson", "fontWeight": "bold"})),
                ]) for e in events
            ]),
        ], bordered=True, size="sm")

    return fence_list, event_log


# ---- Anomalies tab ----
@app.callback(
    Output("anomalies-table", "children"),
    [Input("device-dropdown", "value"), Input("refresh-interval", "n_intervals")],
    State("auth-token", "data"),
    prevent_initial_call=True,
)
def update_anomalies(device_id, n, token):
    if not device_id:
        return "Select a device."

    try:
        resp = requests.get(f"{API_URL}/devices/{device_id}/anomalies", headers=auth_headers(token))
    except requests.exceptions.RequestException:
        return "Could not reach backend."

    if not resp.ok:
        return html.Div(resp.json().get("detail", "Error"), className="text-muted")

    flags = resp.json()
    if not flags:
        return html.Div("No anomalies detected.", className="text-muted")

    return dbc.Table([
        html.Thead(html.Tr([html.Th("Time"), html.Th("Location"), html.Th("Score"), html.Th("Reason(s)")])),
        html.Tbody([
            html.Tr([
                html.Td(a["recorded_at"]), html.Td(f"{a['latitude']:.5f}, {a['longitude']:.5f}"),
                html.Td(a["anomaly_score"] if a["anomaly_score"] is not None else "--"),
                html.Td("; ".join(a["reasons"]), style={"color": "crimson"}),
            ]) for a in flags
        ]),
    ], bordered=True, size="sm")


# ---- ETA tab ----
@app.callback(
    Output("eta-result", "children"),
    Input("predict-eta-btn", "n_clicks"),
    [State("device-dropdown", "value"), State("eta-dest-lat", "value"), State("eta-dest-lon", "value"), State("auth-token", "data")],
    prevent_initial_call=True,
)
def predict_eta_callback(n_clicks, device_id, dest_lat, dest_lon, token):
    if not device_id:
        return "Select a device first."
    if dest_lat is None or dest_lon is None:
        return "Enter a destination latitude and longitude."

    try:
        resp = requests.post(
            f"{API_URL}/eta",
            json={"device_id": device_id, "dest_lat": dest_lat, "dest_lon": dest_lon},
            headers=auth_headers(token),
        )
        if not resp.ok:
            return f"Failed: {resp.json().get('detail', resp.text)}"
        result = resp.json()
    except requests.exceptions.RequestException as e:
        return f"Could not reach backend: {e}"

    method_note = (
        "based on this device's own historical trip speeds"
        if result["method"] == "historical"
        else "using a default speed assumption -- not enough trip history yet for this device"
    )
    return dbc.Card(dbc.CardBody([
        html.H4(f"{result['predicted_eta_minutes']} min"),
        html.P(f"Range: {result['eta_interval_minutes'][0]}\u2013{result['eta_interval_minutes'][1]} min"),
        html.P(f"Distance: {result['distance_mi']} mi ({result['distance_m']} m)"),
        html.Small(f"Assumed speed: {result['assumed_speed_mps']} m/s -- {method_note}", className="text-muted"),
    ]))


# ---- Sharing tab ----
@app.callback(
    Output("share-status", "children"),
    Input("grant-share-btn", "n_clicks"),
    [State("device-dropdown", "value"), State("share-username", "value"), State("auth-token", "data")],
    prevent_initial_call=True,
)
def grant_share(n_clicks, device_id, viewer_username, token):
    if not device_id or not viewer_username:
        return "Select a device and enter a username."
    try:
        resp = requests.post(
            f"{API_URL}/devices/{device_id}/share", json={"viewer_username": viewer_username}, headers=auth_headers(token)
        )
        if resp.ok:
            return f"Granted access to '{viewer_username}'."
        return f"Failed: {resp.json().get('detail', resp.text)}"
    except requests.exceptions.RequestException as e:
        return f"Could not reach backend: {e}"


@app.callback(
    Output("share-list", "children"),
    [Input("device-dropdown", "value"), Input("refresh-interval", "n_intervals"), Input("share-status", "children")],
    State("auth-token", "data"),
    prevent_initial_call=True,
)
def refresh_shares(device_id, n, status, token):
    if not device_id:
        return "Select a device."
    try:
        resp = requests.get(f"{API_URL}/devices/{device_id}/shares", headers=auth_headers(token))
    except requests.exceptions.RequestException:
        return "Could not reach backend."

    if not resp.ok:
        return html.Div(resp.json().get("detail", "Could not load shares (are you the owner?)."), className="text-muted")

    shares = resp.json()
    if not shares:
        return html.Div("Not shared with anyone yet.", className="text-muted")

    return dbc.Table([
        html.Thead(html.Tr([html.Th("Viewer"), html.Th("Status")])),
        html.Tbody([html.Tr([html.Td(s["viewer_username"]), html.Td("Active" if s["active"] else "Revoked")]) for s in shares]),
    ], bordered=True, size="sm")


if __name__ == "__main__":
    app.run(debug=True, port=8050)