"""
Tests the following api functions:

* Python API: get, mget, set, sql, wait_for_trigger, session_id
* Python API: blob data

"""
import motion
import os
import pytest
import random


@pytest.fixture
def test_client(basic_config_with_cron):
    # Create store and client
    connection = motion.test(basic_config_with_cron, session_id="TESTING")
    yield connection

    # Close connection
    connection.close(wait=False)


def test_python_set(test_client):
    connection = test_client

    # Specify all keywords
    student_id = connection.set(
        relation="test",
        identifier="some_student_id_1",
        key_values={"name": "Mary", "age": random.randint(10, 30)},
    )
    assert student_id == "some_student_id_1"

    # Don't specify keywords
    with pytest.raises(TypeError):
        student_id = connection.set(
            "test",
            "some_student_id_2",
            {"name": "Mary", "age": random.randint(10, 30)},
        )

    # Nonexistent relation
    with pytest.raises(KeyError):
        student_id = connection.set(
            relation="nonexistent",
            identifier="some_student_id_2",
            key_values={"name": "Mary", "age": random.randint(10, 30)},
        )

    # Trying to set without identifiers
    student_id = connection.set(
        relation="test",
        identifier="",
        key_values={"name": "Mary", "age": random.randint(10, 30)},
    )
    assert student_id is not None
    assert student_id != ""
    student_id = connection.set(
        relation="test",
        identifier=None,
        key_values={"name": "Mary", "age": random.randint(10, 30)},
    )
    assert student_id is not None
    assert student_id != ""

    # Setting kv pairs that don't exist in the relation
    with pytest.raises(AttributeError):
        student_id = connection.set(
            relation="test",
            identifier=None,
            key_values={"heheheh": "Mary", "age": random.randint(10, 30)},
        )
        student_id = connection.set(
            relation="test",
            identifier=None,
            key_values="something",
        )


def test_python_get(test_client):
    connection = test_client

    # Set some data
    student_id = connection.set(
        relation="test",
        identifier="",  # Let the client generate an identifier
        key_values={"name": "Mary", "age": random.randint(10, 30)},
    )

    # Specify all keywords
    results = connection.get(
        identifier=student_id, relation="test", keys=["*"]
    )
    assert results["name"] == "Mary"
    assert results["doubled_age"] == 2 * results["age"]
    assert results["session_id"] == connection.session_id

    # Get as dataframe
    results = connection.get(
        identifier=student_id, relation="test", keys=["*"], as_df=True
    )
    assert results["name"].values[0] == "Mary"
    assert results["doubled_age"].values[0] == 2 * results["age"].values[0]

    # Test derived ids
    derived_id = connection.duplicate(relation="test", identifier=student_id)
    results = connection.get(
        identifier=student_id,
        relation="test",
        keys=["*"],
        as_df=True,
        include_derived=True,
    )
    assert len(results) == 2

    # Get results that don't exist
    results = connection.get(
        identifier="nonexistent",
        relation="test",
        keys=["*"],
        include_derived=False,
    )
    assert not results


def test_python_mget(test_client):
    connection = test_client

    # Set some data
    student_id = connection.set(
        relation="test",
        identifier="",  # Let the client generate an identifier
        key_values={"name": "Mary", "age": random.randint(10, 30)},
    )
    student_id_2 = connection.set(
        relation="test",
        identifier="",  # Let the client generate an identifier
        key_values={"name": "John", "age": random.randint(10, 30)},
    )

    # Specify all keywords
    results = connection.mget(
        identifiers=[student_id, student_id_2],
        relation="test",
        keys=["*"],
    )

    assert len(results) == 2
    assert results[0]["name"] == "Mary"
    assert results[0]["doubled_age"] == 2 * results[0]["age"]
    assert results[0]["session_id"] == connection.session_id
    assert results[1]["name"] == "John"
    assert results[1]["doubled_age"] == 2 * results[1]["age"]
    assert results[1]["session_id"] == connection.session_id

    # Get as dataframe
    results = connection.mget(
        identifiers=[student_id, student_id_2],
        relation="test",
        keys=["*"],
        as_df=True,
    )
    assert len(results) == 2
    assert results["name"].values[0] == "Mary"
    assert results["doubled_age"].values[0] == 2 * results["age"].values[0]
    assert results["name"].values[1] == "John"
    assert results["doubled_age"].values[1] == 2 * results["age"].values[1]

    # Test derived ids
    derived_id = connection.duplicate(relation="test", identifier=student_id)
    derived_id_2 = connection.duplicate(
        relation="test", identifier=student_id_2
    )
    results = connection.mget(
        identifiers=[student_id, student_id_2],
        relation="test",
        keys=["*"],
        as_df=True,
        include_derived=True,
    )
    assert len(results) == 4

    # Get results that don't exist
    results = connection.mget(
        identifiers=["nonexistent", student_id_2],
        relation="test",
        keys=["*"],
        include_derived=False,
    )
    assert len(results) == 1


def test_python_sql(test_client):
    connection = test_client

    # Set some data
    student_id = connection.set(
        relation="test",
        identifier="",  # Let the client generate an identifier
        key_values={"name": "Mary", "age": random.randint(10, 30)},
    )

    # Run sql query
    results = connection.sql(
        query=f"SELECT * FROM test WHERE identifier = '{student_id}'",
    )
    assert len(results) == 1


def test_wait_for_trigger(test_client):
    connection = test_client
    res = connection.waitForTrigger("cron_trigger")
    assert res == "cron_trigger"

    # Try waiting for invalid trigger
    with pytest.raises(FileNotFoundError):
        connection.waitForTrigger("invalid_trigger")


def test_wait_for_triggers(basic_config_with_cron):
    # Create store and client
    basic_config_with_cron["application"]["name"] = "test_wait_for_triggers"
    connection = motion.test(
        basic_config_with_cron,
        session_id="TESTING",
        wait_for_triggers=["cron_trigger"],
    )

    # Retrieve result
    res = connection.sql(query="SELECT * FROM test WHERE name = 'Johnny'")
    assert len(res) == 1

    # Close connection
    connection.close(wait=False)


def test_blob_data(basic_config_with_blob):
    # Create connection
    connection = motion.test(basic_config_with_blob, session_id="TESTING")

    # Set some data
    img_path = os.path.join(os.path.dirname(__file__), "assets/landscape.jpeg")
    student_id = connection.set(
        relation="test",
        identifier="",
        key_values={
            "name": "Mary",
            "age": random.randint(10, 30),
            "photo": open(img_path, "rb").read(),
        },
    )

    # Read back the blob
    results = connection.get(
        identifier=student_id, relation="test", keys=["*"], as_df=True
    )
    assert results["photo"].values[0] == open(img_path, "rb").read()