from mvs.infrastructure.observability import PrometheusTelemetry


def test_collector_isolation_and_label_bounds():
    one, two = PrometheusTelemetry({"demo"}), PrometheusTelemetry({"demo"})
    one.shell_finished("user supplied secret", "error", 0.25)
    one.policy_denied("user supplied host", "user supplied token")
    one.registry_finished("demo", "cancelled", 0.5)
    assert "user supplied" not in one.export().decode()
    assert (
        one.registry.get_sample_value(
            "mvs_shell_requests_total", {"command": "unknown", "status": "error"}
        )
        == 1
    )
    assert (
        two.registry.get_sample_value(
            "mvs_shell_requests_total", {"command": "unknown", "status": "error"}
        )
        is None
    )
