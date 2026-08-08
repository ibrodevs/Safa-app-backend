from pathlib import Path


def test_stop_serializer_has_compact_safa_hierarchy():
    source = Path('apps/delivery/serializer.py').read_text()
    assert '"district"' in source
    assert 'parts.append(f"Базар: {bazar}")' in source
    assert 'parts.append(f"Район: {district}")' in source
    assert 'parts.append(f"Проход: {passage}")' in source
    assert 'parts.append(f"Контейнер: {container}")' in source
