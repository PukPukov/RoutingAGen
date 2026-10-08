"""All tests run in a temporary directory with HTTP/DNS prohibited."""

import json
import socket
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from routingagen import generate

URL = "https://example.org/list"


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("home").mkdir()
    monkeypatch.setattr("routingagen.__file__", str(tmp_path / "home/routingagen.py"))

    def forbidden(*args, **kwargs):
        raise AssertionError("Реальные HTTP/DNS-запросы запрещены в автотестах")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    for method in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, method, forbidden)


@pytest.fixture
def config():
    return {
        "cache": {"ttl_seconds": 60, "file": ".cache"},
        "dns": {"doh_url": "https://dns.google/resolve"},
        "vars": {"url": URL},
        "rules": "default: direct",
    }


@pytest.fixture
def session():
    return Mock()


@pytest.fixture
def reply():
    def make(data):
        response = Mock()
        response.json.return_value = data
        return response

    return make


@pytest.fixture
def dns_reply(reply):
    def make(*answers, status=0):
        return reply(
            {"Status": status, "Answer": [{"type": kind, "data": data} for kind, data in answers]}
        )

    return make


@pytest.fixture
def render(config, session):
    return lambda rules, **settings: generate(config | {"rules": rules} | settings, session)


@pytest.fixture
def seed_cache(config):
    def write(data, timestamp=0, url=URL):
        Path(config["cache"]["file"]).write_text(
            json.dumps({url: {"timestamp": timestamp, "data": data}})
        )

    return write
