import helper
import service


def test_integration():
    svc_result = service.handle()
    hlp_result = helper.work()
    assert svc_result == hlp_result
