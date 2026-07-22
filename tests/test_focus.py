from src.core.focus import FocusParser


def test_parse_af_points_returns_empty_list():
    parser = FocusParser()
    assert parser.parse_af_points("D:/photos/test.jpg") == []
