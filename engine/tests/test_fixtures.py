from sylo.record_fixtures import main


def test_recorded_fixtures_are_up_to_date():
    assert main(["--check"]) == 0, "run `make fixtures`"
