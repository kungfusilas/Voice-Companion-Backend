import textwrap

import pytest

from benchmark import loader


def test_loads_events_and_checkpoints(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(textwrap.dedent('''
      scenario: t
      events:
        - time: "2026-01-10"
          companion: aeva
          user: "I live in Bethlehem."
          extraction:
            - subject_type: user
              predicate: home_city
              value_json: {city: Bethlehem}
              confirmation_status: explicitly_stated
              valid_from: "2026-01-10"
        - checkpoint: c1
          expected_active:
            - key: user.home_city
              value: {city: Bethlehem}
    '''))
    sc = loader.load_scenario(str(p))
    assert sc.name == "t"
    assert len(sc.events) == 2
    assert sc.events[0]["kind"] == "turn"
    assert sc.events[1]["kind"] == "checkpoint"


def test_rejects_non_string_key(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text('scenario: b\nevents:\n  - checkpoint: c\n    expected_active:\n      - key: 123\n')
    with pytest.raises(ValueError):
        loader.load_scenario(str(p))
