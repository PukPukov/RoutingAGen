"""Mocked sources, cache and DNS; no real requests."""

import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from routingagen import Sources


@pytest.mark.parametrize("data", [["b", "a", "b"], {"one": ["b", "a"], "two": ["b"]}])
def test_source_formats(config, render, session, reply, data):
    session.get.return_value = reply(data)
    assert render("{{ resolve(vars.url) }}") == "b, a"
    assert json.loads(Path(".cache").read_text())[config["vars"]["url"]]["data"] == data


def test_fresh_cache_avoids_http(render, session, seed_cache):
    seed_cache(["saved"], timestamp=time.time())
    assert render("{{ resolve(vars.url) }}") == "saved"
    session.get.assert_not_called()


@pytest.mark.parametrize("failure", [requests.ConnectionError("offline"), ValueError("not JSON")])
def test_stale_cache_fallback(render, session, seed_cache, caplog, failure):
    seed_cache(["saved"])
    session.get.side_effect = failure
    assert render("{{ resolve(vars.url) }}") == "saved"
    assert "устаревший кеш" in caplog.text


@pytest.mark.parametrize("data", [{"error": [500]}, {"error": "failed"}, "failed"])
def test_invalid_response_does_not_poison_cache(render, session, reply, seed_cache, data):
    seed_cache(["saved"])
    old = Path(".cache").read_text()
    session.get.return_value = reply(data)
    assert render("{{ resolve(vars.url) }}") == "saved"
    assert Path(".cache").read_text() == old


@pytest.mark.parametrize("cache", ["{", "[]", '{"https://example.org/list": {"timestamp": "bad"}}'])
def test_bad_cache_recovers(render, session, reply, cache):
    Path(".cache").write_text(cache)
    session.get.return_value = reply(["new"])
    assert render("{{ resolve(vars.url) }}") == "new"


def test_unavailable_source_without_cache_fails(render, session):
    session.get.side_effect = requests.Timeout("timeout")
    with pytest.raises(ValueError, match="кеш пуст"):
        render("{{ resolve(vars.url) }}")


@pytest.mark.parametrize("online", [True, False])
def test_each_response_is_parsed_once(config, session, reply, seed_cache, online):
    if online:
        session.get.return_value = reply(["a", "a"])
    else:
        seed_cache(["a", "a"])
        session.get.side_effect = requests.ConnectionError("offline")
    parse = Mock(side_effect=len)
    assert Sources(config, session).fetch(config["vars"]["url"], parse) == 2
    parse.assert_called_once_with(["a", "a"])


def test_read_only_cache_does_not_discard_response(render, session, reply, monkeypatch):
    monkeypatch.setattr("routingagen.write_text", Mock(side_effect=OSError("read-only")))
    session.get.return_value = reply(["a"])
    assert render("{{ resolve(vars.url) }}") == "a"


def test_to_ip_resolves_a_and_minecraft_srv(render, session, dns_reply):
    answers = {
        "https://dns.google/resolve?name=_minecraft._tcp.game.test&type=SRV": dns_reply(
            (33, "0 5 25565 node.test.")
        ),
        "https://dns.google/resolve?name=game.test&type=A": dns_reply(
            (5, "node.test."), (1, "192.0.2.1")
        ),
        "https://dns.google/resolve?name=node.test&type=A": dns_reply(
            (1, "192.0.2.2"), (1, "192.0.2.1")
        ),
    }
    session.get.side_effect = lambda url, **kwargs: answers[url]
    assert (
        render("{{ toIp(lists.hosts) }}", lists={"hosts": ["game.test", "game.test"]})
        == "192.0.2.1, 192.0.2.2"
    )
    assert session.get.call_count == 3


def test_remote_ips_and_dns_are_deduplicated_together(render, session, reply, dns_reply):
    session.get.side_effect = [
        reply(["192.0.2.1"]),
        dns_reply(),
        dns_reply((1, "192.0.2.1"), (1, "192.0.2.2")),
    ]
    assert (
        render("{{ resolve(vars.url) + toIp(lists.hosts) }}", lists={"hosts": ["game.test"]})
        == "192.0.2.1, 192.0.2.2"
    )


def test_nxdomain_and_unavailable_srv(render, session, dns_reply, caplog):
    session.get.side_effect = [dns_reply((33, "0 0 0 .")), dns_reply(status=3)]
    assert render("{{ toIp(lists.hosts) }}", lists={"hosts": ["game.test"]}) == ""
    assert "Не найдено IP" in caplog.text
    assert session.get.call_count == 2


@pytest.mark.parametrize(
    "invalid", [{"Status": 2}, {"Status": 0, "Answer": [{"type": 1, "data": "invalid"}]}]
)
def test_invalid_dns_response_uses_stale_cache(
    render, session, reply, dns_reply, seed_cache, invalid
):
    url = "https://dns.google/resolve?name=game.test&type=A"
    seed_cache({"Status": 0, "Answer": [{"type": 1, "data": "192.0.2.1"}]}, url=url)
    session.get.side_effect = [dns_reply(), reply(invalid)]
    assert render("{{ toIp(lists.hosts) }}", lists={"hosts": ["game.test"]}) == "192.0.2.1"


@pytest.mark.parametrize("values", ["game.test", ["game.test"]])
def test_to_ip_requires_dictionary(config, session, values):
    with pytest.raises(TypeError):
        Sources(config, session).to_ip(values)
    session.get.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"Status": 2, "Comment": "upstream timed out"},
        {"Status": 5, "Comment": "query refused"},
        {"error": "API rate limit exceeded"},
    ],
)
def test_dns_error_contains_request_url_and_complete_response(config, session, reply, data):
    session.get.return_value = reply(data)
    with pytest.raises(ValueError) as error:
        Sources(config, session).dns_answers("game.test", "A")
    message = str(error.value)
    assert "https://dns.google/resolve?name=game.test&type=A" in message
    assert repr(data) in message
