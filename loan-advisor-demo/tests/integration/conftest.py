def pytest_addoption(parser):
    parser.addoption(
        "--agent-resource",
        default=None,
        help="Full Agent Engine resource name, e.g. projects/123/locations/us-central1/reasoningEngines/456",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "smoke: fast sanity checks for deployed agent")
