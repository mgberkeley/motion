from motion import Component

import pytest

C = Component("MyComponent")


@C.init_state
def setUp():
    return {"value": 0}


@C.serve("my_key")
def serve(state, props):
    return state.instance_id


def test_write_state():
    c_instance = C()
    assert c_instance.read_state("value") == 0
    c_instance.write_state({"value": 1, "value2": 2})
    assert c_instance.read_state("value") == 1
    assert c_instance.read_state("value2") == 2

    # Test something that should fail
    with pytest.raises(TypeError):
        c_instance.write_state(1)

    with pytest.raises(TypeError):
        c_instance.write_state("Hello")

    # Should do nothing
    c_instance.write_state({})


def test_read_instance_id():
    c_instance = C("some_id")
    assert c_instance.run("my_key", ignore_cache=True) == "some_id"
