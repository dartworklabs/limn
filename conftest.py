"""What every test run shares: no property test fails for taking long.

Hypothesis fails an example past 200 ms (deadline) and a run whose input generation is slow (the too_slow health check). Both
read the wall clock, and neither is what a property says: on a busy machine a pure function failed at 539 ms. A hang is still
caught, by CI's job limits and faulthandler_timeout (docs/handbook/verification.md §검증 시간과 병렬 실행).
"""

from hypothesis import HealthCheck, settings

settings.register_profile("limn", deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("limn")
