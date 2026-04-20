import service


def test_handle():
    result = service.handle()
    assert result is not None
