from pathlib import Path

from app.config import load_config


def test_load_example_config():
    config = load_config(Path("sap-mcp.example.yaml"))

    assert config.server.name == "SAP BTP Trial ABAP ADT MCP Server"
    assert config.abap_dev.system_url == "https://your-abap-instance.abap.region.hana.ondemand.com"
    assert config.abap_dev.readable_packages == ["*"]
    assert config.abap_dev.allowed_packages == ["Z*"]
    assert config.abap_dev.allow_write is False
    assert config.abap_dev.allow_activate is False
