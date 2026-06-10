from app.server import app


def test_server_exposes_health_and_mcp_routes():
    paths = [route.path for route in app.routes]

    assert "/healthz" in paths
    assert "" in paths
