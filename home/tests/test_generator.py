"""The single generation path and its Jinja substitutions."""

import socket
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml
from jinja2 import TemplateError

from routingagen import exclude, main, string_dict, write_text


def test_plain_routinga_text_is_not_interpreted(render, session):
    text = "# anything\ndefault: future\nnewRule(<x>)->unknown-action\n"
    assert render(text) == text
    session.get.assert_not_called()


def test_nested_functions_and_merge(render, session, reply):
    session.get.return_value = reply({"site": ["excluded", "a", "a", "b"]})
    text = "domain({{ exclude(lists.exclude, resolve(vars.url)) + lists.main }})->custom"
    assert (
        render(text, lists={"main": ["b", "local"], "exclude": ["excluded"]})
        == "domain(a, b, local)->custom"
    )


@pytest.mark.parametrize("expression", ["lists.main", 'lists["main"]', '{"b": none, "a": none}'])
def test_dictionaries_are_formatted_in_insertion_order(render, expression):
    assert render("{{ " + expression + " }}", lists={"main": ["b", "a", "b"]}) == "b, a"


def test_merge_deduplicates_before_finalization(render):
    text = (
        "{% set x = lists.one + lists.two %}"
        '{% if x | length == 3 and x | join(";") == "a;b;c" %}{{ x }}{% else %}incorrect{% endif %}'
    )
    assert render(text, lists={"one": ["a", "b"], "two": ["b", "c"]}) == "a, b, c"


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("lists.one + lists.two + lists.one", "b, a, c"),
        ("lists.empty + lists.one", "b, a"),
        ("lists.one + lists.empty", "b, a"),
        ("lists.empty + lists.empty", ""),
    ],
)
def test_merge_preserves_order_and_does_not_mutate_inputs(render, expression, expected):
    text = "{{ " + expression + " }}|{{ lists.one }}|{{ lists.two }}"
    assert render(text, lists={"one": ["b", "a"], "two": ["a", "c"], "empty": []}) == (
        expected + "|b, a|a, c"
    )


@pytest.mark.parametrize("expression", ["2 + 3", '"a" + "b"', "[1] + [2]", 'lists.main + "bad"'])
def test_addition_requires_dictionaries(render, expression):
    with pytest.raises(TypeError):
        render("{{ " + expression + " }}", lists={"main": ["a"]})


@pytest.mark.parametrize("expression", ['"a, a"', "42", "[1, 1]", "none", "vars.url", "{1: none}"])
def test_finalization_requires_dictionary_with_string_keys(render, expression):
    with pytest.raises(TypeError):
        render("{{ " + expression + " }}")


@pytest.mark.parametrize(
    "values", [("b", "a", "b"), {"b": None, "a": None}, (value for value in ("b", "a", "b"))]
)
def test_string_dict_deduplicates_and_preserves_order(values):
    result = string_dict(values)
    assert isinstance(result, dict)
    assert tuple(result) == ("b", "a")
    assert all(value is None for value in result.values())


def test_exclusion_is_exact():
    assert exclude({"a": None}, {"a": None, "sub.a": None, "b": None}) == {
        "sub.a": None,
        "b": None,
    }


@pytest.mark.parametrize("values", ["a", ["a"]])
def test_exclusion_requires_dictionaries(values):
    with pytest.raises(TypeError):
        exclude(values, {"a": None})
    with pytest.raises(TypeError):
        exclude({"a": None}, values)


@pytest.mark.parametrize(
    "expression",
    [
        "lists.missing",
        "vars.missing",
        "unknown()",
        'list("main")',
        "domains(vars.url)",
        "ips(vars.url)",
    ],
)
def test_unknown_names_fail(render, expression):
    with pytest.raises((TemplateError, TypeError)):
        render("{{ " + expression + " }}")


def test_syntax_errors_fail(render):
    with pytest.raises(TemplateError):
        render("{{ broken(")


def test_main_reads_config_beside_script(config, monkeypatch):
    Path("home/config.yml").write_text(yaml.safe_dump(config))
    Path("work").mkdir()
    monkeypatch.chdir("work")
    Path("config.yml").write_text("not: used")
    assert main() == 0
    assert Path("rules").read_text() == "default: direct"


@pytest.mark.parametrize("rules", ["{{ unknown }}", "{{ resolve(vars.url) }}", '{{ "bad" }}'])
def test_failure_preserves_working_rules(config, monkeypatch, rules):
    config["rules"] = rules
    Path("home/config.yml").write_text(yaml.safe_dump(config))
    Path("rules").write_text("working")
    monkeypatch.setattr(
        requests.Session, "get", Mock(side_effect=requests.ConnectionError("offline"))
    )
    assert main() == 1
    assert Path("rules").read_text() == "working"


def test_missing_config_fails():
    assert main() == 1


def test_atomic_write_failure_preserves_file(monkeypatch):
    Path("rules").write_text("working")
    monkeypatch.setattr("atomicwrites.os.rename", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError):
        write_text("rules", "new")
    assert Path("rules").read_text() == "working"


def test_network_guard():
    with pytest.raises(AssertionError, match="запрещены"):
        requests.get("https://example.org")
    with pytest.raises(AssertionError, match="запрещены"):
        socket.getaddrinfo("example.org", 53)
