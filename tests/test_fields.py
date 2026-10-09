"""Tests for the fields module."""

import pytest

from labschema.errors import SchemaError
from labschema.fields import Field


class TestFieldConstruction:
    """Tests for Field construction."""

    def test_basic_field(self) -> None:
        f = Field("name", str)
        assert f.name == "name"
        assert f.dtype is str
        assert f.nullable is False
        assert f.unit is None

    def test_numeric_field_with_unit(self) -> None:
        f = Field("temperature", float, unit="degC")
        assert f.name == "temperature"
        assert f.dtype is float
        assert f.unit == "degC"

    def test_nullable_field(self) -> None:
        f = Field("optional", str, nullable=True)
        assert f.nullable is True

    def test_field_with_constraints(self) -> None:
        f = Field("value", float, ge=0, le=100)
        assert f.ge == 0
        assert f.le == 100

    def test_field_with_pattern(self) -> None:
        f = Field("well", str, pattern=r"^[A-H][1-9]|1[0-2]$")
        assert f.pattern == r"^[A-H][1-9]|1[0-2]$"

    def test_field_with_enum(self) -> None:
        f = Field("status", str, enum=["active", "inactive"])
        assert f.enum == ["active", "inactive"]

    def test_field_with_default(self) -> None:
        f = Field("value", int, default=0)
        assert f.has_default
        assert f.default == 0

    def test_field_with_aliases(self) -> None:
        f = Field("temperature", float, aliases=("temp", "T"))
        assert f.aliases == ("temp", "T")


class TestFieldValidation:
    """Tests for Field construction-time validation."""

    def test_invalid_name(self) -> None:
        with pytest.raises(SchemaError, match="Invalid field name"):
            Field("123invalid", str)

    def test_invalid_dtype(self) -> None:
        with pytest.raises(SchemaError, match="Invalid dtype"):
            Field("name", list)  # type: ignore

    def test_unit_on_non_numeric(self) -> None:
        with pytest.raises(SchemaError, match="unit is only allowed for numeric"):
            Field("name", str, unit="degC")

    def test_pattern_on_non_string(self) -> None:
        with pytest.raises(SchemaError, match="pattern is only allowed for str"):
            Field("value", int, pattern=r"\d+")

    def test_bounds_on_non_numeric(self) -> None:
        with pytest.raises(SchemaError, match="bounds.*only allowed for numeric"):
            Field("name", str, ge=0)

    def test_ge_and_gt_both_set(self) -> None:
        with pytest.raises(SchemaError, match="cannot set both 'ge' and 'gt'"):
            Field("value", float, ge=0, gt=0)

    def test_le_and_lt_both_set(self) -> None:
        with pytest.raises(SchemaError, match="cannot set both 'le' and 'lt'"):
            Field("value", float, le=100, lt=100)

    def test_invalid_unit_string(self) -> None:
        with pytest.raises(SchemaError, match="Unknown unit"):
            Field("value", float, unit="invalid_unit_xyz")

    def test_invalid_regex_pattern(self) -> None:
        with pytest.raises(SchemaError, match="invalid regex pattern"):
            Field("value", str, pattern="[invalid")


class TestFieldSerialization:
    """Tests for Field serialization."""

    def test_to_dict_basic(self) -> None:
        f = Field("name", str)
        d = f.to_dict()
        assert d == {"name": "name", "dtype": "str"}

    def test_to_dict_with_all_attributes(self) -> None:
        f = Field(
            "temperature",
            float,
            unit="degC",
            nullable=True,
            description="Temperature in Celsius",
            ge=-273.15,
        )
        d = f.to_dict()
        assert d["name"] == "temperature"
        assert d["dtype"] == "float"
        assert "degC" in d["unit"] or "celsius" in d["unit"].lower()
        assert d["nullable"] is True
        assert d["description"] == "Temperature in Celsius"
        assert d["ge"] == -273.15

    def test_from_dict_basic(self) -> None:
        d = {"name": "name", "dtype": "str"}
        f = Field.from_dict(d)
        assert f.name == "name"
        assert f.dtype is str

    def test_from_dict_roundtrip(self) -> None:
        original = Field(
            "temperature",
            float,
            unit="degC",
            nullable=True,
            ge=-273.15,
        )
        d = original.to_dict()
        restored = Field.from_dict(d)
        assert restored.name == original.name
        assert restored.dtype == original.dtype
        assert restored.nullable == original.nullable
        assert restored.ge == original.ge


class TestFieldHashable:
    """Tests for Field hashability."""

    def test_field_is_hashable(self) -> None:
        f = Field("name", str)
        assert hash(f) is not None

    def test_equal_fields_have_same_hash(self) -> None:
        f1 = Field("name", str, nullable=True)
        f2 = Field("name", str, nullable=True)
        assert hash(f1) == hash(f2)

    def test_fields_can_be_in_set(self) -> None:
        f1 = Field("a", str)
        f2 = Field("b", int)
        s = {f1, f2}
        assert len(s) == 2
