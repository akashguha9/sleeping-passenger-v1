from src.scoring.state_classifier import classify_state


def test_high_ems_low_eqs_is_ignore() -> None:
    assert classify_state(ems=0.80, eqs=0.40, ds=0.5, ls=0.5, efs=0.2, aps=0.6).state == "IGNORE"


def test_medium_aps_is_watch() -> None:
    assert classify_state(ems=0.3, eqs=0.5, ds=0.5, ls=0.5, efs=0.3, aps=0.4).state == "WATCH"


def test_strong_evidence_but_not_enough_paper_thresholds_is_validate() -> None:
    assert classify_state(ems=0.3, eqs=0.6, ds=0.5, ls=0.45, efs=0.45, aps=0.58).state == "VALIDATE"


def test_all_thresholds_passed_is_paper_trade() -> None:
    assert classify_state(ems=0.2, eqs=0.7, ds=0.7, ls=0.6, efs=0.2, aps=0.8).state == "PAPER_TRADE"
