"""
Tests for _resolve_class_ids — pure function that converts YOLO_CLASSES names
to COCO integer class IDs for YOLO batch inference filtering.

No ML dependencies required — this is a pure Python function.

Run from services/ingestion-worker/:
    python -m pytest tests/test_yolo_class_resolver.py -v
"""
import pytest

from app.detect import _resolve_class_ids


class TestResolveClassIds:
    # ── Happy path ────────────────────────────────────────────────────────────

    def test_all_12_default_classes_resolved(self):
        default = "person,bicycle,car,motorcycle,bus,truck,cat,dog,horse,sheep,cow,bird".split(",")
        ids = _resolve_class_ids(default)
        assert len(ids) == 12

    def test_person_maps_to_coco_id_0(self):
        assert _resolve_class_ids(["person"]) == [0]

    def test_car_maps_to_coco_id_2(self):
        assert _resolve_class_ids(["car"]) == [2]

    def test_bus_maps_to_coco_id_5(self):
        assert _resolve_class_ids(["bus"]) == [5]

    def test_truck_maps_to_coco_id_7(self):
        assert _resolve_class_ids(["truck"]) == [7]

    def test_bird_maps_to_coco_id_14(self):
        assert _resolve_class_ids(["bird"]) == [14]

    def test_cat_maps_to_coco_id_15(self):
        assert _resolve_class_ids(["cat"]) == [15]

    def test_dog_maps_to_coco_id_16(self):
        assert _resolve_class_ids(["dog"]) == [16]

    def test_traffic_light_maps_to_coco_id_9(self):
        """Multi-word class name that contains a space."""
        assert _resolve_class_ids(["traffic light"]) == [9]

    # ── Input normalisation ───────────────────────────────────────────────────

    def test_case_insensitive_uppercase(self):
        assert _resolve_class_ids(["PERSON"]) == [0]

    def test_case_insensitive_mixed(self):
        assert _resolve_class_ids(["Person", "CAR"]) == [0, 2]

    def test_leading_trailing_whitespace_stripped(self):
        assert _resolve_class_ids([" person "]) == [0]
        assert _resolve_class_ids(["  car  "]) == [2]

    # ── Empty / unknown input ─────────────────────────────────────────────────

    def test_empty_list_returns_empty(self):
        assert _resolve_class_ids([]) == []

    def test_unknown_class_is_skipped(self):
        ids = _resolve_class_ids(["person", "spaceship", "car"])
        assert ids == [0, 2]

    def test_all_unknown_classes_returns_empty(self):
        assert _resolve_class_ids(["foo", "bar", "baz"]) == []

    def test_single_unknown_class_returns_empty(self):
        assert _resolve_class_ids(["unicorn"]) == []

    # ── Ordering ──────────────────────────────────────────────────────────────

    def test_output_order_matches_input_order_not_coco_id(self):
        """IDs must be in input order, not sorted by COCO ID."""
        ids = _resolve_class_ids(["car", "person", "bus"])
        assert ids == [2, 0, 5]

    def test_single_class_result_is_single_element_list(self):
        ids = _resolve_class_ids(["dog"])
        assert ids == [16]

    # ── Idempotency ───────────────────────────────────────────────────────────

    def test_duplicate_class_names_produce_duplicate_ids(self):
        """If user accidentally lists a class twice, we return its ID twice."""
        ids = _resolve_class_ids(["person", "person"])
        assert ids == [0, 0]

    # ── Return type ───────────────────────────────────────────────────────────

    def test_returns_list_of_ints(self):
        ids = _resolve_class_ids(["person", "car"])
        assert isinstance(ids, list)
        assert all(isinstance(i, int) for i in ids)
