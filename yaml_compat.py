"""Read YAML with Hermes' ruamel.yaml when optional PyYAML is absent."""

try:
    import yaml as _pyyaml
except ImportError:
    _pyyaml = None


def safe_load(source):
    if _pyyaml is not None:
        return _pyyaml.safe_load(source)
    from ruamel.yaml import YAML
    return YAML(typ="safe").load(source)
