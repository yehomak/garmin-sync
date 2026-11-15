from garmin_sync import docs


def test_data_dictionary_matches_schema():
    """docs/DATA.md is generated from schema.sql comments. Regenerate: python -m garmin_sync.docs"""
    assert docs.OUT.read_text() == docs.render()
