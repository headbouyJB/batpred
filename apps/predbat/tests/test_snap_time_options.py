# fmt: off
# pylint: disable=line-too-long
"""
Unit tests for snapping charge/export window times onto a select entity's options (#4947).

Solar Assistant's slot time selects only list 15 minute steps plus 23:59, while the plan works in
5 minute steps. A time that isn't an option is rejected by Home Assistant on every retry, so the
window is snapped outwards onto the options before it is compared with the inverter or written.
"""

from datetime import datetime

from inverter import Inverter
from utils import snap_time_to_options

# What Solar Assistant publishes for a Growatt work mode slot time
SA_OPTIONS = ["{:02d}:{:02d}".format(hour, minute) for hour in range(24) for minute in (0, 15, 30, 45)] + ["23:59"]


def test_snap_time_to_options():
    """The pure helper: which option each time lands on, and when it is left alone."""
    print("Test: snap_time_to_options")
    failed = 0
    cases = [
        # (description, time, options, snap_down, expected)
        ("start snaps earlier", "22:05:00", SA_OPTIONS, True, "22:00:00"),
        ("end snaps later", "22:05:00", SA_OPTIONS, False, "22:15:00"),
        ("an option is left alone going down", "22:30:00", SA_OPTIONS, True, "22:30:00"),
        ("an option is left alone going up", "22:30:00", SA_OPTIONS, False, "22:30:00"),
        ("end after the last step uses 23:59", "23:50:00", SA_OPTIONS, False, "23:59:00"),
        ("start after the last step uses it", "23:50:00", SA_OPTIONS, True, "23:45:00"),
        ("midnight is an option", "00:00:00", SA_OPTIONS, False, "00:00:00"),
        ("a short time string is understood", "22:05", SA_OPTIONS, True, "22:00:00"),
        ("options with seconds are understood", "22:05:00", ["22:00:00", "22:15:00"], False, "22:15:00"),
        ("end wraps to the first option when none is later", "23:50:00", ["00:00", "12:00", "23:45"], False, "00:00:00"),
        ("start wraps to the last option when none is earlier", "00:05:00", ["00:15", "12:00", "23:45"], True, "23:45:00"),
        ("no options leaves the time alone", "22:05:00", None, True, "22:05:00"),
        ("an empty option list leaves the time alone", "22:05:00", [], True, "22:05:00"),
        ("options that aren't times leave the time alone", "22:05:00", ["Load first", "Battery first"], True, "22:05:00"),
        ("a single time option is not a grid", "22:05:00", ["00:00", "Disabled"], True, "22:05:00"),
        ("non-time options are ignored among times", "22:05:00", ["Disabled", "22:00", "22:15"], True, "22:00:00"),
        ("an unreadable time is returned as given", "unknown", SA_OPTIONS, True, "unknown"),
        ("no time is returned as given", None, SA_OPTIONS, True, None),
    ]
    for description, time_string, options, snap_down, expected in cases:
        got = snap_time_to_options(time_string, options, snap_down)
        if got != expected:
            print("ERROR: snap_time_to_options: {}: expected {} got {}".format(description, expected, got))
            failed += 1
    return failed


class _SnapBase:
    """A minimal Predbat stand-in holding the window entities and their option lists."""

    def __init__(self, args, options):
        self.args = args
        self.options = options
        self.logs = []

    def log(self, message):
        """Keep the log lines so a test can check a snap was reported."""
        self.logs.append(message)

    def get_arg(self, arg, default=None, indirect=True, index=None):
        """Return the entity id configured for this inverter."""
        return self.args[arg][index]

    def get_state_wrapper(self, entity_id=None, default=None, attribute=None, refresh=False, required_unit=None, raw=False):
        """Return the entity's option list, the only thing the snap reads."""
        return self.options.get(entity_id) if attribute == "options" else default


def _stub_inverter(base):
    """A real (uninitialised) Inverter wired to the stand-in base."""
    stub = Inverter.__new__(Inverter)
    stub.base = base
    stub.log = base.log
    stub.id = 0
    return stub


def test_snap_window_to_options():
    """Inverter.snap_window_to_options(): outward snapping, and everything it must leave alone."""
    print("Test: snap_window_to_options")
    failed = 0
    args = {"charge_start_time": ["select.slot_start"], "charge_end_time": ["select.slot_end"]}
    options = {"select.slot_start": SA_OPTIONS, "select.slot_end": SA_OPTIONS}
    cases = [
        # (description, args, options, start, end, expected start, expected end)
        ("window snaps outwards", args, options, "23:35:00", "05:25:00", "23:30:00", "05:30:00"),
        ("window on the options is unchanged", args, options, "23:30:00", "05:30:00", "23:30:00", "05:30:00"),
        ("an empty window stays empty", args, options, "22:05:00", "22:05:00", "22:00:00", "22:00:00"),
        ("the disabled window is unchanged", args, options, "00:00:00", "00:00:00", "00:00:00", "00:00:00"),
        ("times not supplied are passed through", args, options, None, None, None, None),
        ("only the end supplied", args, options, None, "05:25:00", None, "05:30:00"),
        ("a select without options is unchanged", args, {}, "23:35:00", "05:25:00", "23:35:00", "05:25:00"),
        ("a time entity is unchanged", {"charge_start_time": ["time.slot_start"], "charge_end_time": ["time.slot_end"]}, {"time.slot_start": SA_OPTIONS, "time.slot_end": SA_OPTIONS}, "23:35:00", "05:25:00", "23:35:00", "05:25:00"),
        ("an input_select snaps too", {"charge_start_time": ["input_select.slot_start"], "charge_end_time": ["input_select.slot_end"]}, {"input_select.slot_start": SA_OPTIONS, "input_select.slot_end": SA_OPTIONS}, "23:35:00", "05:25:00", "23:30:00", "05:30:00"),
        ("an unconfigured window is unchanged", {}, options, "23:35:00", "05:25:00", "23:35:00", "05:25:00"),
        ("each end uses its own entity's options", args, {"select.slot_start": SA_OPTIONS}, "23:35:00", "05:25:00", "23:30:00", "05:25:00"),
    ]
    for description, case_args, case_options, start, end, expect_start, expect_end in cases:
        base = _SnapBase(case_args, case_options)
        got = _stub_inverter(base).snap_window_to_options("charge_start_time", "charge_end_time", start, end)
        if got != (expect_start, expect_end):
            print("ERROR: snap_window_to_options: {}: expected {} got {}".format(description, (expect_start, expect_end), got))
            failed += 1
        snapped = (start, end) != (expect_start, expect_end)
        if snapped != bool(base.logs):
            print("ERROR: snap_window_to_options: {}: a snap should be logged and nothing else, got {}".format(description, base.logs))
            failed += 1
    return failed


def _adjust_and_record(my_predbat, start_arg, end_arg, start_entity, end_entity, state_start, state_end, adjust):
    """
    Run a window adjust on a real Inverter whose window entities are selects with Solar Assistant's
    options, returning the times it wrote.

    The option writes are recorded rather than sent: what matters here is which value reaches
    write_and_poll_option(), and whether one is sent at all when the inverter already holds the
    snapped window. The switch, value and button writes around them are accepted without being sent.
    """
    inv = Inverter(my_predbat, 0, quiet=True)
    ha = my_predbat.ha_interface
    saved_items = dict(ha.dummy_items)
    saved_args = {arg: my_predbat.args.get(arg) for arg in (start_arg, end_arg)}
    writes = {}

    def record(name, entity_id, new_value, ignore_fail=False):
        """Stand in for the option write, keeping the last value sent per control."""
        writes[name] = new_value
        return True

    try:
        my_predbat.args[start_arg] = [start_entity]
        my_predbat.args[end_arg] = [end_entity]
        ha.dummy_items[start_entity] = {"state": state_start, "options": SA_OPTIONS}
        ha.dummy_items[end_entity] = {"state": state_end, "options": SA_OPTIONS}
        inv.rest_data = None
        inv.write_and_poll_option = record
        inv.sleep = lambda seconds: None
        for other_write in ("write_and_poll_switch", "write_and_poll_value", "press_and_poll_button"):
            setattr(inv, other_write, lambda *args, **kwargs: True)
        adjust(inv)
    finally:
        ha.dummy_items.clear()
        ha.dummy_items.update(saved_items)
        for arg, value in saved_args.items():
            if value is None:
                my_predbat.args.pop(arg, None)
            else:
                my_predbat.args[arg] = value
    return {name: value for name, value in writes.items() if name in (start_arg, end_arg)}


def test_adjust_charge_window_snaps(my_predbat):
    """adjust_charge_window() writes the snapped window, and nothing once the inverter holds it."""
    print("Test: adjust_charge_window snaps to select options")
    failed = 0
    start = datetime.strptime("23:35:00", "%H:%M:%S")
    end = datetime.strptime("05:25:00", "%H:%M:%S")

    def adjust(inv):
        """Program a charge window that is off the 15 minute grid at both ends."""
        inv.adjust_charge_window(start, end, my_predbat.minutes_now)

    writes = _adjust_and_record(my_predbat, "charge_start_time", "charge_end_time", "select.snap_charge_start", "select.snap_charge_end", "00:00", "00:00", adjust)
    expected = {"charge_start_time": "23:30:00", "charge_end_time": "05:30:00"}
    if writes != expected:
        print("ERROR: adjust_charge_window should write {} got {}".format(expected, writes))
        failed += 1

    # Next cycle: the inverter reads back the snapped window, so there is nothing to write
    writes = _adjust_and_record(my_predbat, "charge_start_time", "charge_end_time", "select.snap_charge_start", "select.snap_charge_end", "23:30", "05:30", adjust)
    if writes:
        print("ERROR: adjust_charge_window should not rewrite a window already snapped, wrote {}".format(writes))
        failed += 1
    return failed


def test_adjust_force_export_snaps(my_predbat):
    """adjust_force_export() writes the snapped window, and nothing once the inverter holds it."""
    print("Test: adjust_force_export snaps to select options")
    failed = 0
    start = datetime.strptime("18:05:00", "%H:%M:%S")
    end = datetime.strptime("18:50:00", "%H:%M:%S")

    def adjust(inv):
        """Program an export window that is off the 15 minute grid at both ends."""
        inv.adjust_force_export(True, start, end)

    writes = _adjust_and_record(my_predbat, "discharge_start_time", "discharge_end_time", "select.snap_export_start", "select.snap_export_end", "00:00", "00:00", adjust)
    expected = {"discharge_start_time": "18:00:00", "discharge_end_time": "19:00:00"}
    if writes != expected:
        print("ERROR: adjust_force_export should write {} got {}".format(expected, writes))
        failed += 1

    writes = _adjust_and_record(my_predbat, "discharge_start_time", "discharge_end_time", "select.snap_export_start", "select.snap_export_end", "18:00", "19:00", adjust)
    if writes:
        print("ERROR: adjust_force_export should not rewrite a window already snapped, wrote {}".format(writes))
        failed += 1
    return failed


def run_snap_time_options_tests(my_predbat):
    """Run every select option snapping test, returning a non-zero count on failure."""
    failed = 0
    failed += test_snap_time_to_options()
    failed += test_snap_window_to_options()
    failed += test_adjust_charge_window_snaps(my_predbat)
    failed += test_adjust_force_export_snaps(my_predbat)
    return failed
