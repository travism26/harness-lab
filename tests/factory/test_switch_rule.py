from factory.switch_rule import is_factory_app, refusal

OWNER, SLUG = "travism26", "harness-factory"


def test_owner_work_may_use_the_subscription():
    assert refusal("subscription", ["travism26"], OWNER, SLUG) is None


def test_the_factory_app_counts_as_the_owner_in_both_spellings():
    assert refusal("subscription", ["harness-factory[bot]", "app/harness-factory"], OWNER, SLUG) is None


def test_someone_elses_work_refuses_the_subscription():
    reason = refusal("subscription", ["travism26", "stranger"], OWNER, SLUG)
    assert reason and "stranger" in reason and "openrouter" in reason


def test_scheduled_runs_refuse_the_subscription():
    assert refusal("subscription", [OWNER], OWNER, SLUG, scheduled=True)


def test_openrouter_may_act_on_anyones_work():
    assert refusal("openrouter", ["stranger"], OWNER, SLUG, scheduled=True) is None


def test_unknown_login_is_refused():
    assert "must be one of" in refusal("api-key", [OWNER], OWNER, SLUG)


def test_no_slug_matches_no_app():
    assert not is_factory_app("[bot]", "")
