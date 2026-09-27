"""Import-safe shared helpers for standalone verification tools."""

import math


def assert_near(a, b, path='root', *, rel_tol, abs_tol, require_finite):
    """Compare JSON-like values using the caller's numeric policy.

    Booleans retain scalar equality semantics rather than numeric tolerance.
    Every mismatch, including container structure, reports its compared path.
    """
    mismatch = (path, a, b)
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), mismatch
        for key in a:
            assert_near(a[key], b[key], f'{path}.{key}', rel_tol=rel_tol,
                        abs_tol=abs_tol, require_finite=require_finite)
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), mismatch
        for index, (x, y) in enumerate(zip(a, b)):
            assert_near(x, y, f'{path}[{index}]', rel_tol=rel_tol,
                        abs_tol=abs_tol, require_finite=require_finite)
    elif isinstance(a, (int, float)) and not isinstance(a, bool):
        assert isinstance(b, (int, float)), mismatch
        assert (not require_finite or math.isfinite(b)) and math.isclose(
            a, b, rel_tol=rel_tol, abs_tol=abs_tol), mismatch
    else:
        assert a == b, mismatch
