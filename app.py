import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, date, timedelta
from collections import defaultdict
import calendar
import threading
import re
import webbrowser
import os
import textwrap
import math

import requests
import pycountry
import geonamescache

try:
    from PIL import Image, ImageDraw, ImageFont, ImageGrab
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


# ============================================================
# CONFIG
# ============================================================

API_BASE = "https://api.aladhan.com/v1"
DEFAULT_METHOD = 5
HADITH_URL = "https://sunnah.com/bukhari:1131"
GITHUB_URL = "https://github.com/abde1razek"

# Theme
BG = "#0A0D11"
PANEL = "#11161D"
CARD = "#171D25"
CARD_2 = "#1D2530"
BORDER = "#29323E"

TEXT = "#F4F6F8"
MUTED = "#98A2AF"

ACCENT = "#D9C58F"
ACCENT_DARK = "#8F783D"
SLEEP_COLOR = "#7BC4A4"
PRAYER_COLOR = "#D6B762"
AWAKE_COLOR = "#8391A2"
TRAVEL_COLOR = "#78A8D8"
WAIT_COLOR = "#E39B76"
CYCLE_COLOR = "#B99BEA"
CUSTOM_COLOR = "#80C7D7"

SUCCESS = "#8BD5AE"
ERROR = "#FF9A9A"

HADITH_TEXT = (
    'Allah\'s Messenger (ﷺ) told me, "The most beloved prayer to Allah is that '
    'of David and the most beloved fasts to Allah are those of David. He used '
    'to sleep for half of the night and then pray for one third of the night '
    'and again sleep for its sixth part and used to fast on alternate days."'
)


# ============================================================
# PRAYER CALCULATION METHODS
# ============================================================

METHODS = {
    5: {
        "name": "Egyptian General Authority of Survey",
        "short": "Egypt",
        "info": (
            "Commonly used in Egypt. Prayer times can still differ by a few "
            "minutes from a local mosque timetable."
        ),
    },
    3: {
        "name": "Muslim World League",
        "short": "MWL",
        "info": (
            "Widely used internationally, including by many communities in Europe."
        ),
    },
    4: {
        "name": "Umm Al-Qura University, Makkah",
        "short": "Umm Al-Qura",
        "info": (
            "Commonly used in Saudi Arabia and uses Umm Al-Qura conventions."
        ),
    },
    2: {
        "name": "Islamic Society of North America",
        "short": "ISNA",
        "info": (
            "Commonly used by many Muslim communities in North America."
        ),
    },
    1: {
        "name": "University of Islamic Sciences, Karachi",
        "short": "Karachi",
        "info": (
            "Commonly used in Pakistan and parts of South Asia."
        ),
    },
    8: {
        "name": "Gulf Region",
        "short": "Gulf",
        "info": (
            "Calculation parameters commonly used in parts of the Gulf region."
        ),
    },
}


# ============================================================
# TIME HELPERS
# ============================================================

def extract_time(value):
    match = re.search(r"(\d{1,2}):(\d{2})", value)

    if not match:
        raise ValueError(f"Cannot parse time: {value}")

    return int(match.group(1)), int(match.group(2))


def prayer_datetime(day, value):
    hour, minute = extract_time(value)
    return datetime(day.year, day.month, day.day, hour, minute)


def clock(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def short_clock(dt):
    return dt.strftime("%I:%M").lstrip("0")


def duration(td):
    minutes = max(round(td.total_seconds() / 60), 0)
    hours, mins = divmod(minutes, 60)

    if hours and mins:
        return f"{hours}h {mins}m"

    if hours:
        return f"{hours}h"

    return f"{mins}m"


def clip_segment(start, end, clip_start, clip_end):
    start = max(start, clip_start)
    end = min(end, clip_end)

    if end <= start:
        return None

    return start, end


def sum_sleep(segments):
    total = timedelta(0)

    for segment in segments:
        if segment["kind"] in ("sleep", "cycle"):
            total += segment["end"] - segment["start"]

    return total


# ============================================================
# SEARCHABLE COMBOBOX
# ============================================================

class SearchableCombobox(ttk.Combobox):
    """
    Editable combobox with live suggestions.

    The native ttk dropdown can steal focus on Windows while typing.
    This class uses its own borderless suggestion list, so the user can
    type continuously (for example: 'Egy...' or 'Cai...') without having
    to click the field again.
    """

    def __init__(self, master, values=None, **kwargs):
        self.all_values = sorted(values or [])
        self.variable = tk.StringVar()

        kwargs["textvariable"] = self.variable
        kwargs.setdefault("state", "normal")

        super().__init__(
            master,
            values=self.all_values,
            **kwargs,
        )

        self._suggestion_popup = None
        self._suggestion_list = None
        self._last_matches = []

        self.bind(
            "<KeyRelease>",
            self._filter,
        )

        self.bind(
            "<FocusOut>",
            self._schedule_hide,
        )

        self.bind(
            "<Escape>",
            lambda event: self._hide_suggestions(),
        )

        self.bind(
            "<Return>",
            self._accept_first,
        )

        self.bind(
            "<Down>",
            self._select_first_with_keyboard,
        )

    def set_values(self, values):
        self.all_values = sorted(
            list(
                dict.fromkeys(values)
            )
        )

        self["values"] = self.all_values
        self._hide_suggestions()

    def _matches_for(self, typed):
        if not typed:
            return []

        typed = typed.lower()

        begins = []
        contains = []

        for item in self.all_values:
            low = item.lower()

            if low.startswith(typed):
                begins.append(item)
            elif typed in low:
                contains.append(item)

        return begins + contains

    def _filter(self, event):
        if event.keysym in (
            "Up",
            "Down",
            "Left",
            "Right",
            "Return",
            "Escape",
            "Tab",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
        ):
            return

        typed = self.variable.get().strip()

        matches = self._matches_for(
            typed
        )

        self._last_matches = matches[:100]
        self["values"] = self._last_matches

        if typed and self._last_matches:
            self._show_suggestions(
                self._last_matches
            )
        else:
            self._hide_suggestions()

    def _show_suggestions(
        self,
        matches,
    ):
        if not self.winfo_exists():
            return

        if (
            self._suggestion_popup is None
            or not self._suggestion_popup.winfo_exists()
        ):
            popup = tk.Toplevel(
                self
            )

            popup.overrideredirect(
                True
            )

            try:
                popup.attributes(
                    "-topmost",
                    True,
                )
            except tk.TclError:
                pass

            frame = tk.Frame(
                popup,
                bg=BORDER,
                highlightthickness=0,
            )

            frame.pack(
                fill="both",
                expand=True,
            )

            listbox = tk.Listbox(
                frame,
                bg=CARD,
                fg=TEXT,
                selectbackground=ACCENT,
                selectforeground="#111111",
                activestyle="none",
                relief="flat",
                borderwidth=0,
                exportselection=False,
                font=("Segoe UI", 9),
            )

            listbox.pack(
                fill="both",
                expand=True,
                padx=1,
                pady=1,
            )

            listbox.bind(
                "<ButtonRelease-1>",
                self._accept_mouse,
            )

            listbox.bind(
                "<Return>",
                self._accept_listbox,
            )

            listbox.bind(
                "<Escape>",
                lambda event: self._hide_suggestions(),
            )

            self._suggestion_popup = popup
            self._suggestion_list = listbox

        listbox = self._suggestion_list

        listbox.delete(
            0,
            tk.END,
        )

        visible_matches = matches[:10]

        for item in visible_matches:
            listbox.insert(
                tk.END,
                item,
            )

        rows = max(
            1,
            len(visible_matches),
        )

        self.update_idletasks()

        x = self.winfo_rootx()
        y = (
            self.winfo_rooty()
            + self.winfo_height()
        )

        width = max(
            self.winfo_width(),
            230,
        )

        height = (
            rows * 23
            + 2
        )

        self._suggestion_popup.geometry(
            f"{width}x{height}+{x}+{y}"
        )

        self._suggestion_popup.deiconify()

        # Do not focus the popup. Keyboard focus stays in the entry.

    def _accept_value(
        self,
        value,
    ):
        if not value:
            return

        self.set(
            value
        )

        self.icursor(
            tk.END
        )

        self._hide_suggestions()
        self.focus_set()

        self.event_generate(
            "<<ComboboxSelected>>"
        )

    def _accept_mouse(
        self,
        event=None,
    ):
        if not self._suggestion_list:
            return

        selection = self._suggestion_list.curselection()

        if not selection:
            index = self._suggestion_list.nearest(
                event.y
            )

            if index >= 0:
                selection = (
                    index,
                )

        if selection:
            self._accept_value(
                self._suggestion_list.get(
                    selection[0]
                )
            )

    def _accept_listbox(
        self,
        event=None,
    ):
        if not self._suggestion_list:
            return

        selection = self._suggestion_list.curselection()

        if selection:
            self._accept_value(
                self._suggestion_list.get(
                    selection[0]
                )
            )

    def _accept_first(
        self,
        event=None,
    ):
        if self._last_matches:
            self._accept_value(
                self._last_matches[0]
            )

            return "break"

    def _select_first_with_keyboard(
        self,
        event=None,
    ):
        if (
            self._suggestion_list
            and self._suggestion_popup
            and self._suggestion_popup.winfo_viewable()
            and self._suggestion_list.size()
        ):
            self._suggestion_list.selection_clear(
                0,
                tk.END,
            )

            self._suggestion_list.selection_set(
                0
            )

            self._suggestion_list.activate(
                0
            )

            return "break"

    def _schedule_hide(
        self,
        event=None,
    ):
        self.after(
            160,
            self._hide_if_focus_elsewhere,
        )

    def _hide_if_focus_elsewhere(
        self,
    ):
        focus = self.focus_get()

        if (
            focus is self
            or focus is self._suggestion_list
        ):
            return

        self._hide_suggestions()

    def _hide_suggestions(
        self,
    ):
        if (
            self._suggestion_popup
            and self._suggestion_popup.winfo_exists()
        ):
            self._suggestion_popup.withdraw()


# ============================================================
# LOCATION DATABASE
# ============================================================

class LocationDatabase:
    def __init__(self):
        self.country_names = []
        self.country_name_to_code = {}
        self.cities_by_country = defaultdict(list)
        self.load()

    def load(self):
        countries = sorted(pycountry.countries, key=lambda c: c.name)

        for country in countries:
            self.country_names.append(country.name)
            self.country_name_to_code[country.name] = country.alpha_2

        gc = geonamescache.GeonamesCache()

        for city_data in gc.get_cities().values():
            code = city_data.get("countrycode")
            name = city_data.get("name")

            if code and name:
                self.cities_by_country[code].append(name)

        for code in self.cities_by_country:
            self.cities_by_country[code] = sorted(
                set(self.cities_by_country[code])
            )

    def get_cities(self, country_name):
        code = self.country_name_to_code.get(country_name)

        if not code:
            return []

        return self.cities_by_country.get(code, [])


# ============================================================
# PRAYER TIMES API
# ============================================================

def fetch_prayer_data(day, city, country, method):
    url = f"{API_BASE}/timingsByCity/{day.strftime('%d-%m-%Y')}"

    response = requests.get(
        url,
        params={
            "city": city,
            "country": country,
            "method": method,
        },
        timeout=20,
    )

    response.raise_for_status()
    payload = response.json()

    if payload.get("code") != 200:
        raise RuntimeError(payload.get("status", "Prayer Times API error"))

    return payload["data"]


def fetch_night_information(selected_date, city, country, method):
    today_data = fetch_prayer_data(
        selected_date,
        city,
        country,
        method,
    )

    tomorrow_date = selected_date + timedelta(days=1)

    tomorrow_data = fetch_prayer_data(
        tomorrow_date,
        city,
        country,
        method,
    )

    today = today_data["timings"]
    tomorrow = tomorrow_data["timings"]

    return {
        "today_data": today_data,
        "tomorrow_data": tomorrow_data,
        "maghrib": prayer_datetime(selected_date, today["Maghrib"]),
        "isha": prayer_datetime(selected_date, today["Isha"]),
        "fajr_next": prayer_datetime(tomorrow_date, tomorrow["Fajr"]),
    }


# ============================================================
# NIGHT CORE
# ============================================================

def calculate_night_core(maghrib, isha, fajr):
    night = fajr - maghrib

    if night <= timedelta(0):
        raise ValueError("Next-day Fajr must be after Maghrib.")

    half = night / 2
    third = night / 3
    sixth = night / 6

    return {
        "maghrib": maghrib,
        "isha": isha,
        "fajr": fajr,
        "night": night,
        "half": half,
        "third": third,
        "sixth": sixth,
        "wake": maghrib + half,
        "last_third": maghrib + night * (2 / 3),
        "final_sixth": maghrib + night * (5 / 6),
        "two_thirds": night * (2 / 3),
    }


# ============================================================
# PRAYER ROUTINE
# ============================================================

def build_prayer_routine(
    prayer_name,
    prayer_time,
    place,
    prayer_minutes,
    travel_minutes,
    iqama_wait_minutes,
):
    """
    Prayer structure used everywhere in the application.

    PRAYER NODES
    ------------
    Maghrib / Isha / Fajr nodes are ADHAN times.

    HOME
    ----
    There is no iqama-wait calculation and no mosque travel:
        adhan -> prayer -> prayer end

    MOSQUE
    ------
    The adhan -> iqama interval is one shared waiting window.

    Outbound travel happens INSIDE that waiting window, not in addition to it:
        adhan -> travel to mosque -> remaining wait -> iqama -> prayer

    Example:
        adhan       19:00
        iqama       19:15
        travel      10 min

        19:00-19:10  travel to mosque
        19:10-19:15  remaining wait
        19:15        prayer starts

    If travel takes longer than the configured iqama delay, arrival is after
    the configured iqama time and the planner records how late the arrival is.

    RETURN TRAVEL
    -------------
    Travel HOME is AFTER the prayer. It therefore consumes real night time and
    is counted as post-prayer/post-Isha awake time by the sleep models.
    """
    prayer_delta = timedelta(
        minutes=prayer_minutes
    )

    if place == "Home":
        prayer_start = prayer_time
        prayer_end = (
            prayer_start
            + prayer_delta
        )

        return {
            "name": prayer_name,
            "place": place,
            "start": prayer_time,
            "adhan": prayer_time,
            "departure": None,
            "arrival": None,
            "iqama_time": None,
            "prayer_start": prayer_start,
            "prayer_end": prayer_end,
            "end": prayer_end,
            "late_by": timedelta(0),
            "segments": [
                {
                    "name": f"{prayer_name} prayer",
                    "start": prayer_start,
                    "end": prayer_end,
                    "kind": "prayer",
                }
            ],
            "prayer_minutes": prayer_minutes,
            "travel_minutes": 0,
            "iqama_wait_minutes": 0,
        }

    travel_delta = timedelta(
        minutes=travel_minutes
    )

    iqama_delta = timedelta(
        minutes=iqama_wait_minutes
    )

    iqama_time = (
        prayer_time
        + iqama_delta
    )

    # Travel immediately after the adhan. It consumes part of the same
    # adhan->iqama waiting window.
    departure = prayer_time
    arrival = (
        departure
        + travel_delta
    )

    prayer_start = max(
        arrival,
        iqama_time,
    )

    late_by = max(
        arrival
        - iqama_time,
        timedelta(0),
    )

    prayer_end = (
        prayer_start
        + prayer_delta
    )

    return_home = (
        prayer_end
        + travel_delta
    )

    segments = []

    if travel_minutes:
        segments.append(
            {
                "name": f"Travel to {prayer_name}",
                "start": departure,
                "end": arrival,
                "kind": "travel",
            }
        )

    if arrival < iqama_time:
        segments.append(
            {
                "name": "Wait for iqama",
                "start": arrival,
                "end": iqama_time,
                "kind": "wait",
            }
        )

    segments.append(
        {
            "name": f"{prayer_name} prayer",
            "start": prayer_start,
            "end": prayer_end,
            "kind": "prayer",
        }
    )

    if travel_minutes:
        segments.append(
            {
                "name": "Travel home",
                "start": prayer_end,
                "end": return_home,
                "kind": "travel",
            }
        )

    return {
        "name": prayer_name,
        "place": place,
        "start": prayer_time,
        "adhan": prayer_time,
        "departure": departure,
        "arrival": arrival,
        "iqama_time": iqama_time,
        "prayer_start": prayer_start,
        "prayer_end": prayer_end,
        "end": return_home,
        "late_by": late_by,
        "segments": segments,
        "prayer_minutes": prayer_minutes,
        "travel_minutes": travel_minutes,
        "iqama_wait_minutes": iqama_wait_minutes,
    }



def overlap_td(
    start_a,
    end_a,
    start_b,
    end_b,
):
    start = max(
        start_a,
        start_b,
    )

    end = min(
        end_a,
        end_b,
    )

    if end <= start:
        return timedelta(0)

    return end - start


def post_isha_awake_time(
    model,
    core,
):
    """
    'Awake' in the UI means non-Qiyam awake time AFTER the Isha adhan.

    It includes:
      - ordinary awake/preparation time
      - outbound/return travel
      - waiting for iqama

    It deliberately does NOT include Qiyam/prayer segments.
    """
    total = timedelta(0)

    for segment in model.get(
        "segments",
        [],
    ):
        if segment.get(
            "kind"
        ) not in {
            "awake",
            "travel",
            "wait",
        }:
            continue

        total += overlap_td(
            segment["start"],
            segment["end"],
            core["isha"],
            core["fajr"],
        )

    return total




def model_night_start(
    model,
    core,
):
    return model.get(
        "night_start",
        core["maghrib"],
    )


def model_night_end(
    model,
    core,
):
    return model.get(
        "night_end",
        core["fajr"],
    )


def model_night_length(
    model,
    core,
):
    return model.get(
        "night_length",
        model_night_end(model, core)
        - model_night_start(model, core),
    )


def model_half_duration(
    model,
    core,
):
    return model.get(
        "night_half",
        model_night_length(model, core) / 2,
    )


def model_third_duration(
    model,
    core,
):
    return model.get(
        "night_third",
        model_night_length(model, core) / 3,
    )


def model_sixth_duration(
    model,
    core,
):
    return model.get(
        "night_sixth",
        model_night_length(model, core) / 6,
    )


def sleep_segments_between(start, end, busy_windows):
    if end <= start:
        return []

    clipped = []

    for busy_start, busy_end in busy_windows:
        overlap = clip_segment(
            busy_start,
            busy_end,
            start,
            end,
        )

        if overlap:
            clipped.append(overlap)

    clipped.sort(key=lambda item: item[0])

    merged = []

    for busy_start, busy_end in clipped:
        if not merged or busy_start > merged[-1][1]:
            merged.append([busy_start, busy_end])
        else:
            merged[-1][1] = max(merged[-1][1], busy_end)

    result = []
    cursor = start

    for busy_start, busy_end in merged:
        if busy_start > cursor:
            result.append(
                {
                    "name": "Sleep",
                    "start": cursor,
                    "end": busy_start,
                    "kind": "sleep",
                }
            )

        cursor = max(cursor, busy_end)

    if cursor < end:
        result.append(
            {
                "name": "Sleep",
                "start": cursor,
                "end": end,
                "kind": "sleep",
            }
        )

    return result


# ============================================================
# MODELS
# ============================================================

def build_models(
    core,
    maghrib_routine,
    isha_routine,
    sleep_latency_minutes=10,
    sleep_cycle_minutes=90,
):
    M = core["maghrib"]
    I = core["isha"]
    F = core["fajr"]

    HALF = core["half"]
    THIRD = core["third"]
    SIXTH = core["sixth"]

    WAKE = core["wake"]
    FINAL_SIXTH = core["final_sixth"]

    sleep_latency = timedelta(minutes=sleep_latency_minutes)
    cycle = timedelta(minutes=sleep_cycle_minutes)

    ready_after_isha = isha_routine["end"]
    practical_sleep_start = min(
        ready_after_isha + sleep_latency,
        F,
    )

    models = []

    # --------------------------------------------------------
    # MODEL 1 — Literal fractions
    # --------------------------------------------------------

    models.append(
        {
            "name": "1. Exact Hadith Fractions",
            "description": (
                "The complete Maghrib → Fajr night is divided directly into "
                "1/2 sleep, 1/3 prayer and 1/6 sleep."
            ),
            "segments": [
                {
                    "name": "Sleep",
                    "start": M,
                    "end": WAKE,
                    "kind": "sleep",
                },
                {
                    "name": "Prayer / Qiyam",
                    "start": WAKE,
                    "end": FINAL_SIXTH,
                    "kind": "prayer",
                },
                {
                    "name": "Sleep",
                    "start": FINAL_SIXTH,
                    "end": F,
                    "kind": "sleep",
                },
            ],
            "total_sleep": HALF + SIXTH,
            "qiyam": THIRD,
            "wake": WAKE,
            "sleep_again": FINAL_SIXTH,
            "note": (
                "Pure mathematical fraction model. It does not subtract Maghrib, "
                "Isha or travel time."
            ),
        }
    )

    # --------------------------------------------------------
    # MODEL 2 — Sleep after Isha
    # --------------------------------------------------------

    first_sleep_start = min(
        max(
            practical_sleep_start,
            I,
        ),
        WAKE,
    )

    first_sleep = max(
        WAKE
        - first_sleep_start,
        timedelta(0),
    )

    segments = []

    # Isha itself stays a prayer/routine node. We do not paint Maghrib->Isha
    # as generic "awake"; in this app the gray Awake metric means post-Isha
    # non-Qiyam time.
    segments.extend(
        isha_routine["segments"]
    )

    # Return travel is already represented by the routine as "travel".
    # The extra fall-asleep buffer after reaching home is ordinary awake time.
    if (
        isha_routine["end"]
        < practical_sleep_start
    ):
        segments.append(
            {
                "name": "Prepare / fall asleep",
                "start": isha_routine["end"],
                "end": practical_sleep_start,
                "kind": "awake",
            }
        )

    if (
        first_sleep_start
        < WAKE
    ):
        segments.append(
            {
                "name": "Sleep",
                "start": first_sleep_start,
                "end": WAKE,
                "kind": "sleep",
            }
        )

    practical_qiyam_start = max(
        WAKE,
        practical_sleep_start,
    )

    if (
        practical_qiyam_start
        < FINAL_SIXTH
    ):
        segments.append(
            {
                "name": "Prayer / Qiyam",
                "start": practical_qiyam_start,
                "end": FINAL_SIXTH,
                "kind": "prayer",
            }
        )

    segments.append(
        {
            "name": "Final sleep",
            "start": FINAL_SIXTH,
            "end": F,
            "kind": "sleep",
        }
    )

    model2_qiyam = max(
        FINAL_SIXTH
        - practical_qiyam_start,
        timedelta(0),
    )

    models.append(
        {
            "name": "2. Sleep After Isha",
            "description": (
                "The hadith boundaries still use the full Maghrib→Fajr night. "
                "Isha prayer is shown separately; mosque return travel and the "
                "fall-asleep buffer count as post-Isha awake time before sleep."
            ),
            "segments": segments,
            "total_sleep": (
                first_sleep
                + SIXTH
            ),
            "qiyam": model2_qiyam,
            "wake": practical_qiyam_start,
            "sleep_again": FINAL_SIXTH,
            "note": (
                f"Isha prayer ends {clock(isha_routine['prayer_end'])}. "
                f"Ready after the routine {clock(ready_after_isha)}. "
                f"Estimated asleep {clock(practical_sleep_start)}."
            ),
        }
    )

    # --------------------------------------------------------
    # MODEL 3 — Remaining available time fractions
    # --------------------------------------------------------

    remaining_start = practical_sleep_start

    if remaining_start >= F:
        remaining_start = F - timedelta(minutes=1)

    remaining_night = F - remaining_start
    p_half = remaining_night / 2
    p_third = remaining_night / 3
    p_sixth = remaining_night / 6

    p_wake = remaining_start + p_half
    p_final_sixth = F - p_sixth

    models.append(
        {
            "name": "3. Post-Isha Fraction Plan",
            "description": (
                "Wait until the Isha routine is finished and you are estimated "
                "asleep, then divide the remaining time to Fajr into "
                "1/2 sleep, 1/3 prayer and 1/6 sleep."
            ),
            "segments": [
                {
                    "name": "Awake / prayer routine",
                    "start": M,
                    "end": remaining_start,
                    "kind": "awake",
                },
                {
                    "name": "Sleep",
                    "start": remaining_start,
                    "end": p_wake,
                    "kind": "sleep",
                },
                {
                    "name": "Prayer / Qiyam",
                    "start": p_wake,
                    "end": p_final_sixth,
                    "kind": "prayer",
                },
                {
                    "name": "Sleep",
                    "start": p_final_sixth,
                    "end": F,
                    "kind": "sleep",
                },
            ],
            "total_sleep": p_half + p_sixth,
            "qiyam": p_third,
            "wake": p_wake,
            "sleep_again": p_final_sixth,
            "note": (
                "This applies the fractions to the practical remaining sleep "
                "window rather than the complete Maghrib → Fajr night."
            ),
        }
    )

    # --------------------------------------------------------
    # MODEL 4 — Prayer/travel compensated model
    # --------------------------------------------------------

    busy_windows = [
        (maghrib_routine["start"], maghrib_routine["end"]),
        (isha_routine["start"], isha_routine["end"]),
    ]

    first_half_sleep_segments = sleep_segments_between(
        M,
        WAKE,
        busy_windows,
    )

    first_half_actual_sleep = sum_sleep(first_half_sleep_segments)
    lost_first_half_sleep = max(
        HALF - first_half_actual_sleep,
        timedelta(0),
    )

    desired_second_sleep = SIXTH + lost_first_half_sleep
    qiyam_start = max(WAKE, isha_routine["end"])
    desired_second_sleep_start = F - desired_second_sleep

    compensated_sleep_start = max(
        desired_second_sleep_start,
        qiyam_start,
    )

    actual_second_sleep = max(
        F - compensated_sleep_start,
        timedelta(0),
    )

    compensated_qiyam = max(
        compensated_sleep_start - qiyam_start,
        timedelta(0),
    )

    segments = list(first_half_sleep_segments)

    for routine in (maghrib_routine, isha_routine):
        segments.extend(routine["segments"])

    if qiyam_start < compensated_sleep_start:
        segments.append(
            {
                "name": "Prayer / Qiyam",
                "start": qiyam_start,
                "end": compensated_sleep_start,
                "kind": "prayer",
            }
        )

    if compensated_sleep_start < F:
        segments.append(
            {
                "name": "Second sleep",
                "start": compensated_sleep_start,
                "end": F,
                "kind": "sleep",
            }
        )

    segments.sort(key=lambda segment: segment["start"])

    recovered = max(
        actual_second_sleep - SIXTH,
        timedelta(0),
    )

    unrecovered = max(
        lost_first_half_sleep - recovered,
        timedelta(0),
    )

    models.append(
        {
            "name": "4. Prayer-Routine Recovery",
            "description": (
                "Treat Maghrib/Isha prayer and mosque travel as real awake time. "
                "Sleep missed from the theoretical first half is added to the "
                "last sleep block when there is enough room."
            ),
            "segments": segments,
            "total_sleep": first_half_actual_sleep + actual_second_sleep,
            "qiyam": compensated_qiyam,
            "wake": qiyam_start,
            "sleep_again": compensated_sleep_start,
            "note": (
                f"First-half sleep lost to prayer/travel: "
                f"{duration(lost_first_half_sleep)}. Recovered later: "
                f"{duration(recovered)}."
                + (
                    f" Unrecovered: {duration(unrecovered)}."
                    if unrecovered > timedelta(0)
                    else ""
                )
            ),
        }
    )

    # --------------------------------------------------------
    # MODEL 5 — Maghrib-to-Isha Qiyam credit model
    # --------------------------------------------------------
    #
    # User-requested idea:
    #   - Maghrib prayer counts toward the one-third prayer/Qiyam target.
    #   - The elapsed Maghrib -> Isha routine period is treated as a
    #     pre-Isha Qiyam/awake contribution, including configured travel.
    #   - Isha prayer also belongs to that pre-sleep period.
    #   - After Isha, sleep.
    #   - Only wake later if the pre-Isha contribution is shorter than
    #     the target one-third of the whole night.
    #   - If later waking is needed, complete the remaining amount before
    #     the final-sixth sleep block.
    #
    # This is presented as a planning interpretation, not a fiqh ruling.

    # Credit stops when the Isha prayer itself ends.
    # Return travel home is post-prayer awake time, not Qiyam credit.
    pre_isha_credit_end = min(
        isha_routine["prayer_end"],
        F,
    )

    pre_isha_credit = max(
        pre_isha_credit_end - M,
        timedelta(0),
    )

    credited_before_sleep = min(
        pre_isha_credit,
        THIRD,
    )

    qiyam_remaining = max(
        THIRD - credited_before_sleep,
        timedelta(0),
    )

    sleep_after_isha = min(
        practical_sleep_start,
        F,
    )

    # Reserve the final sixth for sleep when a later wake is needed.
    later_qiyam_end = FINAL_SIXTH

    if qiyam_remaining > timedelta(0):
        requested_later_wake = later_qiyam_end - qiyam_remaining

        # Do not "wake" before the user has actually gone to sleep.
        later_wake = max(
            requested_later_wake,
            sleep_after_isha,
        )

        actual_later_qiyam = max(
            later_qiyam_end - later_wake,
            timedelta(0),
        )

        qiyam_shortfall = max(
            qiyam_remaining - actual_later_qiyam,
            timedelta(0),
        )

        sleep_again = later_qiyam_end
    else:
        later_wake = F
        actual_later_qiyam = timedelta(0)
        qiyam_shortfall = timedelta(0)
        sleep_again = F

    segments = []

    # Maghrib routine with its real prayer/travel colors.
    segments.extend(maghrib_routine["segments"])

    # Between Maghrib routine and Isha adhan: Qiyam/awake period.
    between_start = max(
        maghrib_routine["end"],
        M,
    )

    if between_start < I:
        segments.append(
            {
                "name": "Qiyam until Isha",
                "start": between_start,
                "end": I,
                "kind": "prayer",
            }
        )

    # Isha routine with real prayer/travel colors.
    segments.extend(isha_routine["segments"])

    # Sleep preparation / latency.
    if isha_routine["end"] < sleep_after_isha:
        segments.append(
            {
                "name": "Prepare / fall asleep",
                "start": isha_routine["end"],
                "end": sleep_after_isha,
                "kind": "awake",
            }
        )

    if qiyam_remaining > timedelta(0):
        if sleep_after_isha < later_wake:
            segments.append(
                {
                    "name": "Sleep after Isha",
                    "start": sleep_after_isha,
                    "end": later_wake,
                    "kind": "sleep",
                }
            )

        if later_wake < later_qiyam_end:
            segments.append(
                {
                    "name": "Remaining Qiyam",
                    "start": later_wake,
                    "end": later_qiyam_end,
                    "kind": "prayer",
                }
            )

        if later_qiyam_end < F:
            segments.append(
                {
                    "name": "Final sleep",
                    "start": later_qiyam_end,
                    "end": F,
                    "kind": "sleep",
                }
            )

        total_sleep = max(
            later_wake - sleep_after_isha,
            timedelta(0),
        ) + max(
            F - later_qiyam_end,
            timedelta(0),
        )

        displayed_wake = later_wake
    else:
        if sleep_after_isha < F:
            segments.append(
                {
                    "name": "Sleep after Isha",
                    "start": sleep_after_isha,
                    "end": F,
                    "kind": "sleep",
                }
            )

        total_sleep = max(
            F - sleep_after_isha,
            timedelta(0),
        )

        displayed_wake = F

    models.append(
        {
            "name": "5. Maghrib-to-Isha Qiyam Credit",
            "description": (
                "Count the elapsed Maghrib-to-Isha routine period toward the "
                "one-third Qiyam target: Maghrib prayer, the period until Isha, "
                "the period until Isha and Isha prayer are part of the "
                "pre-sleep contribution. Return travel after Isha prayer is "
                "post-Isha awake time. Sleep after the routine, and only wake later "
                "if that contribution is shorter than one third of the night."
            ),
            "segments": segments,
            "total_sleep": total_sleep,
            "qiyam": credited_before_sleep + actual_later_qiyam,
            "wake": displayed_wake,
            "sleep_again": sleep_again,
            "note": (
                f"Target 1/3 = {duration(THIRD)}. "
                f"Maghrib → end of Isha routine = {duration(pre_isha_credit)}. "
                f"Remaining later Qiyam = {duration(qiyam_remaining)}."
                + (
                    f" Timing leaves a shortfall of {duration(qiyam_shortfall)}."
                    if qiyam_shortfall > timedelta(0)
                    else ""
                )
                + (
                    " No later wake is needed in this planning model."
                    if qiyam_remaining == timedelta(0)
                    else ""
                )
            ),
        }
    )

    # --------------------------------------------------------
    # MODEL 6 — Sleep-cycle planning
    # --------------------------------------------------------

    cycle_start = practical_sleep_start
    final_cycle_start = F - cycle

    cycle_candidates = []

    if cycle_start < final_cycle_start:
        max_cycles = int(
            (final_cycle_start - cycle_start) / cycle
        )

        for count in range(1, max_cycles + 1):
            cycle_end = cycle_start + cycle * count

            if cycle_end < final_cycle_start:
                cycle_candidates.append(
                    (count, cycle_end)
                )

    if cycle_candidates:
        first_cycle_count, cycle_wake = min(
            cycle_candidates,
            key=lambda item: abs(
                (item[1] - WAKE).total_seconds()
            ),
        )
    else:
        first_cycle_count = 0
        cycle_wake = cycle_start

    final_cycle_count = (
        1
        if final_cycle_start >= cycle_wake
        else 0
    )

    segments = []

    if cycle_start > M:
        segments.append(
            {
                "name": "Awake / prayer routine",
                "start": M,
                "end": cycle_start,
                "kind": "awake",
            }
        )

    if first_cycle_count and cycle_start < cycle_wake:
        segments.append(
            {
                "name": (
                    f"Sleep ({first_cycle_count} cycle"
                    f"{'s' if first_cycle_count != 1 else ''})"
                ),
                "start": cycle_start,
                "end": cycle_wake,
                "kind": "cycle",
            }
        )

    if (
        final_cycle_count
        and cycle_wake < final_cycle_start
    ):
        segments.append(
            {
                "name": "Prayer / Qiyam",
                "start": cycle_wake,
                "end": final_cycle_start,
                "kind": "prayer",
            }
        )

    if final_cycle_count:
        segments.append(
            {
                "name": "Final sleep cycle",
                "start": final_cycle_start,
                "end": F,
                "kind": "cycle",
            }
        )

    cycle_total_sleep = (
        cycle * first_cycle_count
        + (
            cycle
            if final_cycle_count
            else timedelta(0)
        )
    )

    cycle_qiyam = (
        max(
            final_cycle_start - cycle_wake,
            timedelta(0),
        )
        if final_cycle_count
        else timedelta(0)
    )

    models.append(
        {
            "name": "6. Sleep Cycle Plan",
            "description": (
                f"Uses an adjustable {sleep_cycle_minutes}-minute planning "
                f"cycle. Complete cycles are placed around the Qiyam period."
            ),
            "segments": segments,
            "total_sleep": cycle_total_sleep,
            "qiyam": cycle_qiyam,
            "wake": cycle_wake,
            "sleep_again": (
                final_cycle_start
                if final_cycle_count
                else F
            ),
            "note": (
                f"Approximate plan: {first_cycle_count} first cycle(s) + "
                f"{final_cycle_count} final cycle. Real sleep cycles vary; "
                f"the selected cycle length is only a planning aid."
            ),
        }
    )

    # --------------------------------------------------------
    # MODEL 7 — Night begins after Isha prayer ends
    # --------------------------------------------------------
    #
    # This is intentionally different from Model 3:
    #   Model 3 starts the fraction calculation after the whole practical
    #   routine + fall-asleep buffer.
    #
    #   Model 7 starts the FRACTION CLOCK immediately when the Isha PRAYER
    #   ends. If the person prayed in a mosque, the travel home happens
    #   inside this new post-Isha-prayer night and therefore consumes part
    #   of the first sleep-half as awake/travel time.
    #

    after_isha_start = min(
        isha_routine["prayer_end"],
        F,
    )

    after_isha_night = max(
        F
        - after_isha_start,
        timedelta(0),
    )

    ai_half = (
        after_isha_night
        / 2
    )

    ai_third = (
        after_isha_night
        / 3
    )

    ai_sixth = (
        after_isha_night
        / 6
    )

    ai_wake = (
        after_isha_start
        + ai_half
    )

    ai_final_sixth = (
        after_isha_start
        + after_isha_night
        * (5 / 6)
    )

    ai_sleep_ready = min(
        isha_routine["end"]
        + sleep_latency,
        F,
    )

    ai_segments = []

    # Return-home travel is after the prayer and belongs to the available
    # post-Isha-prayer time. Show it explicitly.
    if (
        isha_routine["place"]
        == "Mosque"
        and isha_routine["prayer_end"]
        < isha_routine["end"]
    ):
        ai_segments.append(
            {
                "name": "Travel home after Isha",
                "start": isha_routine["prayer_end"],
                "end": isha_routine["end"],
                "kind": "travel",
            }
        )

    if (
        isha_routine["end"]
        < ai_sleep_ready
    ):
        ai_segments.append(
            {
                "name": "Prepare / fall asleep",
                "start": isha_routine["end"],
                "end": ai_sleep_ready,
                "kind": "awake",
            }
        )

    ai_first_sleep_start = max(
        ai_sleep_ready,
        after_isha_start,
    )

    if (
        ai_first_sleep_start
        < ai_wake
    ):
        ai_segments.append(
            {
                "name": "Sleep",
                "start": ai_first_sleep_start,
                "end": ai_wake,
                "kind": "sleep",
            }
        )

    if (
        ai_wake
        < ai_final_sixth
    ):
        ai_segments.append(
            {
                "name": "Prayer / Qiyam",
                "start": ai_wake,
                "end": ai_final_sixth,
                "kind": "prayer",
            }
        )

    if (
        ai_final_sixth
        < F
    ):
        ai_segments.append(
            {
                "name": "Final sleep",
                "start": ai_final_sixth,
                "end": F,
                "kind": "sleep",
            }
        )

    ai_first_sleep = max(
        ai_wake
        - ai_first_sleep_start,
        timedelta(0),
    )

    models.append(
        {
            "name": "7. Night After Isha Prayer (Isha End → Fajr)",
            "description": (
                "The fraction clock starts when the Isha prayer itself ends, "
                "whether Isha was prayed at home or in a mosque. If it was at "
                "the mosque, return travel home happens after that starting "
                "point and is counted as post-Isha awake/travel time."
            ),
            "segments": ai_segments,
            "total_sleep": (
                ai_first_sleep
                + ai_sixth
            ),
            "qiyam": ai_third,
            "wake": ai_wake,
            "sleep_again": ai_final_sixth,
            "night_start": after_isha_start,
            "night_end": F,
            "night_length": after_isha_night,
            "night_half": ai_half,
            "night_third": ai_third,
            "night_sixth": ai_sixth,
            "note": (
                f"Post-Isha-prayer night = {duration(after_isha_night)}. "
                f"1/2 = {duration(ai_half)}, "
                f"1/3 = {duration(ai_third)}, "
                f"1/6 = {duration(ai_sixth)}."
            ),
        }
    )

    return models, {
        "ready_after_isha": ready_after_isha,
        "estimated_asleep": practical_sleep_start,
    }



# ============================================================
# CUSTOM MODEL
# ============================================================

CUSTOM_ACTIVITY_TO_KIND = {
    "Sleep": "sleep",
    "Qiyam / Prayer": "prayer",
    "Awake": "awake",
}

CUSTOM_RULES = (
    "For minutes",
    "For 1/2 of night",
    "For 1/3 of night",
    "For 1/6 of night",
    "Until Isha adhan",
    "Until Isha routine end",
    "Until half-night",
    "Until final sixth",
    "Until Fajr",
)


def non_sleep_time(core, total_sleep):
    return max(
        core["night"] - total_sleep,
        timedelta(0),
    )


def build_custom_model(
    core,
    isha_routine,
    name,
    spec,
):
    cursor = core["maghrib"]
    segments = []

    for item in spec:
        if cursor >= core["fajr"]:
            break

        activity = item["activity"]
        rule = item["rule"]
        value = item.get("value", 0)
        kind = CUSTOM_ACTIVITY_TO_KIND[activity]

        if rule == "For minutes":
            end = cursor + timedelta(
                minutes=float(value)
            )
        elif rule == "For 1/2 of night":
            end = cursor + core["half"]
        elif rule == "For 1/3 of night":
            end = cursor + core["third"]
        elif rule == "For 1/6 of night":
            end = cursor + core["sixth"]
        elif rule == "Until Isha adhan":
            end = core["isha"]
        elif rule == "Until Isha routine end":
            end = isha_routine["end"]
        elif rule == "Until half-night":
            end = core["wake"]
        elif rule == "Until final sixth":
            end = core["final_sixth"]
        elif rule == "Until Fajr":
            end = core["fajr"]
        else:
            raise ValueError(
                f"Unknown custom model rule: {rule}"
            )

        end = min(
            end,
            core["fajr"],
        )

        if end <= cursor:
            continue

        segments.append(
            {
                "name": activity,
                "start": cursor,
                "end": end,
                "kind": kind,
            }
        )

        cursor = end

    if cursor < core["fajr"]:
        segments.append(
            {
                "name": "Unplanned / Awake",
                "start": cursor,
                "end": core["fajr"],
                "kind": "awake",
            }
        )

    total_sleep = timedelta(0)
    qiyam = timedelta(0)

    for segment in segments:
        if segment["kind"] == "sleep":
            total_sleep += (
                segment["end"]
                - segment["start"]
            )
        elif segment["kind"] == "prayer":
            qiyam += (
                segment["end"]
                - segment["start"]
            )

    wake = core["fajr"]
    sleep_again = core["fajr"]

    for index, segment in enumerate(segments):
        if (
            segment["kind"] == "sleep"
            and index + 1 < len(segments)
            and segments[index + 1]["kind"] != "sleep"
        ):
            wake = segment["end"]
            break

    for segment in segments:
        if (
            segment["start"] >= wake
            and segment["kind"] == "sleep"
        ):
            sleep_again = segment["start"]
            break

    return {
        "name": f"Custom — {name}",
        "description": (
            "User-defined model. Segments run in order from Maghrib "
            "using the selected durations or prayer/night anchors."
        ),
        "segments": segments,
        "total_sleep": total_sleep,
        "qiyam": qiyam,
        "wake": wake,
        "sleep_again": sleep_again,
        "note": (
            "Custom scheduling model. It is shown as a planning tool, "
            "not as a religious ruling."
        ),
    }


# ============================================================
# SCROLLABLE CONTENT
# ============================================================

class ScrollArea(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)

        self.canvas = tk.Canvas(
            self,
            bg=BG,
            highlightthickness=0,
        )

        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )

        self.inner = tk.Frame(
            self.canvas,
            bg=BG,
        )

        self.window = self.canvas.create_window(
            (0, 0),
            window=self.inner,
            anchor="nw",
        )

        self.canvas.configure(
            yscrollcommand=self.scrollbar.set,
        )

        self.canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.scrollbar.pack(
            side="right",
            fill="y",
        )

        self.inner.bind(
            "<Configure>",
            self._update_scroll,
        )

        self.canvas.bind(
            "<Configure>",
            self._update_width,
        )

        self.canvas.bind_all(
            "<MouseWheel>",
            self._mousewheel,
        )

    def _update_scroll(self, event=None):
        self.canvas.configure(
            scrollregion=self.canvas.bbox("all")
        )

    def _update_width(self, event):
        self.canvas.itemconfigure(
            self.window,
            width=event.width,
        )

    def _mousewheel(self, event):
        self.canvas.yview_scroll(
            int(-event.delta / 120),
            "units",
        )


# ============================================================
# MAIN APP
# ============================================================

class DawudPlannerApp:
    def __init__(self, root):
        self.root = root

        root.title("Night of Dawud Planner")
        root.geometry("1420x960")
        root.minsize(1080, 760)
        root.configure(bg=BG)

        self.location_db = LocationDatabase()

        self.selected_date = date.today()
        self.week_start = (
            self.selected_date
            - timedelta(days=self.selected_date.weekday())
        )

        self.date_buttons = []
        self.result = None
        self.last_country = None
        self.fetch_generation = 0

        self.cards_per_row = tk.IntVar(
            value=3
        )

        self.custom_model_name = None
        self.custom_model_spec = None

        self.setup_style()
        self.build_header()
        self.build_search_panel()
        self.build_day_picker()
        self.build_fixed_prayer_strip()
        self.build_fixed_legend()

        # Main content is split into tabs. The All Models tab is deliberately
        # non-scrollable so every model is visible on one screen.
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(
            fill="both",
            expand=True,
            padx=24,
            pady=(0, 18),
        )

        self.dashboard_page = tk.Frame(self.notebook, bg=BG)
        self.models_page = tk.Frame(self.notebook, bg=BG)
        self.comparison_page = tk.Frame(self.notebook, bg=BG)

        self.notebook.add(self.dashboard_page, text="Dashboard")
        self.notebook.add(self.models_page, text="All Models")
        self.notebook.add(self.comparison_page, text="Comparison")

        self.scroll = ScrollArea(self.dashboard_page)
        self.scroll.pack(fill="both", expand=True)
        self.content = self.scroll.inner

        self.show_empty()
        self.show_empty_secondary_pages()

    # ========================================================
    # STYLE
    # ========================================================

    def setup_style(self):
        style = ttk.Style()

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "TNotebook",
            background=BG,
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=CARD,
            foreground=TEXT,
            padding=(16, 7),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", CARD_2)],
            foreground=[("selected", ACCENT)],
        )

        style.configure(
            "TCombobox",
            fieldbackground=CARD,
            background=CARD,
            foreground=TEXT,
            arrowcolor=TEXT,
            padding=6,
        )

        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", CARD)
            ],
            foreground=[
                ("readonly", TEXT)
            ],
            selectbackground=[
                ("readonly", CARD)
            ],
            selectforeground=[
                ("readonly", TEXT)
            ],
        )

    # ========================================================
    # HEADER
    # ========================================================

    def build_header(self):
        header = tk.Frame(
            self.root,
            bg=BG,
        )

        header.pack(
            fill="x",
            padx=24,
            pady=(10, 6),
        )

        # Subtle Islamic geometric texture, drawn locally (no image asset).
        pattern = tk.Canvas(
            header,
            height=26,
            bg=BG,
            highlightthickness=0,
        )
        pattern.pack(fill="x", side="bottom", pady=(5, 0))

        def draw_pattern(event=None):
            pattern.delete("all")
            width = max(pattern.winfo_width(), 700)
            pattern.create_line(0, 24, width, 24, fill=ACCENT, width=1)
            for cx in range(28, width, 64):
                pts = []
                for i in range(16):
                    angle = -math.pi / 2 + i * math.pi / 8
                    radius = 10 if i % 2 == 0 else 4
                    pts.extend([
                        cx + math.cos(angle) * radius,
                        12 + math.sin(angle) * radius,
                    ])
                pattern.create_polygon(pts, outline=BORDER, fill="")
                pattern.create_oval(cx - 2, 10, cx + 2, 14, outline=ACCENT)

        pattern.bind("<Configure>", draw_pattern)
        draw_pattern()

        left = tk.Frame(
            header,
            bg=BG,
        )

        left.pack(
            side="left",
            fill="x",
            expand=True,
        )

        tk.Label(
            left,
            text="Night of Dawud",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 24, "bold"),
        ).pack(anchor="w")

        tk.Label(
            left,
            text=(
                "Prayer routines • travel • night fractions • "
                "Qiyam • sleep-cycle planning"
            ),
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(
            anchor="w",
            pady=(2, 0),
        )

        right = tk.Frame(
            header,
            bg=BG,
        )

        right.pack(
            side="right",
        )

        tk.Label(
            right,
            text="Cards / row",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            side="left",
            padx=(0, 5),
        )

        cards_combo = ttk.Combobox(
            right,
            values=("2", "3", "4"),
            state="readonly",
            width=3,
        )

        cards_combo.set("3")

        cards_combo.pack(
            side="left",
        )

        def cards_changed(event=None):
            try:
                value = int(cards_combo.get())
            except ValueError:
                value = 3

            self.cards_per_row.set(value)

            if self.result:
                self.render_dashboard()

        cards_combo.bind(
            "<<ComboboxSelected>>",
            cards_changed,
        )

    # ========================================================
    # SETTINGS
    # ========================================================

    def build_search_panel(self):
        panel = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        panel.pack(
            fill="x",
            padx=24,
            pady=(0, 7),
        )

        for column in range(6):
            panel.grid_columnconfigure(
                column,
                weight=1 if column < 5 else 0,
            )

        tk.Label(
            panel,
            text="Location & planning settings",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
        ).grid(
            row=0,
            column=0,
            columnspan=6,
            sticky="w",
            padx=14,
            pady=(11, 7),
        )

        # Country
        wrap = self.field_wrapper(
            panel,
            "Country / territory",
            0,
            1,
        )

        self.country_combo = SearchableCombobox(
            wrap,
            values=self.location_db.country_names,
            width=24,
        )

        self.country_combo.pack(
            fill="x",
            pady=(3, 0),
        )

        self.country_combo.set("Egypt")

        self.country_combo.bind(
            "<<ComboboxSelected>>",
            self.country_changed,
        )

        self.country_combo.bind(
            "<FocusOut>",
            self.country_changed,
        )

        # City
        wrap = self.field_wrapper(
            panel,
            "City",
            1,
            1,
        )

        self.city_combo = SearchableCombobox(
            wrap,
            values=[],
            width=24,
        )

        self.city_combo.pack(
            fill="x",
            pady=(3, 0),
        )

        self.load_cities(
            "Egypt",
            preserve_city=False,
        )

        if "Cairo" in self.city_combo.all_values:
            self.city_combo.set("Cairo")

        # Calculation method
        wrap = self.field_wrapper(
            panel,
            "Prayer calculation method",
            2,
            1,
        )

        self.method_map = {}
        method_values = []

        for method_id, data in METHODS.items():
            label = (
                f"{data['short']} — "
                f"{data['name']}"
            )

            self.method_map[label] = method_id
            method_values.append(label)

        self.method_combo = ttk.Combobox(
            wrap,
            values=method_values,
            state="readonly",
            width=34,
        )

        self.method_combo.pack(
            fill="x",
            pady=(3, 0),
        )

        egypt_label = next(
            label
            for label, method_id in self.method_map.items()
            if method_id == DEFAULT_METHOD
        )

        self.method_combo.set(egypt_label)

        self.method_combo.bind(
            "<<ComboboxSelected>>",
            self.method_changed,
        )

        # Travel
        wrap = self.field_wrapper(
            panel,
            "Mosque travel (one way)",
            3,
            1,
        )

        travel_row = tk.Frame(
            wrap,
            bg=PANEL,
        )

        travel_row.pack(
            fill="x",
            pady=(3, 0),
        )

        self.travel_minutes = tk.Spinbox(
            travel_row,
            from_=0,
            to=90,
            width=5,
            bg=CARD,
            fg=TEXT,
            buttonbackground=CARD,
            insertbackground=TEXT,
            relief="flat",
        )

        self.travel_minutes.delete(
            0,
            tk.END,
        )

        self.travel_minutes.insert(
            0,
            "10",
        )

        self.travel_minutes.pack(
            side="left",
        )

        tk.Label(
            travel_row,
            text=" min",
            bg=PANEL,
            fg=MUTED,
        ).pack(
            side="left",
        )

        # Sleep settings
        wrap = self.field_wrapper(
            panel,
            "Sleep planning",
            4,
            1,
        )

        sleep_row = tk.Frame(
            wrap,
            bg=PANEL,
        )

        sleep_row.pack(
            fill="x",
            pady=(3, 0),
        )

        tk.Label(
            sleep_row,
            text="Fall asleep ",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            side="left",
        )

        self.sleep_latency = tk.Spinbox(
            sleep_row,
            from_=0,
            to=60,
            width=4,
            bg=CARD,
            fg=TEXT,
            buttonbackground=CARD,
            insertbackground=TEXT,
            relief="flat",
        )

        self.sleep_latency.delete(
            0,
            tk.END,
        )

        self.sleep_latency.insert(
            0,
            "10",
        )

        self.sleep_latency.pack(
            side="left",
        )

        tk.Label(
            sleep_row,
            text="m   Cycle ",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            side="left",
        )

        self.sleep_cycle = tk.Spinbox(
            sleep_row,
            from_=60,
            to=120,
            increment=5,
            width=4,
            bg=CARD,
            fg=TEXT,
            buttonbackground=CARD,
            insertbackground=TEXT,
            relief="flat",
        )

        self.sleep_cycle.delete(
            0,
            tk.END,
        )

        self.sleep_cycle.insert(
            0,
            "90",
        )

        self.sleep_cycle.pack(
            side="left",
        )

        tk.Label(
            sleep_row,
            text="m",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            side="left",
        )

        # Fetch/recalculate buttons
        actions = tk.Frame(
            panel,
            bg=PANEL,
        )

        actions.grid(
            row=1,
            column=5,
            rowspan=2,
            sticky="ne",
            padx=14,
            pady=(18, 4),
        )

        self.fetch_button = tk.Button(
            actions,
            text="Fetch prayer times",
            command=self.start_fetch,
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=7,
        )

        self.fetch_button.pack(
            fill="x",
        )

        self.recalc_button = tk.Button(
            actions,
            text="Recalculate plan",
            command=self.recalculate_plan,
            bg=CARD_2,
            fg=TEXT,
            activebackground=BORDER,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=14,
            pady=7,
            state="disabled",
        )

        self.recalc_button.pack(
            fill="x",
            pady=(5, 0),
        )

        tk.Button(
            actions,
            text="Custom Model Maker",
            command=self.open_custom_model_builder,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=14,
            pady=7,
        ).pack(
            fill="x",
            pady=(5, 0),
        )

        tk.Button(
            actions,
            text="Compare 5 locations",
            command=self.open_location_comparison,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=14,
            pady=7,
        ).pack(
            fill="x",
            pady=(5, 0),
        )

        # Prayer routine
        tk.Label(
            panel,
            text="Prayer routine",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 9, "bold"),
        ).grid(
            row=2,
            column=0,
            sticky="w",
            padx=14,
            pady=(5, 2),
        )

        (
            self.maghrib_place,
            self.maghrib_duration,
            self.maghrib_iqama,
        ) = self.build_prayer_controls(
            panel,
            "Maghrib",
            0,
            3,
        )

        (
            self.isha_place,
            self.isha_duration,
            self.isha_iqama,
        ) = self.build_prayer_controls(
            panel,
            "Isha",
            1,
            3,
        )

        self.method_info = tk.Label(
            panel,
            text="",
            bg=PANEL,
            fg=MUTED,
            wraplength=600,
            justify="left",
            font=("Segoe UI", 8),
        )

        self.method_info.grid(
            row=3,
            column=2,
            columnspan=3,
            sticky="w",
            padx=8,
            pady=(3, 7),
        )

        self.status = tk.Label(
            panel,
            text="Ready.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        )

        self.status.grid(
            row=4,
            column=0,
            columnspan=6,
            sticky="w",
            padx=14,
            pady=(0, 9),
        )

        self.method_changed()

    def field_wrapper(
        self,
        parent,
        label,
        column,
        row,
    ):
        wrapper = tk.Frame(
            parent,
            bg=PANEL,
        )

        wrapper.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=(14 if column == 0 else 6, 6),
            pady=(0, 7),
        )

        tk.Label(
            wrapper,
            text=label,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            anchor="w",
        )

        return wrapper

    def build_prayer_controls(
        self,
        parent,
        name,
        column,
        row,
    ):
        wrapper = tk.Frame(
            parent,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        wrapper.grid(
            row=row,
            column=column,
            sticky="w",
            padx=(14 if column == 0 else 6, 6),
            pady=(0, 7),
        )

        tk.Label(
            wrapper,
            text=name,
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 8, "bold"),
        ).pack(
            side="left",
            padx=(8, 5),
            pady=6,
        )

        place = ttk.Combobox(
            wrapper,
            values=("Home", "Mosque"),
            state="readonly",
            width=7,
        )

        place.set("Home")

        place.pack(
            side="left",
            padx=(0, 5),
            pady=3,
        )

        tk.Label(
            wrapper,
            text="Prayer",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            side="left",
        )

        minutes = tk.Spinbox(
            wrapper,
            from_=5,
            to=15,
            width=3,
            bg=CARD_2,
            fg=TEXT,
            buttonbackground=CARD_2,
            insertbackground=TEXT,
            relief="flat",
        )

        minutes.delete(
            0,
            tk.END,
        )

        minutes.insert(
            0,
            "10",
        )

        minutes.pack(
            side="left",
            padx=(4, 2),
            pady=3,
        )

        tk.Label(
            wrapper,
            text="m  Iqama +",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            side="left",
        )

        iqama = tk.Spinbox(
            wrapper,
            from_=0,
            to=60,
            width=3,
            bg=CARD_2,
            fg=TEXT,
            buttonbackground=CARD_2,
            insertbackground=TEXT,
            relief="flat",
        )

        iqama.delete(
            0,
            tk.END,
        )

        iqama.insert(
            0,
            "10" if name == "Maghrib" else "15",
        )

        iqama.pack(
            side="left",
            padx=(4, 2),
            pady=3,
        )

        tk.Label(
            wrapper,
            text="m",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            side="left",
            padx=(0, 7),
        )

        return place, minutes, iqama


    # ========================================================
    # LOCATION
    # ========================================================

    def country_changed(self, event=None):
        country = self.country_combo.get().strip()

        if country == self.last_country:
            return

        self.load_cities(
            country,
            preserve_city=False,
        )

    def load_cities(
        self,
        country,
        preserve_city=True,
    ):
        current_city = (
            self.city_combo.get().strip()
            if preserve_city
            else ""
        )

        cities = self.location_db.get_cities(
            country
        )

        self.city_combo.set_values(
            cities
        )

        self.last_country = country

        if (
            preserve_city
            and current_city in cities
        ):
            self.city_combo.set(
                current_city
            )
        else:
            self.city_combo.set("")

    # ========================================================
    # METHOD
    # ========================================================

    def method_changed(self, event=None):
        label = self.method_combo.get()
        method_id = self.method_map.get(
            label,
            DEFAULT_METHOD,
        )

        data = METHODS[method_id]

        self.method_info.config(
            text=(
                f"Method {method_id}: {data['info']} "
                f"Use the method that matches your local mosque "
                f"or official timetable."
            )
        )

    # ========================================================
    # DATE NAVIGATION
    # ========================================================

    def build_day_picker(self):
        container = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        container.pack(
            fill="x",
            padx=24,
            pady=(0, 7),
        )

        bar = tk.Frame(
            container,
            bg=PANEL,
        )

        bar.pack(
            fill="x",
            padx=9,
            pady=8,
        )

        tk.Button(
            bar,
            text="‹ Week",
            command=lambda: self.shift_week(-7),
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=9,
            pady=5,
        ).pack(
            side="left",
            padx=(0, 4),
        )

        days_holder = tk.Frame(
            bar,
            bg=PANEL,
        )

        days_holder.pack(
            side="left",
            fill="x",
            expand=True,
        )

        self.days_holder = days_holder

        tk.Button(
            bar,
            text="Week ›",
            command=lambda: self.shift_week(7),
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=9,
            pady=5,
        ).pack(
            side="left",
            padx=(4, 4),
        )

        tk.Button(
            bar,
            text="Today",
            command=self.go_today,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=9,
            pady=5,
        ).pack(
            side="left",
            padx=4,
        )

        tk.Button(
            bar,
            text="Calendar",
            command=self.open_month_calendar,
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=5,
            font=("Segoe UI", 8, "bold"),
        ).pack(
            side="left",
            padx=(4, 0),
        )

        self.rebuild_week_buttons()

    def rebuild_week_buttons(self):
        for child in self.days_holder.winfo_children():
            child.destroy()

        self.date_buttons = []

        for index in range(7):
            day = self.week_start + timedelta(days=index)

            title = (
                "Today"
                if day == date.today()
                else day.strftime("%a")
            )

            button = tk.Button(
                self.days_holder,
                text=(
                    f"{title}\n"
                    f"{day.strftime('%d %b')}"
                ),
                command=lambda d=day: self.select_date(
                    d,
                    auto_fetch=True,
                ),
                relief="flat",
                bd=0,
                font=("Segoe UI", 8, "bold"),
                padx=10,
                pady=5,
                cursor="hand2",
            )

            button.pack(
                side="left",
                fill="x",
                expand=True,
                padx=2,
            )

            self.date_buttons.append(
                (day, button)
            )

        self.update_day_buttons()

    def update_day_buttons(self):
        for day, button in self.date_buttons:
            if day == self.selected_date:
                button.config(
                    bg=ACCENT,
                    fg="#111111",
                    activebackground=ACCENT,
                )
            elif day == date.today():
                button.config(
                    bg=CARD_2,
                    fg=TEXT,
                    activebackground=BORDER,
                    activeforeground=TEXT,
                )
            else:
                button.config(
                    bg=CARD,
                    fg=TEXT,
                    activebackground=CARD_2,
                    activeforeground=TEXT,
                )

    def shift_week(self, days):
        self.week_start += timedelta(
            days=days
        )

        self.rebuild_week_buttons()

    def go_today(self):
        today = date.today()

        self.week_start = (
            today
            - timedelta(days=today.weekday())
        )

        self.rebuild_week_buttons()

        self.select_date(
            today,
            auto_fetch=True,
        )

    def select_date(
        self,
        selected,
        auto_fetch=True,
    ):
        self.selected_date = selected

        self.week_start = (
            selected
            - timedelta(days=selected.weekday())
        )

        self.rebuild_week_buttons()
        self.clear_fixed_prayer_times()

        self.status.config(
            text=(
                f"Selected "
                f"{selected.strftime('%A, %d %B %Y')}."
            ),
            fg=MUTED,
        )

        if auto_fetch:
            self.start_fetch(
                auto=True
            )

    def open_month_calendar(self):
        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            "Choose a date"
        )

        popup.geometry(
            "430x430"
        )

        popup.resizable(
            False,
            False,
        )

        popup.configure(
            bg=PANEL
        )

        popup.transient(
            self.root
        )

        popup.grab_set()

        state = {
            "year": self.selected_date.year,
            "month": self.selected_date.month,
        }

        header = tk.Frame(
            popup,
            bg=PANEL,
        )

        header.pack(
            fill="x",
            padx=12,
            pady=(12, 8),
        )

        title_label = tk.Label(
            header,
            text="",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 14, "bold"),
        )

        title_label.pack(
            side="left",
            expand=True,
        )

        grid_holder = tk.Frame(
            popup,
            bg=PANEL,
        )

        grid_holder.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=(0, 12),
        )

        def change_month(delta):
            year = state["year"]
            month = state["month"] + delta

            if month < 1:
                month = 12
                year -= 1

            elif month > 12:
                month = 1
                year += 1

            state["year"] = year
            state["month"] = month

            render_month()

        tk.Button(
            header,
            text="‹",
            command=lambda: change_month(-1),
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            width=3,
        ).pack(
            side="left",
        )

        tk.Button(
            header,
            text="›",
            command=lambda: change_month(1),
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            width=3,
        ).pack(
            side="right",
        )

        def choose_day(day_number):
            selected = date(
                state["year"],
                state["month"],
                day_number,
            )

            popup.destroy()

            self.select_date(
                selected,
                auto_fetch=True,
            )

        def render_month():
            for child in grid_holder.winfo_children():
                child.destroy()

            year = state["year"]
            month = state["month"]

            title_label.config(
                text=(
                    f"{calendar.month_name[month]} "
                    f"{year}"
                )
            )

            weekdays = (
                "Mon",
                "Tue",
                "Wed",
                "Thu",
                "Fri",
                "Sat",
                "Sun",
            )

            for col, name in enumerate(weekdays):
                grid_holder.grid_columnconfigure(
                    col,
                    weight=1,
                )

                tk.Label(
                    grid_holder,
                    text=name,
                    bg=PANEL,
                    fg=MUTED,
                    font=("Segoe UI", 8, "bold"),
                ).grid(
                    row=0,
                    column=col,
                    sticky="nsew",
                    padx=2,
                    pady=3,
                )

            month_weeks = calendar.monthcalendar(
                year,
                month,
            )

            for row_index, week in enumerate(
                month_weeks,
                start=1,
            ):
                grid_holder.grid_rowconfigure(
                    row_index,
                    weight=1,
                )

                for col, day_number in enumerate(week):
                    if day_number == 0:
                        tk.Label(
                            grid_holder,
                            text="",
                            bg=PANEL,
                        ).grid(
                            row=row_index,
                            column=col,
                            sticky="nsew",
                            padx=2,
                            pady=2,
                        )

                        continue

                    current = date(
                        year,
                        month,
                        day_number,
                    )

                    if current == self.selected_date:
                        bg_color = ACCENT
                        fg_color = "#111111"

                    elif current == date.today():
                        bg_color = CARD_2
                        fg_color = TEXT

                    else:
                        bg_color = CARD
                        fg_color = TEXT

                    tk.Button(
                        grid_holder,
                        text=str(day_number),
                        command=lambda d=day_number: choose_day(d),
                        bg=bg_color,
                        fg=fg_color,
                        activebackground=ACCENT,
                        activeforeground="#111111",
                        relief="flat",
                        cursor="hand2",
                        font=("Segoe UI", 9, "bold"),
                    ).grid(
                        row=row_index,
                        column=col,
                        sticky="nsew",
                        padx=2,
                        pady=2,
                        ipadx=4,
                        ipady=7,
                    )

        render_month()

    # ========================================================
    # FIXED PRAYER STRIP
    # ========================================================

    def build_fixed_prayer_strip(self):
        self.prayer_strip = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        self.prayer_strip.pack(
            fill="x",
            padx=24,
            pady=(0, 5),
        )

        top = tk.Frame(
            self.prayer_strip,
            bg=PANEL,
        )

        top.pack(
            fill="x",
            padx=10,
            pady=(6, 3),
        )

        tk.Label(
            top,
            text="Prayer times",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 9, "bold"),
        ).pack(
            side="left",
        )

        self.fixed_prayer_date = tk.Label(
            top,
            text=self.selected_date.strftime(
                "%A, %d %B"
            ),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        )

        self.fixed_prayer_date.pack(
            side="left",
            padx=(7, 0),
        )

        row = tk.Frame(
            self.prayer_strip,
            bg=PANEL,
        )

        row.pack(
            fill="x",
            padx=8,
            pady=(0, 7),
        )

        self.fixed_prayer_labels = {}

        names = (
            "Fajr",
            "Sunrise",
            "Dhuhr",
            "Asr",
            "Maghrib",
            "Isha",
            "Sleep-ready",
        )

        for index, name in enumerate(names):
            row.grid_columnconfigure(
                index,
                weight=1,
                uniform="prayer_times",
            )

            cell = tk.Frame(
                row,
                bg=CARD,
                highlightbackground=BORDER,
                highlightthickness=1,
            )

            cell.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=2,
            )

            tk.Label(
                cell,
                text=name,
                bg=CARD,
                fg=MUTED,
                font=("Segoe UI", 7),
            ).pack(
                pady=(5, 0),
            )

            value = tk.Label(
                cell,
                text="--",
                bg=CARD,
                fg=(
                    ACCENT
                    if name == "Sleep-ready"
                    else TEXT
                ),
                font=("Segoe UI", 9, "bold"),
            )

            value.pack(
                pady=(0, 5),
            )

            self.fixed_prayer_labels[
                name
            ] = value

    def clear_fixed_prayer_times(self):
        self.fixed_prayer_date.config(
            text=self.selected_date.strftime(
                "%A, %d %B"
            )
        )

        for label in self.fixed_prayer_labels.values():
            label.config(
                text="…"
            )

    def update_fixed_prayer_times(self):
        if not self.result:
            return

        r = self.result
        timings = r["api"]["today_data"]["timings"]

        self.fixed_prayer_date.config(
            text=r["date"].strftime(
                "%A, %d %B"
            )
        )

        for name in (
            "Fajr",
            "Sunrise",
            "Dhuhr",
            "Asr",
            "Maghrib",
            "Isha",
        ):
            dt = prayer_datetime(
                r["date"],
                timings[name],
            )

            self.fixed_prayer_labels[
                name
            ].config(
                text=clock(dt)
            )

        self.fixed_prayer_labels[
            "Sleep-ready"
        ].config(
            text=clock(
                r["practical"][
                    "ready_after_isha"
                ]
            )
        )

    # ========================================================
    # LEGEND
    # ========================================================

    def build_fixed_legend(self):
        legend = tk.Frame(
            self.root,
            bg=BG,
        )

        legend.pack(
            fill="x",
            padx=26,
            pady=(0, 5),
        )

        items = (
            ("Sleep", SLEEP_COLOR),
            ("Prayer / Qiyam", PRAYER_COLOR),
            ("Awake", AWAKE_COLOR),
            ("Travel", TRAVEL_COLOR),
            ("Wait for iqama", WAIT_COLOR),
            ("Sleep cycle", CYCLE_COLOR),
            ("Isha marker", ACCENT),
        )

        tk.Label(
            legend,
            text="Legend:",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 7, "bold"),
        ).pack(
            side="left",
            padx=(0, 6),
        )

        for label, color in items:
            dot = tk.Canvas(
                legend,
                width=11,
                height=11,
                bg=BG,
                highlightthickness=0,
            )

            dot.create_rectangle(
                2,
                2,
                9,
                9,
                fill=color,
                outline="",
            )

            dot.pack(
                side="left",
                padx=(0, 2),
            )

            tk.Label(
                legend,
                text=label,
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 7),
            ).pack(
                side="left",
                padx=(0, 9),
            )

    # ========================================================
    # SETTINGS VALUES
    # ========================================================

    def get_plan_settings(self):
        try:
            travel_minutes = int(
                self.travel_minutes.get()
            )

            maghrib_prayer_minutes = int(
                self.maghrib_duration.get()
            )

            isha_prayer_minutes = int(
                self.isha_duration.get()
            )

            maghrib_iqama_minutes = int(
                self.maghrib_iqama.get()
            )

            isha_iqama_minutes = int(
                self.isha_iqama.get()
            )

            sleep_latency_minutes = int(
                self.sleep_latency.get()
            )

            sleep_cycle_minutes = int(
                self.sleep_cycle.get()
            )

        except ValueError:
            raise ValueError(
                "Prayer, iqama, travel and sleep settings must be numbers."
            )

        if not 5 <= maghrib_prayer_minutes <= 15:
            raise ValueError(
                "Maghrib prayer duration must be 5–15 minutes."
            )

        if not 5 <= isha_prayer_minutes <= 15:
            raise ValueError(
                "Isha prayer duration must be 5–15 minutes."
            )

        if travel_minutes < 0:
            raise ValueError(
                "Travel time cannot be negative."
            )

        if maghrib_iqama_minutes < 0 or isha_iqama_minutes < 0:
            raise ValueError(
                "Iqama delay cannot be negative."
            )

        if sleep_latency_minutes < 0:
            raise ValueError(
                "Fall-asleep time cannot be negative."
            )

        if not 60 <= sleep_cycle_minutes <= 120:
            raise ValueError(
                "Sleep-cycle length must be 60–120 minutes."
            )

        return {
            "travel_minutes": travel_minutes,
            "maghrib_prayer_minutes": maghrib_prayer_minutes,
            "isha_prayer_minutes": isha_prayer_minutes,
            "maghrib_iqama_minutes": maghrib_iqama_minutes,
            "isha_iqama_minutes": isha_iqama_minutes,
            "maghrib_place": self.maghrib_place.get(),
            "isha_place": self.isha_place.get(),
            "sleep_latency_minutes": sleep_latency_minutes,
            "sleep_cycle_minutes": sleep_cycle_minutes,
        }


    # ========================================================
    # FETCH
    # ========================================================

    def start_fetch(
        self,
        auto=False,
    ):
        country = self.country_combo.get().strip()
        city = self.city_combo.get().strip()

        if not country or not city:
            if not auto:
                messagebox.showerror(
                    "Location",
                    "Choose both a country and a city.",
                )

            self.status.config(
                text="Choose a country and city before fetching.",
                fg=ERROR,
            )

            return

        method = self.method_map.get(
            self.method_combo.get(),
            DEFAULT_METHOD,
        )

        try:
            settings = self.get_plan_settings()

        except ValueError as error:
            if not auto:
                messagebox.showerror(
                    "Settings",
                    str(error),
                )

            self.status.config(
                text=str(error),
                fg=ERROR,
            )

            return

        self.fetch_generation += 1
        generation = self.fetch_generation

        self.fetch_button.config(
            state="disabled"
        )

        self.clear_fixed_prayer_times()

        self.status.config(
            text=(
                f"Fetching "
                f"{self.selected_date.strftime('%A, %d %B %Y')}…"
            ),
            fg=ACCENT,
        )

        threading.Thread(
            target=self.fetch_worker,
            args=(
                generation,
                self.selected_date,
                city,
                country,
                method,
                settings,
            ),
            daemon=True,
        ).start()

    def fetch_worker(
        self,
        generation,
        selected_date,
        city,
        country,
        method,
        settings,
    ):
        try:
            api = fetch_night_information(
                selected_date,
                city,
                country,
                method,
            )

            core = calculate_night_core(
                api["maghrib"],
                api["isha"],
                api["fajr_next"],
            )

            result = self.build_result_from_core(
                selected_date,
                city,
                country,
                method,
                api,
                core,
                settings,
            )

            self.root.after(
                0,
                lambda: self.fetch_success(
                    generation,
                    result,
                ),
            )

        except Exception as error:
            self.root.after(
                0,
                lambda: self.fetch_error(
                    generation,
                    str(error),
                ),
            )

    def build_result_from_core(
        self,
        selected_date,
        city,
        country,
        method,
        api,
        core,
        settings,
    ):
        maghrib_routine = build_prayer_routine(
            "Maghrib",
            core["maghrib"],
            settings["maghrib_place"],
            settings["maghrib_prayer_minutes"],
            settings["travel_minutes"],
            settings["maghrib_iqama_minutes"],
        )

        isha_routine = build_prayer_routine(
            "Isha",
            core["isha"],
            settings["isha_place"],
            settings["isha_prayer_minutes"],
            settings["travel_minutes"],
            settings["isha_iqama_minutes"],
        )

        models, practical = build_models(
            core,
            maghrib_routine,
            isha_routine,
            settings["sleep_latency_minutes"],
            settings["sleep_cycle_minutes"],
        )

        if self.custom_model_spec:
            models.append(
                build_custom_model(
                    core,
                    isha_routine,
                    self.custom_model_name or "My model",
                    self.custom_model_spec,
                )
            )

        return {
            "date": selected_date,
            "city": city,
            "country": country,
            "method": method,
            "api": api,
            "core": core,
            "models": models,
            "settings": settings,
            "maghrib_routine": maghrib_routine,
            "isha_routine": isha_routine,
            "practical": practical,
        }


    def fetch_success(
        self,
        generation,
        result,
    ):
        # Ignore stale responses if the user clicked another date quickly.
        if generation != self.fetch_generation:
            return

        self.fetch_button.config(
            state="normal"
        )

        self.recalc_button.config(
            state="normal"
        )

        self.result = result

        self.status.config(
            text=(
                f"Loaded {result['city']}, {result['country']} • "
                f"{result['date'].strftime('%A, %d %B %Y')}"
            ),
            fg=SUCCESS,
        )

        self.update_fixed_prayer_times()
        self.render_dashboard()

    def fetch_error(
        self,
        generation,
        error,
    ):
        if generation != self.fetch_generation:
            return

        self.fetch_button.config(
            state="normal"
        )

        self.status.config(
            text="Could not fetch prayer times.",
            fg=ERROR,
        )

        messagebox.showerror(
            "Prayer Times API",
            error,
        )

    # ========================================================
    # RECALCULATE WITHOUT NETWORK
    # ========================================================

    def recalculate_plan(self):
        if not self.result:
            return

        try:
            settings = self.get_plan_settings()

        except ValueError as error:
            messagebox.showerror(
                "Settings",
                str(error),
            )
            return

        r = self.result

        self.result = self.build_result_from_core(
            r["date"],
            r["city"],
            r["country"],
            r["method"],
            r["api"],
            r["core"],
            settings,
        )

        self.status.config(
            text="Plan recalculated using the existing prayer times.",
            fg=SUCCESS,
        )

        self.update_fixed_prayer_times()
        self.render_dashboard()


    # ========================================================
    # CUSTOM MODEL BUILDER
    # ========================================================

    def open_custom_model_builder(self):
        """Visual point-and-segment custom model editor."""
        if not self.result:
            messagebox.showinfo(
                "Custom Model Maker",
                "Fetch prayer times first so the editor can use the real night timeline.",
            )
            return

        r = self.result
        core = r["core"]
        mag = r["maghrib_routine"]
        isha = r["isha_routine"]

        popup = tk.Toplevel(self.root)
        popup.title("Custom Model Maker")
        popup.geometry("1040x610")
        popup.minsize(900, 550)
        popup.configure(bg=PANEL)
        popup.transient(self.root)
        popup.grab_set()

        tk.Label(
            popup,
            text="Custom Model Maker",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 2))

        tk.Label(
            popup,
            text=(
                "Prayer times are fixed points. Click empty timeline space to add a split. "
                "Click a split point and choose what the segment on its LEFT and RIGHT is. "
                "Movable split points can also be dragged."
            ),
            bg=PANEL,
            fg=MUTED,
            wraplength=980,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(0, 9))

        option_bar = tk.Frame(
            popup,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        option_bar.pack(fill="x", padx=16, pady=(0, 8))

        include_iqama = tk.BooleanVar(value=True)
        include_travel = tk.BooleanVar(value=True)

        tk.Label(
            option_bar,
            text="Optional routine points:",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(10, 5), pady=8)

        tk.Checkbutton(
            option_bar,
            text="Iqama",
            variable=include_iqama,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD,
            activeforeground=TEXT,
            selectcolor=PANEL,
        ).pack(side="left", padx=5)

        tk.Checkbutton(
            option_bar,
            text="Travel points",
            variable=include_travel,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD,
            activeforeground=TEXT,
            selectcolor=PANEL,
        ).pack(side="left", padx=5)

        tk.Label(
            option_bar,
            text="Model name",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(side="right", padx=(5, 6))

        name_entry = tk.Entry(
            option_bar,
            bg=CARD_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=22,
        )
        name_entry.pack(side="right", ipady=4, padx=(0, 4))
        name_entry.insert(0, self.custom_model_name or "My custom model")

        body = tk.Frame(popup, bg=PANEL)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        timeline_wrap = tk.Frame(
            body,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        timeline_wrap.pack(side="left", fill="both", expand=True, padx=(0, 8))

        editor = tk.Frame(
            body,
            bg=CARD,
            width=245,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        editor.pack(side="right", fill="y")
        editor.pack_propagate(False)

        canvas = tk.Canvas(
            timeline_wrap,
            bg=CARD,
            highlightthickness=0,
        )
        canvas.pack(fill="both", expand=True, padx=8, pady=8)

        # points = {id, time, label, fixed}
        points = []
        segment_kinds = []
        next_id = [1]
        selected_id = [None]
        dragging_id = [None]

        def add_point(dt, label, fixed=True):
            point = {
                "id": next_id[0],
                "time": dt,
                "label": label,
                "fixed": fixed,
            }
            next_id[0] += 1
            points.append(point)
            return point

        def ordered_points():
            # Deduplicate by rounded timestamp, preferring fixed points.
            by_time = {}
            for point in points:
                key = round(point["time"].timestamp())
                existing = by_time.get(key)
                if existing is None or (point["fixed"] and not existing["fixed"]):
                    by_time[key] = point
            return sorted(by_time.values(), key=lambda p: p["time"])

        def rebuild_fixed_points():
            movable = [p for p in points if not p["fixed"]]
            points.clear()

            add_point(core["maghrib"], "Maghrib", True)

            if include_iqama.get() and mag["place"] == "Mosque":
                add_point(mag["iqama_time"], "Maghrib iqama", True)

            if include_travel.get() and mag["place"] == "Mosque":
                add_point(mag["departure"], "Maghrib depart", True)
                add_point(mag["end"], "Maghrib home", True)

            add_point(core["isha"], "Isha", True)

            if include_iqama.get() and isha["place"] == "Mosque":
                add_point(isha["iqama_time"], "Isha iqama", True)

            if include_travel.get() and isha["place"] == "Mosque":
                add_point(isha["departure"], "Isha depart", True)
                add_point(isha["end"], "Isha home", True)

            points.extend(movable)
            add_point(core["fajr"], "Fajr", True)
            normalize_segments()
            selected_id[0] = None
            update_editor_controls()
            redraw()

        def normalize_segments(default="sleep"):
            needed = max(len(ordered_points()) - 1, 0)
            while len(segment_kinds) < needed:
                segment_kinds.append(default)
            del segment_kinds[needed:]

        # Initial timeline
        add_point(core["maghrib"], "Maghrib", True)
        add_point(core["isha"], "Isha", True)
        add_point(core["fajr"], "Fajr", True)
        normalize_segments()
        # intuitive default: pre-Isha qiyam/awake, post-Isha sleep
        ordered = ordered_points()
        if len(ordered) >= 3:
            segment_kinds[:] = ["prayer", "sleep"]

        tk.Label(
            editor,
            text="Selected point",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=12, pady=(14, 3))

        selected_label = tk.Label(
            editor,
            text="Click a point",
            bg=CARD,
            fg=ACCENT,
            wraplength=215,
            justify="left",
            font=("Segoe UI", 9),
        )
        selected_label.pack(anchor="w", padx=12, pady=(0, 10))

        time_label = tk.Label(
            editor,
            text="",
            bg=CARD,
            fg=MUTED,
            justify="left",
            font=("Segoe UI", 8),
        )
        time_label.pack(anchor="w", padx=12, pady=(0, 10))

        tk.Label(
            editor,
            text="LEFT segment",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=12)

        activity_values = ("Sleep", "Qiyam / Prayer", "Awake")

        left_combo = ttk.Combobox(
            editor,
            values=activity_values,
            state="disabled",
        )
        left_combo.pack(fill="x", padx=12, pady=(3, 10))

        tk.Label(
            editor,
            text="RIGHT segment",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=12)

        right_combo = ttk.Combobox(
            editor,
            values=activity_values,
            state="disabled",
        )
        right_combo.pack(fill="x", padx=12, pady=(3, 10))

        help_label = tk.Label(
            editor,
            text=(
                "Gold points are fixed prayer/routine markers. White points are custom "
                "splits and can be dragged."
            ),
            bg=CARD,
            fg=MUTED,
            wraplength=215,
            justify="left",
            font=("Segoe UI", 8),
        )
        help_label.pack(anchor="w", padx=12, pady=(8, 0))

        label_to_kind = {
            "Sleep": "sleep",
            "Qiyam / Prayer": "prayer",
            "Awake": "awake",
        }
        kind_to_label = {v: k for k, v in label_to_kind.items()}

        def find_point(point_id):
            return next((p for p in points if p["id"] == point_id), None)

        def update_editor_controls():
            point = find_point(selected_id[0])
            if not point:
                selected_label.config(text="Click a point")
                time_label.config(text="")
                left_combo.set("")
                right_combo.set("")
                left_combo.config(state="disabled")
                right_combo.config(state="disabled")
                return

            ordered = ordered_points()
            index = next((i for i, p in enumerate(ordered) if p["id"] == point["id"]), None)

            selected_label.config(text=point["label"])
            left_duration = (
                duration(point["time"] - ordered[index - 1]["time"])
                if index is not None and index > 0
                else "—"
            )
            right_duration = (
                duration(ordered[index + 1]["time"] - point["time"])
                if index is not None and index < len(ordered) - 1
                else "—"
            )

            time_label.config(
                text=(
                    f"{clock(point['time'])}\n"
                    + ("Fixed point" if point["fixed"] else "Movable split point")
                    + f"\n\nLeft split: {left_duration}"
                    + f"\nRight split: {right_duration}"
                )
            )

            if index is not None and index > 0:
                left_combo.config(state="readonly")
                left_combo.set(kind_to_label.get(segment_kinds[index - 1], "Awake"))
            else:
                left_combo.set("")
                left_combo.config(state="disabled")

            if index is not None and index < len(ordered) - 1:
                right_combo.config(state="readonly")
                right_combo.set(kind_to_label.get(segment_kinds[index], "Awake"))
            else:
                right_combo.set("")
                right_combo.config(state="disabled")

        def apply_left(event=None):
            point = find_point(selected_id[0])
            if not point:
                return
            ordered = ordered_points()
            index = next((i for i, p in enumerate(ordered) if p["id"] == point["id"]), None)
            if index is not None and index > 0:
                segment_kinds[index - 1] = label_to_kind[left_combo.get()]
                redraw()

        def apply_right(event=None):
            point = find_point(selected_id[0])
            if not point:
                return
            ordered = ordered_points()
            index = next((i for i, p in enumerate(ordered) if p["id"] == point["id"]), None)
            if index is not None and index < len(ordered) - 1:
                segment_kinds[index] = label_to_kind[right_combo.get()]
                redraw()

        left_combo.bind("<<ComboboxSelected>>", apply_left)
        right_combo.bind("<<ComboboxSelected>>", apply_right)

        def x_from_time(dt, width):
            ratio = (dt - core["maghrib"]).total_seconds() / core["night"].total_seconds()
            return 38 + ratio * (width - 76)

        def time_from_x(x, width):
            ratio = max(0.0, min(1.0, (x - 38) / max(width - 76, 1)))
            return core["maghrib"] + core["night"] * ratio

        def redraw(event=None):
            canvas.delete("all")
            width = max(canvas.winfo_width(), 620)
            height = max(canvas.winfo_height(), 300)
            y = height * 0.53
            ordered = ordered_points()
            normalize_segments()

            # Islamic geometric texture across the upper band.
            for x in range(45, width, 78):
                pts = []
                for i in range(16):
                    angle = -math.pi / 2 + i * math.pi / 8
                    radius = 13 if i % 2 == 0 else 5
                    pts.extend([x + math.cos(angle) * radius, 34 + math.sin(angle) * radius])
                canvas.create_polygon(pts, outline=BORDER, fill="")

            for index in range(len(ordered) - 1):
                p1, p2 = ordered[index], ordered[index + 1]
                x1 = x_from_time(p1["time"], width)
                x2 = x_from_time(p2["time"], width)
                kind = segment_kinds[index]
                color = {
                    "sleep": SLEEP_COLOR,
                    "prayer": PRAYER_COLOR,
                    "awake": AWAKE_COLOR,
                }[kind]
                canvas.create_line(x1, y, x2, y, fill=color, width=16, capstyle=tk.ROUND)
                if x2 - x1 > 72:
                    canvas.create_text(
                        (x1 + x2) / 2,
                        y - 26,
                        text=(
                            f"{kind_to_label[kind]}\n"
                            f"{duration(p2['time'] - p1['time'])}"
                        ),
                        fill=color,
                        font=("Segoe UI", 8, "bold"),
                    )

            for point in ordered:
                x = x_from_time(point["time"], width)
                selected = point["id"] == selected_id[0]
                color = ACCENT if point["fixed"] else TEXT
                radius = 9 if selected else 7
                canvas.create_oval(
                    x - radius, y - radius, x + radius, y + radius,
                    fill=color,
                    outline="#FFFFFF" if selected else "",
                    width=2,
                )
                canvas.create_text(
                    x,
                    y + 23,
                    text=f"{point['label']}\n{short_clock(point['time'])}",
                    fill=ACCENT if point["fixed"] else MUTED,
                    justify="center",
                    font=("Segoe UI", 7),
                )

            canvas.create_text(
                width / 2,
                height - 22,
                text="Click blank timeline space to add a split point.",
                fill=MUTED,
                font=("Segoe UI", 8),
            )

        def near_point(x, width):
            best = None
            best_dist = 9999
            for point in ordered_points():
                px = x_from_time(point["time"], width)
                dist = abs(px - x)
                if dist < best_dist:
                    best = point
                    best_dist = dist
            return best if best_dist <= 14 else None

        def on_press(event):
            width = max(canvas.winfo_width(), 620)
            point = near_point(event.x, width)

            if point:
                selected_id[0] = point["id"]
                if not point["fixed"]:
                    dragging_id[0] = point["id"]
                update_editor_controls()
                redraw()
                return

            dt = time_from_x(event.x, width)
            # Keep inside endpoints.
            dt = max(core["maghrib"] + timedelta(minutes=1), min(core["fajr"] - timedelta(minutes=1), dt))

            ordered = ordered_points()
            inherited = "sleep"
            insertion_index = None
            for index in range(len(ordered) - 1):
                if ordered[index]["time"] < dt < ordered[index + 1]["time"]:
                    inherited = segment_kinds[index]
                    insertion_index = index + 1
                    break

            point = add_point(dt, "Custom split", False)
            if insertion_index is not None:
                segment_kinds.insert(insertion_index, inherited)
            normalize_segments(inherited)
            selected_id[0] = point["id"]
            update_editor_controls()
            redraw()

        def on_drag(event):
            if dragging_id[0] is None:
                return
            point = find_point(dragging_id[0])
            if not point or point["fixed"]:
                return

            width = max(canvas.winfo_width(), 620)
            dt = time_from_x(event.x, width)
            ordered = ordered_points()
            index = next((i for i, p in enumerate(ordered) if p["id"] == point["id"]), None)
            if index is None:
                return

            minimum = ordered[index - 1]["time"] + timedelta(minutes=1) if index > 0 else core["maghrib"] + timedelta(minutes=1)
            maximum = ordered[index + 1]["time"] - timedelta(minutes=1) if index < len(ordered) - 1 else core["fajr"] - timedelta(minutes=1)
            point["time"] = max(minimum, min(maximum, dt))
            update_editor_controls()
            redraw()

        def on_release(event):
            dragging_id[0] = None

        canvas.bind("<Button-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        canvas.bind("<Configure>", redraw)

        include_iqama.trace_add("write", lambda *args: rebuild_fixed_points())
        include_travel.trace_add("write", lambda *args: rebuild_fixed_points())

        bottom = tk.Frame(popup, bg=PANEL)
        bottom.pack(fill="x", padx=16, pady=(0, 14))

        def delete_selected():
            point = find_point(selected_id[0])
            if not point:
                return
            if point["fixed"]:
                messagebox.showinfo(
                    "Custom Model Maker",
                    "Prayer, iqama and travel markers are fixed. Only white custom split points can be removed.",
                    parent=popup,
                )
                return

            ordered = ordered_points()
            index = next((i for i, p in enumerate(ordered) if p["id"] == point["id"]), None)
            points.remove(point)
            if index is not None and 0 < index < len(ordered) - 1 and index < len(segment_kinds):
                del segment_kinds[index]
            normalize_segments()
            selected_id[0] = None
            update_editor_controls()
            redraw()

        tk.Button(
            bottom,
            text="Delete selected split",
            command=delete_selected,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=7,
        ).pack(side="left")

        def save_model():
            ordered = ordered_points()
            normalize_segments()

            spec = []
            activity_name = {
                "sleep": "Sleep",
                "prayer": "Qiyam / Prayer",
                "awake": "Awake",
            }

            for index in range(len(ordered) - 1):
                minutes = max(
                    1,
                    round((ordered[index + 1]["time"] - ordered[index]["time"]).total_seconds() / 60),
                )
                spec.append(
                    {
                        "activity": activity_name[segment_kinds[index]],
                        "rule": "For minutes",
                        "value": minutes,
                    }
                )

            self.custom_model_name = name_entry.get().strip() or "My custom model"
            self.custom_model_spec = spec
            popup.destroy()
            self.recalculate_plan()
            if hasattr(self, "notebook") and hasattr(self, "models_page"):
                self.notebook.select(self.models_page)

        tk.Button(
            bottom,
            text="Save custom model",
            command=save_model,
            bg=ACCENT,
            fg="#111111",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=7,
        ).pack(side="right")

        def clear_custom():
            self.custom_model_name = None
            self.custom_model_spec = None
            popup.destroy()
            self.recalculate_plan()

        tk.Button(
            bottom,
            text="Remove custom model",
            command=clear_custom,
            bg=CARD_2,
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=7,
        ).pack(side="right", padx=(0, 6))

        redraw()

    def _open_custom_model_builder_legacy(self):
        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            "Custom Model Maker"
        )

        popup.geometry(
            "760x560"
        )

        popup.minsize(
            700,
            520,
        )

        popup.configure(
            bg=PANEL
        )

        popup.transient(
            self.root
        )

        popup.grab_set()

        top = tk.Frame(
            popup,
            bg=PANEL,
        )

        top.pack(
            fill="x",
            padx=14,
            pady=(14, 8),
        )

        tk.Label(
            top,
            text="Custom Model Maker",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(
            anchor="w",
        )

        tk.Label(
            top,
            text=(
                "Segments start at Maghrib and run in order. "
                "Choose Sleep, Qiyam/Prayer or Awake, then choose a duration "
                "or a fixed prayer/night boundary."
            ),
            bg=PANEL,
            fg=MUTED,
            wraplength=710,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(
            anchor="w",
            pady=(3, 8),
        )

        name_row = tk.Frame(
            top,
            bg=PANEL,
        )

        name_row.pack(
            fill="x",
        )

        tk.Label(
            name_row,
            text="Model name",
            bg=PANEL,
            fg=MUTED,
        ).pack(
            side="left",
        )

        name_entry = tk.Entry(
            name_row,
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )

        name_entry.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(8, 0),
            ipady=5,
        )

        name_entry.insert(
            0,
            self.custom_model_name or "My custom model",
        )

        rows_holder = tk.Frame(
            popup,
            bg=PANEL,
        )

        rows_holder.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 8),
        )

        row_widgets = []

        for column, header in enumerate(
            ("Activity", "Rule", "Minutes")
        ):
            tk.Label(
                rows_holder,
                text=header,
                bg=PANEL,
                fg=MUTED,
                font=("Segoe UI", 8, "bold"),
            ).grid(
                row=0,
                column=column,
                sticky="w",
                padx=4,
                pady=(0, 4),
            )

        rows_holder.grid_columnconfigure(
            0,
            weight=1,
        )

        rows_holder.grid_columnconfigure(
            1,
            weight=2,
        )

        def add_row(
            activity="Sleep",
            rule="For minutes",
            value="90",
        ):
            row_index = len(
                row_widgets
            ) + 1

            activity_combo = ttk.Combobox(
                rows_holder,
                values=tuple(
                    CUSTOM_ACTIVITY_TO_KIND.keys()
                ),
                state="readonly",
                width=18,
            )

            activity_combo.set(
                activity
            )

            activity_combo.grid(
                row=row_index,
                column=0,
                sticky="ew",
                padx=4,
                pady=3,
            )

            rule_combo = ttk.Combobox(
                rows_holder,
                values=CUSTOM_RULES,
                state="readonly",
                width=28,
            )

            rule_combo.set(
                rule
            )

            rule_combo.grid(
                row=row_index,
                column=1,
                sticky="ew",
                padx=4,
                pady=3,
            )

            value_entry = tk.Entry(
                rows_holder,
                bg=CARD,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                width=10,
            )

            value_entry.insert(
                0,
                str(value),
            )

            value_entry.grid(
                row=row_index,
                column=2,
                sticky="ew",
                padx=4,
                pady=3,
                ipady=5,
            )

            row_widgets.append(
                (
                    activity_combo,
                    rule_combo,
                    value_entry,
                )
            )

        if self.custom_model_spec:
            for item in self.custom_model_spec:
                add_row(
                    item["activity"],
                    item["rule"],
                    item.get("value", 0),
                )
        else:
            add_row(
                "Sleep",
                "Until half-night",
                "0",
            )

            add_row(
                "Qiyam / Prayer",
                "Until final sixth",
                "0",
            )

            add_row(
                "Sleep",
                "Until Fajr",
                "0",
            )

        controls = tk.Frame(
            popup,
            bg=PANEL,
        )

        controls.pack(
            fill="x",
            padx=14,
            pady=(0, 14),
        )

        tk.Button(
            controls,
            text="+ Add segment",
            command=add_row,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=7,
        ).pack(
            side="left",
        )

        def remove_last():
            if not row_widgets:
                return

            widgets = row_widgets.pop()

            for widget in widgets:
                widget.destroy()

        tk.Button(
            controls,
            text="Remove last",
            command=remove_last,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=7,
        ).pack(
            side="left",
            padx=(6, 0),
        )

        def save_model():
            spec = []

            for (
                activity_combo,
                rule_combo,
                value_entry,
            ) in row_widgets:
                activity = activity_combo.get()
                rule = rule_combo.get()

                if (
                    activity not in CUSTOM_ACTIVITY_TO_KIND
                    or rule not in CUSTOM_RULES
                ):
                    continue

                value = 0

                if rule == "For minutes":
                    try:
                        value = float(
                            value_entry.get()
                        )
                    except ValueError:
                        messagebox.showerror(
                            "Custom Model Maker",
                            "Minutes must be a number.",
                            parent=popup,
                        )
                        return

                    if value <= 0:
                        messagebox.showerror(
                            "Custom Model Maker",
                            "Minutes must be greater than zero.",
                            parent=popup,
                        )
                        return

                spec.append(
                    {
                        "activity": activity,
                        "rule": rule,
                        "value": value,
                    }
                )

            if not spec:
                messagebox.showerror(
                    "Custom Model Maker",
                    "Add at least one segment.",
                    parent=popup,
                )
                return

            self.custom_model_name = (
                name_entry.get().strip()
                or "My custom model"
            )

            self.custom_model_spec = spec

            popup.destroy()

            if self.result:
                self.recalculate_plan()
            else:
                self.status.config(
                    text=(
                        f"Custom model '{self.custom_model_name}' saved. "
                        f"Fetch prayer times to view it."
                    ),
                    fg=SUCCESS,
                )

        tk.Button(
            controls,
            text="Save custom model",
            command=save_model,
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=7,
        ).pack(
            side="right",
        )

        def clear_model():
            self.custom_model_name = None
            self.custom_model_spec = None
            popup.destroy()

            if self.result:
                self.recalculate_plan()

        tk.Button(
            controls,
            text="Clear custom model",
            command=clear_model,
            bg=CARD_2,
            fg=TEXT,
            activebackground=BORDER,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=7,
        ).pack(
            side="right",
            padx=(0, 6),
        )

    # ========================================================
    # LOCATION COMPARISON
    # ========================================================

    def open_location_comparison(self):
        if not self.result:
            messagebox.showinfo(
                "Compare locations",
                "Fetch prayer times once first, then open the comparison.",
            )
            return

        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            "Compare model across up to 5 locations"
        )

        popup.geometry(
            "1180x650"
        )

        popup.minsize(
            1000,
            560,
        )

        popup.configure(
            bg=PANEL
        )

        popup.transient(
            self.root
        )

        top = tk.Frame(
            popup,
            bg=PANEL,
        )

        top.pack(
            fill="x",
            padx=14,
            pady=(14, 8),
        )

        tk.Label(
            top,
            text="Compare one model across up to 5 countries / cities",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 15, "bold"),
        ).pack(
            anchor="w",
        )

        tk.Label(
            top,
            text=(
                "Each country needs a city because prayer times depend on "
                "location. The selected date, calculation method and your "
                "prayer/sleep settings stay the same for every row."
            ),
            bg=PANEL,
            fg=MUTED,
            wraplength=1100,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(
            anchor="w",
            pady=(3, 8),
        )

        model_row = tk.Frame(
            top,
            bg=PANEL,
        )

        model_row.pack(
            fill="x",
        )

        tk.Label(
            model_row,
            text="Model",
            bg=PANEL,
            fg=MUTED,
        ).pack(
            side="left",
        )

        model_names = [
            model["name"]
            for model in self.result["models"]
        ]

        model_combo = ttk.Combobox(
            model_row,
            values=model_names,
            state="readonly",
            width=52,
        )

        model_combo.set(
            model_names[0]
        )

        model_combo.pack(
            side="left",
            padx=(8, 0),
        )

        rows_frame = tk.Frame(
            popup,
            bg=PANEL,
        )

        rows_frame.pack(
            fill="x",
            padx=14,
            pady=(0, 8),
        )

        for column, header in enumerate(
            ("Use", "Country", "City")
        ):
            tk.Label(
                rows_frame,
                text=header,
                bg=PANEL,
                fg=MUTED,
                font=("Segoe UI", 8, "bold"),
            ).grid(
                row=0,
                column=column,
                sticky="w",
                padx=4,
            )

        compare_rows = []

        for index in range(5):
            enabled = tk.BooleanVar(
                value=(index == 0)
            )

            check = tk.Checkbutton(
                rows_frame,
                variable=enabled,
                bg=PANEL,
                activebackground=PANEL,
                selectcolor=CARD,
            )

            check.grid(
                row=index + 1,
                column=0,
                padx=4,
                pady=4,
            )

            country_combo = SearchableCombobox(
                rows_frame,
                values=self.location_db.country_names,
                width=31,
            )

            country_combo.grid(
                row=index + 1,
                column=1,
                sticky="ew",
                padx=4,
                pady=4,
            )

            city_combo = SearchableCombobox(
                rows_frame,
                values=[],
                width=31,
            )

            city_combo.grid(
                row=index + 1,
                column=2,
                sticky="ew",
                padx=4,
                pady=4,
            )

            if index == 0:
                country_combo.set(
                    self.result["country"]
                )

                cities = self.location_db.get_cities(
                    self.result["country"]
                )

                city_combo.set_values(
                    cities
                )

                city_combo.set(
                    self.result["city"]
                )

            def make_country_changed(
                country_box,
                city_box,
            ):
                def changed(event=None):
                    country = country_box.get().strip()

                    cities = self.location_db.get_cities(
                        country
                    )

                    city_box.set_values(
                        cities
                    )

                    city_box.set("")

                return changed

            country_combo.bind(
                "<<ComboboxSelected>>",
                make_country_changed(
                    country_combo,
                    city_combo,
                ),
            )

            compare_rows.append(
                (
                    enabled,
                    country_combo,
                    city_combo,
                )
            )

        rows_frame.grid_columnconfigure(
            1,
            weight=1,
        )

        rows_frame.grid_columnconfigure(
            2,
            weight=1,
        )

        status_label = tk.Label(
            popup,
            text="",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        )

        status_label.pack(
            anchor="w",
            padx=14,
        )

        result_holder = tk.Frame(
            popup,
            bg=PANEL,
        )

        result_holder.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(8, 14),
        )

        def render_results(results):
            for child in result_holder.winfo_children():
                child.destroy()

            if not results:
                return

            columns = (
                "Location",
                "Maghrib",
                "Isha",
                "Fajr",
                "Night",
                "Ready sleep",
                "Wake",
                "Sleep again",
                "Total sleep",
                "Qiyam",
                "Non-sleep",
            )

            for column, name in enumerate(
                columns
            ):
                result_holder.grid_columnconfigure(
                    column,
                    weight=1 if column == 0 else 0,
                )

                tk.Label(
                    result_holder,
                    text=name,
                    bg=CARD_2,
                    fg=ACCENT,
                    font=("Segoe UI", 8, "bold"),
                    padx=6,
                    pady=7,
                ).grid(
                    row=0,
                    column=column,
                    sticky="nsew",
                    padx=1,
                    pady=1,
                )

            for row_index, result in enumerate(
                results,
                start=1,
            ):
                model = result["model"]
                core = result["core"]

                values = (
                    (
                        f"{result['country']}\n"
                        f"{result['city']}"
                    ),
                    clock(core["maghrib"]),
                    clock(core["isha"]),
                    clock(core["fajr"]),
                    duration(core["night"]),
                    clock(
                        result["practical"][
                            "estimated_asleep"
                        ]
                    ),
                    clock(model["wake"]),
                    clock(model["sleep_again"]),
                    duration(model["total_sleep"]),
                    duration(model["qiyam"]),
                    duration(
                        non_sleep_time(
                            core,
                            model["total_sleep"],
                        )
                    ),
                )

                for column, value in enumerate(
                    values
                ):
                    tk.Label(
                        result_holder,
                        text=value,
                        bg=CARD,
                        fg=TEXT,
                        font=("Segoe UI", 8),
                        justify="center",
                        padx=6,
                        pady=8,
                    ).grid(
                        row=row_index,
                        column=column,
                        sticky="nsew",
                        padx=1,
                        pady=1,
                    )

        def start_compare():
            selected = []

            for (
                enabled,
                country_combo,
                city_combo,
            ) in compare_rows:
                if not enabled.get():
                    continue

                country = country_combo.get().strip()
                city = city_combo.get().strip()

                if country and city:
                    selected.append(
                        (country, city)
                    )

            if not selected:
                messagebox.showerror(
                    "Compare",
                    "Choose at least one country/city row.",
                    parent=popup,
                )
                return

            chosen_name = model_combo.get()

            try:
                settings = self.get_plan_settings()
            except ValueError as error:
                messagebox.showerror(
                    "Settings",
                    str(error),
                    parent=popup,
                )
                return

            method = self.result["method"]

            status_label.config(
                text="Fetching comparison locations…",
                fg=ACCENT,
            )

            compare_button.config(
                state="disabled"
            )

            def worker():
                results = []
                errors = []

                for country, city in selected:
                    try:
                        api = fetch_night_information(
                            self.selected_date,
                            city,
                            country,
                            method,
                        )

                        core = calculate_night_core(
                            api["maghrib"],
                            api["isha"],
                            api["fajr_next"],
                        )

                        built = self.build_result_from_core(
                            self.selected_date,
                            city,
                            country,
                            method,
                            api,
                            core,
                            settings,
                        )

                        model = next(
                            (
                                item
                                for item in built["models"]
                                if item["name"] == chosen_name
                            ),
                            built["models"][0],
                        )

                        results.append(
                            {
                                "country": country,
                                "city": city,
                                "core": core,
                                "model": model,
                                "practical": built["practical"],
                            }
                        )

                    except Exception as error:
                        errors.append(
                            f"{country} / {city}: {error}"
                        )

                def done():
                    compare_button.config(
                        state="normal"
                    )

                    render_results(
                        results
                    )

                    if errors:
                        status_label.config(
                            text=(
                                "Some locations failed: "
                                + " | ".join(errors)
                            ),
                            fg=ERROR,
                        )
                    else:
                        status_label.config(
                            text=(
                                f"Compared {len(results)} location(s) "
                                f"using {chosen_name}."
                            ),
                            fg=SUCCESS,
                        )

                self.root.after(
                    0,
                    done,
                )

            threading.Thread(
                target=worker,
                daemon=True,
            ).start()

        compare_button = tk.Button(
            top,
            text="Run comparison",
            command=start_compare,
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=7,
        )

        compare_button.pack(
            anchor="e",
            pady=(8, 0),
        )

    # ========================================================
    # UI HELPERS
    # ========================================================

    def clear_content(self):
        for child in self.content.winfo_children():
            child.destroy()

    def show_empty_secondary_pages(self):
        """Placeholders for the non-scrollable tabs before data is fetched."""
        for page in (self.models_page, self.comparison_page):
            for child in page.winfo_children():
                child.destroy()
            tk.Label(
                page,
                text="Fetch prayer times to build this view.",
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 14, "bold"),
            ).pack(expand=True)

    def render_models_overview(self):
        """All models in one non-scrollable screen."""
        if not self.result:
            return

        for child in self.models_page.winfo_children():
            child.destroy()

        models = self.result["models"]
        core = self.result["core"]

        top = tk.Frame(self.models_page, bg=BG)
        top.pack(fill="x", padx=8, pady=(7, 2))

        tk.Label(
            top,
            text="All models — one screen",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 13, "bold"),
        ).pack(side="left")

        tk.Label(
            top,
            text="Hover a segment for its exact type, time and duration.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            top,
            text="Edit custom model",
            command=self.open_custom_model_builder,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=6,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="right")

        grid = tk.Frame(self.models_page, bg=BG)
        grid.pack(fill="both", expand=True, padx=5, pady=(2, 6))

        columns = 3 if len(models) <= 6 else 4
        rows = math.ceil(len(models) / columns)

        for col in range(columns):
            grid.grid_columnconfigure(col, weight=1, uniform="model_col")
        for row in range(rows):
            grid.grid_rowconfigure(row, weight=1, uniform="model_row")

        for index, model in enumerate(models):
            row = index // columns
            col = index % columns

            card = tk.Frame(
                grid,
                bg=PANEL,
                highlightbackground=BORDER,
                highlightthickness=1,
            )
            card.grid(
                row=row,
                column=col,
                sticky="nsew",
                padx=4,
                pady=4,
            )

            self.draw_model_compact(card, core, model)

    def render_comparison_page(self):
        if not self.result:
            return

        for child in self.comparison_page.winfo_children():
            child.destroy()

        top = tk.Frame(self.comparison_page, bg=BG)
        top.pack(fill="x", padx=8, pady=(8, 5))

        tk.Label(
            top,
            text="Detailed model comparison",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 13, "bold"),
        ).pack(side="left")

        tk.Button(
            top,
            text="Compare 5 locations",
            command=self.open_location_comparison,
            bg=ACCENT,
            fg="#111111",
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="right")

        self.draw_model_comparison_table(
            self.result["models"],
            self.result["core"],
            parent=self.comparison_page,
        )

        info = tk.Frame(
            self.comparison_page,
            bg=CARD_2,
            highlightbackground=ACCENT,
            highlightthickness=1,
        )
        info.pack(fill="x", padx=8, pady=8)

        tk.Label(
            info,
            text=(
                "Mosque timing rule: travel TO the mosque uses the adhan→iqama "
                "window. Return travel is after prayer. The comparison uses the "
                "same Maghrib→next-Fajr night for every model."
            ),
            bg=CARD_2,
            fg=TEXT,
            wraplength=1150,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=12, pady=10)

    def draw_model_compact(self, parent, core, model):
        """Compact timeline card used by the one-screen All Models tab."""
        tk.Label(
            parent,
            text=model["name"],
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=8, pady=(7, 1))

        tk.Label(
            parent,
            text=model.get("description", ""),
            bg=PANEL,
            fg=MUTED,
            wraplength=390,
            justify="left",
            font=("Segoe UI", 7),
        ).pack(anchor="w", padx=8)

        canvas = tk.Canvas(
            parent,
            bg=PANEL,
            highlightthickness=0,
            height=118,
        )
        canvas.pack(fill="both", expand=True, padx=5, pady=2)

        def redraw(event=None):
            canvas.delete("all")
            width = max(canvas.winfo_width(), 260)
            height = max(canvas.winfo_height(), 105)
            left = 17
            right = width - 17
            y = 44
            total = core["night"].total_seconds()

            def xpos(dt):
                return left + ((dt - core["maghrib"]).total_seconds() / total) * (right - left)

            canvas.create_line(left, y, right, y, fill=BORDER, width=4)

            color_map = {
                "sleep": SLEEP_COLOR,
                "prayer": PRAYER_COLOR,
                "awake": AWAKE_COLOR,
                "travel": TRAVEL_COLOR,
                "wait": WAIT_COLOR,
                "cycle": CYCLE_COLOR,
            }

            for segment in model["segments"]:
                clipped = clip_segment(
                    segment["start"], segment["end"],
                    core["maghrib"], core["fajr"],
                )
                if not clipped:
                    continue
                start, end = clipped
                x1, x2 = xpos(start), xpos(end)
                color = color_map.get(segment["kind"], AWAKE_COLOR)
                line_id = canvas.create_line(
                    x1, y, x2, y,
                    fill=color,
                    width=10,
                    capstyle=tk.ROUND,
                )
                self.bind_segment_tooltip(
                    canvas,
                    line_id,
                    segment["name"],
                    start,
                    end,
                    segment["kind"],
                )

            ix = xpos(core["isha"])
            canvas.create_line(ix, y - 18, ix, y + 18, fill=ACCENT, dash=(3, 3))
            canvas.create_text(ix, y + 29, text="Isha", fill=ACCENT, font=("Segoe UI", 6))

            canvas.create_text(
                width / 2,
                height - 12,
                text=(
                    f"Sleep {duration(model['total_sleep'])}  •  "
                    f"Qiyam {duration(model['qiyam'])}  •  "
                    f"Awake {duration(non_sleep_time(core, model['total_sleep']))}"
                ),
                fill=TEXT,
                font=("Segoe UI", 7, "bold"),
            )

        canvas.bind("<Configure>", redraw)
        redraw()

        tk.Label(
            parent,
            text=model.get("note", ""),
            bg=PANEL,
            fg=ACCENT,
            wraplength=390,
            justify="left",
            font=("Segoe UI", 6),
        ).pack(anchor="w", padx=8, pady=(0, 5))

    def show_empty(self):
        self.clear_content()
        self.draw_hadith_card()

        box = tk.Frame(
            self.content,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        box.pack(
            fill="x",
            pady=(5, 0),
        )

        tk.Label(
            box,
            text="Choose a day to build the night plan",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 17, "bold"),
        ).pack(
            pady=(38, 7),
        )

        tk.Label(
            box,
            text=(
                "Prayer times are fetched automatically when you select a day. "
                "Use Calendar to browse any month."
            ),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(
            pady=(0, 38),
        )

    def section(
        self,
        title,
        subtitle="",
    ):
        wrapper = tk.Frame(
            self.content,
            bg=BG,
        )

        wrapper.pack(
            fill="x",
            pady=(9, 5),
        )

        tk.Label(
            wrapper,
            text=title,
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 14, "bold"),
        ).pack(
            anchor="w",
        )

        if subtitle:
            tk.Label(
                wrapper,
                text=subtitle,
                bg=BG,
                fg=MUTED,
                wraplength=1150,
                justify="left",
                font=("Segoe UI", 8),
            ).pack(
                anchor="w",
                pady=(2, 0),
            )

    def draw_hadith_card(self):
        card = tk.Frame(
            self.content,
            bg=CARD_2,
            highlightbackground=ACCENT,
            highlightthickness=1,
        )

        card.pack(
            fill="x",
            pady=(4, 8),
        )

        tk.Label(
            card,
            text="Hadith",
            bg=CARD_2,
            fg=ACCENT,
            font=("Segoe UI", 10, "bold"),
        ).pack(
            anchor="w",
            padx=14,
            pady=(10, 3),
        )

        tk.Label(
            card,
            text=HADITH_TEXT,
            bg=CARD_2,
            fg=TEXT,
            justify="left",
            wraplength=1160,
            font=("Segoe UI", 9),
        ).pack(
            anchor="w",
            padx=14,
        )

        source = tk.Label(
            card,
            text="Sahih al-Bukhari 1131 — open source",
            bg=CARD_2,
            fg=ACCENT,
            cursor="hand2",
            font=("Segoe UI", 8, "underline"),
        )

        source.pack(
            anchor="w",
            padx=14,
            pady=(5, 10),
        )

        source.bind(
            "<Button-1>",
            lambda event: webbrowser.open(
                HADITH_URL
            ),
        )

    def card_grid(
        self,
        items,
    ):
        container = tk.Frame(
            self.content,
            bg=BG,
        )

        container.pack(
            fill="x",
            pady=(0, 10),
        )

        columns = max(
            2,
            min(
                self.cards_per_row.get(),
                4,
            ),
        )

        for column in range(columns):
            container.grid_columnconfigure(
                column,
                weight=1,
                uniform="cards",
            )

        for index, item in enumerate(items):
            row = index // columns
            column = index % columns

            card = tk.Frame(
                container,
                bg=CARD,
                highlightbackground=BORDER,
                highlightthickness=1,
            )

            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=4,
                pady=4,
            )

            tk.Label(
                card,
                text=item[0],
                bg=CARD,
                fg=MUTED,
                font=("Segoe UI", 8),
            ).pack(
                anchor="w",
                padx=11,
                pady=(9, 1),
            )

            tk.Label(
                card,
                text=item[1],
                bg=CARD,
                fg=TEXT,
                font=("Segoe UI", 12, "bold"),
            ).pack(
                anchor="w",
                padx=11,
            )

            if len(item) > 2 and item[2]:
                tk.Label(
                    card,
                    text=item[2],
                    bg=CARD,
                    fg=ACCENT,
                    justify="left",
                    wraplength=280,
                    font=("Segoe UI", 8),
                ).pack(
                    anchor="w",
                    padx=11,
                    pady=(3, 9),
                )

            else:
                tk.Frame(
                    card,
                    bg=CARD,
                    height=9,
                ).pack()

        return container

    # ========================================================
    # DASHBOARD
    # ========================================================

    def render_dashboard(self):
        self.clear_content()

        r = self.result
        core = r["core"]

        self.draw_hadith_card()

        self.section(
            "Tonight at a glance",
            (
                f"{r['city']}, {r['country']} • "
                f"{r['date'].strftime('%A, %d %B %Y')}"
            ),
        )

        self.card_grid(
            [
                (
                    "Night length",
                    duration(core["night"]),
                    "Maghrib → next Fajr",
                ),
                (
                    "1/2 of night",
                    duration(core["half"]),
                    f"boundary {clock(core['wake'])}",
                ),
                (
                    "1/3 of night",
                    duration(core["third"]),
                    "Qiyam fraction",
                ),
                (
                    "1/6 of night",
                    duration(core["sixth"]),
                    f"final sixth {clock(core['final_sixth'])}",
                ),
                (
                    "Half-night",
                    clock(core["wake"]),
                    duration(core["half"]),
                ),
                (
                    "Last third",
                    clock(core["last_third"]),
                    "2/3 through the night",
                ),
                (
                    "Isha routine ends",
                    clock(r["isha_routine"]["end"]),
                    self.routine_subtitle(
                        r["isha_routine"]
                    ),
                ),
                (
                    "Ready for bed",
                    clock(
                        r["practical"][
                            "ready_after_isha"
                        ]
                    ),
                    "Isha prayer + return travel",
                ),
                (
                    "Estimated asleep",
                    clock(
                        r["practical"][
                            "estimated_asleep"
                        ]
                    ),
                    (
                        f"+ "
                        f"{r['settings']['sleep_latency_minutes']}m "
                        f"fall-asleep time"
                    ),
                ),
            ]
        )

        # ----------------------------------------------------
        # Prayer routine
        # ----------------------------------------------------

        maghrib_to_isha = (
            core["isha"]
            - core["maghrib"]
        )

        self.section(
            "Prayer routine",
            (
                "For mosque prayer, travel happens inside the adhan→iqama window. "
                "Only the remaining time after arrival is counted as waiting."
            ),
        )

        self.card_grid(
            [
                (
                    "Maghrib routine",
                    (
                        f"{clock(r['maghrib_routine']['start'])}"
                        f" → "
                        f"{clock(r['maghrib_routine']['end'])}"
                    ),
                    self.routine_subtitle(
                        r["maghrib_routine"]
                    ),
                ),
                (
                    "Maghrib adhan → Isha adhan",
                    duration(
                        maghrib_to_isha
                    ),
                    (
                        f"{clock(core['maghrib'])}"
                        f" → "
                        f"{clock(core['isha'])}"
                    ),
                ),
                (
                    "Isha routine",
                    (
                        f"{clock(r['isha_routine']['start'])}"
                        f" → "
                        f"{clock(r['isha_routine']['end'])}"
                    ),
                    self.routine_subtitle(
                        r["isha_routine"]
                    ),
                ),
                (
                    "Maghrib iqama",
                    self.iqama_card_value(
                        r["maghrib_routine"]
                    ),
                    self.iqama_card_subtitle(
                        r["maghrib_routine"]
                    ),
                ),
                (
                    "Isha iqama",
                    self.iqama_card_value(
                        r["isha_routine"]
                    ),
                    self.iqama_card_subtitle(
                        r["isha_routine"]
                    ),
                ),
                (
                    "Mosque travel",
                    (
                        f"{r['settings']['travel_minutes']}m "
                        f"one way"
                    ),
                    (
                        "Travel is not added on top of the iqama wait; "
                        "it uses part of the same window."
                    ),
                ),
                (
                    "Fall-asleep estimate",
                    (
                        f"{r['settings']['sleep_latency_minutes']}m"
                    ),
                    "Added after the Isha routine",
                ),
                (
                    "Sleep-cycle setting",
                    (
                        f"{r['settings']['sleep_cycle_minutes']}m"
                    ),
                    "Planning approximation",
                ),
            ]
        )

        # ----------------------------------------------------
        # Hadith fraction timeline
        # ----------------------------------------------------

        self.section(
            "Hadith fraction model",
            (
                f"1/2 = {duration(core['half'])} • "
                f"1/3 = {duration(core['third'])} • "
                f"1/6 = {duration(core['sixth'])} • "
                f"2/3 sleep = {duration(core['two_thirds'])}. "
                f"Hover over a colored line for details."
            ),
        )

        self.draw_core_timeline(
            core
        )

        # ----------------------------------------------------
        # Model overview lives on a dedicated non-scrollable tab
        # ----------------------------------------------------

        self.section(
            "Models & comparison",
            (
                "All models are now arranged in a compact grid on the "
                "All Models tab, and the numeric table is on Comparison. "
                "This avoids scrolling through one model after another."
            ),
        )

        quick = tk.Frame(self.content, bg=CARD_2, highlightbackground=BORDER, highlightthickness=1)
        quick.pack(fill="x", pady=(0, 10))

        tk.Button(
            quick, text="Open All Models",
            command=lambda: self.notebook.select(self.models_page),
            bg=ACCENT, fg="#111111", relief="flat", cursor="hand2",
            font=("Segoe UI", 9, "bold"), padx=16, pady=8,
        ).pack(side="left", padx=10, pady=10)

        tk.Button(
            quick, text="Open Comparison",
            command=lambda: self.notebook.select(self.comparison_page),
            bg=CARD, fg=TEXT, activebackground=CARD_2, activeforeground=TEXT,
            relief="flat", cursor="hand2", font=("Segoe UI", 9, "bold"),
            padx=16, pady=8,
        ).pack(side="left", padx=(0, 10), pady=10)

        self.render_models_overview()
        self.render_comparison_page()

        actions = tk.Frame(
            self.content,
            bg=BG,
        )

        actions.pack(
            fill="x",
            pady=(12, 26),
        )

        tk.Button(
            actions,
            text="Copy night summary",
            command=self.copy_summary,
            bg=ACCENT,
            fg="#111111",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=16,
            pady=8,
        ).pack(
            side="left",
        )

        tk.Button(
            actions,
            text="Build / edit custom model",
            command=self.open_custom_model_builder,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=16,
            pady=8,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        tk.Button(
            actions,
            text="Compare 5 locations",
            command=self.open_location_comparison,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=16,
            pady=8,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        tk.Button(
            actions,
            text="Export PNG",
            command=self.open_export_png_menu,
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=16,
            pady=8,
        ).pack(
            side="right",
        )

    @staticmethod
    def routine_subtitle(
        routine,
    ):
        if routine["place"] == "Mosque":
            text = (
                f"Mosque • "
                f"{routine['prayer_minutes']}m prayer • "
                f"iqama +{routine['iqama_wait_minutes']}m • "
                f"{routine['travel_minutes']}m travel each way"
            )

            if routine["late_by"] > timedelta(0):
                text += (
                    f" • arrival is {duration(routine['late_by'])} "
                    f"after configured iqama"
                )

            return text

        return (
            f"Home • "
            f"{routine['prayer_minutes']}m prayer"
        )

    @staticmethod
    def iqama_card_value(
        routine,
    ):
        if routine["place"] != "Mosque":
            return "Home"

        return clock(
            routine["iqama_time"]
        )

    @staticmethod
    def iqama_card_subtitle(
        routine,
    ):
        if routine["place"] != "Mosque":
            return "Iqama setting is ignored at home"

        if routine["late_by"] > timedelta(0):
            return (
                f"Arrival {clock(routine['arrival'])} • "
                f"{duration(routine['late_by'])} after iqama"
            )

        wait_after_arrival = max(
            routine["iqama_time"] - routine["arrival"],
            timedelta(0),
        )

        return (
            f"Arrival {clock(routine['arrival'])} • "
            f"remaining wait {duration(wait_after_arrival)}"
        )

    def draw_model_comparison_table(
        self,
        models,
        core,
        parent=None,
    ):
        target = parent or self.content
        holder = tk.Frame(
            target,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        holder.pack(
            fill="x",
            pady=(0, 10),
        )

        columns = (
            "Model",
            "Wake",
            "Sleep again",
            "Total sleep",
            "Qiyam",
            "Non-sleep",
            "Sleep %",
        )

        for column, title in enumerate(
            columns
        ):
            holder.grid_columnconfigure(
                column,
                weight=1 if column == 0 else 0,
            )

            tk.Label(
                holder,
                text=title,
                bg=CARD_2,
                fg=ACCENT,
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=7,
            ).grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=1,
                pady=1,
            )

        night_seconds = core["night"].total_seconds()

        for row_index, model in enumerate(
            models,
            start=1,
        ):
            sleep_pct = (
                model["total_sleep"].total_seconds()
                / night_seconds
                * 100
                if night_seconds
                else 0
            )

            values = (
                model["name"],
                clock(model["wake"]),
                clock(model["sleep_again"]),
                duration(model["total_sleep"]),
                duration(model["qiyam"]),
                duration(
                    non_sleep_time(
                        core,
                        model["total_sleep"],
                    )
                ),
                f"{sleep_pct:.1f}%",
            )

            for column, value in enumerate(
                values
            ):
                tk.Label(
                    holder,
                    text=value,
                    bg=CARD,
                    fg=TEXT,
                    font=("Segoe UI", 8),
                    justify="left" if column == 0 else "center",
                    padx=8,
                    pady=8,
                ).grid(
                    row=row_index,
                    column=column,
                    sticky="nsew",
                    padx=1,
                    pady=1,
                )


    # ========================================================
    # CANVAS TOOLTIPS
    # ========================================================

    def bind_segment_tooltip(
        self,
        canvas,
        item_id,
        title,
        start,
        end,
        kind,
    ):
        names = {
            "sleep": "Sleep",
            "prayer": "Prayer / Qiyam",
            "awake": "Awake",
            "travel": "Travel",
            "wait": "Wait for iqama",
            "cycle": "Sleep-cycle block",
        }

        text_value = (
            f"{names.get(kind, kind.title())}\n"
            f"{title}\n"
            f"{clock(start)} → {clock(end)}\n"
            f"{duration(end - start)}"
        )

        canvas.tag_bind(
            item_id,
            "<Enter>",
            lambda event: self.show_canvas_tooltip(
                canvas,
                event.x,
                event.y,
                text_value,
            ),
        )

        canvas.tag_bind(
            item_id,
            "<Motion>",
            lambda event: self.show_canvas_tooltip(
                canvas,
                event.x,
                event.y,
                text_value,
            ),
        )

        canvas.tag_bind(
            item_id,
            "<Leave>",
            lambda event: self.hide_canvas_tooltip(
                canvas
            ),
        )

    @staticmethod
    def hide_canvas_tooltip(
        canvas,
    ):
        for attr in (
            "_tooltip_rect",
            "_tooltip_text",
        ):
            item = getattr(
                canvas,
                attr,
                None,
            )

            if item:
                canvas.delete(
                    item
                )

                setattr(
                    canvas,
                    attr,
                    None,
                )

    def show_canvas_tooltip(
        self,
        canvas,
        x,
        y,
        text_value,
    ):
        self.hide_canvas_tooltip(
            canvas
        )

        text_id = canvas.create_text(
            x + 22,
            max(y - 55, 9),
            text=text_value,
            anchor="nw",
            fill=TEXT,
            justify="left",
            font=("Segoe UI", 8),
        )

        bbox = canvas.bbox(
            text_id
        )

        if not bbox:
            return

        rect_id = canvas.create_rectangle(
            bbox[0] - 7,
            bbox[1] - 7,
            bbox[2] + 7,
            bbox[3] + 7,
            fill=CARD_2,
            outline=ACCENT,
            width=1,
        )

        canvas.tag_raise(
            text_id
        )

        canvas._tooltip_rect = rect_id
        canvas._tooltip_text = text_id

    # ========================================================
    # CORE TIMELINE
    # ========================================================

    def draw_core_timeline(
        self,
        core,
    ):
        container = tk.Frame(
            self.content,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        container.pack(
            fill="x",
            pady=(0, 12),
        )

        canvas = tk.Canvas(
            container,
            height=220,
            bg=PANEL,
            highlightthickness=0,
        )

        canvas.pack(
            fill="x",
            padx=10,
            pady=8,
        )

        def redraw(event=None):
            canvas.delete("all")

            width = max(
                canvas.winfo_width(),
                850,
            )

            left = 65
            right = width - 65
            y = 105

            total = (
                core["night"]
                .total_seconds()
            )

            def xpos(dt):
                return (
                    left
                    + (
                        (
                            dt
                            - core["maghrib"]
                        ).total_seconds()
                        / total
                    )
                    * (
                        right
                        - left
                    )
                )

            specs = (
                (
                    core["maghrib"],
                    core["wake"],
                    SLEEP_COLOR,
                    "Sleep • 1/2",
                    "sleep",
                ),
                (
                    core["wake"],
                    core["final_sixth"],
                    PRAYER_COLOR,
                    "Prayer / Qiyam • 1/3",
                    "prayer",
                ),
                (
                    core["final_sixth"],
                    core["fajr"],
                    SLEEP_COLOR,
                    "Sleep • 1/6",
                    "sleep",
                ),
            )

            for (
                start,
                end,
                color,
                title,
                kind,
            ) in specs:
                x1 = xpos(start)
                x2 = xpos(end)

                line_id = canvas.create_line(
                    x1,
                    y,
                    x2,
                    y,
                    fill=color,
                    width=12,
                    capstyle=tk.ROUND,
                )

                canvas.create_text(
                    (x1 + x2) / 2,
                    y - 36,
                    text=title,
                    fill=color,
                    font=("Segoe UI", 8, "bold"),
                )

                canvas.create_text(
                    (x1 + x2) / 2,
                    y - 19,
                    text=duration(
                        end - start
                    ),
                    fill=TEXT,
                    font=("Segoe UI", 8),
                )

                self.bind_segment_tooltip(
                    canvas,
                    line_id,
                    title,
                    start,
                    end,
                    kind,
                )

            # Isha reference in the core model.
            isha_x = xpos(
                core["isha"]
            )

            canvas.create_line(
                isha_x,
                y - 33,
                isha_x,
                y + 33,
                fill=ACCENT,
                width=2,
                dash=(4, 4),
            )

            canvas.create_oval(
                isha_x - 6,
                y - 6,
                isha_x + 6,
                y + 6,
                fill=ACCENT,
                outline="",
            )

            canvas.create_text(
                isha_x,
                y + 67,
                text=(
                    f"Isha\n"
                    f"{short_clock(core['isha'])}"
                ),
                fill=ACCENT,
                justify="center",
                font=("Segoe UI", 8, "bold"),
            )

            points = (
                (
                    core["maghrib"],
                    "Maghrib",
                ),
                (
                    core["wake"],
                    "Wake",
                ),
                (
                    core["final_sixth"],
                    "Sleep again",
                ),
                (
                    core["fajr"],
                    "Fajr",
                ),
            )

            for dt, label in points:
                x = xpos(dt)

                canvas.create_oval(
                    x - 6,
                    y - 6,
                    x + 6,
                    y + 6,
                    fill=TEXT,
                    outline="",
                )

                canvas.create_text(
                    x,
                    y + 24,
                    text=label,
                    fill=MUTED,
                    font=("Segoe UI", 8, "bold"),
                )

                canvas.create_text(
                    x,
                    y + 41,
                    text=short_clock(dt),
                    fill=TEXT,
                    font=("Segoe UI", 8),
                )

        canvas.bind(
            "<Configure>",
            redraw,
        )

        redraw()

    # ========================================================
    # MODEL TIMELINES
    # ========================================================

    def draw_model(
        self,
        core,
        model,
    ):
        card = tk.Frame(
            self.content,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        card.pack(
            fill="x",
            pady=5,
        )

        tk.Label(
            card,
            text=model["name"],
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
        ).pack(
            anchor="w",
            padx=14,
            pady=(11, 2),
        )

        tk.Label(
            card,
            text=model["description"],
            bg=PANEL,
            fg=MUTED,
            wraplength=1140,
            justify="left",
            font=("Segoe UI", 8),
        ).pack(
            anchor="w",
            padx=14,
            pady=(0, 3),
        )

        canvas = tk.Canvas(
            card,
            height=222,
            bg=PANEL,
            highlightthickness=0,
        )

        canvas.pack(
            fill="x",
            padx=10,
        )

        def redraw(event=None):
            canvas.delete("all")

            width = max(
                canvas.winfo_width(),
                850,
            )

            left = 62
            right = width - 62
            y = 92

            total = (
                core["night"]
                .total_seconds()
            )

            def xpos(dt):
                return (
                    left
                    + (
                        (
                            dt
                            - core["maghrib"]
                        ).total_seconds()
                        / total
                    )
                    * (
                        right
                        - left
                    )
                )

            canvas.create_line(
                left,
                y,
                right,
                y,
                fill=BORDER,
                width=5,
            )

            color_map = {
                "sleep": SLEEP_COLOR,
                "prayer": PRAYER_COLOR,
                "awake": AWAKE_COLOR,
                "travel": TRAVEL_COLOR,
                "wait": WAIT_COLOR,
                "cycle": CYCLE_COLOR,
            }

            for segment in model["segments"]:
                clipped = clip_segment(
                    segment["start"],
                    segment["end"],
                    core["maghrib"],
                    core["fajr"],
                )

                if not clipped:
                    continue

                start, end = clipped
                x1 = xpos(start)
                x2 = xpos(end)

                color = color_map.get(
                    segment["kind"],
                    AWAKE_COLOR,
                )

                line_id = canvas.create_line(
                    x1,
                    y,
                    x2,
                    y,
                    fill=color,
                    width=12,
                    capstyle=tk.ROUND,
                )

                self.bind_segment_tooltip(
                    canvas,
                    line_id,
                    segment["name"],
                    start,
                    end,
                    segment["kind"],
                )

                if x2 - x1 > 92:
                    canvas.create_text(
                        (x1 + x2) / 2,
                        y - 31,
                        text=(
                            f"{segment['name']}\n"
                            f"{duration(end - start)}"
                        ),
                        fill=color,
                        justify="center",
                        font=("Segoe UI", 8, "bold"),
                    )

            # Isha is always visible.
            isha_x = xpos(
                core["isha"]
            )

            canvas.create_line(
                isha_x,
                y - 32,
                isha_x,
                y + 30,
                fill=ACCENT,
                width=2,
                dash=(4, 4),
            )

            canvas.create_oval(
                isha_x - 6,
                y - 6,
                isha_x + 6,
                y + 6,
                fill=ACCENT,
                outline="",
            )

            canvas.create_text(
                isha_x,
                y + 62,
                text=(
                    f"Isha\n"
                    f"{short_clock(core['isha'])}"
                ),
                fill=ACCENT,
                justify="center",
                font=("Segoe UI", 8, "bold"),
            )

            points = (
                (
                    core["maghrib"],
                    "Maghrib",
                ),
                (
                    model["wake"],
                    "Wake",
                ),
                (
                    model["sleep_again"],
                    "Sleep again",
                ),
                (
                    core["fajr"],
                    "Fajr",
                ),
            )

            seen = set()

            for dt, label in points:
                if (
                    dt < core["maghrib"]
                    or dt > core["fajr"]
                ):
                    continue

                key = (
                    round(dt.timestamp()),
                    label,
                )

                if key in seen:
                    continue

                seen.add(key)

                x = xpos(dt)

                canvas.create_oval(
                    x - 5,
                    y - 5,
                    x + 5,
                    y + 5,
                    fill=TEXT,
                    outline="",
                )

                canvas.create_text(
                    x,
                    y + 22,
                    text=label,
                    fill=MUTED,
                    font=("Segoe UI", 7, "bold"),
                )

                canvas.create_text(
                    x,
                    y + 38,
                    text=short_clock(dt),
                    fill=TEXT,
                    font=("Segoe UI", 7),
                )

            canvas.create_text(
                width / 2,
                196,
                text=(
                    f"Total sleep: "
                    f"{duration(model['total_sleep'])}"
                    f"     •     "
                    f"Prayer / Qiyam: "
                    f"{duration(model['qiyam'])}"
                ),
                fill=TEXT,
                font=("Segoe UI", 8, "bold"),
            )

        canvas.bind(
            "<Configure>",
            redraw,
        )

        redraw()

        tk.Label(
            card,
            text=(
                "Note: "
                + model["note"]
            ),
            bg=PANEL,
            fg=ACCENT,
            wraplength=1140,
            justify="left",
            font=("Segoe UI", 8),
        ).pack(
            anchor="w",
            padx=14,
            pady=(0, 11),
        )

    # ========================================================
    # COPY SUMMARY
    # ========================================================

    # ========================================================
    # PNG EXPORT
    # ========================================================

    def open_export_png_menu(self):
        if not PIL_AVAILABLE:
            messagebox.showerror(
                "PNG export",
                "Pillow is required for PNG export.\n\nInstall it with:\npython -m pip install pillow",
            )
            return

        popup = tk.Toplevel(self.root)
        popup.title("Export PNG")
        popup.geometry("390x225")
        popup.resizable(False, False)
        popup.configure(bg=PANEL)
        popup.transient(self.root)
        popup.grab_set()

        tk.Label(
            popup,
            text="Export as PNG",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 4))

        tk.Label(
            popup,
            text=(
                "Current window captures exactly what you see. Full report creates "
                "one long image containing the key calculations, prayer routines, "
                "all model timelines and the comparison numbers."
            ),
            bg=PANEL,
            fg=MUTED,
            wraplength=350,
            justify="left",
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=16, pady=(0, 12))

        tk.Button(
            popup,
            text="Export current window",
            command=lambda: (popup.destroy(), self.export_current_window_png()),
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=7,
        ).pack(fill="x", padx=16, pady=3)

        tk.Button(
            popup,
            text="Export full report",
            command=lambda: (popup.destroy(), self.export_full_report_png()),
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=7,
        ).pack(fill="x", padx=16, pady=3)

    def export_current_window_png(self):
        if not PIL_AVAILABLE:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            initialfile=f"dawud_planner_{self.selected_date.isoformat()}.png",
        )
        if not path:
            return

        self.root.update_idletasks()
        x = self.root.winfo_rootx()
        y = self.root.winfo_rooty()
        w = self.root.winfo_width()
        h = self.root.winfo_height()

        image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        image.save(path)
        messagebox.showinfo("PNG export", f"Saved:\n{path}")

    def export_full_report_png(self):
        if not self.result:
            messagebox.showinfo("PNG export", "Fetch prayer times first.")
            return
        if not PIL_AVAILABLE:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            initialfile=f"dawud_full_report_{self.selected_date.isoformat()}.png",
        )
        if not path:
            return

        r = self.result
        core = r["core"]
        models = r["models"]

        width = 1600
        model_h = 145
        height = 690 + model_h * len(models)
        image = Image.new("RGB", (width, height), BG)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        # Islamic star border.
        for cx in range(35, width - 20, 72):
            pts = []
            for i in range(16):
                angle = -math.pi / 2 + i * math.pi / 8
                radius = 15 if i % 2 == 0 else 6
                pts.append((
                    cx + math.cos(angle) * radius,
                    30 + math.sin(angle) * radius,
                ))
            draw.polygon(pts, outline=BORDER)

        y = 60
        draw.text((40, y), "Night of Dawud Planner", fill=TEXT, font=font)
        y += 24
        draw.text(
            (40, y),
            f"{r['city']}, {r['country']} • {r['date'].strftime('%A, %d %B %Y')}",
            fill=ACCENT,
            font=font,
        )
        y += 38

        glance = [
            ("Maghrib", clock(core["maghrib"])),
            ("Isha", clock(core["isha"])),
            ("Next Fajr", clock(core["fajr"])),
            ("Night", duration(core["night"])),
            ("1/2", duration(core["half"])),
            ("1/3", duration(core["third"])),
            ("1/6", duration(core["sixth"])),
            ("2/3 sleep", duration(core["two_thirds"])),
        ]

        x = 40
        for label, value in glance:
            draw.rounded_rectangle(
                (x, y, x + 175, y + 58),
                radius=8,
                fill=CARD,
                outline=BORDER,
            )
            draw.text((x + 10, y + 10), label, fill=MUTED, font=font)
            draw.text((x + 10, y + 31), value, fill=TEXT, font=font)
            x += 188
            if x + 175 > width - 40:
                x = 40
                y += 68
        y += 85

        draw.text((40, y), "Prayer routines", fill=ACCENT, font=font)
        y += 23

        for routine in (r["maghrib_routine"], r["isha_routine"]):
            if routine["place"] == "Mosque":
                text = (
                    f"{routine['name']}: adhan {clock(routine['start'])} | "
                    f"depart {clock(routine['departure'])} | iqama {clock(routine['iqama_time'])} | "
                    f"prayer {clock(routine['prayer_start'])}-{clock(routine['prayer_end'])} | "
                    f"home {clock(routine['end'])}"
                )
            else:
                text = (
                    f"{routine['name']}: Home | prayer "
                    f"{clock(routine['prayer_start'])}-{clock(routine['prayer_end'])}"
                )
            draw.text((40, y), text, fill=TEXT, font=font)
            y += 21

        y += 18
        draw.text((40, y), "All models", fill=ACCENT, font=font)
        y += 28

        tl_left = 270
        tl_right = width - 70
        total_sec = core["night"].total_seconds()
        color_map = {
            "sleep": SLEEP_COLOR,
            "prayer": PRAYER_COLOR,
            "awake": AWAKE_COLOR,
            "travel": TRAVEL_COLOR,
            "wait": WAIT_COLOR,
            "cycle": CYCLE_COLOR,
        }

        for model in models:
            draw.rounded_rectangle(
                (35, y, width - 35, y + model_h - 8),
                radius=10,
                fill=PANEL,
                outline=BORDER,
            )
            draw.text((50, y + 12), model["name"], fill=TEXT, font=font)
            draw.text(
                (50, y + 34),
                (
                    f"Sleep {duration(model['total_sleep'])} | "
                    f"Qiyam {duration(model['qiyam'])} | "
                    f"Awake {duration(non_sleep_time(core, model['total_sleep']))}"
                ),
                fill=MUTED,
                font=font,
            )

            ty = y + 88
            draw.line((tl_left, ty, tl_right, ty), fill=BORDER, width=5)

            for segment in model["segments"]:
                clipped = clip_segment(
                    segment["start"],
                    segment["end"],
                    core["maghrib"],
                    core["fajr"],
                )
                if not clipped:
                    continue

                start, end = clipped
                r1 = (start - core["maghrib"]).total_seconds() / total_sec
                r2 = (end - core["maghrib"]).total_seconds() / total_sec
                x1 = tl_left + r1 * (tl_right - tl_left)
                x2 = tl_left + r2 * (tl_right - tl_left)

                draw.line(
                    (x1, ty, x2, ty),
                    fill=color_map.get(segment["kind"], AWAKE_COLOR),
                    width=10,
                )

            y += model_h

        draw.text(
            (40, height - 55),
            "Sahih al-Bukhari 1131 — sleep 1/2, pray 1/3, sleep 1/6",
            fill=ACCENT,
            font=font,
        )

        image.save(path)
        messagebox.showinfo("PNG export", f"Saved full report:\n{path}")

    def copy_summary(self):
        if not self.result:
            return

        r = self.result
        c = r["core"]

        lines = [
            "Night of Dawud Planner",
            "",
            f"{r['city']}, {r['country']}",
            r["date"].strftime(
                "%A, %d %B %Y"
            ),
            "",
            f"Maghrib: {clock(c['maghrib'])}",
            f"Isha: {clock(c['isha'])}",
            f"Next Fajr: {clock(c['fajr'])}",
            (
                f"Maghrib → Isha: "
                f"{duration(c['isha'] - c['maghrib'])}"
            ),
            "",
            (
                f"Maghrib routine: "
                f"{clock(r['maghrib_routine']['start'])}"
                f" → "
                f"{clock(r['maghrib_routine']['end'])}"
            ),
            (
                f"Isha routine: "
                f"{clock(r['isha_routine']['start'])}"
                f" → "
                f"{clock(r['isha_routine']['end'])}"
            ),
            (
                f"Ready for bed: "
                f"{clock(r['practical']['ready_after_isha'])}"
            ),
            (
                f"Estimated asleep: "
                f"{clock(r['practical']['estimated_asleep'])}"
            ),
            "",
            f"Night length: {duration(c['night'])}",
            f"1/2: {duration(c['half'])}",
            f"1/3: {duration(c['third'])}",
            f"1/6: {duration(c['sixth'])}",
            "",
            "Models:",
        ]

        for model in r["models"]:
            lines.extend(
                [
                    "",
                    model["name"],
                    f"Wake: {clock(model['wake'])}",
                    (
                        f"Sleep again: "
                        f"{clock(model['sleep_again'])}"
                    ),
                    (
                        f"Total sleep: "
                        f"{duration(model['total_sleep'])}"
                    ),
                    (
                        f"Qiyam: "
                        f"{duration(model['qiyam'])}"
                    ),
                ]
            )

        self.root.clipboard_clear()

        self.root.clipboard_append(
            "\n".join(lines)
        )

        self.status.config(
            text="Night summary copied to clipboard.",
            fg=SUCCESS,
        )



# ============================================================
# V6 — COMPACT ONE-SCREEN UI
# ============================================================

class DawudPlannerAppV6(DawudPlannerApp):
    """
    Compact UI revision:
      * One main screen: glance + prayer routine + every model.
      * Advanced settings live inside a collapsible drawer.
      * Country/city remain visible in the drawer and support live type-ahead.
      * Comparison/custom/export open as focused tools instead of taking
        permanent vertical space.
    """

    def __init__(self, root):
        self.root = root

        root.title("Night of Dawud Planner")
        root.geometry("1500x950")
        root.minsize(1180, 760)
        root.configure(bg=BG)

        self.location_db = LocationDatabase()

        self.selected_date = date.today()
        self.week_start = (
            self.selected_date
            - timedelta(days=self.selected_date.weekday())
        )

        self.date_buttons = []
        self.result = None
        self.last_country = None
        self.fetch_generation = 0

        self.cards_per_row = tk.IntVar(value=3)

        self.custom_model_name = None
        self.custom_model_spec = None

        self.settings_open = False
        self.hadith_open = False

        self.setup_style()
        self.v6_build_header()
        self.v6_build_compact_toolbar()
        self.v6_build_settings_drawer()
        self.build_day_picker()
        self.build_fixed_prayer_strip()
        self.build_fixed_legend()

        self.main_content = tk.Frame(root, bg=BG)
        self.main_content.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=(2, 12),
        )

        self.content = self.main_content
        self.show_empty()

    # --------------------------------------------------------
    # Header / Islamic texture
    # --------------------------------------------------------

    def v6_build_header(self):
        header = tk.Canvas(
            self.root,
            height=62,
            bg=BG,
            highlightthickness=0,
        )

        header.pack(
            fill="x",
            padx=18,
            pady=(8, 0),
        )

        def redraw(event=None):
            header.delete("all")

            width = max(
                header.winfo_width(),
                900,
            )

            # Repeating subtle 8-point geometric stars.
            for x in range(36, width, 88):
                pts = []
                for i in range(16):
                    angle = -math.pi / 2 + i * math.pi / 8
                    radius = 14 if i % 2 == 0 else 6
                    pts.extend(
                        [
                            x + math.cos(angle) * radius,
                            18 + math.sin(angle) * radius,
                        ]
                    )

                header.create_polygon(
                    pts,
                    outline=BORDER,
                    fill="",
                    width=1,
                )

            header.create_line(
                15,
                54,
                width - 15,
                54,
                fill=ACCENT,
                width=1,
            )

            header.create_text(
                22,
                16,
                text="Night of Dawud",
                anchor="w",
                fill=TEXT,
                font=("Segoe UI", 20, "bold"),
            )


        header.bind(
            "<Configure>",
            redraw,
        )

        redraw()

    # --------------------------------------------------------
    # Always-visible compact toolbar
    # --------------------------------------------------------

    def v6_build_compact_toolbar(self):
        bar = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        bar.pack(
            fill="x",
            padx=18,
            pady=(3, 4),
        )

        left = tk.Frame(
            bar,
            bg=PANEL,
        )

        left.pack(
            side="left",
            fill="x",
            expand=True,
            padx=7,
            pady=6,
        )

        self.settings_toggle_button = tk.Button(
            left,
            text="⚙ Settings ▾",
            command=self.v6_toggle_settings,
            bg=CARD_2,
            fg=ACCENT,
            activebackground=CARD,
            activeforeground=ACCENT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=11,
            pady=5,
        )

        self.settings_toggle_button.pack(
            side="left",
        )

        self.v6_location_summary = tk.Label(
            left,
            text="Egypt • Cairo",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 8, "bold"),
        )

        self.v6_location_summary.pack(
            side="left",
            padx=(10, 0),
        )

        self.v6_date_summary = tk.Label(
            left,
            text=self.selected_date.strftime("%A, %d %B %Y"),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        )

        self.v6_date_summary.pack(
            side="left",
            padx=(10, 0),
        )

        right = tk.Frame(
            bar,
            bg=PANEL,
        )

        right.pack(
            side="right",
            padx=7,
            pady=6,
        )

        self.v6_small_button(
            right,
            "Hadith",
            self.v6_toggle_hadith,
        ).pack(
            side="left",
            padx=2,
        )

        self.v6_small_button(
            right,
            "Prayer methods",
            self.v10_open_prayer_methods,
        ).pack(
            side="left",
            padx=2,
        )

        self.v6_small_button(
            right,
            "Custom Model Maker",
            self.open_custom_model_builder,
        ).pack(
            side="left",
            padx=2,
        )

        self.v6_small_button(
            right,
            "Compare with other countries",
            self.open_location_comparison,
        ).pack(
            side="left",
            padx=2,
        )

        self.v6_small_button(
            right,
            "Export PNG",
            self.open_export_png_menu,
            accent=True,
        ).pack(
            side="left",
            padx=2,
        )

        self.hadith_drawer = tk.Frame(
            self.root,
            bg=CARD_2,
            highlightbackground=ACCENT_DARK,
            highlightthickness=1,
        )

        self.hadith_label = tk.Label(
            self.hadith_drawer,
            text=(
                HADITH_TEXT
                + "\nSahih al-Bukhari 1131"
            ),
            bg=CARD_2,
            fg=TEXT,
            wraplength=1350,
            justify="left",
            font=("Segoe UI", 8),
        )

        self.hadith_label.pack(
            fill="x",
            padx=12,
            pady=8,
        )

    def v6_small_button(
        self,
        parent,
        text,
        command,
        accent=False,
    ):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=(ACCENT if accent else CARD),
            fg=("#111111" if accent else TEXT),
            activebackground=(ACCENT if accent else CARD_2),
            activeforeground=("#111111" if accent else TEXT),
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=9,
            pady=5,
        )

    def v6_toggle_hadith(self):
        self.hadith_open = not self.hadith_open

        if self.hadith_open:
            self.hadith_drawer.pack(
                fill="x",
                padx=18,
                pady=(0, 4),
                before=self.day_picker_container,
            )
        else:
            self.hadith_drawer.pack_forget()

    # --------------------------------------------------------
    # Collapsible settings drawer
    # --------------------------------------------------------

    def v6_build_settings_drawer(self):
        self.settings_drawer = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        # Drawer is intentionally NOT packed initially.

        row = tk.Frame(
            self.settings_drawer,
            bg=PANEL,
        )

        row.pack(
            fill="x",
            padx=8,
            pady=(7, 4),
        )

        for col in range(7):
            row.grid_columnconfigure(
                col,
                weight=1,
            )

        # Country
        wrapper = self.v6_setting_cell(
            row,
            "Country / territory",
            0,
        )

        self.country_combo = SearchableCombobox(
            wrapper,
            values=self.location_db.country_names,
            width=21,
        )

        self.country_combo.pack(
            fill="x",
        )

        self.country_combo.set(
            "Egypt"
        )

        self.country_combo.bind(
            "<<ComboboxSelected>>",
            self.country_changed,
        )

        self.country_combo.bind(
            "<FocusOut>",
            self.country_changed,
        )

        # City
        wrapper = self.v6_setting_cell(
            row,
            "City",
            1,
        )

        self.city_combo = SearchableCombobox(
            wrapper,
            values=[],
            width=21,
        )

        self.city_combo.pack(
            fill="x",
        )

        self.load_cities(
            "Egypt",
            preserve_city=False,
        )

        if "Cairo" in self.city_combo.all_values:
            self.city_combo.set(
                "Cairo"
            )

        # Method
        wrapper = self.v6_setting_cell(
            row,
            "Prayer method",
            2,
        )

        self.method_map = {}
        method_values = []

        for method_id, data in METHODS.items():
            label = (
                f"{data['short']} — "
                f"{data['name']}"
            )

            self.method_map[
                label
            ] = method_id

            method_values.append(
                label
            )

        self.method_combo = ttk.Combobox(
            wrapper,
            values=method_values,
            state="readonly",
            width=26,
        )

        self.method_combo.pack(
            fill="x",
        )

        self.method_combo.set(
            next(
                label
                for label, method_id in self.method_map.items()
                if method_id == DEFAULT_METHOD
            )
        )

        # Travel
        wrapper = self.v6_setting_cell(
            row,
            "Travel one way",
            3,
        )

        self.travel_minutes = self.v6_spin(
            wrapper,
            0,
            90,
            "10",
        )

        # Sleep
        wrapper = self.v6_setting_cell(
            row,
            "Sleep",
            4,
        )

        sleep_line = tk.Frame(
            wrapper,
            bg=PANEL,
        )

        sleep_line.pack(
            fill="x",
        )

        tk.Label(
            sleep_line,
            text="latency",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
        )

        self.sleep_latency = self.v6_spin(
            sleep_line,
            0,
            60,
            "10",
            pack_side=True,
        )

        tk.Label(
            sleep_line,
            text=" cycle",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
        )

        self.sleep_cycle = self.v6_spin(
            sleep_line,
            60,
            120,
            "90",
            increment=5,
            pack_side=True,
        )

        # Maghrib
        wrapper = self.v6_setting_cell(
            row,
            "Maghrib routine",
            5,
        )

        (
            self.maghrib_place,
            self.maghrib_duration,
            self.maghrib_iqama,
        ) = self.v6_prayer_controls(
            wrapper,
            "10",
            "10",
        )

        # Isha
        wrapper = self.v6_setting_cell(
            row,
            "Isha routine",
            6,
        )

        (
            self.isha_place,
            self.isha_duration,
            self.isha_iqama,
        ) = self.v6_prayer_controls(
            wrapper,
            "10",
            "15",
        )

        bottom = tk.Frame(
            self.settings_drawer,
            bg=PANEL,
        )

        bottom.pack(
            fill="x",
            padx=8,
            pady=(0, 7),
        )

        self.status = tk.Label(
            bottom,
            text="Ready.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        )

        self.status.pack(
            side="left",
        )

        self.fetch_button = self.v6_small_button(
            bottom,
            "Fetch prayer times",
            self.start_fetch,
            accent=True,
        )

        self.fetch_button.pack(
            side="right",
        )

        self.recalc_button = self.v6_small_button(
            bottom,
            "Recalculate",
            self.recalculate_plan,
        )

        self.recalc_button.config(
            state="disabled"
        )

        self.recalc_button.pack(
            side="right",
            padx=(0, 5),
        )

    def v6_setting_cell(
        self,
        parent,
        title,
        column,
    ):
        frame = tk.Frame(
            parent,
            bg=PANEL,
        )

        frame.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=4,
        )

        tk.Label(
            frame,
            text=title,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7, "bold"),
        ).pack(
            anchor="w",
            pady=(0, 2),
        )

        return frame

    def v6_spin(
        self,
        parent,
        low,
        high,
        initial,
        increment=1,
        pack_side=False,
    ):
        widget = tk.Spinbox(
            parent,
            from_=low,
            to=high,
            increment=increment,
            width=4,
            bg=CARD,
            fg=TEXT,
            buttonbackground=CARD,
            insertbackground=TEXT,
            relief="flat",
        )

        widget.delete(
            0,
            tk.END,
        )

        widget.insert(
            0,
            initial,
        )

        if pack_side:
            widget.pack(
                side="left",
                padx=3,
            )
        else:
            widget.pack(
                anchor="w",
            )

        return widget

    def v6_prayer_controls(
        self,
        parent,
        prayer_default,
        iqama_default,
    ):
        """
        Clear compact controls:
          [Home/Mosque]  Prayer [10] min  Iqama +[15] min

        Iqama means minutes after adhan.
        """

        line = tk.Frame(
            parent,
            bg=PANEL,
        )

        line.pack(
            fill="x",
        )

        place = ttk.Combobox(
            line,
            values=("Home", "Mosque"),
            state="readonly",
            width=6,
        )

        place.set(
            "Home"
        )

        place.pack(
            side="left",
            padx=(0, 4),
        )

        tk.Label(
            line,
            text="Prayer",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
        )

        prayer = self.v6_spin(
            line,
            5,
            15,
            prayer_default,
            pack_side=True,
        )

        tk.Label(
            line,
            text="min",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
            padx=(0, 5),
        )

        tk.Label(
            line,
            text="Iqama +",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
        )

        iqama = self.v6_spin(
            line,
            0,
            60,
            iqama_default,
            pack_side=True,
        )

        tk.Label(
            line,
            text="min",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
        )

        hint = tk.Label(
            parent,
            text="Home: iqama setting is not used",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 6),
        )

        hint.pack(
            anchor="w",
            pady=(2, 0),
        )

        def update_iqama_state(
            event=None,
        ):
            if place.get() == "Home":
                iqama.config(
                    state="disabled"
                )

                hint.config(
                    text="Home: iqama setting is not used"
                )
            else:
                iqama.config(
                    state="normal"
                )

                hint.config(
                    text="Mosque: iqama = minutes after adhan"
                )

        place.bind(
            "<<ComboboxSelected>>",
            update_iqama_state,
        )

        update_iqama_state()

        return place, prayer, iqama

    def v6_toggle_settings(self):
        self.settings_open = not self.settings_open

        if self.settings_open:
            self.settings_drawer.pack(
                fill="x",
                padx=18,
                pady=(0, 4),
                before=self.day_picker_container,
            )

            self.settings_toggle_button.config(
                text="⚙ Settings ▴"
            )

        else:
            self.settings_drawer.pack_forget()

            self.settings_toggle_button.config(
                text="⚙ Settings ▾"
            )

    # --------------------------------------------------------
    # Compact week/date picker
    # --------------------------------------------------------

    def build_day_picker(self):
        self.day_picker_container = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        self.day_picker_container.pack(
            fill="x",
            padx=18,
            pady=(0, 4),
        )

        bar = tk.Frame(
            self.day_picker_container,
            bg=PANEL,
        )

        bar.pack(
            fill="x",
            padx=6,
            pady=4,
        )

        self.v6_small_button(
            bar,
            "‹",
            lambda: self.shift_week(-7),
        ).pack(
            side="left",
        )

        self.days_holder = tk.Frame(
            bar,
            bg=PANEL,
        )

        self.days_holder.pack(
            side="left",
            fill="x",
            expand=True,
            padx=3,
        )

        self.v6_small_button(
            bar,
            "›",
            lambda: self.shift_week(7),
        ).pack(
            side="left",
        )

        self.v6_small_button(
            bar,
            "Calendar",
            self.open_month_calendar,
        ).pack(
            side="left",
            padx=(4, 0),
        )

        self.rebuild_week_buttons()

    def rebuild_week_buttons(self):
        for child in self.days_holder.winfo_children():
            child.destroy()

        self.date_buttons = []

        for index in range(7):
            day = (
                self.week_start
                + timedelta(days=index)
            )

            title = (
                "Today"
                if day == date.today()
                else day.strftime("%a")
            )

            button = tk.Button(
                self.days_holder,
                text=(
                    f"{title}  "
                    f"{day.strftime('%d %b')}"
                ),
                command=lambda d=day: self.select_date(
                    d,
                    auto_fetch=True,
                ),
                relief="flat",
                bd=0,
                cursor="hand2",
                font=("Segoe UI", 7, "bold"),
                padx=5,
                pady=4,
            )

            button.pack(
                side="left",
                fill="x",
                expand=True,
                padx=2,
            )

            self.date_buttons.append(
                (day, button)
            )

        self.update_day_buttons()

    def update_day_buttons(self):
        for day, button in self.date_buttons:
            if day == self.selected_date:
                button.config(
                    bg=ACCENT,
                    fg="#111111",
                )
            elif day == date.today():
                button.config(
                    bg=CARD_2,
                    fg=TEXT,
                )
            else:
                button.config(
                    bg=CARD,
                    fg=TEXT,
                )

    def shift_week(self, days):
        self.week_start += timedelta(
            days=days
        )

        self.rebuild_week_buttons()

    def go_today(self):
        self.select_date(
            date.today(),
            auto_fetch=True,
        )

    def select_date(
        self,
        selected,
        auto_fetch=True,
    ):
        self.selected_date = selected

        self.week_start = (
            selected
            - timedelta(
                days=selected.weekday()
            )
        )

        self.v6_date_summary.config(
            text=selected.strftime(
                "%A, %d %B %Y"
            )
        )

        self.rebuild_week_buttons()
        self.clear_fixed_prayer_times()

        if auto_fetch:
            self.start_fetch(
                auto=True
            )

    # --------------------------------------------------------
    # Compact prayer strip
    # --------------------------------------------------------

    def build_fixed_prayer_strip(self):
        self.prayer_strip = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        self.prayer_strip.pack(
            fill="x",
            padx=18,
            pady=(0, 3),
        )

        self.fixed_prayer_date = tk.Label(
            self.prayer_strip,
            text=self.selected_date.strftime(
                "%d %B"
            ),
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 7, "bold"),
        )

        self.fixed_prayer_date.pack(
            side="left",
            padx=(7, 5),
        )

        self.fixed_prayer_labels = {}

        for name in (
            "Fajr",
            "Sunrise",
            "Dhuhr",
            "Asr",
            "Maghrib",
            "Isha",
            "Sleep-ready",
        ):
            cell = tk.Frame(
                self.prayer_strip,
                bg=CARD,
            )

            cell.pack(
                side="left",
                fill="x",
                expand=True,
                padx=2,
                pady=3,
            )

            tk.Label(
                cell,
                text=name,
                bg=CARD,
                fg=MUTED,
                font=("Segoe UI", 6),
            ).pack(
                side="left",
                padx=(5, 2),
            )

            label = tk.Label(
                cell,
                text="--",
                bg=CARD,
                fg=(
                    ACCENT
                    if name == "Sleep-ready"
                    else TEXT
                ),
                font=("Segoe UI", 8, "bold"),
            )

            label.pack(
                side="left",
                padx=(0, 5),
            )

            self.fixed_prayer_labels[
                name
            ] = label

    def clear_fixed_prayer_times(self):
        self.fixed_prayer_date.config(
            text=self.selected_date.strftime(
                "%d %B"
            )
        )

        for label in self.fixed_prayer_labels.values():
            label.config(
                text="…"
            )

    def update_fixed_prayer_times(self):
        if not self.result:
            return

        r = self.result
        timings = r["api"][
            "today_data"
        ]["timings"]

        self.fixed_prayer_date.config(
            text=r["date"].strftime(
                "%d %B"
            )
        )

        for name in (
            "Fajr",
            "Sunrise",
            "Dhuhr",
            "Asr",
            "Maghrib",
            "Isha",
        ):
            dt = prayer_datetime(
                r["date"],
                timings[name],
            )

            self.fixed_prayer_labels[
                name
            ].config(
                text=clock(dt)
            )

        self.fixed_prayer_labels[
            "Sleep-ready"
        ].config(
            text=clock(
                r["practical"][
                    "ready_after_isha"
                ]
            )
        )

        self.v6_location_summary.config(
            text=(
                f"{r['country']} • "
                f"{r['city']}"
            )
        )

    # --------------------------------------------------------
    # Compact legend
    # --------------------------------------------------------

    def build_fixed_legend(self):
        self.legend_bar = tk.Frame(
            self.root,
            bg=BG,
        )

        self.legend_bar.pack(
            fill="x",
            padx=22,
            pady=(0, 2),
        )

        for label, color in (
            ("Sleep", SLEEP_COLOR),
            ("Qiyam", PRAYER_COLOR),
            ("Awake", AWAKE_COLOR),
            ("Travel", TRAVEL_COLOR),
            ("Iqama wait", WAIT_COLOR),
            ("Cycle", CYCLE_COLOR),
        ):
            tk.Label(
                self.legend_bar,
                text=f"■ {label}",
                bg=BG,
                fg=color,
                font=("Segoe UI", 7),
            ).pack(
                side="left",
                padx=(0, 9),
            )

    # --------------------------------------------------------
    # Main one-screen rendering
    # --------------------------------------------------------

    def show_empty(self):
        for child in self.main_content.winfo_children():
            child.destroy()

        card = tk.Frame(
            self.main_content,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        card.pack(
            fill="both",
            expand=True,
            pady=5,
        )

        tk.Label(
            card,
            text="Select a location and fetch prayer times",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(
            pady=(110, 8),
        )

        tk.Label(
            card,
            text=(
                "Open Settings only when you need to change location, "
                "prayer routine, iqama, travel or sleep assumptions."
            ),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack()

    def render_dashboard(self):
        for child in self.main_content.winfo_children():
            child.destroy()

        r = self.result
        core = r["core"]
        models = r["models"]

        # -----------------------------
        # Glance row
        # -----------------------------
        glance = tk.Frame(
            self.main_content,
            bg=BG,
        )

        glance.pack(
            fill="x",
            pady=(2, 4),
        )

        glance_items = [
            (
                "Night",
                duration(core["night"]),
            ),
            (
                "1/2",
                duration(core["half"]),
            ),
            (
                "1/3",
                duration(core["third"]),
            ),
            (
                "1/6",
                duration(core["sixth"]),
            ),
            (
                "Half boundary",
                clock(core["wake"]),
            ),
            (
                "Final sixth",
                clock(core["final_sixth"]),
            ),
            (
                "Isha ready",
                clock(
                    r["practical"][
                        "ready_after_isha"
                    ]
                ),
            ),
            (
                "Sleep-ready",
                clock(
                    r["practical"][
                        "estimated_asleep"
                    ]
                ),
            ),
        ]

        for index, (
            title,
            value,
        ) in enumerate(
            glance_items
        ):
            glance.grid_columnconfigure(
                index,
                weight=1,
                uniform="glance",
            )

            card = tk.Frame(
                glance,
                bg=CARD,
                highlightbackground=BORDER,
                highlightthickness=1,
            )

            card.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=2,
            )

            tk.Label(
                card,
                text=title,
                bg=CARD,
                fg=MUTED,
                font=("Segoe UI", 6),
            ).pack(
                pady=(5, 0),
            )

            tk.Label(
                card,
                text=value,
                bg=CARD,
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
            ).pack(
                pady=(0, 5),
            )

        # -----------------------------
        # Prayer routine strip
        # -----------------------------
        routine = tk.Frame(
            self.main_content,
            bg=CARD_2,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        routine.pack(
            fill="x",
            pady=(0, 5),
        )

        routine_text = (
            f"Night intervals   •   "
            f"Maghrib → Isha: {duration(core['isha'] - core['maghrib'])}"
            f"   •   Isha → Fajr: {duration(core['fajr'] - core['isha'])}"
            f"   •   Maghrib → Fajr: {duration(core['night'])}"
        )

        tk.Label(
            routine,
            text=routine_text,
            bg=CARD_2,
            fg=TEXT,
            font=("Segoe UI", 7),
            anchor="w",
        ).pack(
            fill="x",
            padx=8,
            pady=5,
        )

        # -----------------------------
        # Models header
        # -----------------------------
        model_header = tk.Frame(
            self.main_content,
            bg=BG,
        )

        model_header.pack(
            fill="x",
            pady=(0, 2),
        )

        tk.Label(
            model_header,
            text="All models",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
        ).pack(
            side="left",
        )

        tk.Label(
            model_header,
            text="Everything stays on this screen • hover timeline segments for details",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
            padx=(7, 0),
        )

        self.v6_small_button(
            model_header,
            "Detailed comparison",
            self.v6_open_comparison_popup,
        ).pack(
            side="right",
        )

        # -----------------------------
        # Model grid: 3x2 built-ins, 4x2 if custom exists.
        # -----------------------------
        grid = tk.Frame(
            self.main_content,
            bg=BG,
        )

        grid.pack(
            fill="both",
            expand=True,
        )

        columns = (
            3
            if len(models) <= 6
            else 4
        )

        rows = math.ceil(
            len(models)
            / columns
        )

        for col in range(columns):
            grid.grid_columnconfigure(
                col,
                weight=1,
                uniform="models",
            )

        for row_index in range(rows):
            grid.grid_rowconfigure(
                row_index,
                weight=1,
                minsize=190,
                uniform="model_rows",
            )

        for index, model in enumerate(
            models
        ):
            row_index = (
                index // columns
            )

            col = (
                index % columns
            )

            card = tk.Frame(
                grid,
                bg=PANEL,
                highlightbackground=BORDER,
                highlightthickness=1,
            )

            card.grid(
                row=row_index,
                column=col,
                sticky="nsew",
                padx=3,
                pady=3,
            )

            self.v6_draw_model_card(
                card,
                core,
                model,
            )

    def v6_draw_model_card(
        self,
        parent,
        core,
        model,
        focused=False,
    ):
        """
        Responsive two-row timeline.

        Normal cards expand to use the remaining window height.
        Press Focus (or double-click) to open a zoomed version.
        """

        header = tk.Frame(
            parent,
            bg=PANEL,
        )

        header.pack(
            fill="x",
            padx=(8, 6),
            pady=(6, 0),
        )

        title_row = tk.Frame(
            header,
            bg=PANEL,
        )

        title_row.pack(
            fill="x",
        )

        tk.Label(
            title_row,
            text=model["name"],
            bg=PANEL,
            fg=TEXT,
            anchor="w",
            justify="left",
            font=(
                "Segoe UI",
                14 if focused else 9,
                "bold",
            ),
        ).pack(
            side="left",
            fill="x",
            expand=True,
        )

        if not focused:
            tk.Button(
                title_row,
                text="⤢ Focus",
                command=lambda m=model: self.v6_open_model_focus(
                    m
                ),
                bg=CARD_2,
                fg=ACCENT,
                activebackground=CARD,
                activeforeground=ACCENT,
                relief="flat",
                cursor="hand2",
                font=("Segoe UI", 6, "bold"),
                padx=6,
                pady=2,
            ).pack(
                side="right",
            )

        tk.Label(
            header,
            text=(
                f"Model night {duration(model_night_length(model, core))}"
                f"   •   Sleep {duration(model['total_sleep'])}"
                f"   •   Qiyam {duration(model['qiyam'])}"
                f"   •   Post-Isha awake {duration(post_isha_awake_time(model, core))}"
            ),
            bg=PANEL,
            fg=ACCENT,
            anchor="w",
            justify="left",
            font=(
                "Segoe UI",
                10 if focused else 7,
            ),
        ).pack(
            fill="x",
            pady=(2, 0),
        )

        if focused:
            tk.Label(
                header,
                text=model.get(
                    "description",
                    "",
                ),
                bg=PANEL,
                fg=MUTED,
                anchor="w",
                justify="left",
                wraplength=1050,
                font=("Segoe UI", 9),
            ).pack(
                fill="x",
                pady=(4, 0),
            )

        canvas = tk.Canvas(
            parent,
            bg=PANEL,
            highlightthickness=0,
            height=(
                380
                if focused
                else 145
            ),
        )

        canvas.pack(
            fill="both",
            expand=True,
            padx=5,
            pady=(2, 4),
        )

        color_map = {
            "sleep": SLEEP_COLOR,
            "prayer": PRAYER_COLOR,
            "awake": AWAKE_COLOR,
            "travel": TRAVEL_COLOR,
            "wait": WAIT_COLOR,
            "cycle": CYCLE_COLOR,
        }

        def ratio(dt):
            total = core["night"].total_seconds()

            if total <= 0:
                return 0.0

            return max(
                0.0,
                min(
                    1.0,
                    (dt - core["maghrib"]).total_seconds()
                    / total,
                ),
            )

        def redraw(event=None):
            canvas.delete("all")

            width = max(
                canvas.winfo_width(),
                300,
            )

            height = max(
                canvas.winfo_height(),
                130,
            )

            left = (
                45
                if focused
                else 20
            )

            right = (
                width - 45
                if focused
                else width - 20
            )

            # Use the vertical space instead of leaving a large blank block.
            top_y = max(
                42,
                height * 0.30,
            )

            bottom_y = min(
                height - 45,
                height * 0.69,
            )

            if bottom_y - top_y < 46:
                bottom_y = (
                    top_y + 46
                )

            usable = right - left

            def point_for_ratio(value):
                value = max(
                    0.0,
                    min(
                        1.0,
                        value,
                    ),
                )

                if value <= 0.5:
                    local = (
                        value / 0.5
                    )

                    return (
                        left + local * usable,
                        top_y,
                    )

                local = (
                    value - 0.5
                ) / 0.5

                return (
                    right - local * usable,
                    bottom_y,
                )

            canvas.create_line(
                left,
                top_y,
                right,
                top_y,
                fill=BORDER,
                width=(
                    6
                    if focused
                    else 4
                ),
            )

            canvas.create_line(
                right,
                top_y,
                right,
                bottom_y,
                fill=BORDER,
                width=(
                    6
                    if focused
                    else 4
                ),
            )

            canvas.create_line(
                right,
                bottom_y,
                left,
                bottom_y,
                fill=BORDER,
                width=(
                    6
                    if focused
                    else 4
                ),
            )

            def draw_piece(
                start_ratio,
                end_ratio,
                segment,
                piece_start,
                piece_end,
                row_name,
            ):
                if row_name == "top":
                    x1 = (
                        left
                        + (
                            start_ratio
                            / 0.5
                        ) * usable
                    )

                    x2 = (
                        left
                        + (
                            end_ratio
                            / 0.5
                        ) * usable
                    )

                    y1 = y2 = top_y

                else:
                    x1 = (
                        right
                        - (
                            (
                                start_ratio
                                - 0.5
                            )
                            / 0.5
                        ) * usable
                    )

                    x2 = (
                        right
                        - (
                            (
                                end_ratio
                                - 0.5
                            )
                            / 0.5
                        ) * usable
                    )

                    y1 = y2 = bottom_y

                color = color_map.get(
                    segment["kind"],
                    AWAKE_COLOR,
                )

                line_id = canvas.create_line(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=color,
                    width=(
                        16
                        if focused
                        else 11
                    ),
                    capstyle=tk.ROUND,
                )

                self.bind_segment_tooltip(
                    canvas,
                    line_id,
                    segment["name"],
                    piece_start,
                    piece_end,
                    segment["kind"],
                )

                piece_width = abs(
                    x2 - x1
                )

                min_label_width = (
                    80
                    if focused
                    else 54
                )

                if piece_width >= min_label_width:
                    label_y = (
                        y1
                        - (
                            33
                            if focused
                            else 18
                        )
                        if row_name == "top"
                        else y1
                        + (
                            33
                            if focused
                            else 18
                        )
                    )

                    canvas.create_text(
                        (
                            x1 + x2
                        ) / 2,
                        label_y,
                        text=(
                            f"{segment['name']}\n"
                            f"{duration(piece_end - piece_start)}"
                        ),
                        fill=color,
                        justify="center",
                        width=max(
                            min_label_width,
                            int(
                                piece_width
                                - 8
                            ),
                        ),
                        font=(
                            "Segoe UI",
                            10 if focused else 6,
                            "bold",
                        ),
                    )

            for segment in model[
                "segments"
            ]:
                clipped = clip_segment(
                    segment["start"],
                    segment["end"],
                    core["maghrib"],
                    core["fajr"],
                )

                if not clipped:
                    continue

                start_dt, end_dt = clipped

                r1 = ratio(
                    start_dt
                )

                r2 = ratio(
                    end_dt
                )

                if r2 <= 0.5:
                    draw_piece(
                        r1,
                        r2,
                        segment,
                        start_dt,
                        end_dt,
                        "top",
                    )

                elif r1 >= 0.5:
                    draw_piece(
                        r1,
                        r2,
                        segment,
                        start_dt,
                        end_dt,
                        "bottom",
                    )

                else:
                    half_dt = core[
                        "wake"
                    ]

                    draw_piece(
                        r1,
                        0.5,
                        segment,
                        start_dt,
                        half_dt,
                        "top",
                    )

                    color = color_map.get(
                        segment["kind"],
                        AWAKE_COLOR,
                    )

                    turn_id = canvas.create_line(
                        right,
                        top_y,
                        right,
                        bottom_y,
                        fill=color,
                        width=(
                            16
                            if focused
                            else 11
                        ),
                    )

                    self.bind_segment_tooltip(
                        canvas,
                        turn_id,
                        segment["name"],
                        start_dt,
                        end_dt,
                        segment["kind"],
                    )

                    draw_piece(
                        0.5,
                        r2,
                        segment,
                        half_dt,
                        end_dt,
                        "bottom",
                    )

            marker_font = (
                ("Segoe UI", 9, "bold")
                if focused
                else ("Segoe UI", 6, "bold")
            )

            small_font = (
                ("Segoe UI", 8)
                if focused
                else ("Segoe UI", 6)
            )

            radius = (
                7
                if focused
                else 5
            )

            # Isha
            ir = ratio(
                core["isha"]
            )

            ix, iy = point_for_ratio(
                ir
            )

            canvas.create_oval(
                ix - radius,
                iy - radius,
                ix + radius,
                iy + radius,
                fill=ACCENT,
                outline="",
            )

            canvas.create_text(
                ix,
                (
                    iy + (
                        20
                        if focused
                        else 14
                    )
                    if ir <= 0.5
                    else iy - (
                        20
                        if focused
                        else 14
                    )
                ),
                text=(
                    f"Isha {short_clock(core['isha'])}"
                ),
                fill=ACCENT,
                font=marker_font,
            )

            # Maghrib / half-night / Fajr.
            for (
                rr,
                dt,
                label,
            ) in (
                (
                    0.0,
                    core["maghrib"],
                    "Maghrib",
                ),
                (
                    0.5,
                    core["wake"],
                    "½ night",
                ),
                (
                    1.0,
                    core["fajr"],
                    "Fajr",
                ),
            ):
                mx, my = point_for_ratio(
                    rr
                )

                canvas.create_oval(
                    mx - radius,
                    my - radius,
                    mx + radius,
                    my + radius,
                    fill=TEXT,
                    outline="",
                )

                if rr == 0.5:
                    canvas.create_text(
                        mx - 4,
                        (
                            top_y
                            + bottom_y
                        ) / 2,
                        text=(
                            f"{label}\n"
                            f"{short_clock(dt)}"
                        ),
                        fill=MUTED,
                        anchor="e",
                        justify="right",
                        font=small_font,
                    )

                elif rr == 0.0:
                    canvas.create_text(
                        mx,
                        my + (
                            26
                            if focused
                            else 15
                        ),
                        text=(
                            f"{label}\n"
                            f"{short_clock(dt)}"
                        ),
                        fill=MUTED,
                        anchor="w",
                        justify="left",
                        font=small_font,
                    )

                else:
                    canvas.create_text(
                        mx,
                        my - (
                            26
                            if focused
                            else 15
                        ),
                        text=(
                            f"{label}\n"
                            f"{short_clock(dt)}"
                        ),
                        fill=MUTED,
                        anchor="w",
                        justify="left",
                        font=small_font,
                    )

            # Model-specific wake / sleep-again points.
            for dt, label in (
                (
                    model["wake"],
                    "Wake",
                ),
                (
                    model["sleep_again"],
                    "Sleep again",
                ),
            ):
                if not (
                    core["maghrib"]
                    <= dt
                    <= core["fajr"]
                ):
                    continue

                rr = ratio(
                    dt
                )

                mx, my = point_for_ratio(
                    rr
                )

                canvas.create_oval(
                    mx - radius,
                    my - radius,
                    mx + radius,
                    my + radius,
                    fill=TEXT,
                    outline="",
                )

                label_y = (
                    my + (
                        42
                        if focused
                        else 29
                    )
                    if rr <= 0.5
                    else my - (
                        42
                        if focused
                        else 29
                    )
                )

                canvas.create_text(
                    mx,
                    label_y,
                    text=(
                        f"{label}\n"
                        f"{short_clock(dt)}"
                    ),
                    fill=TEXT,
                    justify="center",
                    font=small_font,
                )

            if focused:
                canvas.create_text(
                    width / 2,
                    height - 16,
                    text=(
                        f"Model night {duration(model_night_length(model, core))}"
                        f"   •   Sleep {duration(model['total_sleep'])}"
                        f"   •   Qiyam {duration(model['qiyam'])}"
                        f"   •   Post-Isha awake {duration(post_isha_awake_time(model, core))}"
                    ),
                    fill=TEXT,
                    font=("Segoe UI", 9, "bold"),
                )

        canvas.bind(
            "<Configure>",
            redraw,
        )

        if not focused:
            canvas.bind(
                "<Double-Button-1>",
                lambda event, m=model: self.v6_open_model_focus(
                    m
                ),
            )

        redraw()

        if focused and model.get(
            "note"
        ):
            tk.Label(
                parent,
                text=(
                    "Note: "
                    + model["note"]
                ),
                bg=PANEL,
                fg=ACCENT,
                wraplength=1080,
                justify="left",
                font=("Segoe UI", 8),
            ).pack(
                anchor="w",
                padx=10,
                pady=(0, 10),
            )

    def v6_open_model_focus(
        self,
        model,
    ):
        if not self.result:
            return

        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            model["name"]
        )

        popup.geometry(
            "1180x650"
        )

        popup.minsize(
            900,
            520,
        )

        popup.configure(
            bg=BG
        )

        popup.transient(
            self.root
        )

        outer = tk.Frame(
            popup,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        outer.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=14,
        )

        self.v6_draw_model_card(
            outer,
            self.result["core"],
            model,
            focused=True,
        )

    # --------------------------------------------------------
    # Comparison popup instead of a permanent tab
    # --------------------------------------------------------

    def v6_open_comparison_popup(self):
        if not self.result:
            return

        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            "Detailed model comparison"
        )

        popup.geometry(
            "1160x760"
        )

        popup.minsize(
            950,
            650,
        )

        popup.configure(
            bg=BG
        )

        popup.transient(
            self.root
        )

        tk.Label(
            popup,
            text="Detailed model comparison",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 14, "bold"),
        ).pack(
            anchor="w",
            padx=12,
            pady=(12, 2),
        )

        tk.Label(
            popup,
            text=(
                "Each bar is the complete Maghrib→Fajr night. "
                "Sleep + Qiyam + other awake time = the whole night."
            ),
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            anchor="w",
            padx=12,
            pady=(0, 6),
        )

        chart_frame = tk.Frame(
            popup,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        chart_frame.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=(0, 8),
        )

        self.v6_draw_model_comparison_graph(
            chart_frame,
            self.result["models"],
            self.result["core"],
        )

        table_frame = tk.Frame(
            popup,
            bg=BG,
        )

        table_frame.pack(
            fill="x",
            padx=10,
            pady=(0, 10),
        )

        self.draw_model_comparison_table(
            self.result["models"],
            self.result["core"],
            parent=table_frame,
        )

    def v6_draw_model_comparison_graph(
        self,
        parent,
        models,
        core,
    ):
        canvas = tk.Canvas(
            parent,
            bg=PANEL,
            highlightthickness=0,
            height=330,
        )

        canvas.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        def redraw(event=None):
            canvas.delete(
                "all"
            )

            width = max(
                canvas.winfo_width(),
                800,
            )

            height = max(
                canvas.winfo_height(),
                300,
            )

            # Legend
            legend_y = 16
            legend_x = 175

            for label, color in (
                (
                    "Sleep",
                    SLEEP_COLOR,
                ),
                (
                    "Qiyam",
                    PRAYER_COLOR,
                ),
                (
                    "Other non-sleep",
                    AWAKE_COLOR,
                ),
            ):
                canvas.create_rectangle(
                    legend_x,
                    legend_y - 5,
                    legend_x + 12,
                    legend_y + 7,
                    fill=color,
                    outline="",
                )

                canvas.create_text(
                    legend_x + 18,
                    legend_y + 1,
                    text=label,
                    anchor="w",
                    fill=TEXT,
                    font=("Segoe UI", 8),
                )

                legend_x += 120

            left = 185
            right = width - 35
            top = 45
            bottom = height - 18

            count = max(
                len(models),
                1,
            )

            row_height = (
                bottom - top
            ) / count

            night_seconds = max(
                core["night"].total_seconds(),
                1,
            )

            for index, model in enumerate(
                models
            ):
                cy = (
                    top
                    + row_height
                    * (
                        index
                        + 0.5
                    )
                )

                bar_height = min(
                    28,
                    row_height * 0.58,
                )

                total_width = (
                    right - left
                )

                sleep_seconds = max(
                    model["total_sleep"].total_seconds(),
                    0,
                )

                qiyam_seconds = max(
                    model["qiyam"].total_seconds(),
                    0,
                )

                other_seconds = max(
                    night_seconds
                    - sleep_seconds
                    - qiyam_seconds,
                    0,
                )

                short_name = model["name"]

                if ". " in short_name:
                    short_name = short_name.split(
                        ". ",
                        1,
                    )[1]

                canvas.create_text(
                    left - 10,
                    cy,
                    text=short_name,
                    anchor="e",
                    fill=TEXT,
                    font=("Segoe UI", 8, "bold"),
                )

                current_x = left

                for label, seconds, color in (
                    (
                        "Sleep",
                        sleep_seconds,
                        SLEEP_COLOR,
                    ),
                    (
                        "Qiyam",
                        qiyam_seconds,
                        PRAYER_COLOR,
                    ),
                    (
                        "Other non-sleep",
                        other_seconds,
                        AWAKE_COLOR,
                    ),
                ):
                    part_width = (
                        seconds
                        / night_seconds
                        * total_width
                    )

                    if part_width <= 0:
                        continue

                    x1 = (
                        current_x
                        + part_width
                    )

                    canvas.create_rectangle(
                        current_x,
                        cy - bar_height / 2,
                        x1,
                        cy + bar_height / 2,
                        fill=color,
                        outline="",
                    )

                    if part_width > 68:
                        canvas.create_text(
                            (
                                current_x
                                + x1
                            ) / 2,
                            cy,
                            text=duration(
                                timedelta(
                                    seconds=seconds
                                )
                            ),
                            fill="#111111",
                            font=("Segoe UI", 7, "bold"),
                        )

                    current_x = x1

                canvas.create_rectangle(
                    left,
                    cy - bar_height / 2,
                    right,
                    cy + bar_height / 2,
                    outline=BORDER,
                    width=1,
                )

        canvas.bind(
            "<Configure>",
            redraw,
        )

        redraw()

    # --------------------------------------------------------
    # Keep settings summary fresh after fetch
    # --------------------------------------------------------

    def fetch_success(
        self,
        generation,
        result,
    ):
        if generation != self.fetch_generation:
            return

        self.fetch_button.config(
            state="normal"
        )

        self.recalc_button.config(
            state="normal"
        )

        self.result = result

        self.status.config(
            text=(
                f"Loaded {result['city']}, {result['country']} • "
                f"{result['date'].strftime('%A, %d %B %Y')}"
            ),
            fg=SUCCESS,
        )

        self.v6_location_summary.config(
            text=(
                f"{result['country']} • "
                f"{result['city']}"
            )
        )

        self.v6_date_summary.config(
            text=result["date"].strftime(
                "%A, %d %B %Y"
            )
        )

        self.update_fixed_prayer_times()
        self.render_dashboard()



# ============================================================
# V8 — BORDERLESS SHELL + DETAILED EXPORTS / COMPARISON
# ============================================================

class DawudPlannerAppV8(DawudPlannerAppV6):
    def __init__(
        self,
        root,
    ):
        self._drag_dx = 0
        self._drag_dy = 0
        self._resize_state = None
        self._maximized = False
        self._restore_geometry = None

        # Custom app chrome replaces the ordinary Windows title bar.
        root.overrideredirect(
            True
        )

        super().__init__(
            root
        )

        self.v8_add_resize_grip()

    # --------------------------------------------------------
    # Borderless title bar
    # --------------------------------------------------------

    def v6_build_header(
        self,
    ):
        header = tk.Frame(
            self.root,
            bg=PANEL,
            height=44,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        header.pack(
            fill="x",
            padx=8,
            pady=(7, 2),
        )

        header.pack_propagate(
            False
        )

        left = tk.Frame(
            header,
            bg=PANEL,
        )

        left.pack(
            side="left",
            fill="both",
            expand=True,
        )

        # Tiny geometric ornament — decorative, but the requested subtitle
        # under the app name is intentionally removed.
        ornament = tk.Canvas(
            left,
            width=42,
            height=38,
            bg=PANEL,
            highlightthickness=0,
        )

        ornament.pack(
            side="left",
            padx=(7, 2),
        )

        pts = []

        for i in range(16):
            angle = (
                -math.pi / 2
                + i * math.pi / 8
            )

            radius = (
                13
                if i % 2 == 0
                else 5
            )

            pts.extend(
                [
                    21
                    + math.cos(angle)
                    * radius,
                    19
                    + math.sin(angle)
                    * radius,
                ]
            )

        ornament.create_polygon(
            pts,
            outline=ACCENT_DARK,
            fill="",
        )

        title = tk.Label(
            left,
            text="Night of Dawud",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 12, "bold"),
        )

        title.pack(
            side="left",
            padx=(4, 0),
        )

        controls = tk.Frame(
            header,
            bg=PANEL,
        )

        controls.pack(
            side="right",
            fill="y",
        )

        def chrome_button(
            text,
            command,
            danger=False,
        ):
            return tk.Button(
                controls,
                text=text,
                command=command,
                bg=PANEL,
                fg=(
                    ERROR
                    if danger
                    else TEXT
                ),
                activebackground=(
                    "#5E2323"
                    if danger
                    else CARD_2
                ),
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                cursor="hand2",
                width=5,
                font=("Segoe UI", 9, "bold"),
            )

        chrome_button(
            "—",
            self.v8_minimize,
        ).pack(
            side="left",
            fill="y",
        )

        self._maximize_button = chrome_button(
            "□",
            self.v8_toggle_maximize,
        )

        self._maximize_button.pack(
            side="left",
            fill="y",
        )

        chrome_button(
            "×",
            self.root.destroy,
            danger=True,
        ).pack(
            side="left",
            fill="y",
        )

        for widget in (
            header,
            left,
            title,
            ornament,
        ):
            widget.bind(
                "<ButtonPress-1>",
                self.v8_start_move,
            )

            widget.bind(
                "<B1-Motion>",
                self.v8_do_move,
            )

            widget.bind(
                "<Double-Button-1>",
                lambda event: self.v8_toggle_maximize(),
            )

    def v8_start_move(
        self,
        event,
    ):
        if self._maximized:
            return

        self._drag_dx = (
            event.x_root
            - self.root.winfo_x()
        )

        self._drag_dy = (
            event.y_root
            - self.root.winfo_y()
        )

    def v8_do_move(
        self,
        event,
    ):
        if self._maximized:
            return

        x = (
            event.x_root
            - self._drag_dx
        )

        y = (
            event.y_root
            - self._drag_dy
        )

        self.root.geometry(
            f"+{x}+{y}"
        )

    def v8_work_area(
        self,
    ):
        # Windows: use the actual desktop work area so maximizing does not
        # cover the taskbar. Fallback: use the whole screen.
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()

            ctypes.windll.user32.SystemParametersInfoW(
                48,
                0,
                ctypes.byref(rect),
                0,
            )

            return (
                rect.left,
                rect.top,
                rect.right
                - rect.left,
                rect.bottom
                - rect.top,
            )

        except Exception:
            return (
                0,
                0,
                self.root.winfo_screenwidth(),
                self.root.winfo_screenheight(),
            )

    def v8_toggle_maximize(
        self,
    ):
        if not self._maximized:
            self._restore_geometry = (
                self.root.geometry()
            )

            x, y, w, h = (
                self.v8_work_area()
            )

            self.root.geometry(
                f"{w}x{h}+{x}+{y}"
            )

            self._maximized = True

            self._maximize_button.config(
                text="❐"
            )

        else:
            if self._restore_geometry:
                self.root.geometry(
                    self._restore_geometry
                )

            self._maximized = False

            self._maximize_button.config(
                text="□"
            )

    def v8_minimize(
        self,
    ):
        # Tk needs the override-redirect flag temporarily disabled to
        # minimize reliably on Windows.
        self.root.overrideredirect(
            False
        )

        self.root.iconify()

        def restore_borderless(
            event=None,
        ):
            if (
                self.root.state()
                == "normal"
            ):
                self.root.after(
                    10,
                    lambda: self.root.overrideredirect(
                        True
                    ),
                )

                try:
                    self.root.unbind(
                        "<Map>",
                        bind_id,
                    )
                except Exception:
                    pass

        bind_id = self.root.bind(
            "<Map>",
            restore_borderless,
            add="+",
        )

    def v8_add_resize_grip(
        self,
    ):
        grip = tk.Label(
            self.root,
            text="◢",
            bg=BG,
            fg=ACCENT_DARK,
            cursor="size_nw_se",
            font=("Segoe UI", 9),
        )

        grip.place(
            relx=1.0,
            rely=1.0,
            anchor="se",
        )

        def begin(
            event,
        ):
            if self._maximized:
                return

            self._resize_state = (
                event.x_root,
                event.y_root,
                self.root.winfo_width(),
                self.root.winfo_height(),
            )

        def resize(
            event,
        ):
            if (
                self._maximized
                or not self._resize_state
            ):
                return

            sx, sy, sw, sh = (
                self._resize_state
            )

            width = max(
                1100,
                sw
                + event.x_root
                - sx,
            )

            height = max(
                720,
                sh
                + event.y_root
                - sy,
            )

            self.root.geometry(
                f"{width}x{height}"
            )

        grip.bind(
            "<ButtonPress-1>",
            begin,
        )

        grip.bind(
            "<B1-Motion>",
            resize,
        )

    # --------------------------------------------------------
    # Focused model + PNG export
    # --------------------------------------------------------

    def v6_open_model_focus(
        self,
        model,
    ):
        if not self.result:
            return

        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            model["name"]
        )

        popup.geometry(
            "1180x690"
        )

        popup.minsize(
            900,
            540,
        )

        popup.configure(
            bg=BG
        )

        popup.transient(
            self.root
        )

        top = tk.Frame(
            popup,
            bg=BG,
        )

        top.pack(
            fill="x",
            padx=14,
            pady=(12, 0),
        )

        tk.Label(
            top,
            text=model["name"],
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 13, "bold"),
        ).pack(
            side="left",
        )

        tk.Button(
            top,
            text="Export this model as PNG",
            command=lambda m=model: self.v8_export_focused_model_png(
                m
            ),
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=12,
            pady=6,
        ).pack(
            side="right",
        )

        outer = tk.Frame(
            popup,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        outer.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(8, 14),
        )

        self.v6_draw_model_card(
            outer,
            self.result["core"],
            model,
            focused=True,
        )

    # --------------------------------------------------------
    # 5-location comparison — ALL models, not one model
    # --------------------------------------------------------

    def open_location_comparison(
        self,
    ):
        if not self.result:
            messagebox.showinfo(
                "Compare locations",
                "Fetch prayer times once first.",
            )

            return

        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            "Compare all models across up to 5 locations"
        )

        popup.geometry(
            "1450x760"
        )

        popup.minsize(
            1100,
            620,
        )

        popup.configure(
            bg=PANEL
        )

        popup.transient(
            self.root
        )

        tk.Label(
            popup,
            text="Compare every model across up to 5 countries / cities",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 14, "bold"),
        ).pack(
            anchor="w",
            padx=14,
            pady=(12, 2),
        )

        tk.Label(
            popup,
            text=(
                "The same date, calculation method, prayer routine, iqama, "
                "travel and sleep settings are applied to every location."
            ),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            anchor="w",
            padx=14,
            pady=(0, 8),
        )

        rows_frame = tk.Frame(
            popup,
            bg=PANEL,
        )

        rows_frame.pack(
            fill="x",
            padx=14,
        )

        for column, header in enumerate(
            (
                "Use",
                "Country",
                "City",
            )
        ):
            tk.Label(
                rows_frame,
                text=header,
                bg=PANEL,
                fg=MUTED,
                font=("Segoe UI", 8, "bold"),
            ).grid(
                row=0,
                column=column,
                sticky="w",
                padx=4,
            )

        compare_rows = []

        for index in range(5):
            enabled = tk.BooleanVar(
                value=(
                    index == 0
                )
            )

            tk.Checkbutton(
                rows_frame,
                variable=enabled,
                bg=PANEL,
                activebackground=PANEL,
                selectcolor=CARD,
            ).grid(
                row=index + 1,
                column=0,
                padx=4,
                pady=3,
            )

            country_combo = SearchableCombobox(
                rows_frame,
                values=self.location_db.country_names,
                width=31,
            )

            country_combo.grid(
                row=index + 1,
                column=1,
                sticky="ew",
                padx=4,
                pady=3,
            )

            city_combo = SearchableCombobox(
                rows_frame,
                values=[],
                width=31,
            )

            city_combo.grid(
                row=index + 1,
                column=2,
                sticky="ew",
                padx=4,
                pady=3,
            )

            if index == 0:
                country_combo.set(
                    self.result["country"]
                )

                city_combo.set_values(
                    self.location_db.get_cities(
                        self.result["country"]
                    )
                )

                city_combo.set(
                    self.result["city"]
                )

            def bind_country(
                country_box,
                city_box,
            ):
                def changed(
                    event=None,
                ):
                    country = (
                        country_box
                        .get()
                        .strip()
                    )

                    city_box.set_values(
                        self.location_db.get_cities(
                            country
                        )
                    )

                    city_box.set("")

                return changed

            country_combo.bind(
                "<<ComboboxSelected>>",
                bind_country(
                    country_combo,
                    city_combo,
                ),
            )

            compare_rows.append(
                (
                    enabled,
                    country_combo,
                    city_combo,
                )
            )

        rows_frame.grid_columnconfigure(
            1,
            weight=1,
        )

        rows_frame.grid_columnconfigure(
            2,
            weight=1,
        )

        action_row = tk.Frame(
            popup,
            bg=PANEL,
        )

        action_row.pack(
            fill="x",
            padx=14,
            pady=(5, 5),
        )

        status = tk.Label(
            action_row,
            text="",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        )

        status.pack(
            side="left",
        )

        result_wrap = tk.Frame(
            popup,
            bg=PANEL,
        )

        result_wrap.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14),
        )

        columns = (
            "model",
            "location",
            "maghrib",
            "isha",
            "fajr",
            "night",
            "half",
            "third",
            "sixth",
            "ready",
            "wake",
            "sleep_again",
            "sleep",
            "qiyam",
            "awake",
        )

        tree = ttk.Treeview(
            result_wrap,
            columns=columns,
            show="headings",
        )

        y_scroll = ttk.Scrollbar(
            result_wrap,
            orient="vertical",
            command=tree.yview,
        )

        x_scroll = ttk.Scrollbar(
            result_wrap,
            orient="horizontal",
            command=tree.xview,
        )

        tree.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )

        tree.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        y_scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        x_scroll.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        result_wrap.grid_rowconfigure(
            0,
            weight=1,
        )

        result_wrap.grid_columnconfigure(
            0,
            weight=1,
        )

        headings = {
            "model": "Model",
            "location": "Location",
            "maghrib": "Maghrib",
            "isha": "Isha",
            "fajr": "Fajr",
            "night": "Night",
            "half": "1/2",
            "third": "1/3",
            "sixth": "1/6",
            "ready": "Sleep-ready",
            "wake": "Wake",
            "sleep_again": "Sleep again",
            "sleep": "Total sleep",
            "qiyam": "Qiyam",
            "awake": "Post-Isha awake",
        }

        widths = {
            "model": 210,
            "location": 165,
            "maghrib": 90,
            "isha": 90,
            "fajr": 90,
            "night": 85,
            "half": 75,
            "third": 75,
            "sixth": 75,
            "ready": 95,
            "wake": 90,
            "sleep_again": 95,
            "sleep": 90,
            "qiyam": 85,
            "awake": 105,
        }

        for column in columns:
            tree.heading(
                column,
                text=headings[
                    column
                ],
            )

            tree.column(
                column,
                width=widths[
                    column
                ],
                anchor=(
                    "w"
                    if column
                    in {
                        "model",
                        "location",
                    }
                    else "center"
                ),
                stretch=(
                    column
                    in {
                        "model",
                        "location",
                    }
                ),
            )

        def run_comparison(
            results,
        ):
            for item in tree.get_children():
                tree.delete(
                    item
                )

            for built in results:
                core = built[
                    "core"
                ]

                location = (
                    f"{built['country']} / "
                    f"{built['city']}"
                )

                for model in built[
                    "models"
                ]:
                    tree.insert(
                        "",
                        "end",
                        values=(
                            model["name"],
                            location,
                            clock(
                                core["maghrib"]
                            ),
                            clock(
                                core["isha"]
                            ),
                            clock(
                                core["fajr"]
                            ),
                            duration(
                                core["night"]
                            ),
                            duration(
                                core["half"]
                            ),
                            duration(
                                core["third"]
                            ),
                            duration(
                                core["sixth"]
                            ),
                            clock(
                                built[
                                    "practical"
                                ][
                                    "estimated_asleep"
                                ]
                            ),
                            clock(
                                model[
                                    "wake"
                                ]
                            ),
                            clock(
                                model[
                                    "sleep_again"
                                ]
                            ),
                            duration(
                                model[
                                    "total_sleep"
                                ]
                            ),
                            duration(
                                model[
                                    "qiyam"
                                ]
                            ),
                            duration(
                                post_isha_awake_time(
                                    model,
                                    core,
                                )
                            ),
                        ),
                    )

        def start_compare(
        ):
            selected = []

            for (
                enabled,
                country_box,
                city_box,
            ) in compare_rows:
                if not enabled.get():
                    continue

                country = (
                    country_box
                    .get()
                    .strip()
                )

                city = (
                    city_box
                    .get()
                    .strip()
                )

                if (
                    country
                    and city
                ):
                    selected.append(
                        (
                            country,
                            city,
                        )
                    )

            if not selected:
                messagebox.showerror(
                    "Compare",
                    "Choose at least one country/city.",
                    parent=popup,
                )

                return

            try:
                settings = (
                    self.get_plan_settings()
                )

            except ValueError as error:
                messagebox.showerror(
                    "Settings",
                    str(error),
                    parent=popup,
                )

                return

            run_button.config(
                state="disabled"
            )

            status.config(
                text="Fetching every location and every model…",
                fg=ACCENT,
            )

            method = self.result[
                "method"
            ]

            def worker(
            ):
                results = []
                errors = []

                for (
                    country,
                    city,
                ) in selected:
                    try:
                        api = fetch_night_information(
                            self.selected_date,
                            city,
                            country,
                            method,
                        )

                        core = calculate_night_core(
                            api["maghrib"],
                            api["isha"],
                            api["fajr_next"],
                        )

                        built = self.build_result_from_core(
                            self.selected_date,
                            city,
                            country,
                            method,
                            api,
                            core,
                            settings,
                        )

                        results.append(
                            built
                        )

                    except Exception as error:
                        errors.append(
                            f"{country}/{city}: {error}"
                        )

                def done(
                ):
                    run_button.config(
                        state="normal"
                    )

                    run_comparison(
                        results
                    )

                    if errors:
                        status.config(
                            text=(
                                "Some locations failed: "
                                + " | ".join(
                                    errors
                                )
                            ),
                            fg=ERROR,
                        )

                    else:
                        status.config(
                            text=(
                                f"{len(results)} location(s) × "
                                f"{len(results[0]['models']) if results else 0} models"
                            ),
                            fg=SUCCESS,
                        )

                self.root.after(
                    0,
                    done,
                )

            threading.Thread(
                target=worker,
                daemon=True,
            ).start()

        run_button = tk.Button(
            action_row,
            text="Compare all models",
            command=start_compare,
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=12,
            pady=6,
        )

        run_button.pack(
            side="right",
        )

    # --------------------------------------------------------
    # PNG helpers
    # --------------------------------------------------------

    @staticmethod
    def v8_pil_font(
        size,
        bold=False,
    ):
        if not PIL_AVAILABLE:
            return None

        candidates = []

        if bold:
            candidates.extend(
                [
                    "C:/Windows/Fonts/seguisb.ttf",
                    "C:/Windows/Fonts/segoeuib.ttf",
                    "arialbd.ttf",
                ]
            )

        else:
            candidates.extend(
                [
                    "C:/Windows/Fonts/segoeui.ttf",
                    "arial.ttf",
                ]
            )

        for candidate in candidates:
            try:
                return ImageFont.truetype(
                    candidate,
                    size,
                )
            except Exception:
                pass

        return ImageFont.load_default()

    @staticmethod
    def v8_draw_wrapped(
        draw,
        xy,
        text,
        font,
        fill,
        width_chars=100,
        line_spacing=7,
    ):
        x, y = xy

        lines = []

        for paragraph in str(
            text
        ).splitlines():
            wrapped = textwrap.wrap(
                paragraph,
                width=width_chars,
            )

            lines.extend(
                wrapped
                or [""]
            )

        for line in lines:
            draw.text(
                (
                    x,
                    y,
                ),
                line,
                fill=fill,
                font=font,
            )

            bbox = draw.textbbox(
                (
                    x,
                    y,
                ),
                line or "Ag",
                font=font,
            )

            y += (
                bbox[3]
                - bbox[1]
                + line_spacing
            )

        return y

    def v8_export_focused_model_png(
        self,
        model,
    ):
        if not PIL_AVAILABLE:
            messagebox.showerror(
                "PNG export",
                "Install Pillow first:\npython -m pip install pillow",
            )

            return

        if not self.result:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[
                (
                    "PNG image",
                    "*.png",
                )
            ],
            initialfile=(
                "dawud_model_"
                + re.sub(
                    r"[^A-Za-z0-9_-]+",
                    "_",
                    model["name"],
                )
                + "_"
                + self.selected_date.isoformat()
                + ".png"
            ),
        )

        if not path:
            return

        r = self.result
        core = r[
            "core"
        ]

        width = 1700
        height = (
            720
            + 46
            * len(
                model.get(
                    "segments",
                    [],
                )
            )
        )

        image = Image.new(
            "RGB",
            (
                width,
                height,
            ),
            BG,
        )

        draw = ImageDraw.Draw(
            image
        )

        f_title = self.v8_pil_font(
            38,
            True,
        )

        f_h = self.v8_pil_font(
            23,
            True,
        )

        f_body = self.v8_pil_font(
            18,
        )

        f_small = self.v8_pil_font(
            15,
        )

        # Border texture.
        for cx in range(
            35,
            width - 20,
            78,
        ):
            pts = []

            for i in range(16):
                angle = (
                    -math.pi / 2
                    + i
                    * math.pi
                    / 8
                )

                radius = (
                    16
                    if i % 2 == 0
                    else 7
                )

                pts.append(
                    (
                        cx
                        + math.cos(
                            angle
                        )
                        * radius,
                        32
                        + math.sin(
                            angle
                        )
                        * radius,
                    )
                )

            draw.polygon(
                pts,
                outline=BORDER,
            )

        y = 62

        draw.text(
            (
                45,
                y,
            ),
            model["name"],
            fill=TEXT,
            font=f_title,
        )

        y += 54

        draw.text(
            (
                45,
                y,
            ),
            (
                f"{r['city']}, {r['country']}  •  "
                f"{r['date'].strftime('%A, %d %B %Y')}"
            ),
            fill=ACCENT,
            font=f_body,
        )

        y += 42

        y = self.v8_draw_wrapped(
            draw,
            (
                45,
                y,
            ),
            model.get(
                "description",
                "",
            ),
            f_body,
            MUTED,
            125,
        )

        y += 14

        metrics = [
            (
                "Night",
                duration(
                    core["night"]
                ),
            ),
            (
                "Sleep",
                duration(
                    model[
                        "total_sleep"
                    ]
                ),
            ),
            (
                "Qiyam",
                duration(
                    model[
                        "qiyam"
                    ]
                ),
            ),
            (
                "Post-Isha awake",
                duration(
                    post_isha_awake_time(
                        model,
                        core,
                    )
                ),
            ),
            (
                "Wake",
                clock(
                    model[
                        "wake"
                    ]
                ),
            ),
            (
                "Sleep again",
                clock(
                    model[
                        "sleep_again"
                    ]
                ),
            ),
        ]

        x = 45

        for label, value in metrics:
            draw.rounded_rectangle(
                (
                    x,
                    y,
                    x + 245,
                    y + 74,
                ),
                radius=10,
                fill=CARD,
                outline=BORDER,
            )

            draw.text(
                (
                    x + 12,
                    y + 10,
                ),
                label,
                fill=MUTED,
                font=f_small,
            )

            draw.text(
                (
                    x + 12,
                    y + 36,
                ),
                value,
                fill=TEXT,
                font=f_body,
            )

            x += 258

        y += 108

        draw.text(
            (
                45,
                y,
            ),
            "Timeline",
            fill=ACCENT,
            font=f_h,
        )

        y += 48

        tl_left = 80
        tl_right = (
            width - 80
        )

        draw.line(
            (
                tl_left,
                y,
                tl_right,
                y,
            ),
            fill=BORDER,
            width=8,
        )

        total_seconds = max(
            core[
                "night"
            ].total_seconds(),
            1,
        )

        color_map = {
            "sleep": SLEEP_COLOR,
            "prayer": PRAYER_COLOR,
            "awake": AWAKE_COLOR,
            "travel": TRAVEL_COLOR,
            "wait": WAIT_COLOR,
            "cycle": CYCLE_COLOR,
        }

        for segment in model.get(
            "segments",
            [],
        ):
            clipped = clip_segment(
                segment[
                    "start"
                ],
                segment[
                    "end"
                ],
                core[
                    "maghrib"
                ],
                core[
                    "fajr"
                ],
            )

            if not clipped:
                continue

            start_dt, end_dt = (
                clipped
            )

            r1 = (
                start_dt
                - core[
                    "maghrib"
                ]
            ).total_seconds() / total_seconds

            r2 = (
                end_dt
                - core[
                    "maghrib"
                ]
            ).total_seconds() / total_seconds

            x1 = (
                tl_left
                + r1
                * (
                    tl_right
                    - tl_left
                )
            )

            x2 = (
                tl_left
                + r2
                * (
                    tl_right
                    - tl_left
                )
            )

            draw.line(
                (
                    x1,
                    y,
                    x2,
                    y,
                ),
                fill=color_map.get(
                    segment[
                        "kind"
                    ],
                    AWAKE_COLOR,
                ),
                width=18,
            )

        draw.text(
            (
                tl_left,
                y + 18,
            ),
            (
                f"Maghrib "
                f"{clock(core['maghrib'])}"
            ),
            fill=MUTED,
            font=f_small,
        )

        draw.text(
            (
                tl_right - 170,
                y + 18,
            ),
            (
                f"Fajr "
                f"{clock(core['fajr'])}"
            ),
            fill=MUTED,
            font=f_small,
        )

        y += 85

        draw.text(
            (
                45,
                y,
            ),
            "Segments",
            fill=ACCENT,
            font=f_h,
        )

        y += 40

        for segment in model.get(
            "segments",
            [],
        ):
            line = (
                f"{segment['name']}   "
                f"{clock(segment['start'])} → "
                f"{clock(segment['end'])}   "
                f"({duration(segment['end'] - segment['start'])})"
            )

            draw.text(
                (
                    65,
                    y,
                ),
                line,
                fill=TEXT,
                font=f_body,
            )

            y += 40

        if model.get(
            "note"
        ):
            y += 10

            draw.text(
                (
                    45,
                    y,
                ),
                "Note",
                fill=ACCENT,
                font=f_h,
            )

            y += 34

            y = self.v8_draw_wrapped(
                draw,
                (
                    45,
                    y,
                ),
                model[
                    "note"
                ],
                f_body,
                MUTED,
                130,
            )

        image.save(
            path
        )

        messagebox.showinfo(
            "PNG export",
            f"Saved model report:\n{path}",
        )

    def export_full_report_png(
        self,
    ):
        """
        Detailed long-form PNG:
          - source/location/date/method
          - all prayer times
          - every planning setting
          - night fraction math + boundaries
          - Maghrib & Isha routine event breakdown
          - every model, every segment, wake/sleep/Qiyam/awake metrics
          - visual comparison graph
          - hadith/source footer
        """
        if not self.result:
            messagebox.showinfo(
                "PNG export",
                "Fetch prayer times first.",
            )

            return

        if not PIL_AVAILABLE:
            messagebox.showerror(
                "PNG export",
                "Install Pillow first:\npython -m pip install pillow",
            )

            return

        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[
                (
                    "PNG image",
                    "*.png",
                )
            ],
            initialfile=(
                f"dawud_detailed_report_"
                f"{self.selected_date.isoformat()}.png"
            ),
        )

        if not path:
            return

        r = self.result
        core = r[
            "core"
        ]

        models = r[
            "models"
        ]

        settings = r[
            "settings"
        ]

        # More height than older versions because the report now prints every
        # segment and more settings, instead of just a thin timeline.
        model_heights = [
            (
                250
                + 34
                * len(
                    model.get(
                        "segments",
                        [],
                    )
                )
            )
            for model in models
        ]

        height = (
            1180
            + sum(
                model_heights
            )
            + 380
        )

        width = 1800

        image = Image.new(
            "RGB",
            (
                width,
                height,
            ),
            BG,
        )

        draw = ImageDraw.Draw(
            image
        )

        f_title = self.v8_pil_font(
            40,
            True,
        )

        f_h = self.v8_pil_font(
            24,
            True,
        )

        f_body = self.v8_pil_font(
            17,
        )

        f_small = self.v8_pil_font(
            14,
        )

        f_bold = self.v8_pil_font(
            17,
            True,
        )

        # Islamic border.
        for cx in range(
            36,
            width - 20,
            78,
        ):
            pts = []

            for i in range(16):
                angle = (
                    -math.pi / 2
                    + i
                    * math.pi
                    / 8
                )

                radius = (
                    16
                    if i % 2 == 0
                    else 7
                )

                pts.append(
                    (
                        cx
                        + math.cos(
                            angle
                        )
                        * radius,
                        32
                        + math.sin(
                            angle
                        )
                        * radius,
                    )
                )

            draw.polygon(
                pts,
                outline=BORDER,
            )

        y = 66

        draw.text(
            (
                45,
                y,
            ),
            "Night of Dawud — Detailed Planner Report",
            fill=TEXT,
            font=f_title,
        )

        y += 56

        method_data = METHODS.get(
            r[
                "method"
            ],
            {},
        )

        draw.text(
            (
                45,
                y,
            ),
            (
                f"{r['city']}, {r['country']}  •  "
                f"{r['date'].strftime('%A, %d %B %Y')}  •  "
                f"Method: {method_data.get('name', r['method'])}"
            ),
            fill=ACCENT,
            font=f_body,
        )

        y += 52

        # Prayer times
        draw.text(
            (
                45,
                y,
            ),
            "Prayer times",
            fill=ACCENT,
            font=f_h,
        )

        y += 38

        timings = r[
            "api"
        ][
            "today_data"
        ][
            "timings"
        ]

        prayer_items = []

        for name in (
            "Fajr",
            "Sunrise",
            "Dhuhr",
            "Asr",
            "Maghrib",
            "Isha",
        ):
            prayer_items.append(
                (
                    name,
                    clock(
                        prayer_datetime(
                            r[
                                "date"
                            ],
                            timings[
                                name
                            ],
                        )
                    ),
                )
            )

        prayer_items.append(
            (
                "Next Fajr",
                clock(
                    core[
                        "fajr"
                    ]
                ),
            )
        )

        x = 45

        for label, value in prayer_items:
            draw.rounded_rectangle(
                (
                    x,
                    y,
                    x + 220,
                    y + 68,
                ),
                radius=9,
                fill=CARD,
                outline=BORDER,
            )

            draw.text(
                (
                    x + 10,
                    y + 9,
                ),
                label,
                fill=MUTED,
                font=f_small,
            )

            draw.text(
                (
                    x + 10,
                    y + 34,
                ),
                value,
                fill=TEXT,
                font=f_body,
            )

            x += 235

        y += 98

        # Settings
        draw.text(
            (
                45,
                y,
            ),
            "Planning settings",
            fill=ACCENT,
            font=f_h,
        )

        y += 40

        setting_lines = [
            (
                f"Maghrib: {settings['maghrib_place']} • "
                f"prayer {settings['maghrib_prayer_minutes']}m • "
                f"iqama +{settings['maghrib_iqama_minutes']}m "
                f"(iqama ignored at Home)"
            ),
            (
                f"Isha: {settings['isha_place']} • "
                f"prayer {settings['isha_prayer_minutes']}m • "
                f"iqama +{settings['isha_iqama_minutes']}m "
                f"(iqama ignored at Home)"
            ),
            (
                f"Mosque travel: {settings['travel_minutes']}m one way • "
                f"Fall-asleep buffer: {settings['sleep_latency_minutes']}m • "
                f"Sleep-cycle planning value: {settings['sleep_cycle_minutes']}m"
            ),
        ]

        for line in setting_lines:
            draw.text(
                (
                    60,
                    y,
                ),
                line,
                fill=TEXT,
                font=f_body,
            )

            y += 34

        y += 16

        # Night math
        draw.text(
            (
                45,
                y,
            ),
            "Night mathematics",
            fill=ACCENT,
            font=f_h,
        )

        y += 40

        fraction_lines = [
            (
                f"Full night: {duration(core['night'])}  "
                f"({clock(core['maghrib'])} → {clock(core['fajr'])})"
            ),
            (
                f"1/2 = {duration(core['half'])}  •  "
                f"half-night boundary = {clock(core['wake'])}"
            ),
            (
                f"1/3 = {duration(core['third'])}  •  "
                f"last-third boundary = {clock(core['last_third'])}"
            ),
            (
                f"1/6 = {duration(core['sixth'])}  •  "
                f"final-sixth boundary = {clock(core['final_sixth'])}"
            ),
            (
                f"2/3 sleep target = {duration(core['two_thirds'])}"
            ),
        ]

        for line in fraction_lines:
            draw.text(
                (
                    60,
                    y,
                ),
                line,
                fill=TEXT,
                font=f_body,
            )

            y += 32

        y += 20

        # Prayer routine breakdown
        draw.text(
            (
                45,
                y,
            ),
            "Prayer routine structure",
            fill=ACCENT,
            font=f_h,
        )

        y += 40

        for routine in (
            r[
                "maghrib_routine"
            ],
            r[
                "isha_routine"
            ],
        ):
            draw.text(
                (
                    55,
                    y,
                ),
                (
                    f"{routine['name']} — {routine['place']}"
                ),
                fill=TEXT,
                font=f_bold,
            )

            y += 30

            draw.text(
                (
                    75,
                    y,
                ),
                (
                    f"Adhan node: {clock(routine['start'])}  •  "
                    f"Prayer: {clock(routine['prayer_start'])} → "
                    f"{clock(routine['prayer_end'])}"
                ),
                fill=MUTED,
                font=f_body,
            )

            y += 30

            if routine[
                "place"
            ] == "Mosque":
                draw.text(
                    (
                        75,
                        y,
                    ),
                    (
                        f"Travel TO mosque: {clock(routine['departure'])} → "
                        f"{clock(routine['arrival'])}  •  "
                        f"Iqama: {clock(routine['iqama_time'])}  •  "
                        f"Travel HOME ends: {clock(routine['end'])}"
                    ),
                    fill=MUTED,
                    font=f_body,
                )

                y += 30

            for segment in routine.get(
                "segments",
                [],
            ):
                draw.text(
                    (
                        95,
                        y,
                    ),
                    (
                        f"• {segment['name']}: "
                        f"{clock(segment['start'])} → "
                        f"{clock(segment['end'])} "
                        f"({duration(segment['end'] - segment['start'])})"
                    ),
                    fill=TEXT,
                    font=f_small,
                )

                y += 26

            y += 14

        # Legend
        draw.text(
            (
                45,
                y,
            ),
            "Legend",
            fill=ACCENT,
            font=f_h,
        )

        y += 38

        legend_x = 55

        for label, color in (
            (
                "Sleep",
                SLEEP_COLOR,
            ),
            (
                "Qiyam / Prayer",
                PRAYER_COLOR,
            ),
            (
                "Post-Isha awake",
                AWAKE_COLOR,
            ),
            (
                "Travel",
                TRAVEL_COLOR,
            ),
            (
                "Iqama wait",
                WAIT_COLOR,
            ),
            (
                "Sleep cycle",
                CYCLE_COLOR,
            ),
        ):
            draw.rectangle(
                (
                    legend_x,
                    y,
                    legend_x + 18,
                    y + 18,
                ),
                fill=color,
            )

            draw.text(
                (
                    legend_x + 27,
                    y - 1,
                ),
                label,
                fill=TEXT,
                font=f_small,
            )

            legend_x += 245

        y += 58

        # Every model in detail
        draw.text(
            (
                45,
                y,
            ),
            "All models — full details",
            fill=ACCENT,
            font=f_h,
        )

        y += 45

        color_map = {
            "sleep": SLEEP_COLOR,
            "prayer": PRAYER_COLOR,
            "awake": AWAKE_COLOR,
            "travel": TRAVEL_COLOR,
            "wait": WAIT_COLOR,
            "cycle": CYCLE_COLOR,
        }

        total_sec = max(
            core[
                "night"
            ].total_seconds(),
            1,
        )

        for model, model_height in zip(
            models,
            model_heights,
        ):
            box_top = y

            draw.rounded_rectangle(
                (
                    35,
                    box_top,
                    width - 35,
                    box_top
                    + model_height
                    - 8,
                ),
                radius=12,
                fill=PANEL,
                outline=BORDER,
            )

            draw.text(
                (
                    55,
                    y + 14,
                ),
                model[
                    "name"
                ],
                fill=TEXT,
                font=f_h,
            )

            y += 50

            draw.text(
                (
                    55,
                    y,
                ),
                (
                    f"Sleep {duration(model['total_sleep'])}  •  "
                    f"Qiyam {duration(model['qiyam'])}  •  "
                    f"Post-Isha awake {duration(post_isha_awake_time(model, core))}  •  "
                    f"Wake {clock(model['wake'])}  •  "
                    f"Sleep again {clock(model['sleep_again'])}"
                ),
                fill=ACCENT,
                font=f_small,
            )

            y += 34

            tl_left = 80
            tl_right = (
                width - 80
            )

            draw.line(
                (
                    tl_left,
                    y,
                    tl_right,
                    y,
                ),
                fill=BORDER,
                width=7,
            )

            for segment in model.get(
                "segments",
                [],
            ):
                clipped = clip_segment(
                    segment[
                        "start"
                    ],
                    segment[
                        "end"
                    ],
                    core[
                        "maghrib"
                    ],
                    core[
                        "fajr"
                    ],
                )

                if not clipped:
                    continue

                s, e = clipped

                r1 = (
                    s
                    - core[
                        "maghrib"
                    ]
                ).total_seconds() / total_sec

                r2 = (
                    e
                    - core[
                        "maghrib"
                    ]
                ).total_seconds() / total_sec

                x1 = (
                    tl_left
                    + r1
                    * (
                        tl_right
                        - tl_left
                    )
                )

                x2 = (
                    tl_left
                    + r2
                    * (
                        tl_right
                        - tl_left
                    )
                )

                draw.line(
                    (
                        x1,
                        y,
                        x2,
                        y,
                    ),
                    fill=color_map.get(
                        segment[
                            "kind"
                        ],
                        AWAKE_COLOR,
                    ),
                    width=15,
                )

            y += 38

            y = self.v8_draw_wrapped(
                draw,
                (
                    55,
                    y,
                ),
                model.get(
                    "description",
                    "",
                ),
                f_small,
                MUTED,
                170,
                4,
            )

            y += 8

            for segment in model.get(
                "segments",
                [],
            ):
                draw.text(
                    (
                        75,
                        y,
                    ),
                    (
                        f"• {segment['name']}: "
                        f"{clock(segment['start'])} → "
                        f"{clock(segment['end'])}  "
                        f"({duration(segment['end'] - segment['start'])})"
                    ),
                    fill=TEXT,
                    font=f_small,
                )

                y += 27

            if model.get(
                "note"
            ):
                y = self.v8_draw_wrapped(
                    draw,
                    (
                        75,
                        y,
                    ),
                    (
                        "Note: "
                        + model[
                            "note"
                        ]
                    ),
                    f_small,
                    ACCENT,
                    165,
                    4,
                )

            y = (
                box_top
                + model_height
            )

        # Comparison graph
        y += 18

        draw.text(
            (
                45,
                y,
            ),
            "Model comparison",
            fill=ACCENT,
            font=f_h,
        )

        y += 50

        chart_left = 285
        chart_right = (
            width - 70
        )

        chart_width = (
            chart_right
            - chart_left
        )

        night_seconds = max(
            core[
                "night"
            ].total_seconds(),
            1,
        )

        for model in models:
            sleep_s = model[
                "total_sleep"
            ].total_seconds()

            qiyam_s = model[
                "qiyam"
            ].total_seconds()

            other_s = max(
                night_seconds
                - sleep_s
                - qiyam_s,
                0,
            )

            name = model[
                "name"
            ]

            draw.text(
                (
                    chart_left - 15,
                    y + 7,
                ),
                name,
                anchor="ra",
                fill=TEXT,
                font=f_small,
            )

            x = chart_left

            for seconds, color in (
                (
                    sleep_s,
                    SLEEP_COLOR,
                ),
                (
                    qiyam_s,
                    PRAYER_COLOR,
                ),
                (
                    other_s,
                    AWAKE_COLOR,
                ),
            ):
                w = (
                    seconds
                    / night_seconds
                    * chart_width
                )

                draw.rectangle(
                    (
                        x,
                        y,
                        x + w,
                        y + 26,
                    ),
                    fill=color,
                )

                x += w

            y += 42

        y += 25

        draw.text(
            (
                45,
                y,
            ),
            "Hadith / source",
            fill=ACCENT,
            font=f_h,
        )

        y += 38

        y = self.v8_draw_wrapped(
            draw,
            (
                55,
                y,
            ),
            HADITH_TEXT,
            f_body,
            TEXT,
            155,
            5,
        )

        draw.text(
            (
                55,
                y + 8,
            ),
            "Sahih al-Bukhari 1131 — https://sunnah.com/bukhari:1131",
            fill=ACCENT,
            font=f_small,
        )

        # Crop unused bottom space while preserving a margin.
        crop_bottom = min(
            height,
            y + 85,
        )

        image = image.crop(
            (
                0,
                0,
                width,
                crop_bottom,
            )
        )

        image.save(
            path
        )

        messagebox.showinfo(
            "PNG export",
            f"Saved detailed report:\n{path}",
        )



# ============================================================
# V9 — ALT-TAB FIX / ROUTINE TRAVEL / COUNTRY GRAPH / PNG NODES
# ============================================================

class DawudPlannerAppV9(DawudPlannerAppV8):
    def __init__(
        self,
        root,
    ):
        self._v9_appwindow_initialized = False

        super().__init__(
            root
        )

        # An override-redirect Tk window normally disappears from Windows
        # Alt+Tab/taskbar. Re-apply the Windows APPWINDOW extended style to
        # keep the borderless UI while making it behave like a normal app.
        self.root.after(
            120,
            self.v9_enable_alt_tab,
        )

    # --------------------------------------------------------
    # Borderless + Alt+Tab support
    # --------------------------------------------------------

    def v9_enable_alt_tab(
        self,
    ):
        if os.name != "nt":
            return

        try:
            import ctypes

            user32 = ctypes.windll.user32

            hwnd = user32.GetParent(
                self.root.winfo_id()
            )

            if not hwnd:
                hwnd = self.root.winfo_id()

            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000

            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020

            style = user32.GetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
            )

            style = (
                style
                & ~WS_EX_TOOLWINDOW
            )

            style = (
                style
                | WS_EX_APPWINDOW
            )

            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                style,
            )

            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                (
                    SWP_NOMOVE
                    | SWP_NOSIZE
                    | SWP_NOZORDER
                    | SWP_FRAMECHANGED
                ),
            )

            # A single hide/show after changing the style makes Windows add
            # the override-redirect window to the app switcher reliably.
            if not self._v9_appwindow_initialized:
                self._v9_appwindow_initialized = True

                geometry = self.root.geometry()

                self.root.withdraw()

                def show_again(
                ):
                    self.root.deiconify()

                    if geometry:
                        self.root.geometry(
                            geometry
                        )

                    self.root.lift()

                    # Keep the custom borderless shell after the style refresh.
                    self.root.overrideredirect(
                        True
                    )

                self.root.after(
                    35,
                    show_again,
                )

        except Exception:
            # If Windows styling fails on a particular Tk build, keep the app
            # usable rather than crashing.
            pass

    def v8_minimize(
        self,
    ):
        # Temporarily let Windows manage the window while minimized.
        self.root.overrideredirect(
            False
        )

        self.root.iconify()

        def on_map(
            event=None,
        ):
            if (
                self.root.state()
                == "normal"
            ):
                self.root.after(
                    20,
                    self.v9_restore_borderless_after_minimize,
                )

                try:
                    self.root.unbind(
                        "<Map>",
                        bind_id,
                    )
                except Exception:
                    pass

        bind_id = self.root.bind(
            "<Map>",
            on_map,
            add="+",
        )

    def v9_restore_borderless_after_minimize(
        self,
    ):
        self.root.overrideredirect(
            True
        )

        self.root.after(
            30,
            self.v9_enable_alt_tab,
        )

    # --------------------------------------------------------
    # Header: linked GitHub mark
    # --------------------------------------------------------

    def v6_build_header(
        self,
    ):
        header = tk.Frame(
            self.root,
            bg=PANEL,
            height=44,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        header.pack(
            fill="x",
            padx=8,
            pady=(7, 2),
        )

        header.pack_propagate(
            False
        )

        left = tk.Frame(
            header,
            bg=PANEL,
        )

        left.pack(
            side="left",
            fill="both",
            expand=True,
        )

        ornament = tk.Canvas(
            left,
            width=42,
            height=38,
            bg=PANEL,
            highlightthickness=0,
        )

        ornament.pack(
            side="left",
            padx=(7, 2),
        )

        pts = []

        for i in range(16):
            angle = (
                -math.pi / 2
                + i * math.pi / 8
            )

            radius = (
                13
                if i % 2 == 0
                else 5
            )

            pts.extend(
                [
                    21
                    + math.cos(angle)
                    * radius,
                    19
                    + math.sin(angle)
                    * radius,
                ]
            )

        ornament.create_polygon(
            pts,
            outline=ACCENT_DARK,
            fill="",
        )

        title = tk.Label(
            left,
            text="Night of Dawud",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 12, "bold"),
        )

        title.pack(
            side="left",
            padx=(4, 0),
        )

        # Linked GitHub logo/profile shortcut.
        github_wrap = tk.Frame(
            left,
            bg=PANEL,
            cursor="hand2",
        )

        github_wrap.pack(
            side="left",
            padx=(14, 0),
        )

        gh = tk.Canvas(
            github_wrap,
            width=28,
            height=28,
            bg=PANEL,
            highlightthickness=0,
            cursor="hand2",
        )

        gh.pack(
            side="left",
        )

        # Small programmatic GitHub-style cat mark so there is no external
        # image dependency.
        gh.create_oval(
            4,
            4,
            24,
            24,
            fill=TEXT,
            outline="",
        )

        gh.create_polygon(
            7,
            9,
            8,
            2,
            13,
            7,
            fill=TEXT,
            outline="",
        )

        gh.create_polygon(
            15,
            7,
            20,
            2,
            21,
            9,
            fill=TEXT,
            outline="",
        )

        gh.create_oval(
            8,
            9,
            20,
            20,
            fill=PANEL,
            outline="",
        )

        gh.create_oval(
            10,
            12,
            12,
            14,
            fill=TEXT,
            outline="",
        )

        gh.create_oval(
            16,
            12,
            18,
            14,
            fill=TEXT,
            outline="",
        )

        gh_label = tk.Label(
            github_wrap,
            text="GitHub",
            bg=PANEL,
            fg=MUTED,
            cursor="hand2",
            font=("Segoe UI", 7, "bold"),
        )

        gh_label.pack(
            side="left",
            padx=(2, 0),
        )

        def open_github(
            event=None,
        ):
            webbrowser.open(
                GITHUB_URL
            )

        for widget in (
            github_wrap,
            gh,
            gh_label,
        ):
            widget.bind(
                "<Button-1>",
                open_github,
            )

        controls = tk.Frame(
            header,
            bg=PANEL,
        )

        controls.pack(
            side="right",
            fill="y",
        )

        def chrome_button(
            text,
            command,
            danger=False,
        ):
            return tk.Button(
                controls,
                text=text,
                command=command,
                bg=PANEL,
                fg=(
                    ERROR
                    if danger
                    else TEXT
                ),
                activebackground=(
                    "#5E2323"
                    if danger
                    else CARD_2
                ),
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                cursor="hand2",
                width=5,
                font=("Segoe UI", 9, "bold"),
            )

        chrome_button(
            "—",
            self.v8_minimize,
        ).pack(
            side="left",
            fill="y",
        )

        self._maximize_button = chrome_button(
            "□",
            self.v8_toggle_maximize,
        )

        self._maximize_button.pack(
            side="left",
            fill="y",
        )

        chrome_button(
            "×",
            self.root.destroy,
            danger=True,
        ).pack(
            side="left",
            fill="y",
        )

        # Do NOT bind the GitHub control to window dragging.
        for widget in (
            header,
            left,
            title,
            ornament,
        ):
            widget.bind(
                "<ButtonPress-1>",
                self.v8_start_move,
            )

            widget.bind(
                "<B1-Motion>",
                self.v8_do_move,
            )

            widget.bind(
                "<Double-Button-1>",
                lambda event: self.v8_toggle_maximize(),
            )

    # --------------------------------------------------------
    # Settings drawer:
    # travel now sits directly under Maghrib/Isha routines and is faded
    # until explicitly enabled or a routine is set to Mosque.
    # --------------------------------------------------------

    def v6_build_settings_drawer(
        self,
    ):
        self.settings_drawer = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        row = tk.Frame(
            self.settings_drawer,
            bg=PANEL,
        )

        row.pack(
            fill="x",
            padx=8,
            pady=(7, 3),
        )

        for col in range(6):
            row.grid_columnconfigure(
                col,
                weight=1,
            )

        # Country
        wrapper = self.v6_setting_cell(
            row,
            "Country / territory",
            0,
        )

        self.country_combo = SearchableCombobox(
            wrapper,
            values=self.location_db.country_names,
            width=21,
        )

        self.country_combo.pack(
            fill="x",
        )

        self.country_combo.set(
            "Egypt"
        )

        self.country_combo.bind(
            "<<ComboboxSelected>>",
            self.country_changed,
        )

        self.country_combo.bind(
            "<FocusOut>",
            self.country_changed,
        )

        # City
        wrapper = self.v6_setting_cell(
            row,
            "City",
            1,
        )

        self.city_combo = SearchableCombobox(
            wrapper,
            values=[],
            width=21,
        )

        self.city_combo.pack(
            fill="x",
        )

        self.load_cities(
            "Egypt",
            preserve_city=False,
        )

        if (
            "Cairo"
            in self.city_combo.all_values
        ):
            self.city_combo.set(
                "Cairo"
            )

        # Method
        wrapper = self.v6_setting_cell(
            row,
            "Prayer method",
            2,
        )

        self.method_map = {}
        method_values = []

        for method_id, data in METHODS.items():
            label = (
                f"{data['short']} — "
                f"{data['name']}"
            )

            self.method_map[
                label
            ] = method_id

            method_values.append(
                label
            )

        self.method_combo = ttk.Combobox(
            wrapper,
            values=method_values,
            state="readonly",
            width=26,
        )

        self.method_combo.pack(
            fill="x",
        )

        self.method_combo.set(
            next(
                label
                for label, method_id
                in self.method_map.items()
                if method_id
                == DEFAULT_METHOD
            )
        )

        # Sleep
        wrapper = self.v6_setting_cell(
            row,
            "Sleep",
            3,
        )

        sleep_line = tk.Frame(
            wrapper,
            bg=PANEL,
        )

        sleep_line.pack(
            fill="x",
        )

        tk.Label(
            sleep_line,
            text="latency",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
        )

        self.sleep_latency = self.v6_spin(
            sleep_line,
            0,
            60,
            "10",
            pack_side=True,
        )

        tk.Label(
            sleep_line,
            text="cycle",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            side="left",
        )

        self.sleep_cycle = self.v6_spin(
            sleep_line,
            60,
            120,
            "90",
            increment=5,
            pack_side=True,
        )

        # Maghrib routine
        wrapper = self.v6_setting_cell(
            row,
            "Maghrib routine",
            4,
        )

        (
            self.maghrib_place,
            self.maghrib_duration,
            self.maghrib_iqama,
        ) = self.v6_prayer_controls(
            wrapper,
            "10",
            "10",
        )

        # Isha routine
        wrapper = self.v6_setting_cell(
            row,
            "Isha routine",
            5,
        )

        (
            self.isha_place,
            self.isha_duration,
            self.isha_iqama,
        ) = self.v6_prayer_controls(
            wrapper,
            "10",
            "15",
        )

        # Travel belongs visually to the prayer routines.
        travel_row = tk.Frame(
            self.settings_drawer,
            bg=PANEL,
        )

        travel_row.pack(
            fill="x",
            padx=8,
            pady=(0, 5),
        )

        spacer = tk.Frame(
            travel_row,
            bg=PANEL,
        )

        spacer.pack(
            side="left",
            fill="x",
            expand=True,
        )

        self.travel_panel = tk.Frame(
            travel_row,
            bg=CARD_2,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        self.travel_panel.pack(
            side="right",
            padx=(4, 0),
        )

        self.travel_override_var = tk.BooleanVar(
            value=False
        )

        self.travel_checkbox = tk.Checkbutton(
            self.travel_panel,
            text="Use mosque travel",
            variable=self.travel_override_var,
            command=self.v9_refresh_travel_control,
            bg=CARD_2,
            fg=MUTED,
            activebackground=CARD_2,
            activeforeground=TEXT,
            selectcolor=PANEL,
            font=("Segoe UI", 7),
        )

        self.travel_checkbox.pack(
            side="left",
            padx=(8, 6),
            pady=6,
        )

        self.travel_title_label = tk.Label(
            self.travel_panel,
            text="Mosque travel • one way",
            bg=CARD_2,
            fg=BORDER,
            font=("Segoe UI", 7, "bold"),
        )

        self.travel_title_label.pack(
            side="left",
            padx=(0, 3),
        )

        self.travel_minutes = self.v6_spin(
            self.travel_panel,
            0,
            90,
            "10",
            pack_side=True,
        )

        self.travel_unit_label = tk.Label(
            self.travel_panel,
            text="min",
            bg=CARD_2,
            fg=BORDER,
            font=("Segoe UI", 7),
        )

        self.travel_unit_label.pack(
            side="left",
            padx=(0, 5),
        )

        self.travel_hint_label = tk.Label(
            self.travel_panel,
            text="Choose Mosque in either routine to activate automatically.",
            bg=CARD_2,
            fg=BORDER,
            font=("Segoe UI", 6),
        )

        self.travel_hint_label.pack(
            side="left",
            padx=(3, 8),
        )

        # Add a second event handler without replacing the prayer-control
        # handler that enables/disables the iqama field.
        self.maghrib_place.bind(
            "<<ComboboxSelected>>",
            lambda event: self.v9_refresh_travel_control(),
            add="+",
        )

        self.isha_place.bind(
            "<<ComboboxSelected>>",
            lambda event: self.v9_refresh_travel_control(),
            add="+",
        )

        self.v9_refresh_travel_control()

        bottom = tk.Frame(
            self.settings_drawer,
            bg=PANEL,
        )

        bottom.pack(
            fill="x",
            padx=8,
            pady=(0, 7),
        )

        self.status = tk.Label(
            bottom,
            text="Ready.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 7),
        )

        self.status.pack(
            side="left",
        )

        self.fetch_button = self.v6_small_button(
            bottom,
            "Fetch prayer times",
            self.start_fetch,
            accent=True,
        )

        self.fetch_button.pack(
            side="right",
        )

        self.recalc_button = self.v6_small_button(
            bottom,
            "Recalculate",
            self.recalculate_plan,
        )

        self.recalc_button.config(
            state="disabled"
        )

        self.recalc_button.pack(
            side="right",
            padx=(0, 5),
        )

    def v9_refresh_travel_control(
        self,
    ):
        mosque_selected = (
            self.maghrib_place.get()
            == "Mosque"
            or self.isha_place.get()
            == "Mosque"
        )

        # Selecting Mosque explicitly turns the travel checkbox on so the
        # setting and its effect are visible to the user.
        if (
            mosque_selected
            and not self.travel_override_var.get()
        ):
            self.travel_override_var.set(
                True
            )

        active = (
            bool(
                self.travel_override_var.get()
            )
            or mosque_selected
        )

        if active:
            self.travel_minutes.config(
                state="normal",
            )

            self.travel_title_label.config(
                fg=TEXT
            )

            self.travel_unit_label.config(
                fg=MUTED
            )

            self.travel_hint_label.config(
                fg=MUTED,
                text=(
                    "Outbound travel uses the adhan→iqama wait; "
                    "return travel is after prayer."
                ),
            )

            self.travel_checkbox.config(
                fg=TEXT
            )

        else:
            self.travel_minutes.config(
                state="disabled",
            )

            self.travel_title_label.config(
                fg=BORDER
            )

            self.travel_unit_label.config(
                fg=BORDER
            )

            self.travel_hint_label.config(
                fg=BORDER,
                text=(
                    "Choose Mosque in either routine to activate automatically."
                ),
            )

            self.travel_checkbox.config(
                fg=MUTED
            )

    # --------------------------------------------------------
    # Compare with other countries:
    # all models at once, line graph, metric buttons.
    # --------------------------------------------------------

    def open_location_comparison(
        self,
    ):
        if not self.result:
            messagebox.showinfo(
                "Compare with other countries",
                "Fetch prayer times first.",
            )

            return

        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            "Compare with other countries"
        )

        popup.geometry(
            "1320x760"
        )

        popup.minsize(
            1050,
            640,
        )

        popup.configure(
            bg=PANEL
        )

        popup.transient(
            self.root
        )

        tk.Label(
            popup,
            text="Compare with other countries",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 15, "bold"),
        ).pack(
            anchor="w",
            padx=14,
            pady=(12, 2),
        )

        tk.Label(
            popup,
            text=(
                "Each line is one location. The x-axis contains every model. "
                "Switch the metric to compare sleep time, Qiyam, or the "
                "model's own night window."
            ),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            anchor="w",
            padx=14,
            pady=(0, 7),
        )

        inputs = tk.Frame(
            popup,
            bg=PANEL,
        )

        inputs.pack(
            fill="x",
            padx=14,
            pady=(0, 5),
        )

        compare_rows = []

        for index in range(5):
            row = tk.Frame(
                inputs,
                bg=PANEL,
            )

            row.pack(
                side="left",
                fill="x",
                expand=True,
                padx=3,
            )

            enabled = tk.BooleanVar(
                value=(
                    index == 0
                )
            )

            tk.Checkbutton(
                row,
                text=f"{index + 1}",
                variable=enabled,
                bg=PANEL,
                fg=MUTED,
                activebackground=PANEL,
                activeforeground=TEXT,
                selectcolor=CARD,
                font=("Segoe UI", 7, "bold"),
            ).pack(
                anchor="w",
            )

            country_box = SearchableCombobox(
                row,
                values=self.location_db.country_names,
                width=21,
            )

            country_box.pack(
                fill="x",
                pady=(1, 2),
            )

            city_box = SearchableCombobox(
                row,
                values=[],
                width=21,
            )

            city_box.pack(
                fill="x",
            )

            if index == 0:
                country_box.set(
                    self.result["country"]
                )

                city_box.set_values(
                    self.location_db.get_cities(
                        self.result["country"]
                    )
                )

                city_box.set(
                    self.result["city"]
                )

            def make_country_changed(
                country_combo,
                city_combo,
            ):
                def changed(
                    event=None,
                ):
                    country = (
                        country_combo
                        .get()
                        .strip()
                    )

                    city_combo.set_values(
                        self.location_db.get_cities(
                            country
                        )
                    )

                    city_combo.set("")

                return changed

            country_box.bind(
                "<<ComboboxSelected>>",
                make_country_changed(
                    country_box,
                    city_box,
                ),
            )

            compare_rows.append(
                (
                    enabled,
                    country_box,
                    city_box,
                )
            )

        toolbar = tk.Frame(
            popup,
            bg=PANEL,
        )

        toolbar.pack(
            fill="x",
            padx=14,
            pady=(3, 6),
        )

        status = tk.Label(
            toolbar,
            text="Choose locations, then run the comparison.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        )

        status.pack(
            side="left",
        )

        metric_var = tk.StringVar(
            value="Sleep time"
        )

        metric_buttons = {}

        metrics = (
            "Sleep time",
            "Qiyam",
            "Model night",
        )

        metric_holder = tk.Frame(
            toolbar,
            bg=PANEL,
        )

        metric_holder.pack(
            side="right",
            padx=(8, 0),
        )

        chart_frame = tk.Frame(
            popup,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        chart_frame.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14),
        )

        chart = tk.Canvas(
            chart_frame,
            bg=CARD,
            highlightthickness=0,
        )

        chart.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        state = {
            "results": [],
        }

        palette = (
            "#79C4A2",
            "#D6B762",
            "#78A8D8",
            "#B99BEA",
            "#E39B76",
        )

        def metric_minutes(
            model,
            core,
        ):
            metric = metric_var.get()

            if metric == "Sleep time":
                value = model[
                    "total_sleep"
                ]

            elif metric == "Qiyam":
                value = model[
                    "qiyam"
                ]

            else:
                value = model_night_length(
                    model,
                    core,
                )

            return max(
                value.total_seconds()
                / 60,
                0,
            )

        def short_model_name(
            name,
        ):
            if ". " in name:
                name = name.split(
                    ". ",
                    1,
                )[1]

            replacements = {
                "Exact Hadith Fractions": "Exact",
                "Sleep After Isha": "After Isha",
                "Post-Isha Fraction Plan": "Post-Isha",
                "Prayer-Routine Recovery": "Recovery",
                "Maghrib-to-Isha Qiyam Credit": "Qiyam Credit",
                "Sleep Cycle Plan": "Cycles",
                "Night After Isha Prayer (Isha End → Fajr)": "Isha-End Night",
            }

            return replacements.get(
                name,
                name[:18],
            )

        def redraw_chart(
            event=None,
        ):
            chart.delete(
                "all"
            )

            results = state[
                "results"
            ]

            width = max(
                chart.winfo_width(),
                850,
            )

            height = max(
                chart.winfo_height(),
                420,
            )

            if not results:
                chart.create_text(
                    width / 2,
                    height / 2,
                    text=(
                        "Run the comparison to draw all models."
                    ),
                    fill=MUTED,
                    font=("Segoe UI", 13, "bold"),
                )

                return

            models = results[
                0
            ][
                "models"
            ]

            left = 78
            right = width - 38
            top = 60
            bottom = height - 88

            all_values = []

            for built in results:
                for model in built[
                    "models"
                ]:
                    all_values.append(
                        metric_minutes(
                            model,
                            built[
                                "core"
                            ],
                        )
                    )

            max_value = max(
                all_values
                or [1]
            )

            max_value = max(
                60,
                math.ceil(
                    max_value
                    / 30
                )
                * 30,
            )

            # Y grid / labels.
            tick_count = 5

            for tick in range(
                tick_count + 1
            ):
                value = (
                    max_value
                    * tick
                    / tick_count
                )

                y = (
                    bottom
                    - (
                        value
                        / max_value
                    )
                    * (
                        bottom
                        - top
                    )
                )

                chart.create_line(
                    left,
                    y,
                    right,
                    y,
                    fill=BORDER,
                    dash=(3, 5),
                )

                chart.create_text(
                    left - 9,
                    y,
                    text=(
                        f"{round(value)}m"
                    ),
                    anchor="e",
                    fill=MUTED,
                    font=("Segoe UI", 7),
                )

            count = max(
                len(models),
                1,
            )

            if count == 1:
                x_positions = [
                    (
                        left
                        + right
                    ) / 2
                ]
            else:
                x_positions = [
                    (
                        left
                        + index
                        * (
                            right - left
                        )
                        / (
                            count - 1
                        )
                    )
                    for index in range(
                        count
                    )
                ]

            # X labels
            for x, model in zip(
                x_positions,
                models,
            ):
                chart.create_line(
                    x,
                    bottom,
                    x,
                    bottom + 5,
                    fill=MUTED,
                )

                chart.create_text(
                    x,
                    bottom + 18,
                    text=short_model_name(
                        model[
                            "name"
                        ]
                    ),
                    angle=0,
                    fill=MUTED,
                    width=max(
                        70,
                        int(
                            (
                                right - left
                            )
                            / count
                        ),
                    ),
                    justify="center",
                    font=("Segoe UI", 7),
                )

            # Graph title
            chart.create_text(
                left,
                22,
                text=metric_var.get(),
                anchor="w",
                fill=TEXT,
                font=("Segoe UI", 12, "bold"),
            )

            chart.create_text(
                left,
                42,
                text=(
                    "Duration in minutes • every point is a model"
                ),
                anchor="w",
                fill=MUTED,
                font=("Segoe UI", 7),
            )

            # Lines by location.
            legend_x = right
            legend_y = 20

            for loc_index, built in enumerate(
                results
            ):
                color = palette[
                    loc_index
                    % len(
                        palette
                    )
                ]

                points = []

                for x, model in zip(
                    x_positions,
                    built[
                        "models"
                    ],
                ):
                    value = metric_minutes(
                        model,
                        built[
                            "core"
                        ],
                    )

                    y = (
                        bottom
                        - (
                            value
                            / max_value
                        )
                        * (
                            bottom
                            - top
                        )
                    )

                    points.extend(
                        [
                            x,
                            y,
                        ]
                    )

                if len(points) >= 4:
                    chart.create_line(
                        *points,
                        fill=color,
                        width=3,
                        smooth=False,
                    )

                location_name = (
                    f"{built['city']}, "
                    f"{built['country']}"
                )

                for index, (
                    x,
                    model,
                ) in enumerate(
                    zip(
                        x_positions,
                        built[
                            "models"
                        ],
                    )
                ):
                    value = metric_minutes(
                        model,
                        built[
                            "core"
                        ],
                    )

                    y = (
                        bottom
                        - (
                            value
                            / max_value
                        )
                        * (
                            bottom
                            - top
                        )
                    )

                    chart.create_oval(
                        x - 5,
                        y - 5,
                        x + 5,
                        y + 5,
                        fill=color,
                        outline=TEXT,
                        width=1,
                    )

                    chart.create_text(
                        x,
                        y - (
                            13
                            + 11
                            * (
                                loc_index
                                % 2
                            )
                        ),
                        text=duration(
                            timedelta(
                                minutes=value
                            )
                        ),
                        fill=color,
                        font=("Segoe UI", 6, "bold"),
                    )

                legend_width = 150

                lx = (
                    legend_x
                    - legend_width
                )

                ly = (
                    legend_y
                    + loc_index
                    * 20
                )

                chart.create_line(
                    lx,
                    ly,
                    lx + 18,
                    ly,
                    fill=color,
                    width=3,
                )

                chart.create_oval(
                    lx + 6,
                    ly - 4,
                    lx + 14,
                    ly + 4,
                    fill=color,
                    outline="",
                )

                chart.create_text(
                    lx + 24,
                    ly,
                    text=location_name,
                    anchor="w",
                    fill=TEXT,
                    font=("Segoe UI", 7),
                )

        chart.bind(
            "<Configure>",
            redraw_chart,
        )

        def set_metric(
            metric,
        ):
            metric_var.set(
                metric
            )

            for name, button in metric_buttons.items():
                button.config(
                    bg=(
                        ACCENT
                        if name
                        == metric
                        else CARD_2
                    ),
                    fg=(
                        "#111111"
                        if name
                        == metric
                        else TEXT
                    ),
                )

            redraw_chart()

        for metric in metrics:
            button = tk.Button(
                metric_holder,
                text=metric,
                command=lambda m=metric: set_metric(
                    m
                ),
                bg=(
                    ACCENT
                    if metric
                    == metric_var.get()
                    else CARD_2
                ),
                fg=(
                    "#111111"
                    if metric
                    == metric_var.get()
                    else TEXT
                ),
                activebackground=ACCENT,
                activeforeground="#111111",
                relief="flat",
                cursor="hand2",
                font=("Segoe UI", 7, "bold"),
                padx=9,
                pady=5,
            )

            button.pack(
                side="left",
                padx=2,
            )

            metric_buttons[
                metric
            ] = button

        def start_compare(
        ):
            selected = []

            for (
                enabled,
                country_box,
                city_box,
            ) in compare_rows:
                if not enabled.get():
                    continue

                country = (
                    country_box
                    .get()
                    .strip()
                )

                city = (
                    city_box
                    .get()
                    .strip()
                )

                if (
                    country
                    and city
                ):
                    selected.append(
                        (
                            country,
                            city,
                        )
                    )

            if not selected:
                messagebox.showerror(
                    "Compare with other countries",
                    "Choose at least one country/city.",
                    parent=popup,
                )

                return

            try:
                settings = self.get_plan_settings()

            except ValueError as error:
                messagebox.showerror(
                    "Settings",
                    str(error),
                    parent=popup,
                )

                return

            run_button.config(
                state="disabled"
            )

            status.config(
                text="Fetching selected locations…",
                fg=ACCENT,
            )

            method = self.result[
                "method"
            ]

            def worker(
            ):
                results = []
                errors = []

                for (
                    country,
                    city,
                ) in selected:
                    try:
                        api = fetch_night_information(
                            self.selected_date,
                            city,
                            country,
                            method,
                        )

                        core = calculate_night_core(
                            api[
                                "maghrib"
                            ],
                            api[
                                "isha"
                            ],
                            api[
                                "fajr_next"
                            ],
                        )

                        built = self.build_result_from_core(
                            self.selected_date,
                            city,
                            country,
                            method,
                            api,
                            core,
                            settings,
                        )

                        results.append(
                            built
                        )

                    except Exception as error:
                        errors.append(
                            f"{country}/{city}: {error}"
                        )

                def done(
                ):
                    run_button.config(
                        state="normal"
                    )

                    state[
                        "results"
                    ] = results

                    redraw_chart()

                    if errors:
                        status.config(
                            text=(
                                "Some locations failed: "
                                + " | ".join(
                                    errors
                                )
                            ),
                            fg=ERROR,
                        )

                    else:
                        status.config(
                            text=(
                                f"Comparing {len(results)} location(s) "
                                f"across all models."
                            ),
                            fg=SUCCESS,
                        )

                self.root.after(
                    0,
                    done,
                )

            threading.Thread(
                target=worker,
                daemon=True,
            ).start()

        run_button = tk.Button(
            toolbar,
            text="Run comparison",
            command=start_compare,
            bg=ACCENT,
            fg="#111111",
            activebackground="#E8D7A9",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=12,
            pady=6,
        )

        run_button.pack(
            side="right",
            padx=(7, 0),
        )

    # --------------------------------------------------------
    # PNG export helpers with timeline nodes
    # --------------------------------------------------------

    def v9_draw_png_timeline(
        self,
        draw,
        model,
        core,
        y,
        left,
        right,
        font_label,
        font_small,
        line_width=16,
    ):
        color_map = {
            "sleep": SLEEP_COLOR,
            "prayer": PRAYER_COLOR,
            "awake": AWAKE_COLOR,
            "travel": TRAVEL_COLOR,
            "wait": WAIT_COLOR,
            "cycle": CYCLE_COLOR,
        }

        total_seconds = max(
            core["night"].total_seconds(),
            1,
        )

        draw.line(
            (
                left,
                y,
                right,
                y,
            ),
            fill=BORDER,
            width=8,
        )

        def xpos(
            dt,
        ):
            ratio = (
                (
                    dt
                    - core[
                        "maghrib"
                    ]
                ).total_seconds()
                / total_seconds
            )

            ratio = max(
                0,
                min(
                    1,
                    ratio,
                ),
            )

            return (
                left
                + ratio
                * (
                    right
                    - left
                )
            )

        for segment in model.get(
            "segments",
            [],
        ):
            clipped = clip_segment(
                segment[
                    "start"
                ],
                segment[
                    "end"
                ],
                core[
                    "maghrib"
                ],
                core[
                    "fajr"
                ],
            )

            if not clipped:
                continue

            start_dt, end_dt = clipped

            draw.line(
                (
                    xpos(
                        start_dt
                    ),
                    y,
                    xpos(
                        end_dt
                    ),
                    y,
                ),
                fill=color_map.get(
                    segment.get(
                        "kind"
                    ),
                    AWAKE_COLOR,
                ),
                width=line_width,
            )

        # Merge nodes at the same minute to avoid duplicate labels.
        night_start = model_night_start(
            model,
            core,
        )

        night_length = model_night_length(
            model,
            core,
        )

        model_half_point = (
            night_start
            + model_half_duration(
                model,
                core,
            )
        )

        model_final_sixth = (
            night_start
            + night_length
            * (5 / 6)
        )

        raw_nodes = [
            (
                core[
                    "maghrib"
                ],
                "Maghrib",
                TEXT,
            ),
            (
                core[
                    "isha"
                ],
                "Isha",
                ACCENT,
            ),
            (
                night_start,
                "Model night start",
                SLEEP_COLOR,
            ),
            (
                model_half_point,
                "1/2 boundary",
                TEXT,
            ),
            (
                model_final_sixth,
                "5/6 boundary",
                PRAYER_COLOR,
            ),
            (
                model[
                    "wake"
                ],
                "Wake",
                TEXT,
            ),
            (
                model[
                    "sleep_again"
                ],
                "Sleep again",
                TEXT,
            ),
            (
                core[
                    "fajr"
                ],
                "Fajr",
                TEXT,
            ),
        ]

        merged = {}

        for dt, label, color in raw_nodes:
            key = round(
                dt.timestamp()
                / 60
            )

            if key not in merged:
                merged[
                    key
                ] = {
                    "time": dt,
                    "labels": [],
                    "color": color,
                }

            merged[
                key
            ][
                "labels"
            ].append(
                label
            )

            if color == ACCENT:
                merged[
                    key
                ][
                    "color"
                ] = ACCENT

        nodes = sorted(
            merged.values(),
            key=lambda item: item[
                "time"
            ],
        )

        for index, node in enumerate(
            nodes
        ):
            x = xpos(
                node[
                    "time"
                ]
            )

            radius = 7

            draw.ellipse(
                (
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                ),
                fill=node[
                    "color"
                ],
                outline=TEXT,
                width=1,
            )

            top = (
                index % 2
                == 0
            )

            label_y = (
                y - 48
                if top
                else y + 19
            )

            label = (
                " / ".join(
                    node[
                        "labels"
                    ]
                )
                + "\n"
                + clock(
                    node[
                        "time"
                    ]
                )
            )

            draw.multiline_text(
                (
                    x,
                    label_y,
                ),
                label,
                fill=node[
                    "color"
                ],
                font=font_small,
                anchor=(
                    "ms"
                    if top
                    else "ma"
                ),
                align="center",
                spacing=3,
            )

        return (
            y + 78
        )

    def v8_export_focused_model_png(
        self,
        model,
    ):
        if not PIL_AVAILABLE:
            messagebox.showerror(
                "PNG export",
                "Install Pillow first:\npython -m pip install pillow",
            )

            return

        if not self.result:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[
                (
                    "PNG image",
                    "*.png",
                )
            ],
            initialfile=(
                "dawud_focused_"
                + re.sub(
                    r"[^A-Za-z0-9_-]+",
                    "_",
                    model[
                        "name"
                    ],
                )
                + "_"
                + self.selected_date.isoformat()
                + ".png"
            ),
        )

        if not path:
            return

        r = self.result
        core = r[
            "core"
        ]

        width = 1800
        height = (
            900
            + 48
            * len(
                model.get(
                    "segments",
                    [],
                )
            )
        )

        image = Image.new(
            "RGB",
            (
                width,
                height,
            ),
            BG,
        )

        draw = ImageDraw.Draw(
            image
        )

        f_title = self.v8_pil_font(
            40,
            True,
        )

        f_h = self.v8_pil_font(
            23,
            True,
        )

        f_body = self.v8_pil_font(
            18,
        )

        f_small = self.v8_pil_font(
            14,
        )

        y = 58

        draw.text(
            (
                45,
                y,
            ),
            model[
                "name"
            ],
            fill=TEXT,
            font=f_title,
        )

        y += 56

        draw.text(
            (
                45,
                y,
            ),
            (
                f"{r['city']}, {r['country']} • "
                f"{r['date'].strftime('%A, %d %B %Y')}"
            ),
            fill=ACCENT,
            font=f_body,
        )

        y += 44

        metrics = [
            (
                "Model night",
                duration(
                    model_night_length(
                        model,
                        core,
                    )
                ),
            ),
            (
                "Sleep",
                duration(
                    model[
                        "total_sleep"
                    ]
                ),
            ),
            (
                "Qiyam",
                duration(
                    model[
                        "qiyam"
                    ]
                ),
            ),
            (
                "Post-Isha awake",
                duration(
                    post_isha_awake_time(
                        model,
                        core,
                    )
                ),
            ),
            (
                "Wake",
                clock(
                    model[
                        "wake"
                    ]
                ),
            ),
            (
                "Sleep again",
                clock(
                    model[
                        "sleep_again"
                    ]
                ),
            ),
        ]

        x = 45

        for label, value in metrics:
            draw.rounded_rectangle(
                (
                    x,
                    y,
                    x + 260,
                    y + 76,
                ),
                radius=9,
                fill=CARD,
                outline=BORDER,
            )

            draw.text(
                (
                    x + 11,
                    y + 9,
                ),
                label,
                fill=MUTED,
                font=f_small,
            )

            draw.text(
                (
                    x + 11,
                    y + 38,
                ),
                value,
                fill=TEXT,
                font=f_body,
            )

            x += 275

        y += 115

        y = self.v8_draw_wrapped(
            draw,
            (
                45,
                y,
            ),
            model.get(
                "description",
                "",
            ),
            f_body,
            MUTED,
            145,
        )

        y += 22

        draw.text(
            (
                45,
                y,
            ),
            "Timeline with nodes",
            fill=ACCENT,
            font=f_h,
        )

        y += 78

        y = self.v9_draw_png_timeline(
            draw,
            model,
            core,
            y,
            80,
            width - 80,
            f_body,
            f_small,
            18,
        )

        y += 20

        draw.text(
            (
                45,
                y,
            ),
            "Segments",
            fill=ACCENT,
            font=f_h,
        )

        y += 40

        for segment in model.get(
            "segments",
            [],
        ):
            draw.text(
                (
                    65,
                    y,
                ),
                (
                    f"• {segment['name']}: "
                    f"{clock(segment['start'])} → "
                    f"{clock(segment['end'])}  "
                    f"({duration(segment['end'] - segment['start'])})"
                ),
                fill=TEXT,
                font=f_body,
            )

            y += 39

        if model.get(
            "note"
        ):
            y += 8

            y = self.v8_draw_wrapped(
                draw,
                (
                    45,
                    y,
                ),
                (
                    "Note: "
                    + model[
                        "note"
                    ]
                ),
                f_body,
                ACCENT,
                145,
            )

        y += 24

        draw.text(
            (
                45,
                y,
            ),
            GITHUB_URL,
            fill=MUTED,
            font=f_small,
        )

        image = image.crop(
            (
                0,
                0,
                width,
                min(
                    height,
                    y + 60,
                ),
            )
        )

        image.save(
            path
        )

        messagebox.showinfo(
            "PNG export",
            f"Saved focused-model report:\n{path}",
        )

    def export_full_report_png(
        self,
    ):
        if not self.result:
            messagebox.showinfo(
                "PNG export",
                "Fetch prayer times first.",
            )

            return

        if not PIL_AVAILABLE:
            messagebox.showerror(
                "PNG export",
                "Install Pillow first:\npython -m pip install pillow",
            )

            return

        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[
                (
                    "PNG image",
                    "*.png",
                )
            ],
            initialfile=(
                f"dawud_detailed_report_"
                f"{self.selected_date.isoformat()}.png"
            ),
        )

        if not path:
            return

        r = self.result
        core = r[
            "core"
        ]

        models = r[
            "models"
        ]

        settings = r[
            "settings"
        ]

        model_heights = [
            (
                390
                + 34
                * len(
                    model.get(
                        "segments",
                        [],
                    )
                )
            )
            for model in models
        ]

        width = 1900

        height = (
            1350
            + sum(
                model_heights
            )
            + 520
        )

        image = Image.new(
            "RGB",
            (
                width,
                height,
            ),
            BG,
        )

        draw = ImageDraw.Draw(
            image
        )

        f_title = self.v8_pil_font(
            42,
            True,
        )

        f_h = self.v8_pil_font(
            25,
            True,
        )

        f_body = self.v8_pil_font(
            18,
        )

        f_small = self.v8_pil_font(
            14,
        )

        f_bold = self.v8_pil_font(
            18,
            True,
        )

        # Islamic geometric top texture.
        for cx in range(
            38,
            width - 20,
            82,
        ):
            pts = []

            for i in range(16):
                angle = (
                    -math.pi / 2
                    + i
                    * math.pi
                    / 8
                )

                radius = (
                    17
                    if i % 2 == 0
                    else 7
                )

                pts.append(
                    (
                        cx
                        + math.cos(
                            angle
                        )
                        * radius,
                        34
                        + math.sin(
                            angle
                        )
                        * radius,
                    )
                )

            draw.polygon(
                pts,
                outline=BORDER,
            )

        y = 70

        draw.text(
            (
                48,
                y,
            ),
            "Night of Dawud — Detailed Planner Report",
            fill=TEXT,
            font=f_title,
        )

        y += 58

        method_data = METHODS.get(
            r[
                "method"
            ],
            {},
        )

        draw.text(
            (
                48,
                y,
            ),
            (
                f"{r['city']}, {r['country']} • "
                f"{r['date'].strftime('%A, %d %B %Y')} • "
                f"{method_data.get('name', r['method'])}"
            ),
            fill=ACCENT,
            font=f_body,
        )

        y += 52

        # Prayer nodes / times
        draw.text(
            (
                48,
                y,
            ),
            "Prayer nodes",
            fill=ACCENT,
            font=f_h,
        )

        y += 42

        timings = r[
            "api"
        ][
            "today_data"
        ][
            "timings"
        ]

        prayer_items = []

        for name in (
            "Fajr",
            "Sunrise",
            "Dhuhr",
            "Asr",
            "Maghrib",
            "Isha",
        ):
            prayer_items.append(
                (
                    name,
                    clock(
                        prayer_datetime(
                            r[
                                "date"
                            ],
                            timings[
                                name
                            ],
                        )
                    ),
                )
            )

        prayer_items.append(
            (
                "Next Fajr",
                clock(
                    core[
                        "fajr"
                    ]
                ),
            )
        )

        x = 48

        for label, value in prayer_items:
            draw.rounded_rectangle(
                (
                    x,
                    y,
                    x + 230,
                    y + 70,
                ),
                radius=9,
                fill=CARD,
                outline=BORDER,
            )

            draw.text(
                (
                    x + 11,
                    y + 10,
                ),
                label,
                fill=MUTED,
                font=f_small,
            )

            draw.text(
                (
                    x + 11,
                    y + 38,
                ),
                value,
                fill=TEXT,
                font=f_body,
            )

            x += 245

        y += 105

        # Settings and corrected travel logic.
        draw.text(
            (
                48,
                y,
            ),
            "Planning settings & routine logic",
            fill=ACCENT,
            font=f_h,
        )

        y += 42

        setting_lines = [
            (
                f"Maghrib: {settings['maghrib_place']} • "
                f"prayer {settings['maghrib_prayer_minutes']}m • "
                f"iqama +{settings['maghrib_iqama_minutes']}m "
                f"(iqama ignored at Home)"
            ),
            (
                f"Isha: {settings['isha_place']} • "
                f"prayer {settings['isha_prayer_minutes']}m • "
                f"iqama +{settings['isha_iqama_minutes']}m "
                f"(iqama ignored at Home)"
            ),
            (
                f"Mosque travel one way: {settings['travel_minutes']}m • "
                f"Fall-asleep buffer: {settings['sleep_latency_minutes']}m • "
                f"Sleep-cycle planning: {settings['sleep_cycle_minutes']}m"
            ),
            (
                "Mosque timing rule: outbound travel is inside the adhan→iqama "
                "waiting window; return travel is AFTER prayer and consumes "
                "sleep/awake time."
            ),
        ]

        for line in setting_lines:
            y = self.v8_draw_wrapped(
                draw,
                (
                    66,
                    y,
                ),
                line,
                f_body,
                TEXT,
                165,
                4,
            )

            y += 5

        y += 12

        # Standard full-night math.
        draw.text(
            (
                48,
                y,
            ),
            "Standard Maghrib → Fajr night mathematics",
            fill=ACCENT,
            font=f_h,
        )

        y += 42

        full_math = [
            (
                f"Night = {duration(core['night'])} "
                f"({clock(core['maghrib'])} → {clock(core['fajr'])})"
            ),
            (
                f"1/2 = {duration(core['half'])} • "
                f"boundary {clock(core['wake'])}"
            ),
            (
                f"1/3 = {duration(core['third'])} • "
                f"last third starts {clock(core['last_third'])}"
            ),
            (
                f"1/6 = {duration(core['sixth'])} • "
                f"final sixth starts {clock(core['final_sixth'])}"
            ),
        ]

        for line in full_math:
            draw.text(
                (
                    66,
                    y,
                ),
                line,
                fill=TEXT,
                font=f_body,
            )

            y += 31

        y += 18

        # Prayer routine event breakdown.
        draw.text(
            (
                48,
                y,
            ),
            "Prayer routines",
            fill=ACCENT,
            font=f_h,
        )

        y += 42

        for routine in (
            r[
                "maghrib_routine"
            ],
            r[
                "isha_routine"
            ],
        ):
            draw.text(
                (
                    58,
                    y,
                ),
                (
                    f"{routine['name']} — "
                    f"{routine['place']}"
                ),
                fill=TEXT,
                font=f_bold,
            )

            y += 31

            draw.text(
                (
                    78,
                    y,
                ),
                (
                    f"Adhan {clock(routine['start'])} • "
                    f"Prayer {clock(routine['prayer_start'])} → "
                    f"{clock(routine['prayer_end'])}"
                ),
                fill=MUTED,
                font=f_body,
            )

            y += 29

            for segment in routine.get(
                "segments",
                [],
            ):
                draw.text(
                    (
                        96,
                        y,
                    ),
                    (
                        f"• {segment['name']}: "
                        f"{clock(segment['start'])} → "
                        f"{clock(segment['end'])} "
                        f"({duration(segment['end'] - segment['start'])})"
                    ),
                    fill=TEXT,
                    font=f_small,
                )

                y += 25

            y += 12

        # Legend
        draw.text(
            (
                48,
                y,
            ),
            "Legend",
            fill=ACCENT,
            font=f_h,
        )

        y += 40

        legend_x = 62

        for label, color in (
            (
                "Sleep",
                SLEEP_COLOR,
            ),
            (
                "Qiyam / Prayer",
                PRAYER_COLOR,
            ),
            (
                "Post-Isha awake",
                AWAKE_COLOR,
            ),
            (
                "Travel",
                TRAVEL_COLOR,
            ),
            (
                "Iqama wait",
                WAIT_COLOR,
            ),
            (
                "Sleep cycle",
                CYCLE_COLOR,
            ),
        ):
            draw.rectangle(
                (
                    legend_x,
                    y,
                    legend_x + 18,
                    y + 18,
                ),
                fill=color,
            )

            draw.text(
                (
                    legend_x + 27,
                    y - 1,
                ),
                label,
                fill=TEXT,
                font=f_small,
            )

            legend_x += 260

        y += 60

        # Every model with nodes + model-specific night window.
        draw.text(
            (
                48,
                y,
            ),
            "All models",
            fill=ACCENT,
            font=f_h,
        )

        y += 45

        for model, model_height in zip(
            models,
            model_heights,
        ):
            box_top = y

            draw.rounded_rectangle(
                (
                    36,
                    box_top,
                    width - 36,
                    box_top
                    + model_height
                    - 10,
                ),
                radius=12,
                fill=PANEL,
                outline=BORDER,
            )

            draw.text(
                (
                    58,
                    y + 13,
                ),
                model[
                    "name"
                ],
                fill=TEXT,
                font=f_h,
            )

            y += 52

            model_start = model_night_start(
                model,
                core,
            )

            model_end = model_night_end(
                model,
                core,
            )

            draw.text(
                (
                    58,
                    y,
                ),
                (
                    f"Model night {duration(model_night_length(model, core))} "
                    f"({clock(model_start)} → {clock(model_end)}) • "
                    f"1/2 {duration(model_half_duration(model, core))} • "
                    f"1/3 {duration(model_third_duration(model, core))} • "
                    f"1/6 {duration(model_sixth_duration(model, core))}"
                ),
                fill=ACCENT,
                font=f_small,
            )

            y += 30

            draw.text(
                (
                    58,
                    y,
                ),
                (
                    f"Sleep {duration(model['total_sleep'])} • "
                    f"Qiyam {duration(model['qiyam'])} • "
                    f"Post-Isha awake "
                    f"{duration(post_isha_awake_time(model, core))} • "
                    f"Wake {clock(model['wake'])} • "
                    f"Sleep again {clock(model['sleep_again'])}"
                ),
                fill=MUTED,
                font=f_small,
            )

            y += 64

            y = self.v9_draw_png_timeline(
                draw,
                model,
                core,
                y,
                95,
                width - 95,
                f_body,
                f_small,
                16,
            )

            y += 10

            y = self.v8_draw_wrapped(
                draw,
                (
                    58,
                    y,
                ),
                model.get(
                    "description",
                    "",
                ),
                f_small,
                MUTED,
                180,
                4,
            )

            y += 7

            for segment in model.get(
                "segments",
                [],
            ):
                draw.text(
                    (
                        78,
                        y,
                    ),
                    (
                        f"• {segment['name']}: "
                        f"{clock(segment['start'])} → "
                        f"{clock(segment['end'])} "
                        f"({duration(segment['end'] - segment['start'])})"
                    ),
                    fill=TEXT,
                    font=f_small,
                )

                y += 27

            if model.get(
                "note"
            ):
                y = self.v8_draw_wrapped(
                    draw,
                    (
                        78,
                        y,
                    ),
                    (
                        "Note: "
                        + model[
                            "note"
                        ]
                    ),
                    f_small,
                    ACCENT,
                    175,
                    4,
                )

            y = (
                box_top
                + model_height
            )

        y += 24

        # Hadith/source and GitHub footer.
        draw.text(
            (
                48,
                y,
            ),
            "Hadith / source",
            fill=ACCENT,
            font=f_h,
        )

        y += 40

        y = self.v8_draw_wrapped(
            draw,
            (
                58,
                y,
            ),
            HADITH_TEXT,
            f_body,
            TEXT,
            165,
            5,
        )

        draw.text(
            (
                58,
                y + 8,
            ),
            (
                "Sahih al-Bukhari 1131 • "
                "https://sunnah.com/bukhari:1131"
            ),
            fill=ACCENT,
            font=f_small,
        )

        y += 44

        draw.text(
            (
                58,
                y,
            ),
            (
                f"GitHub: {GITHUB_URL}"
            ),
            fill=MUTED,
            font=f_small,
        )

        image = image.crop(
            (
                0,
                0,
                width,
                min(
                    height,
                    y + 70,
                ),
            )
        )

        image.save(
            path
        )

        messagebox.showinfo(
            "PNG export",
            f"Saved detailed report:\n{path}",
        )



# ============================================================
# V10 — FLEXIBLE CUSTOM MODEL MAKER / METHOD EXPLAINER
# ============================================================

class DawudPlannerAppV10(DawudPlannerAppV9):
    # --------------------------------------------------------
    # Prayer methods explainer
    # --------------------------------------------------------

    def v10_open_prayer_methods(
        self,
    ):
        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            "Prayer calculation methods"
        )

        popup.geometry(
            "880x620"
        )

        popup.minsize(
            760,
            520,
        )

        popup.configure(
            bg=BG
        )

        popup.transient(
            self.root
        )

        tk.Label(
            popup,
            text="Prayer calculation methods",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(
            anchor="w",
            padx=16,
            pady=(14, 2),
        )

        tk.Label(
            popup,
            text=(
                "The selected method tells the prayer-times API which calculation "
                "convention to use. The biggest differences are normally the "
                "Fajr and Isha twilight calculations and method-specific offsets. "
                "It does not change your prayer duration, mosque travel, or iqama settings."
            ),
            bg=BG,
            fg=MUTED,
            wraplength=830,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(
            anchor="w",
            padx=16,
            pady=(0, 10),
        )

        current_method = self.method_map.get(
            self.method_combo.get(),
            DEFAULT_METHOD,
        )

        holder = tk.Frame(
            popup,
            bg=BG,
        )

        holder.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(0, 12),
        )

        for index, (
            method_id,
            data,
        ) in enumerate(
            METHODS.items()
        ):
            card = tk.Frame(
                holder,
                bg=(
                    CARD_2
                    if method_id
                    == current_method
                    else CARD
                ),
                highlightbackground=(
                    ACCENT
                    if method_id
                    == current_method
                    else BORDER
                ),
                highlightthickness=1,
            )

            card.pack(
                fill="x",
                pady=4,
            )

            top = tk.Frame(
                card,
                bg=card[
                    "bg"
                ],
            )

            top.pack(
                fill="x",
                padx=10,
                pady=(8, 2),
            )

            tk.Label(
                top,
                text=(
                    f"{data['short']} — "
                    f"{data['name']}"
                ),
                bg=card[
                    "bg"
                ],
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
            ).pack(
                side="left",
            )

            if (
                method_id
                == current_method
            ):
                tk.Label(
                    top,
                    text="CURRENT",
                    bg=ACCENT,
                    fg="#111111",
                    font=("Segoe UI", 6, "bold"),
                    padx=6,
                    pady=2,
                ).pack(
                    side="right",
                )

            tk.Label(
                card,
                text=data[
                    "info"
                ],
                bg=card[
                    "bg"
                ],
                fg=MUTED,
                wraplength=810,
                justify="left",
                font=("Segoe UI", 8),
            ).pack(
                anchor="w",
                padx=10,
                pady=(0, 8),
            )

        note = tk.Frame(
            popup,
            bg=CARD_2,
            highlightbackground=ACCENT_DARK,
            highlightthickness=1,
        )

        note.pack(
            fill="x",
            padx=16,
            pady=(0, 14),
        )

        tk.Label(
            note,
            text=(
                "Local mosque timetables can still differ by a few minutes from an "
                "API calculation. Use the method your local authority or mosque follows "
                "when you want the planner to match that timetable as closely as possible."
            ),
            bg=CARD_2,
            fg=TEXT,
            wraplength=820,
            justify="left",
            font=("Segoe UI", 8),
        ).pack(
            anchor="w",
            padx=10,
            pady=9,
        )

    # --------------------------------------------------------
    # Custom Model Maker
    # --------------------------------------------------------

    def open_custom_model_builder(
        self,
    ):
        """
        V10 custom model editor.

        Only the actual adhan nodes (Maghrib, Isha, Fajr) are locked because
        they come from the prayer-times API.

        Routine points such as iqama, prayer end, departure and home-arrival
        are normal editable points:
          - drag them
          - type an exact time
          - rename them
          - delete them
          - add as many extra points as desired
        """
        if not self.result:
            messagebox.showinfo(
                "Custom Model Maker",
                "Fetch prayer times first.",
            )
            return

        r = self.result
        core = r[
            "core"
        ]

        mag = r[
            "maghrib_routine"
        ]

        isha = r[
            "isha_routine"
        ]

        popup = tk.Toplevel(
            self.root
        )

        popup.title(
            "Custom Model Maker"
        )

        popup.geometry(
            "1160x690"
        )

        popup.minsize(
            980,
            600,
        )

        popup.configure(
            bg=PANEL
        )

        popup.transient(
            self.root
        )

        popup.grab_set()

        tk.Label(
            popup,
            text="Custom Model Maker",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(
            anchor="w",
            padx=16,
            pady=(14, 2),
        )

        tk.Label(
            popup,
            text=(
                "Maghrib, Isha and Fajr adhan nodes are locked. Everything else "
                "is yours: move routine markers, rename them, change their exact "
                "time, delete them, or add unlimited extra points."
            ),
            bg=PANEL,
            fg=MUTED,
            wraplength=1100,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(
            anchor="w",
            padx=16,
            pady=(0, 9),
        )

        topbar = tk.Frame(
            popup,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        topbar.pack(
            fill="x",
            padx=16,
            pady=(0, 8),
        )

        tk.Label(
            topbar,
            text="Model name",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(
            side="left",
            padx=(10, 5),
            pady=8,
        )

        name_entry = tk.Entry(
            topbar,
            bg=CARD_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=24,
        )

        name_entry.pack(
            side="left",
            ipady=4,
            padx=(0, 10),
        )

        name_entry.insert(
            0,
            self.custom_model_name
            or "My custom model",
        )

        body = tk.Frame(
            popup,
            bg=PANEL,
        )

        body.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(0, 8),
        )

        timeline_wrap = tk.Frame(
            body,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        timeline_wrap.pack(
            side="left",
            fill="both",
            expand=True,
            padx=(0, 8),
        )

        editor = tk.Frame(
            body,
            bg=CARD,
            width=290,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        editor.pack(
            side="right",
            fill="y",
        )

        editor.pack_propagate(
            False
        )

        canvas = tk.Canvas(
            timeline_wrap,
            bg=CARD,
            highlightthickness=0,
        )

        canvas.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        points = []
        segment_kinds = []
        next_id = [
            1
        ]
        selected_id = [
            None
        ]
        dragging_id = [
            None
        ]

        def add_point(
            dt,
            label,
            locked=False,
            source="custom",
        ):
            # Ignore points outside the actual Maghrib→Fajr display window.
            if (
                dt
                < core[
                    "maghrib"
                ]
                or dt
                > core[
                    "fajr"
                ]
            ):
                return None

            point = {
                "id": next_id[
                    0
                ],
                "time": dt,
                "label": label,
                "locked": locked,
                "source": source,
            }

            next_id[
                0
            ] += 1

            points.append(
                point
            )

            return point

        def ordered_points(
        ):
            # Keep only one point at the exact same second. Locked prayer nodes
            # win if a user marker happens to land exactly on them.
            by_time = {}

            for point in points:
                key = round(
                    point[
                        "time"
                    ].timestamp()
                )

                existing = by_time.get(
                    key
                )

                if (
                    existing
                    is None
                    or (
                        point[
                            "locked"
                        ]
                        and not existing[
                            "locked"
                        ]
                    )
                ):
                    by_time[
                        key
                    ] = point

            return sorted(
                by_time.values(),
                key=lambda p: p[
                    "time"
                ],
            )

        def normalize_segments(
            default="sleep",
        ):
            needed = max(
                len(
                    ordered_points()
                )
                - 1,
                0,
            )

            while (
                len(
                    segment_kinds
                )
                < needed
            ):
                segment_kinds.append(
                    default
                )

            del segment_kinds[
                needed:
            ]

        def point_exists_near(
            dt,
            seconds=30,
        ):
            return any(
                abs(
                    (
                        point[
                            "time"
                        ]
                        - dt
                    ).total_seconds()
                )
                <= seconds
                for point in points
            )

        def add_routine_point(
            dt,
            label,
        ):
            if (
                dt is None
                or point_exists_near(
                    dt
                )
            ):
                return

            add_point(
                dt,
                label,
                False,
                "routine",
            )

        def load_current_routine_points(
            do_redraw=True,
        ):
            # These are deliberately NOT locked.
            # They start from the current settings but can be edited freely.
            routine_points = []

            for routine in (
                mag,
                isha,
            ):
                name = routine[
                    "name"
                ]

                if routine[
                    "place"
                ] == "Mosque":
                    routine_points.extend(
                        [
                            (
                                routine[
                                    "departure"
                                ],
                                f"{name} depart",
                            ),
                            (
                                routine[
                                    "arrival"
                                ],
                                f"{name} mosque arrival",
                            ),
                            (
                                routine[
                                    "iqama_time"
                                ],
                                f"{name} iqama",
                            ),
                        ]
                    )

                routine_points.extend(
                    [
                        (
                            routine[
                                "prayer_end"
                            ],
                            f"{name} prayer end",
                        ),
                    ]
                )

                if (
                    routine[
                        "place"
                    ] == "Mosque"
                ):
                    routine_points.append(
                        (
                            routine[
                                "end"
                            ],
                            f"{name} home",
                        )
                    )

            for dt, label in routine_points:
                add_routine_point(
                    dt,
                    label,
                )

            normalize_segments(
                "sleep"
            )

            if do_redraw:
                redraw()

        # Prayer-time API nodes are the only locked nodes.
        add_point(
            core[
                "maghrib"
            ],
            "Maghrib adhan",
            True,
            "prayer",
        )

        add_point(
            core[
                "isha"
            ],
            "Isha adhan",
            True,
            "prayer",
        )

        add_point(
            core[
                "fajr"
            ],
            "Fajr adhan",
            True,
            "prayer",
        )

        # Load routine markers by default, but keep them editable.
        # redraw() is defined later in this function.
        load_current_routine_points(
            do_redraw=False
        )

        normalize_segments(
            "sleep"
        )

        ordered = ordered_points()

        # Default broad interpretation: before Isha = Qiyam/prayer,
        # after Isha = sleep. Inserted routine points inherit those labels.
        segment_kinds.clear()

        for index in range(
            len(
                ordered
            )
            - 1
        ):
            if (
                ordered[
                    index + 1
                ][
                    "time"
                ]
                <= core[
                    "isha"
                ]
            ):
                segment_kinds.append(
                    "prayer"
                )
            else:
                segment_kinds.append(
                    "sleep"
                )

        # ---------------- Editor controls ----------------

        tk.Label(
            editor,
            text="Selected point",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(
            anchor="w",
            padx=12,
            pady=(14, 3),
        )

        selected_label = tk.Label(
            editor,
            text="Click a point",
            bg=CARD,
            fg=ACCENT,
            wraplength=255,
            justify="left",
            font=("Segoe UI", 9),
        )

        selected_label.pack(
            anchor="w",
            padx=12,
            pady=(0, 8),
        )

        tk.Label(
            editor,
            text="Point label",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            anchor="w",
            padx=12,
        )

        point_name_entry = tk.Entry(
            editor,
            bg=CARD_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )

        point_name_entry.pack(
            fill="x",
            padx=12,
            pady=(2, 8),
            ipady=4,
        )

        tk.Label(
            editor,
            text="Exact time (HH:MM, 24-hour)",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            anchor="w",
            padx=12,
        )

        point_time_entry = tk.Entry(
            editor,
            bg=CARD_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )

        point_time_entry.pack(
            fill="x",
            padx=12,
            pady=(2, 4),
            ipady=4,
        )

        split_info = tk.Label(
            editor,
            text="",
            bg=CARD,
            fg=MUTED,
            justify="left",
            font=("Segoe UI", 8),
        )

        split_info.pack(
            anchor="w",
            padx=12,
            pady=(0, 8),
        )

        activity_values = (
            "Sleep",
            "Qiyam / Prayer",
            "Awake",
        )

        tk.Label(
            editor,
            text="LEFT segment",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            anchor="w",
            padx=12,
        )

        left_combo = ttk.Combobox(
            editor,
            values=activity_values,
            state="disabled",
        )

        left_combo.pack(
            fill="x",
            padx=12,
            pady=(2, 7),
        )

        tk.Label(
            editor,
            text="RIGHT segment",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 7),
        ).pack(
            anchor="w",
            padx=12,
        )

        right_combo = ttk.Combobox(
            editor,
            values=activity_values,
            state="disabled",
        )

        right_combo.pack(
            fill="x",
            padx=12,
            pady=(2, 8),
        )

        label_to_kind = {
            "Sleep": "sleep",
            "Qiyam / Prayer": "prayer",
            "Awake": "awake",
        }

        kind_to_label = {
            value: key
            for key, value
            in label_to_kind.items()
        }

        def find_point(
            point_id,
        ):
            return next(
                (
                    point
                    for point
                    in points
                    if point[
                        "id"
                    ]
                    == point_id
                ),
                None,
            )

        def parse_user_time(
            value,
        ):
            match = re.fullmatch(
                r"\s*(\d{1,2}):(\d{2})\s*",
                value,
            )

            if not match:
                raise ValueError(
                    "Use HH:MM, for example 21:35."
                )

            hour = int(
                match.group(
                    1
                )
            )

            minute = int(
                match.group(
                    2
                )
            )

            if (
                hour > 23
                or minute > 59
            ):
                raise ValueError(
                    "Time must be a valid 24-hour time."
                )

            dt = core[
                "maghrib"
            ].replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )

            # Times after midnight belong to the following date.
            if (
                dt
                < core[
                    "maghrib"
                ]
            ):
                dt += timedelta(
                    days=1
                )

            if not (
                core[
                    "maghrib"
                ]
                <= dt
                <= core[
                    "fajr"
                ]
            ):
                raise ValueError(
                    "Point must be between Maghrib and next Fajr."
                )

            return dt

        def update_editor_controls(
        ):
            point = find_point(
                selected_id[
                    0
                ]
            )

            if not point:
                selected_label.config(
                    text="Click a point"
                )

                point_name_entry.delete(
                    0,
                    tk.END,
                )

                point_time_entry.delete(
                    0,
                    tk.END,
                )

                point_name_entry.config(
                    state="disabled"
                )

                point_time_entry.config(
                    state="disabled"
                )

                split_info.config(
                    text=""
                )

                left_combo.set("")
                right_combo.set("")

                left_combo.config(
                    state="disabled"
                )

                right_combo.config(
                    state="disabled"
                )

                return

            ordered = ordered_points()

            index = next(
                (
                    idx
                    for idx, candidate
                    in enumerate(
                        ordered
                    )
                    if candidate[
                        "id"
                    ]
                    == point[
                        "id"
                    ]
                ),
                None,
            )

            selected_label.config(
                text=(
                    point[
                        "label"
                    ]
                    + (
                        "  • locked adhan node"
                        if point[
                            "locked"
                        ]
                        else "  • editable point"
                    )
                )
            )

            # Fill first, then lock the fields if this is an adhan node.
            point_name_entry.config(
                state="normal"
            )
            point_time_entry.config(
                state="normal"
            )

            point_name_entry.delete(
                0,
                tk.END,
            )
            point_name_entry.insert(
                0,
                point[
                    "label"
                ],
            )

            point_time_entry.delete(
                0,
                tk.END,
            )
            point_time_entry.insert(
                0,
                point[
                    "time"
                ].strftime(
                    "%H:%M"
                ),
            )

            if point[
                "locked"
            ]:
                point_name_entry.config(
                    state="disabled"
                )
                point_time_entry.config(
                    state="disabled"
                )

            left_duration = (
                duration(
                    point[
                        "time"
                    ]
                    - ordered[
                        index - 1
                    ][
                        "time"
                    ]
                )
                if (
                    index is not None
                    and index > 0
                )
                else "—"
            )

            right_duration = (
                duration(
                    ordered[
                        index + 1
                    ][
                        "time"
                    ]
                    - point[
                        "time"
                    ]
                )
                if (
                    index is not None
                    and index
                    < len(
                        ordered
                    )
                    - 1
                )
                else "—"
            )

            split_info.config(
                text=(
                    f"Time: {clock(point['time'])}\n"
                    f"Left split: {left_duration}\n"
                    f"Right split: {right_duration}"
                )
            )

            if (
                index is not None
                and index > 0
            ):
                left_combo.config(
                    state="readonly"
                )

                left_combo.set(
                    kind_to_label.get(
                        segment_kinds[
                            index - 1
                        ],
                        "Awake",
                    )
                )

            else:
                left_combo.set("")
                left_combo.config(
                    state="disabled"
                )

            if (
                index is not None
                and index
                < len(
                    ordered
                )
                - 1
            ):
                right_combo.config(
                    state="readonly"
                )

                right_combo.set(
                    kind_to_label.get(
                        segment_kinds[
                            index
                        ],
                        "Awake",
                    )
                )

            else:
                right_combo.set("")
                right_combo.config(
                    state="disabled"
                )

        def apply_point_changes(
        ):
            point = find_point(
                selected_id[
                    0
                ]
            )

            if (
                not point
                or point[
                    "locked"
                ]
            ):
                return

            try:
                new_time = parse_user_time(
                    point_time_entry.get()
                )

            except ValueError as error:
                messagebox.showerror(
                    "Custom Model Maker",
                    str(
                        error
                    ),
                    parent=popup,
                )

                return

            ordered = ordered_points()

            old_index = next(
                (
                    idx
                    for idx, candidate
                    in enumerate(
                        ordered
                    )
                    if candidate[
                        "id"
                    ]
                    == point[
                        "id"
                    ]
                ),
                None,
            )

            if old_index is None:
                return

            minimum = (
                ordered[
                    old_index - 1
                ][
                    "time"
                ]
                + timedelta(
                    minutes=1
                )
                if old_index > 0
                else core[
                    "maghrib"
                ]
            )

            maximum = (
                ordered[
                    old_index + 1
                ][
                    "time"
                ]
                - timedelta(
                    minutes=1
                )
                if old_index
                < len(
                    ordered
                )
                - 1
                else core[
                    "fajr"
                ]
            )

            if not (
                minimum
                <= new_time
                <= maximum
            ):
                messagebox.showerror(
                    "Custom Model Maker",
                    (
                        "That time would cross another point. "
                        "Move/delete the neighboring point first."
                    ),
                    parent=popup,
                )

                return

            point[
                "time"
            ] = new_time

            point[
                "label"
            ] = (
                point_name_entry.get().strip()
                or "Custom point"
            )

            update_editor_controls()
            redraw()

        tk.Button(
            editor,
            text="Apply point changes",
            command=apply_point_changes,
            bg=CARD_2,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="#111111",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=9,
            pady=5,
        ).pack(
            fill="x",
            padx=12,
            pady=(0, 10),
        )

        def apply_left(
            event=None,
        ):
            point = find_point(
                selected_id[
                    0
                ]
            )

            if not point:
                return

            ordered = ordered_points()

            index = next(
                (
                    idx
                    for idx, candidate
                    in enumerate(
                        ordered
                    )
                    if candidate[
                        "id"
                    ]
                    == point[
                        "id"
                    ]
                ),
                None,
            )

            if (
                index is not None
                and index > 0
            ):
                segment_kinds[
                    index - 1
                ] = label_to_kind[
                    left_combo.get()
                ]

                redraw()

        def apply_right(
            event=None,
        ):
            point = find_point(
                selected_id[
                    0
                ]
            )

            if not point:
                return

            ordered = ordered_points()

            index = next(
                (
                    idx
                    for idx, candidate
                    in enumerate(
                        ordered
                    )
                    if candidate[
                        "id"
                    ]
                    == point[
                        "id"
                    ]
                ),
                None,
            )

            if (
                index is not None
                and index
                < len(
                    ordered
                )
                - 1
            ):
                segment_kinds[
                    index
                ] = label_to_kind[
                    right_combo.get()
                ]

                redraw()

        left_combo.bind(
            "<<ComboboxSelected>>",
            apply_left,
        )

        right_combo.bind(
            "<<ComboboxSelected>>",
            apply_right,
        )

        # ---------------- Timeline geometry ----------------

        def x_from_time(
            dt,
            width,
        ):
            ratio = (
                (
                    dt
                    - core[
                        "maghrib"
                    ]
                ).total_seconds()
                / core[
                    "night"
                ].total_seconds()
            )

            return (
                38
                + ratio
                * (
                    width - 76
                )
            )

        def time_from_x(
            x,
            width,
        ):
            ratio = max(
                0.0,
                min(
                    1.0,
                    (
                        x - 38
                    )
                    / max(
                        width - 76,
                        1,
                    ),
                ),
            )

            return (
                core[
                    "maghrib"
                ]
                + core[
                    "night"
                ]
                * ratio
            )

        def redraw(
            event=None,
        ):
            canvas.delete(
                "all"
            )

            width = max(
                canvas.winfo_width(),
                700,
            )

            height = max(
                canvas.winfo_height(),
                340,
            )

            y = (
                height
                * 0.53
            )

            ordered = ordered_points()

            normalize_segments()

            # Decorative Islamic band.
            for x in range(
                45,
                width,
                78,
            ):
                pts = []

                for i in range(
                    16
                ):
                    angle = (
                        -math.pi / 2
                        + i
                        * math.pi
                        / 8
                    )

                    radius = (
                        13
                        if i % 2 == 0
                        else 5
                    )

                    pts.extend(
                        [
                            x
                            + math.cos(
                                angle
                            )
                            * radius,
                            34
                            + math.sin(
                                angle
                            )
                            * radius,
                        ]
                    )

                canvas.create_polygon(
                    pts,
                    outline=BORDER,
                    fill="",
                )

            color_map = {
                "sleep": SLEEP_COLOR,
                "prayer": PRAYER_COLOR,
                "awake": AWAKE_COLOR,
            }

            for index in range(
                len(
                    ordered
                )
                - 1
            ):
                p1 = ordered[
                    index
                ]

                p2 = ordered[
                    index + 1
                ]

                x1 = x_from_time(
                    p1[
                        "time"
                    ],
                    width,
                )

                x2 = x_from_time(
                    p2[
                        "time"
                    ],
                    width,
                )

                kind = segment_kinds[
                    index
                ]

                color = color_map[
                    kind
                ]

                canvas.create_line(
                    x1,
                    y,
                    x2,
                    y,
                    fill=color,
                    width=16,
                    capstyle=tk.ROUND,
                )

                # Always show duration; when very narrow, only the time fits.
                segment_duration = duration(
                    p2[
                        "time"
                    ]
                    - p1[
                        "time"
                    ]
                )

                if (
                    x2 - x1
                    > 80
                ):
                    label = (
                        f"{kind_to_label[kind]}\n"
                        f"{segment_duration}"
                    )

                elif (
                    x2 - x1
                    > 42
                ):
                    label = segment_duration

                else:
                    label = ""

                if label:
                    canvas.create_text(
                        (
                            x1
                            + x2
                        )
                        / 2,
                        y - 28,
                        text=label,
                        fill=color,
                        font=(
                            "Segoe UI",
                            8,
                            "bold",
                        ),
                        justify="center",
                    )

            for point in ordered:
                x = x_from_time(
                    point[
                        "time"
                    ],
                    width,
                )

                selected = (
                    point[
                        "id"
                    ]
                    == selected_id[
                        0
                    ]
                )

                if point[
                    "locked"
                ]:
                    color = ACCENT
                elif point[
                    "source"
                ] == "routine":
                    color = TRAVEL_COLOR
                else:
                    color = TEXT

                radius = (
                    9
                    if selected
                    else 7
                )

                canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill=color,
                    outline=(
                        "#FFFFFF"
                        if selected
                        else ""
                    ),
                    width=2,
                )

                canvas.create_text(
                    x,
                    y + 23,
                    text=(
                        f"{point['label']}\n"
                        f"{short_clock(point['time'])}"
                    ),
                    fill=color,
                    justify="center",
                    font=("Segoe UI", 7),
                )

            canvas.create_text(
                width / 2,
                height - 24,
                text=(
                    "Gold = locked adhan nodes • Blue = editable routine point • "
                    "White = custom point • click blank space to add another point"
                ),
                fill=MUTED,
                font=("Segoe UI", 8),
            )

        def near_point(
            x,
            width,
        ):
            best = None
            best_distance = 9999

            for point in ordered_points():
                px = x_from_time(
                    point[
                        "time"
                    ],
                    width,
                )

                distance = abs(
                    px - x
                )

                if (
                    distance
                    < best_distance
                ):
                    best = point
                    best_distance = distance

            return (
                best
                if best_distance
                <= 14
                else None
            )

        def on_press(
            event,
        ):
            width = max(
                canvas.winfo_width(),
                700,
            )

            point = near_point(
                event.x,
                width,
            )

            if point:
                selected_id[
                    0
                ] = point[
                    "id"
                ]

                if not point[
                    "locked"
                ]:
                    dragging_id[
                        0
                    ] = point[
                        "id"
                    ]

                update_editor_controls()
                redraw()

                return

            dt = time_from_x(
                event.x,
                width,
            )

            dt = max(
                core[
                    "maghrib"
                ]
                + timedelta(
                    minutes=1
                ),
                min(
                    core[
                        "fajr"
                    ]
                    - timedelta(
                        minutes=1
                    ),
                    dt,
                ),
            )

            ordered = ordered_points()

            inherited = "sleep"
            insertion_index = None

            for index in range(
                len(
                    ordered
                )
                - 1
            ):
                if (
                    ordered[
                        index
                    ][
                        "time"
                    ]
                    < dt
                    < ordered[
                        index + 1
                    ][
                        "time"
                    ]
                ):
                    inherited = segment_kinds[
                        index
                    ]

                    insertion_index = (
                        index
                        + 1
                    )

                    break

            point = add_point(
                dt,
                "Custom point",
                False,
                "custom",
            )

            if (
                point is None
            ):
                return

            if (
                insertion_index
                is not None
            ):
                segment_kinds.insert(
                    insertion_index,
                    inherited,
                )

            normalize_segments(
                inherited
            )

            selected_id[
                0
            ] = point[
                "id"
            ]

            update_editor_controls()
            redraw()

        def on_drag(
            event,
        ):
            if (
                dragging_id[
                    0
                ]
                is None
            ):
                return

            point = find_point(
                dragging_id[
                    0
                ]
            )

            if (
                not point
                or point[
                    "locked"
                ]
            ):
                return

            width = max(
                canvas.winfo_width(),
                700,
            )

            dt = time_from_x(
                event.x,
                width,
            )

            ordered = ordered_points()

            index = next(
                (
                    idx
                    for idx, candidate
                    in enumerate(
                        ordered
                    )
                    if candidate[
                        "id"
                    ]
                    == point[
                        "id"
                    ]
                ),
                None,
            )

            if (
                index is None
            ):
                return

            minimum = (
                ordered[
                    index - 1
                ][
                    "time"
                ]
                + timedelta(
                    minutes=1
                )
                if index > 0
                else core[
                    "maghrib"
                ]
            )

            maximum = (
                ordered[
                    index + 1
                ][
                    "time"
                ]
                - timedelta(
                    minutes=1
                )
                if index
                < len(
                    ordered
                )
                - 1
                else core[
                    "fajr"
                ]
            )

            point[
                "time"
            ] = max(
                minimum,
                min(
                    maximum,
                    dt,
                ),
            )

            update_editor_controls()
            redraw()

        def on_release(
            event,
        ):
            dragging_id[
                0
            ] = None

        canvas.bind(
            "<Button-1>",
            on_press,
        )

        canvas.bind(
            "<B1-Motion>",
            on_drag,
        )

        canvas.bind(
            "<ButtonRelease-1>",
            on_release,
        )

        canvas.bind(
            "<Configure>",
            redraw,
        )

        # ---------------- Bottom actions ----------------

        bottom = tk.Frame(
            popup,
            bg=PANEL,
        )

        bottom.pack(
            fill="x",
            padx=16,
            pady=(0, 14),
        )

        def delete_selected(
        ):
            point = find_point(
                selected_id[
                    0
                ]
            )

            if not point:
                return

            if point[
                "locked"
            ]:
                messagebox.showinfo(
                    "Custom Model Maker",
                    (
                        "Maghrib, Isha and Fajr adhan nodes come from the "
                        "prayer-times API, so those three nodes stay locked."
                    ),
                    parent=popup,
                )

                return

            ordered = ordered_points()

            index = next(
                (
                    idx
                    for idx, candidate
                    in enumerate(
                        ordered
                    )
                    if candidate[
                        "id"
                    ]
                    == point[
                        "id"
                    ]
                ),
                None,
            )

            points.remove(
                point
            )

            # Merge its right-hand segment into the left-hand segment.
            if (
                index is not None
                and 0
                < index
                < len(
                    ordered
                )
                - 1
                and index
                < len(
                    segment_kinds
                )
            ):
                del segment_kinds[
                    index
                ]

            normalize_segments()

            selected_id[
                0
            ] = None

            update_editor_controls()
            redraw()

        tk.Button(
            bottom,
            text="Delete selected point",
            command=delete_selected,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=11,
            pady=7,
        ).pack(
            side="left",
        )

        def remove_routine_points(
        ):
            points[
                :
            ] = [
                point
                for point
                in points
                if (
                    point[
                        "locked"
                    ]
                    or point[
                        "source"
                    ]
                    != "routine"
                )
            ]

            normalize_segments()

            selected_id[
                0
            ] = None

            update_editor_controls()
            redraw()

        tk.Button(
            bottom,
            text="Remove routine points",
            command=remove_routine_points,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD_2,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=11,
            pady=7,
        ).pack(
            side="left",
            padx=(5, 0),
        )

        tk.Button(
            bottom,
            text="Load current routine points",
            command=load_current_routine_points,
            bg=CARD_2,
            fg=ACCENT,
            activebackground=CARD,
            activeforeground=ACCENT,
            relief="flat",
            cursor="hand2",
            padx=11,
            pady=7,
        ).pack(
            side="left",
            padx=(5, 0),
        )

        def save_model(
        ):
            ordered = ordered_points()

            normalize_segments()

            spec = []

            activity_name = {
                "sleep": "Sleep",
                "prayer": "Qiyam / Prayer",
                "awake": "Awake",
            }

            for index in range(
                len(
                    ordered
                )
                - 1
            ):
                minutes = max(
                    1,
                    round(
                        (
                            ordered[
                                index + 1
                            ][
                                "time"
                            ]
                            - ordered[
                                index
                            ][
                                "time"
                            ]
                        ).total_seconds()
                        / 60
                    ),
                )

                spec.append(
                    {
                        "activity": activity_name[
                            segment_kinds[
                                index
                            ]
                        ],
                        "rule": "For minutes",
                        "value": minutes,
                    }
                )

            self.custom_model_name = (
                name_entry.get().strip()
                or "My custom model"
            )

            self.custom_model_spec = spec

            popup.destroy()

            self.recalculate_plan()

        tk.Button(
            bottom,
            text="Save custom model",
            command=save_model,
            bg=ACCENT,
            fg="#111111",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=7,
        ).pack(
            side="right",
        )

        def clear_custom(
        ):
            self.custom_model_name = None
            self.custom_model_spec = None

            popup.destroy()

            self.recalculate_plan()

        tk.Button(
            bottom,
            text="Remove saved custom model",
            command=clear_custom,
            bg=CARD_2,
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            padx=11,
            pady=7,
        ).pack(
            side="right",
            padx=(0, 6),
        )

        redraw()


# ============================================================
# MAIN
# ============================================================

def main():
    root = tk.Tk()
    DawudPlannerAppV10(root)
    root.mainloop()


if __name__ == "__main__":
    main()
