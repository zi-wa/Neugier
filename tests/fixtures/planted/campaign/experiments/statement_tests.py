def test_sumset_pair():
    assert {0, 1, 2} == {a + b for a in {0, 1} for b in {0, 1}}
