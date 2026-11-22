import customtkinter as ctk
from tkinter import filedialog, messagebox
import asyncio
import threading
import os
import calendar
from datetime import date, datetime, timezone
from local_data import (
    read_json, write_json, load_connection_details, save_connection_details,
    forget_connection_details,
)
from downloader import TelegramDownloader, group_folder, topic_folder, TopicFolderConflict, reset_channel_sync
from telethon import utils
from history import load_history, save_history
from diagnostics import record_issue, observe_future, async_exception_handler, open_diagnostics_folder

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

def format_bytes(value):
    value = max(0, value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def format_eta(seconds):
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {seconds:02d}s"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Media Downloader")
        self.geometry(f"{min(1280, self.winfo_screenwidth() - 80)}x{min(900, self.winfo_screenheight() - 80)}")
        self.resizable(True, True)
        self.minsize(700, min(700, self.winfo_screenheight() - 80))
        self.topic_checks = {}
        self.channel_buttons = {}
        self.media_checks = {}
        self.downloader = None
        self.loop = None
        self.channels = []
        self.senders = {}
        self.sender_id = None
        self.sender_generation = 0
        self.topics = {}
        self.topic_generation = 0
        self.busy = False
        self._normal_close_requested = False
        self._pane_weights = [1.0, 1.0, 1.0]
        self._split_weights = [1.0, 1.0]
        self._divider_drag = None
        self._preferences_job = None
        self._restoring = True
        self._login_credentials = None
        self._build()
        self._preferences_job = None
        self._restore_preferences()
        self._update_limit_controls()
        self._show_custom_options()
        self._update_settings_summary()
        self._restore_connection_details()
        self._restoring = False
        self._refresh_layout()
        for variable in [self.folder_path, self.limit_mode, self.reverse, self.all_media,
                         self.include_discussions, self.parallel_downloads, *self.media_checks.values()]:
            variable.trace_add("write", self._queue_preferences)
        for entry in (self.custom_ext, self.custom_limit, self.cutoff_date):
            entry.bind("<KeyRelease>", self._queue_preferences, add="+")
        self.protocol("WM_DELETE_WINDOW", self._close_window)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        surface = ("#ffffff", "#1b222c")
        sidebar = ("#f1f4f8", "#202a36")

        account = ctk.CTkFrame(self, fg_color=surface)
        account.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        account.grid_columnconfigure(0, weight=1)
        heading = ctk.CTkFrame(account, fg_color="transparent")
        heading.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        ctk.CTkLabel(heading, text="Telegram Media Downloader",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        self.account_toggle = ctk.CTkButton(heading, text="Hide login", width=100,
                                          command=self.toggle_account)
        self.account_toggle.pack(side="right")
        ctk.CTkButton(heading, text="Reset layout", width=100,
                      command=self.reset_layout).pack(side="right", padx=8)
        self.account_fields = ctk.CTkFrame(account, fg_color="transparent")
        self.account_fields.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        for column, (label, attr, placeholder) in enumerate([
            ("API ID", "api_id", "Your API ID"),
            ("API hash", "api_hash", "Your API hash"),
            ("Phone", "phone", "Include country code"),
        ]):
            self.account_fields.grid_columnconfigure(column, weight=1, uniform="account")
            field = ctk.CTkFrame(self.account_fields, fg_color="transparent")
            field.grid(row=0, column=column, sticky="ew", padx=4)
            ctk.CTkLabel(field, text=label).pack(anchor="w")
            entry = ctk.CTkEntry(field, width=120, placeholder_text=placeholder,
                                 show="*" if attr in ("api_hash", "phone") else "")
            entry.pack(fill="x")
            setattr(self, attr, entry)
        login_row = ctk.CTkFrame(self.account_fields, fg_color="transparent")
        login_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 0))
        login_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(login_row, text="Telegram code").grid(row=0, column=0, padx=(0, 8))
        self.otp = ctk.CTkEntry(login_row, placeholder_text="Check Telegram app", show="*")
        self.otp.grid(row=0, column=1, sticky="ew")
        self.otp_btn = ctk.CTkButton(login_row, text="Submit code", width=110,
                                   state="disabled", command=self.submit_otp)
        self.otp_btn.grid(row=0, column=2, padx=8)
        self.login_btn = ctk.CTkButton(login_row, text="Log in", width=100, command=self.login)
        self.login_btn.grid(row=0, column=3)
        self.remember_connection = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.account_fields, text="Remember connection details on this Mac",
            variable=self.remember_connection, command=self._connection_preference_changed).grid(row=2, column=0, columnspan=2,
                sticky="w", padx=4, pady=(10, 0))
        ctk.CTkButton(self.account_fields, text="Forget saved details", width=150,
            command=self.forget_saved_connection).grid(row=2, column=2, sticky="e", padx=4, pady=(10, 0))
        self.connection_status = ctk.CTkLabel(self.account_fields, text="", anchor="w")
        self.connection_status.grid(row=3, column=0, columnspan=3, sticky="ew", padx=4)
        self._account_visible = True

        self.workspace = ctk.CTkFrame(self, fg_color="transparent")
        self.workspace.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)
        self.workspace.grid_rowconfigure(1, weight=1)
        self.dividers = []
        for index in range(2):
            divider = ctk.CTkFrame(self.workspace, width=8, corner_radius=0,
                fg_color=("#d4dde7", "#3c495a"), cursor="sb_h_double_arrow")
            divider.bind("<ButtonPress-1>", lambda event, i=index: self._begin_pane_resize(i, event))
            divider.bind("<B1-Motion>", self._resize_panes)
            divider.bind("<ButtonRelease-1>", self._end_pane_resize)
            self.dividers.append(divider)
        self.pane_switch = ctk.CTkSegmentedButton(self.workspace,
            values=["Channels", "Topics", "Settings"], command=self.show_workspace_pane)
        self.pane_switch.set("Topics")
        self.channels_panel = ctk.CTkFrame(self.workspace, fg_color=sidebar)
        self.channels_panel.grid_propagate(False)
        self.channels_panel.grid_columnconfigure(0, weight=1)
        self.channels_panel.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self.channels_panel, text="Channels & groups",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
                         row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.channel_var = ctk.StringVar()
        self.channel_search = ctk.CTkComboBox(self.channels_panel, width=200,
            values=[], state="disabled", command=self.choose_channel_from_dropdown)
        self.channel_search.set("Log in to choose a channel")
        self.channel_search.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        self.channel_search.bind("<KeyRelease>", self.filter_channels)
        self.channel_search.bind("<Return>", self.choose_filtered_channel)
        self.channel_list = ctk.CTkScrollableFrame(self.channels_panel, width=180,
                                                  fg_color="transparent")
        self.channel_list.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        self.channel_hint = ctk.CTkLabel(self.channels_panel,
            text="Log in to load your library.", wraplength=185, justify="left", anchor="w")
        self.channel_hint.grid(row=3, column=0, sticky="ew", padx=12, pady=(4, 12))
        self.sync_reset_btn = ctk.CTkButton(self.channels_panel, text="Reset saved sync…",
            state="disabled", command=self.reset_selected_sync)
        self.sync_reset_btn.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.topics_panel = ctk.CTkFrame(self.workspace, fg_color=surface)
        self.topics_panel.grid_propagate(False)
        self.topics_panel.grid_columnconfigure(0, weight=1)
        self.topics_panel.grid_rowconfigure(4, weight=1)
        self.source_title = ctk.CTkLabel(self.topics_panel, text="Your library", anchor="w",
                                        font=ctk.CTkFont(size=20, weight="bold"), wraplength=300)
        self.source_title.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 4))
        self.topic_var = ctk.StringVar(value="Choose a channel or group to get started.")
        self.topic_status = ctk.CTkLabel(self.topics_panel, textvariable=self.topic_var,
                                        anchor="w", justify="left", wraplength=300)
        self.topic_status.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.topic_search = ctk.CTkComboBox(self.topics_panel, values=[],
            state="disabled", command=self.choose_topic_from_dropdown)
        self.topic_search.set("")
        self.topic_search.grid(row=2, column=0, sticky="ew", padx=18, pady=4)
        self.topic_search.bind("<KeyRelease>", self.filter_topics)
        self.topic_search.bind("<Return>", self.choose_filtered_topic)
        actions = ctk.CTkFrame(self.topics_panel, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=14, pady=8)
        self.select_topics_btn = ctk.CTkButton(actions, text="Select visible", width=115,
            state="disabled", command=lambda: self.select_topics(True))
        self.select_topics_btn.pack(side="left", padx=4)
        self.clear_topics_btn = ctk.CTkButton(actions, text="Clear", width=70,
            state="disabled", command=lambda: self.select_topics(False))
        self.clear_topics_btn.pack(side="left", padx=4)
        self.topic_list = ctk.CTkScrollableFrame(self.topics_panel, height=60,
                                                fg_color="transparent")
        self.topic_list.grid(row=4, column=0, sticky="nsew", padx=12, pady=4)
        self.topic_empty = ctk.CTkLabel(self.topic_list, text="Your topics will appear here.",
                                       wraplength=280, justify="left")
        self.topic_empty.pack(anchor="w", padx=6, pady=16)
        self.topic_count = ctk.CTkLabel(self.topics_panel, text="No topics selected", anchor="w",
                                       wraplength=300)
        self.topic_count.grid(row=5, column=0, sticky="ew", padx=18, pady=(4, 12))

        self.settings_panel = ctk.CTkScrollableFrame(self.workspace, width=300, fg_color=surface)
        settings = self.settings_panel
        ctk.CTkLabel(settings, text="Download settings", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(8, 4))
        self.include_discussions = ctk.BooleanVar(value=False)
        self.discussions_toggle = ctk.CTkCheckBox(settings, text="Include post discussions",
            variable=self.include_discussions, state="disabled", command=self._update_limit_controls)
        self.discussions_toggle.pack(anchor="w", padx=12, pady=(8, 4))
        self.discussions_hint = ctk.CTkLabel(settings, text="Available for broadcast channels.",
            wraplength=280, justify="left", anchor="w")
        self.discussions_hint.pack(fill="x", padx=12, pady=(0, 8))
        self.sender_filter = ctk.BooleanVar(value=False)
        self.sender_toggle = ctk.CTkCheckBox(settings, text="Only selected sender", variable=self.sender_filter,
                                            command=self._update_sender_status)
        self.sender_toggle.pack(anchor="w", padx=12, pady=(8, 4))
        sender_row = ctk.CTkFrame(settings, fg_color="transparent")
        sender_row.pack(fill="x", padx=12)
        self.sender_query = ctk.CTkComboBox(sender_row, width=160, values=[], state="disabled",
                                           command=self.choose_sender)
        self.sender_query.set("")
        self.sender_query.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.sender_query.bind("<Return>", lambda _event: self.find_sender())
        self.sender_query.bind("<KeyRelease>", self._sender_query_changed)
        self.sender_find = ctk.CTkButton(sender_row, text="Find", width=60,
                                        state="disabled", command=self.find_sender)
        self.sender_find.pack(side="right")
        self.sender_status = ctk.CTkLabel(settings, text="Everyone · Find @username, user ID or name",
                                         wraplength=280, justify="left", anchor="w")
        self.sender_status.pack(fill="x", padx=12, pady=(4, 8))
        ctk.CTkLabel(settings, text="Parallel downloads").pack(anchor="w", padx=12, pady=(6, 0))
        self.parallel_downloads = ctk.StringVar(value="2")
        self.parallel_menu = ctk.CTkOptionMenu(settings, values=["1", "2", "3", "4"],
                                              variable=self.parallel_downloads)
        self.parallel_menu.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkLabel(settings, text="Files at once · Choose 1 for a single download",
            wraplength=280, justify="left", anchor="w").pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(settings, text="Media types").pack(anchor="w", padx=12, pady=(8, 0))
        quick_row = ctk.CTkFrame(settings, fg_color="transparent")
        quick_row.pack(fill="x", padx=8)
        for column in range(3):
            quick_row.grid_columnconfigure(column, weight=1)
        for index, (label, value) in enumerate([
            ("Photos", "photo"), ("Videos", "video"), ("Audio", "audio"),
            ("PDF", ".pdf"), ("Word", ".docx"), ("Excel", ".xlsx"),
            ("ZIP", ".zip"), ("Custom", "custom"),
        ]):
            var = ctk.BooleanVar(value=value in ("photo", "video"))
            self.media_checks[value] = var
            ctk.CTkCheckBox(quick_row, text=label, width=75, variable=var,
                            command=self._show_custom_options if value == "custom" else None).grid(
                row=index//3, column=index%3, sticky="w", padx=4, pady=5)
        self.all_media = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(settings, text="All media types", variable=self.all_media).pack(
            anchor="w", padx=12, pady=(6, 12))
        self.limit_label = ctk.CTkLabel(settings, text="New files per topic / channel")
        self.limit_label.pack(anchor="w", padx=12)
        self.limit_mode = ctk.StringVar(value="all")
        self.limit_menu = ctk.CTkOptionMenu(settings,
            values=["All new files", "Last 10", "Last 20", "Last 50", "Last 100", "Custom number"],
            command=self._choose_limit)
        self.limit_menu.pack(fill="x", padx=12, pady=(2, 8))
        self.custom_limit = ctk.CTkEntry(settings, placeholder_text="Number of files, e.g. 23")
        self.custom_limit.bind("<Key>", lambda e: self.limit_mode.set("custom"))
        self.limit_mode.trace_add("write", lambda *_args: self._update_limit_controls())
        ctk.CTkLabel(settings, text="Download folder").pack(anchor="w", padx=12, pady=(6, 0))
        folder_row = ctk.CTkFrame(settings, fg_color="transparent")
        folder_row.pack(fill="x", padx=12, pady=(2, 12))
        self.folder_path = ctk.StringVar(value=os.path.expanduser("~/Downloads/Telegram"))
        ctk.CTkEntry(folder_row, width=120, textvariable=self.folder_path).pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(folder_row, text="Browse", width=70, command=self.browse).pack(side="right")
        self.advanced_toggle = ctk.CTkButton(settings, text="Dates, order & custom types ▸",
            fg_color="transparent", text_color=("#26384c", "#d8e6f5"),
            command=self.toggle_advanced)
        self.advanced_toggle.pack(fill="x", padx=8, pady=(4, 0))
        self.settings_summary = ctk.CTkLabel(settings, text="Newest first · All dates",
                                           anchor="w", justify="left", wraplength=285)
        self.settings_summary.pack(fill="x", padx=12, pady=(4, 8))
        self.advanced_fields = ctk.CTkFrame(settings, fg_color="transparent")
        self._advanced_visible = False
        ctk.CTkLabel(self.advanced_fields, text="Download order").pack(anchor="w", padx=4)
        self.reverse = ctk.BooleanVar(value=False)
        for label, value in [("Newest → Oldest", False), ("Oldest → Newest", True)]:
            ctk.CTkRadioButton(self.advanced_fields, text=label, variable=self.reverse, value=value).pack(
                anchor="w", padx=4, pady=4)
        ctk.CTkLabel(self.advanced_fields, text="Message date (UTC)").pack(anchor="w", padx=4, pady=(8, 0))
        date_row = ctk.CTkFrame(self.advanced_fields, fg_color="transparent")
        date_row.pack(fill="x", padx=4, pady=(2, 4))
        self.cutoff_date = ctk.CTkEntry(date_row, width=120, placeholder_text="YYYY-MM-DD")
        self.cutoff_date.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(date_row, text="Calendar", width=80, command=self.open_date_picker).pack(side="right")
        ctk.CTkLabel(self.advanced_fields,
            text="Newest first: on or before.\nOldest first: on or after.", justify="left").pack(anchor="w", padx=4)
        ctk.CTkLabel(self.advanced_fields, text="Custom extensions").pack(anchor="w", padx=4, pady=(8, 0))
        self.custom_ext = ctk.CTkEntry(self.advanced_fields, placeholder_text=".pdf,.csv")
        self.custom_ext.pack(fill="x", padx=4, pady=(2, 8))
        self.custom_ext.bind("<Key>", lambda e: self.media_checks["custom"].set(True))
        self._update_limit_controls()

        self.activity = ctk.CTkFrame(self, fg_color=surface)
        self.activity.grid(row=2, column=0, sticky="ew", padx=16, pady=4)
        self.activity_tabs = ctk.CTkTabview(self.activity, height=190)
        self.activity_tabs.pack(fill="x", padx=8, pady=6)
        self.activity_tabs.add("Transfer")
        transfer_tab = self.activity_tabs.tab("Transfer")
        self.transfer_scope = ctk.CTkLabel(transfer_tab, text="No active download", anchor="w")
        self.transfer_scope.pack(fill="x", padx=8)
        self.transfer_file = ctk.CTkLabel(transfer_tab, text="Current file details appear here", anchor="w")
        self.transfer_file.pack(fill="x", padx=8)
        self.file_progress = ctk.CTkProgressBar(transfer_tab)
        self.file_progress.pack(fill="x", padx=8, pady=4)
        self.file_progress.set(0)
        self.transfer_metrics = ctk.CTkLabel(transfer_tab, text="", anchor="w", justify="left")
        self.transfer_metrics.pack(fill="x", padx=8)
        self._last_transfer = {}
        self.activity_tabs.add("Log")
        self.activity_tabs.add("History")
        log_tools = ctk.CTkFrame(self.activity_tabs.tab("Log"), fg_color="transparent")
        log_tools.pack(fill="x", padx=4, pady=(0, 4))
        ctk.CTkLabel(log_tools, text="Private diagnostics · No credentials or message content",
            anchor="w").pack(side="left")
        ctk.CTkButton(log_tools, text="Open diagnostics", width=130,
            command=self.open_diagnostics).pack(side="right", padx=4)
        self.log_box = ctk.CTkTextbox(self.activity_tabs.tab("Log"), height=90,
                                     font=("Courier", 11), state="disabled")
        self.log_box.pack(fill="both", expand=True)
        self.history_box = ctk.CTkTextbox(self.activity_tabs.tab("History"), height=90,
                                         font=("Courier", 11))
        self.history_box.pack(fill="both", expand=True)
        self._activity_visible = False
        self.activity.grid_remove()
        self._load_history_tab()
        footer = ctk.CTkFrame(self, fg_color=surface)
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 12))
        footer.grid_columnconfigure(0, weight=1)
        self.progress_label = ctk.CTkLabel(footer, text="Ready · Log in to load your library", anchor="w")
        self.progress_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(6, 0))
        self.progress = ctk.CTkProgressBar(footer)
        self.progress.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 10))
        self.progress.set(0)
        self.transfer_summary = ctk.CTkLabel(footer, text="", anchor="w", justify="left")
        self.transfer_summary.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 4))
        buttons = ctk.CTkFrame(footer, fg_color="transparent")
        buttons.grid(row=0, column=1, rowspan=2, padx=8, pady=8)
        self.activity_toggle = ctk.CTkButton(buttons, text="Activity", width=75, command=self.toggle_activity)
        self.start_btn = ctk.CTkButton(buttons, text="Start download", width=125,
                                     state="disabled", command=self.start_download)
        self.pause_btn = ctk.CTkButton(buttons, text="Pause", width=75, state="disabled", command=self.pause)
        self.cancel_btn = ctk.CTkButton(buttons, text="Cancel", width=75, state="disabled", command=self.cancel)
        for button in (self.activity_toggle, self.pause_btn, self.cancel_btn, self.start_btn):
            button.pack(side="left", padx=4)
        self._layout_mode = None
        self.bind("<Configure>", self._on_window_resize)
        self.after_idle(self._refresh_layout)

    def _choose_limit(self, label):
        modes = {"All new files": "all", "All new messages": "all",
                 "Last 10": "10", "Last 20": "20", "Last 50": "50",
                 "Last 100": "100", "Custom number": "custom"}
        self.limit_mode.set(modes[label])

    def _update_limit_controls(self):
        discussions = bool(self.channels and self.include_discussions.get()
                           and getattr(self.selected_channel().entity, "broadcast", False))
        all_label = "All new messages" if discussions else "All new files"
        self.limit_label.configure(text="Channel messages per run" if discussions else "New files per topic / channel")
        self.custom_limit.configure(placeholder_text=("Number of messages, e.g. 10" if discussions
                                                     else "Number of files, e.g. 10"))
        self.limit_menu.configure(values=[all_label, "Last 10", "Last 20", "Last 50", "Last 100", "Custom number"])
        labels = {"all": all_label, "10": "Last 10", "20": "Last 20", "50": "Last 50",
                  "100": "Last 100", "custom": "Custom number"}
        self.limit_menu.set(labels[self.limit_mode.get()])
        if self.limit_mode.get() == "custom":
            self.custom_limit.pack(fill="x", padx=12, pady=(0, 6), after=self.limit_menu)
        else:
            self.custom_limit.pack_forget()

    def toggle_advanced(self):
        self._advanced_visible = not self._advanced_visible
        if self._advanced_visible:
            self.advanced_fields.pack(fill="x", padx=8, pady=(0, 10))
        else:
            self.advanced_fields.pack_forget()
        arrow = "▾" if self._advanced_visible else "▸"
        self.advanced_toggle.configure(text=f"Dates, order & custom types {arrow}")

    def _show_custom_options(self):
        if self.media_checks["custom"].get() and not self._advanced_visible:
            self.toggle_advanced()

    def _update_settings_summary(self):
        order = "Oldest first" if self.reverse.get() else "Newest first"
        cutoff = self.cutoff_date.get().strip()
        relation = "On or after" if self.reverse.get() else "On or before"
        dates = f"{relation} {cutoff} (UTC)" if cutoff else "All dates"
        self.settings_summary.configure(text=f"{order} · {dates}")

    def _preferences_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "preferences.local.json")

    def _restore_preferences(self):
        try:
            saved = read_json(self._preferences_path(), {})
        except (OSError, UnicodeError) as error:
            record_issue('preferences_read_failed', error)
            saved = {}
        for key, attr, count in (("pane_weights", "_pane_weights", 3),
                                 ("split_weights", "_split_weights", 2)):
            weights = saved.get(key)
            if (isinstance(weights, list) and len(weights) == count
                    and all(type(value) in (int, float) and 0 <= value <= 10000 for value in weights)
                    and sum(weights) > 0):
                setattr(self, attr, weights)
        size = saved.get("window_size")
        if isinstance(size, list) and len(size) == 2 and all(type(n) is int and n > 0 for n in size):
            width = min(max(700, size[0]), self.winfo_screenwidth() - 80)
            height = min(max(600, size[1]), self.winfo_screenheight() - 80)
            self.geometry(f"{width}x{height}")
        for name in ("folder_path", "custom_ext", "custom_limit", "cutoff_date"):
            value = saved.get(name)
            if isinstance(value, str) and len(value) <= 4096:
                widget = getattr(self, name)
                if name == "folder_path":
                    widget.set(value)
                else:
                    widget.delete(0, "end")
                    widget.insert(0, value)
        mode = saved.get("limit_mode")
        if mode in ("all", "10", "20", "50", "100", "custom"):
            self.limit_mode.set(mode)
        parallel = saved.get("parallel_downloads")
        if parallel in ("1", "2", "3", "4"):
            self.parallel_downloads.set(parallel)
        for name in ("reverse", "all_media", "remember_connection", "include_discussions"):
            if type(saved.get(name)) is bool:
                getattr(self, name).set(saved[name])
        media = saved.get("media", {})
        if isinstance(media, dict):
            for name, variable in self.media_checks.items():
                if type(media.get(name)) is bool:
                    variable.set(media[name])

    def _queue_preferences(self, *_args):
        self._update_settings_summary()
        if self._preferences_job is not None:
            self.after_cancel(self._preferences_job)
        self._preferences_job = self.after(400, self._save_preferences)

    def _save_preferences(self):
        self._preferences_job = None
        saved = {name: getattr(self, name).get() for name in (
            "folder_path", "custom_ext", "custom_limit", "cutoff_date",
            "limit_mode", "reverse", "all_media", "remember_connection", "include_discussions",
            "parallel_downloads")}
        saved["media"] = {name: variable.get() for name, variable in self.media_checks.items()}
        saved["pane_weights"] = self._pane_weights
        saved["split_weights"] = self._split_weights
        saved["window_size"] = [self.winfo_width(), self.winfo_height()]
        try:
            write_json(self._preferences_path(), saved)
        except OSError as error:
            record_issue('preferences_save_failed', error)
            self.log("Could not save preferences. Check local folder permissions.")

    def _close_window(self):
        record_issue('window_close_requested', level='INFO', active_job=self.busy)
        if self.busy:
            record_issue('closed_during_download', level='WARNING')
        if self._preferences_job is not None:
            self.after_cancel(self._preferences_job)
        self._save_preferences()
        self._normal_close_requested = True
        self.destroy()

    def open_date_picker(self):
        if getattr(self, "_calendar_window", None) is not None and self._calendar_window.winfo_exists():
            self._calendar_window.lift()
            return
        try:
            selected = date.fromisoformat(self.cutoff_date.get())
        except ValueError:
            selected = datetime.now(timezone.utc).date()
        window = ctk.CTkToplevel(self)
        self._calendar_window = window
        window.title("Choose message date (UTC)")
        window.resizable(False, False)
        window.transient(self)
        header = ctk.CTkFrame(window, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=10)
        month_label = ctk.CTkLabel(header, width=180)
        days = ctk.CTkFrame(window)
        days.pack(padx=10, pady=(0, 10))
        year, month = selected.year, selected.month

        def choose(value):
            self.cutoff_date.delete(0, "end")
            self.cutoff_date.insert(0, value)
            self._queue_preferences()
            window.destroy()

        def draw():
            month_label.configure(text=f"{calendar.month_name[month]} {year}")
            for child in days.winfo_children():
                child.destroy()
            for column, label in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
                ctk.CTkLabel(days, text=label, width=36).grid(row=0, column=column)
            for row, week in enumerate(calendar.monthcalendar(year, month), 1):
                for column, day in enumerate(week):
                    if day:
                        value = date(year, month, day).isoformat()
                        ctk.CTkButton(days, text=str(day), width=36,
                            fg_color="#245d91" if value == self.cutoff_date.get() else "transparent",
                            border_width=1, command=lambda value=value: choose(value)).grid(
                                row=row, column=column, padx=2, pady=2)

        def move(delta):
            nonlocal year, month
            index = year * 12 + month - 1 + delta
            if 12 <= index < 120000:
                year, month = divmod(index, 12)
                month += 1
                draw()

        ctk.CTkButton(header, text="‹", width=36, command=lambda: move(-1)).pack(side="left")
        month_label.pack(side="left")
        ctk.CTkButton(header, text="›", width=36, command=lambda: move(1)).pack(side="left")
        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(actions, text="Today", width=100, command=lambda: choose(datetime.now(timezone.utc).date().isoformat())).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Clear date", width=100, command=lambda: choose("")).pack(side="left", padx=4)
        draw()

    def toggle_account(self):
        self._account_visible = not self._account_visible
        if self._account_visible:
            self.account_fields.grid()
        else:
            self.account_fields.grid_remove()
        self.account_toggle.configure(text="Hide login" if self._account_visible else "Show login")

    def toggle_activity(self):
        self._activity_visible = not self._activity_visible
        if self._activity_visible:
            self.activity.grid()
        else:
            self.activity.grid_remove()
        self.activity_toggle.configure(text="Hide activity" if self._activity_visible else "Activity")

    def _on_window_resize(self, event):
        if event.widget is self:
            self._refresh_layout()
            if not self._restoring:
                self._queue_preferences()

    def _refresh_layout(self):
        width = self.winfo_width()
        mode = "wide" if width >= 1160 else "split" if width >= 880 else "compact"
        self.progress_label.configure(wraplength=max(180, width - 500))
        for label in (self.transfer_summary, self.transfer_scope, self.transfer_file, self.transfer_metrics):
            label.configure(wraplength=max(400, width - 80))
        if mode != self._layout_mode:
            self._layout_mode = mode
            self._divider_drag = None
            for panel in (self.channels_panel, self.topics_panel, self.settings_panel, *self.dividers):
                panel.grid_remove()
            if mode == "wide":
                self.pane_switch.grid_remove()
                for column, panel in zip((0, 2, 4), (self.channels_panel, self.topics_panel, self.settings_panel)):
                    panel.grid(row=1, column=column, sticky="nsew")
                for column, divider in zip((1, 3), self.dividers):
                    divider.grid(row=1, column=column, sticky="ns", padx=2)
            else:
                panes = ["Topics", "Settings"] if mode == "split" else ["Channels", "Topics", "Settings"]
                previous = self.pane_switch.get()
                self.pane_switch.configure(values=panes)
                self.pane_switch.set(previous if previous in panes else "Topics")
                if mode == "split":
                    self.channels_panel.grid(row=1, column=0, sticky="nsew")
                    self.dividers[0].grid(row=1, column=1, sticky="ns", padx=2)
                self.pane_switch.grid(row=0, column=2 if mode == "split" else 0, sticky="ew", pady=(0, 6))
                self.show_workspace_pane(self.pane_switch.get())
        for column in range(5):
            self.workspace.grid_columnconfigure(column, weight=0, minsize=0, uniform="")
        if mode == "wide":
            self._pane_widths = self._fit_widths(width - 56, self._pane_weights, [280, 260, 340])
            for column, size in zip((0, 2, 4), self._pane_widths):
                self.workspace.grid_columnconfigure(column, minsize=size)
            for column in (1, 3):
                self.workspace.grid_columnconfigure(column, minsize=12)
            channel_width, topic_width, _settings_width = self._pane_widths
        elif mode == "split":
            self._pane_widths = self._fit_widths(width - 44, self._split_weights, [280, 340])
            self.workspace.grid_columnconfigure(0, minsize=self._pane_widths[0])
            self.workspace.grid_columnconfigure(1, minsize=12)
            self.workspace.grid_columnconfigure(2, minsize=self._pane_widths[1])
            channel_width, topic_width = self._pane_widths
        else:
            self.workspace.grid_columnconfigure(0, weight=1)
            channel_width = topic_width = width - 32
        self.channel_hint.configure(wraplength=max(200, channel_width - 36))
        for label in (self.source_title, self.topic_status, self.topic_empty, self.topic_count):
            label.configure(wraplength=max(200, topic_width - 40))

    @staticmethod
    def _fit_widths(total, weights, minimums):
        extra = max(0, total - sum(minimums))
        weight_sum = sum(weights)
        sizes = [minimum + int(extra * weight / weight_sum)
                 for minimum, weight in zip(minimums, weights)]
        sizes[-1] += max(0, total - sum(sizes))
        return sizes

    def _begin_pane_resize(self, index, event):
        if self._layout_mode == "compact":
            return
        self._divider_drag = (self._layout_mode, index, event.x_root, self._pane_widths[:])

    def _resize_panes(self, event):
        if self._divider_drag is None:
            return
        mode, index, start, widths = self._divider_drag
        if mode != self._layout_mode:
            return
        minimums = [280, 260, 340] if mode == "wide" else [280, 340]
        delta = max(minimums[index] - widths[index],
                    min(event.x_root - start, widths[index + 1] - minimums[index + 1]))
        sizes = widths[:]
        sizes[index] += delta
        sizes[index + 1] -= delta
        weights = [size - minimum for size, minimum in zip(sizes, minimums)]
        if sum(weights) == 0:
            return
        if mode == "wide":
            self._pane_weights = weights
        else:
            self._split_weights = weights
        self._refresh_layout()

    def _end_pane_resize(self, _event=None):
        self._divider_drag = None
        self._queue_preferences()

    def reset_layout(self):
        self._pane_weights = [1.0, 1.0, 1.0]
        self._split_weights = [1.0, 1.0]
        self._refresh_layout()
        self._queue_preferences()

    def show_workspace_pane(self, pane):
        if self._layout_mode == "wide":
            return
        self.topics_panel.grid_remove()
        self.settings_panel.grid_remove()
        if self._layout_mode == "compact":
            self.channels_panel.grid_remove()
        panels = {"Channels": self.channels_panel, "Topics": self.topics_panel, "Settings": self.settings_panel}
        panel = panels.get(pane, self.topics_panel)
        panel.grid(row=1, column=2 if self._layout_mode == "split" else 0, sticky="nsew")

    def _restore_connection_details(self):
        if not self.remember_connection.get():
            return
        try:
            saved = load_connection_details()
            if saved:
                for name in ("api_id", "api_hash", "phone"):
                    getattr(self, name).insert(0, saved[name])
                self.connection_status.configure(text="Saved connection details loaded")
        except (OSError, ValueError, UnicodeError) as error:
            record_issue('credentials_read_failed', error)
            self.connection_status.configure(text="Could not read saved connection details")

    def _connection_preference_changed(self):
        self._queue_preferences()
        if self.remember_connection.get():
            self.connection_status.configure(text="Details will be saved after a successful login")
            return
        try:
            forget_connection_details()
            self.connection_status.configure(text="Connection details will not be saved")
        except (OSError, ValueError) as error:
            record_issue('credentials_forget_failed', error)
            self.connection_status.configure(text="Could not remove saved connection details")

    def _complete_authentication(self):
        if self.remember_connection.get() and self._login_credentials is not None:
            try:
                save_connection_details(*self._login_credentials)
                self.connection_status.configure(text="Connection details saved privately")
            except (OSError, ValueError) as error:
                record_issue('credentials_save_failed', error)
                self.connection_status.configure(text="Could not save connection details")
                self.log("Could not save connection details. Check local folder permissions.")
        self._login_credentials = None
        for name in ("api_id", "api_hash", "phone"):
            getattr(self, name).delete(0, "end")

    def forget_saved_connection(self):
        try:
            forget_connection_details()
            self.remember_connection.set(False)
            for name in ("api_id", "api_hash", "phone"):
                getattr(self, name).delete(0, "end")
            self.connection_status.configure(text="Saved connection details removed")
            self._queue_preferences()
        except (OSError, ValueError) as error:
            record_issue('credentials_forget_failed', error)
            self.connection_status.configure(text="Could not remove saved connection details")

    def reset_selected_sync(self):
        if self.busy:
            return
        if not self.channels:
            self.progress_label.configure(text="Choose a channel or group first")
            return
        selected = self.selected_channel()
        confirmed = messagebox.askyesno(
            "Reset saved sync?",
            f"{selected.name} [{selected.id}]\n\n"
            "Clear this source's saved sync positions across all topics, discussions, senders, media filters and folders?\n\n"
            "Choose All and clear the date to rescan matching history on the next Start. "
            "Existing files will be skipped and missing files can be downloaded again.",
            parent=self, default="no")
        if not confirmed or self.busy:
            return
        try:
            removed = reset_channel_sync(selected.id)
        except (OSError, UnicodeError) as error:
            record_issue('sync_reset_failed', error)
            self.progress_label.configure(text="Could not reset saved sync · Check local permissions")
            self.log("Could not reset saved sync. Check local state-file permissions.")
            return
        self.progress_label.configure(text="Sync reset · Choose All, clear the date, then Start to rescan")
        self.log(f"Sync reset for {selected.name} [{selected.id}]: {removed} saved positions cleared.")

    def browse(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(folder)

    def log(self, msg):
        self.after(0, self._log_safe, msg)

    def report_callback_exception(self, exc_type, error, tb):
        record_issue('ui_callback_failed', error, tb=tb)
        try:
            self.progress_label.configure(text="Unexpected interface error · Open diagnostics in Activity > Log")
        except Exception:
            pass

    def open_diagnostics(self):
        try:
            if open_diagnostics_folder():
                return
        except (OSError, ValueError) as error:
            record_issue('diagnostics_open_failed', error)
        self.progress_label.configure(text="Diagnostic logs unavailable · Check local permissions")

    def _log_safe(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _load_history_tab(self):
        self.history_box.configure(state="normal")
        self.history_box.delete("1.0", "end")
        history = load_history()
        if not history:
            self.history_box.insert("end", "Completed downloads will appear here.\n")
        for h in reversed(history):
            self.history_box.insert("end",
                f"📅 {h['date']}  |  📢 {h['channel']}  |  ✅ {h['files']} files  |  📁 {h['folder']}\n"
            )
        self.history_box.configure(state="disabled")

    def login(self):
        api_id   = self.api_id.get().strip()
        api_hash = self.api_hash.get().strip()
        phone    = self.phone.get().strip()

        if not api_id or not api_hash or not phone:
            self.log("❌ Please fill in API ID, API Hash and Phone first.")
            return

        if self.downloader is not None:
            self.log("Restart the app to retry login or switch accounts.")
            return
        if not api_id.isdecimal() or int(api_id) <= 0:
            self.log("Enter a valid numeric API ID.")
            return
        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(async_exception_handler)
        try:
            self.downloader = TelegramDownloader(int(api_id), api_hash, phone)
        except Exception as error:
            record_issue('telegram_initialize_failed', error)
            self.log("Could not initialize Telegram. Check local session permissions.")
            self.loop.close()
            self.loop = None
            return
        self._login_credentials = (api_id, api_hash, phone)
        self.after(0, lambda: self.login_btn.configure(state="disabled"))
        self.log("🔄 Connecting to Telegram...")
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        observe_future(asyncio.run_coroutine_threadsafe(self._async_login(), self.loop))

    async def _async_login(self):
        try:
            await self.downloader.client.connect()
            if not await self.downloader.client.is_user_authorized():
                await self.downloader.client.send_code_request(self.downloader.phone)
                self.log("📱 OTP sent to your Telegram app! Enter it and click Submit OTP.")
                self.downloader.otp_future = self.loop.create_future()
                self.after(0, lambda: self.otp_btn.configure(state="normal"))
                code = await self.downloader.otp_future
                await self.downloader.client.sign_in(self.downloader.phone, code)

            self.log("✅ Logged in successfully!")
            self.after(0, lambda: self.otp_btn.configure(state="disabled"))
            self.after(0, self._complete_authentication)

            channels = await self.downloader.get_channels()
            self.after(0, self._apply_channels, channels)
            self.log(f"📋 {len(channels)} channels & groups loaded.")

        except Exception as error:
            record_issue('login_failed', error)
            self.log("❌ Login failed. Check credentials and account authentication settings.")
            self.after(0, lambda: self.login_btn.configure(state="normal"))
        finally:
            self.after(0, lambda: setattr(self, "_login_credentials", None))
            self.downloader.otp_future = None
            self.after(0, lambda: self.otp.delete(0, "end"))
            self.after(0, lambda: self.otp_btn.configure(state="disabled"))

    def submit_otp(self):
        code = self.otp.get().strip()
        if code and self.downloader and self.downloader.otp_future:
            self.otp.delete(0, "end")
            future = self.downloader.otp_future
            self.loop.call_soon_threadsafe(lambda: None if future.done() else future.set_result(code))
            self.after(0, lambda: self.otp_btn.configure(state="disabled"))
            self.log("✅ OTP submitted.")
        else:
            self.log("❌ No OTP entered or login not started.")

    def _apply_channels(self, channels):
        self.channels = channels
        for button in self.channel_buttons.values():
            button.destroy()
        self.channel_buttons = {}
        for channel in channels:
            title = channel.name if len(channel.name) <= 40 else channel.name[:39] + "…"
            kind = "Forum" if getattr(channel.entity, "forum", False) else "Channel / group"
            button = ctk.CTkButton(self.channel_list, text=f"{title}\n{kind} · {channel.id}",
                anchor="w", height=56, fg_color="transparent", text_color=("#26384c", "#e0eafa"),
                hover_color=("#dde6f0", "#314257"),
                command=lambda cid=channel.id: self.choose_channel(cid))
            button.pack(fill="x", padx=4, pady=3)
            self.channel_buttons[channel.id] = button
        self.sync_reset_btn.configure(state="normal" if channels else "disabled")
        self.discussions_toggle.configure(state="disabled")
        self.channel_search.configure(state="normal" if channels else "disabled",
            values=[f"{'📢' if c.is_channel else '👥'} {c.name} [{c.id}]" for c in channels])
        if channels:
            self.choose_channel(channels[0].id)
        else:
            self.topic_var.set("No channels or groups available for this account.")
            self.topic_empty.configure(text=self.topic_var.get())
            self.progress_label.configure(text="No channels or groups available")
        if self._account_visible:
            self.toggle_account()

    def choose_channel(self, channel_id):
        if self.busy:
            return
        selected = next((c for c in self.channels if c.id == channel_id), None)
        if selected is None:
            return
        label = f"{'📢' if selected.is_channel else '👥'} {selected.name} [{selected.id}]"
        self.channel_var.set(label)
        self.channel_search.set(label)
        self.select_channel()
        self.channel_search.configure(values=[f"{'📢' if c.is_channel else '👥'} {c.name} [{c.id}]" for c in self.channels])
        for button in self.channel_buttons.values():
            button.pack(fill="x", padx=4, pady=3)
        self.channel_hint.configure(text=f"{len(self.channels)} channels / groups")
        if self._layout_mode != "wide":
            self.pane_switch.set("Topics")
            self.show_workspace_pane("Topics")

    def choose_channel_from_dropdown(self, label):
        selected = next((c for c in self.channels
            if f"{'📢' if c.is_channel else '👥'} {c.name} [{c.id}]" == label), None)
        if selected is not None:
            self.choose_channel(selected.id)

    def choose_topic_from_dropdown(self, label):
        if self.busy:
            return
        if label in self.topic_checks:
            self.topic_checks[label][0].set(True)
        self.topic_search.set("")
        self.filter_topics()

    def choose_filtered_topic(self, _event=None):
        query = self.topic_search.get().strip().casefold()
        label = next((label for label in self.topics if query in label.casefold()), None)
        if label is not None:
            self.choose_topic_from_dropdown(label)

    def choose_filtered_channel(self, _event=None):
        if self.busy:
            return
        query = self.channel_search.get().strip().casefold()
        selected = next((c for c in self.channels if query in f"{'📢' if c.is_channel else '👥'} {c.name} [{c.id}]".casefold()), None)
        if selected is not None:
            self.choose_channel(selected.id)

    def filter_channels(self, _event=None):
        if self.busy or (_event is not None and _event.keysym in ("Return", "Up", "Down", "Escape")):
            return
        query = self.channel_search.get().strip().casefold()
        visible = 0
        matches = []
        for channel in self.channels:
            button = self.channel_buttons[channel.id]
            button.pack_forget()
            label = f"{'📢' if channel.is_channel else '👥'} {channel.name} [{channel.id}]"
            if query in label.casefold():
                button.pack(fill="x", padx=4, pady=3)
                visible += 1
                matches.append(label)
        self.channel_search.configure(values=matches)
        text = f"{visible} matching channels / groups" if query else f"{visible} channels / groups"
        self.channel_hint.configure(text=text if self.channels else "No channels or groups available.")

    def filter_topics(self, _event=None):
        if self.busy or (_event is not None and _event.keysym in ("Return", "Up", "Down", "Escape")):
            return
        query = self.topic_search.get().strip().casefold()
        for label, (_var, check) in self.topic_checks.items():
            check.pack_forget()
            if query in label.casefold():
                check.pack(anchor="w", fill="x", padx=6, pady=4)
        values = [label for label in self.topics if query in label.casefold()]
        self.topic_search.configure(values=values)
        matches = len(values)
        if self.topics and not matches:
            self.topic_empty.configure(text="No topics match your search.")
            self.topic_empty.pack(anchor="w", padx=6, pady=16)
        elif self.topics:
            self.topic_empty.pack_forget()
        self.update_topic_count()

    def update_topic_count(self):
        count = sum(var.get() for var, _check in self.topic_checks.values())
        visible = sum(self.topic_search.get().strip().casefold() in label.casefold() for label in self.topic_checks)
        self.topic_count.configure(text=f"{count} selected · {visible} matching topics")
        ready = bool(self.channels and (count or not getattr(self.selected_channel().entity, "forum", False)))
        ready = ready and (not self.sender_filter.get() or self.sender_id is not None)
        self.start_btn.configure(state="normal" if ready and not self.busy else "disabled")
        if not self.busy:
            if self.sender_filter.get() and self.sender_id is None:
                text = "Choose a sender or uncheck the sender filter"
            else:
                text = "Ready to download" if ready else "Choose at least one topic"
            self.progress_label.configure(text=text)

    def select_topics(self, selected):
        if self.busy:
            return
        query = self.topic_search.get().strip().casefold()
        for label, (var, _check) in self.topic_checks.items():
            if not selected or query in label.casefold():
                var.set(selected)
        if self.channels:
            self.update_topic_count()

    def selected_channel(self):
        return next(c for c in self.channels
            if f"{'📢' if c.is_channel else '👥'} {c.name} [{c.id}]" == self.channel_var.get())

    def select_channel(self, _value=None):
        if self.busy:
            return
        self.sender_generation += 1
        self.sender_id = None
        self.senders = {}
        self.sender_filter.set(False)
        self.sender_query.set("")
        self.sender_query.configure(values=[], state="normal")
        self.sender_find.configure(state="normal")
        self.sender_status.configure(text="Everyone · Find @username, user ID or name")
        self.topic_generation += 1
        generation = self.topic_generation
        self.topics = {}
        for _var, check in self.topic_checks.values():
            check.destroy()
        self.topic_checks = {}
        self.topic_search.set("")
        self.topic_search.configure(values=[])
        self.topic_count.configure(text="No topics selected")
        selected = self.selected_channel()
        self.source_title.configure(text=f"{selected.name} [{selected.id}]")
        broadcast = bool(getattr(selected.entity, "broadcast", False))
        self.discussions_toggle.configure(state="normal" if broadcast else "disabled")
        self.discussions_hint.configure(text=(
            "Includes comment media only for this run's channel messages. Comments do not count toward the message limit."
            if broadcast else "Available for broadcast channels. Group replies are already in their history."))
        self._update_limit_controls()
        for cid, button in self.channel_buttons.items():
            button.configure(fg_color=("#dbeafa", "#284667") if cid == selected.id else "transparent")
        self.start_btn.configure(state="disabled")
        self.topic_search.configure(state="disabled")
        self.select_topics_btn.configure(state="disabled")
        self.clear_topics_btn.configure(state="disabled")
        self.topic_empty.pack(anchor="w", padx=6, pady=16)
        if not getattr(selected.entity, "forum", False):
            self.topic_var.set("No topic required")
            self.topic_empty.configure(text="The entire channel or group is selected.")
            self.start_btn.configure(state="normal")
            self.progress_label.configure(text="Ready · Entire channel or group selected")
            return
        self.progress_label.configure(text="Loading topics…")
        self.topic_var.set("Loading topics...")
        self.topic_empty.configure(text="Loading topics…")
        async def load():
            try:
                topics = await self.downloader.get_topics(selected)
                self.after(0, apply_topics, topics, None)
            except Exception as error:
                record_issue('topic_load_failed', error)
                self.after(0, apply_topics, [], True)
        def apply_topics(topics, error):
            if generation != self.topic_generation:
                return
            self.topics = {f"{t.title} [{t.id}]": t.id for t in topics}
            if error:
                self.topic_var.set("Topics unavailable — reselect group to retry")
                self.progress_label.configure(text="Topics unavailable · Click the group to retry")
                self.topic_empty.configure(text="Click this group in the sidebar to retry.")
                self.log("❌ Could not load topics. Reselect the group to retry.")
                return
            if not topics:
                self.topic_var.set("No topics available in this group.")
                self.topic_empty.configure(text=self.topic_var.get())
                self.progress_label.configure(text="No topics available in this group")
                return
            self.topic_empty.pack_forget()
            self.topic_search.configure(state="normal", values=list(self.topics))
            self.select_topics_btn.configure(state="normal")
            self.clear_topics_btn.configure(state="normal")
            self.topic_var.set("Choose one or more topics below.")
            for label in self.topics:
                var = ctk.BooleanVar(value=False)
                check = ctk.CTkCheckBox(self.topic_list, text=label, variable=var, command=self.update_topic_count)
                check.pack(anchor="w", fill="x", padx=6, pady=4)
                self.topic_checks[label] = (var, check)
            self.update_topic_count()
        observe_future(asyncio.run_coroutine_threadsafe(load(), self.loop))

    def _sender_query_changed(self, event):
        if self.busy or event.keysym in ("Return", "Up", "Down", "Escape"):
            return
        if self.senders.get(self.sender_query.get()) == self.sender_id and self.sender_id is not None:
            return
        self.sender_generation += 1
        self.sender_id = None
        self.senders = {}
        self.sender_query.configure(values=[])
        self.sender_find.configure(state="normal" if self.channels else "disabled")
        self.sender_filter.set(True)
        self._update_sender_status()

    def find_sender(self):
        if self.busy or not self.channels:
            return
        query = self.sender_query.get().strip()
        if query in self.senders:
            self.choose_sender(query)
            return
        if not query:
            self.sender_status.configure(text="Enter @username, a user ID, or a name to find")
            return
        self.sender_generation += 1
        generation = self.sender_generation
        selected = self.selected_channel()
        self.sender_id = None
        self.senders = {}
        self.sender_filter.set(True)
        self.sender_query.configure(values=[])
        self.sender_find.configure(state="disabled")
        self.sender_status.configure(text="Finding senders…")
        self.start_btn.configure(state="disabled")

        def apply(results, error):
            if generation != self.sender_generation:
                return
            self.sender_find.configure(state="normal" if not self.busy else "disabled")
            if error:
                self.sender_status.configure(text="Could not find sender. Try @username or ID. Member search may be restricted.")
                return
            for entity in results:
                name = (getattr(entity, "title", None)
                        or " ".join(filter(None, (getattr(entity, "first_name", None),
                                                 getattr(entity, "last_name", None)))) or "Sender")
                username = getattr(entity, "username", None)
                peer_id = utils.get_peer_id(entity)
                label = f"{name}" + (f" (@{username})" if username else "") + f" [{peer_id}]"
                self.senders[label] = peer_id
            self.sender_query.configure(values=list(self.senders))
            if len(self.senders) == 1:
                self.choose_sender(next(iter(self.senders)))
            else:
                message = "No matching senders" if not self.senders else "Choose a sender from the arrow list (up to 30 matches)"
                self.sender_status.configure(text=message)

        async def lookup():
            try:
                matches = await self.downloader.find_senders(selected, query)
                self.after(0, apply, matches, False)
            except Exception as error:
                record_issue('sender_lookup_failed', error)
                self.after(0, apply, [], True)
        observe_future(asyncio.run_coroutine_threadsafe(lookup(), self.loop))

    def choose_sender(self, label):
        if self.busy or label not in self.senders:
            return
        self.sender_id = self.senders[label]
        self.sender_query.set(label)
        self.sender_filter.set(True)
        self._update_sender_status()

    def _update_sender_status(self):
        if self.busy:
            return
        selected = self.sender_filter.get()
        if not selected:
            self.sender_generation += 1
            self.sender_find.configure(state="normal" if self.channels else "disabled")
        self.sender_status.configure(text=(f"Sender ID {self.sender_id}" if self.sender_id is not None
                                           else "Find and choose a sender") if selected else "Everyone")
        self.update_topic_count()

    def _render_transfer(self, details):
        previous = self._last_transfer
        self._last_transfer = details
        downloaded = details.get("downloaded", previous.get("downloaded", 0))
        skipped = details.get("skipped", previous.get("skipped", 0))
        self._last_transfer.update(downloaded=downloaded, skipped=skipped)
        state = details.get("state", "scanning")
        states = {"scanning": "Scanning for matching media", "starting": "Starting file",
                  "downloading": "Downloading", "paused": "Paused", "resuming": "Resuming",
                  "cancelling": "Cancelling", "skipping": "Already downloaded",
                  "retrying": "Retrying file", "failed": "Download failed",
                  "rate_limited": "Waiting for Telegram",
                  "file_complete": "File saved", "scope_complete": "Selected source complete",
                  "scope_cancelled": "Cancelled", "scope_incomplete": "Some files failed",
                  "complete": "Download complete", "cancelled": "Download cancelled",
                  "incomplete": "Download incomplete"}
        if self.downloader.cancelled and state in ("starting", "downloading", "paused", "retrying"):
            state = "cancelling"
        elif self.downloader.paused and state in ("starting", "downloading"):
            state = "paused"
        name = details.get("filename", "")
        received = details.get("received", 0)
        total = details.get("total")
        speed = details.get("speed", 0) if state == "downloading" else 0
        eta = details.get("eta") if speed > 0 else None
        self.transfer_file.configure(text=f"{states[state]} · {name}" if name else states[state])
        fraction = min(received / total, 1.0) if total else 0
        if state in ("file_complete", "scope_complete", "complete"):
            fraction = 1.0
        self.file_progress.set(fraction)
        if name and state not in ("skipping", "retrying", "failed"):
            size = f"{format_bytes(received)} / {format_bytes(total)} · {fraction:.0%}" if total is not None else f"{format_bytes(received)} / size unknown"
            metrics = f"{size}  |  Avg {format_bytes(speed)}/s  |  File ETA {format_eta(eta)}"
        else:
            metrics = states[state]
        if details.get("attempt", 1) > 1:
            metrics += f"  |  Attempt {details['attempt']}/5"
        counts = f"{downloaded} downloaded · {skipped} skipped"
        if "parallel_limit" in details:
            combined = details.get("aggregate_speed", 0)
            if state in ("paused", "resuming", "cancelling", "rate_limited", "cancelled",
                         "complete", "incomplete", "scope_complete", "scope_cancelled", "scope_incomplete"):
                combined = 0
            counts += (f" · {details.get('active', 0)}/{details['parallel_limit']} active"
                       f" · Combined {format_bytes(combined)}/s")
        self.transfer_metrics.configure(text=f"{metrics}\n{counts}")
        self.transfer_summary.configure(text=f"{metrics}  |  {counts}")

    def start_download(self):
        if self.busy:
            return
        selected = self.selected_channel()
        raw_parallel = self.parallel_downloads.get()
        if raw_parallel not in ("1", "2", "3", "4"):
            self.progress_label.configure(text="Choose 1–4 parallel downloads")
            return
        parallel_downloads = int(raw_parallel)
        include_discussions = bool(self.include_discussions.get()
                                   and getattr(selected.entity, "broadcast", False))
        sender_id = self.sender_id if self.sender_filter.get() else None
        if self.sender_filter.get() and sender_id is None:
            self.progress_label.configure(text="Find and choose a sender, or uncheck the sender filter")
            return
        # Ignore any lookup still in flight while an unfiltered job starts.
        self.sender_generation += 1
        topic_labels = dict(self.topics)
        topic_ids = [self.topics[label] for label, (var, _check) in self.topic_checks.items() if var.get()]
        topic_id = topic_ids[0] if topic_ids else None
        if getattr(selected.entity, "forum", False) and topic_id is None:
            self.log("Select a topic first.")
            return

        tokens = [token for token, var in self.media_checks.items() if var.get() and token != "custom"]
        if self.media_checks["custom"].get():
            import re
            extensions = [e.strip().lower() for e in self.custom_ext.get().split(",")]
            if not all(re.fullmatch(r"\.[a-z0-9]{1,10}", e) for e in extensions):
                self.log("Enter extensions such as .pdf,.csv for the custom filter.")
                return
            tokens.extend(extensions)
        selected_type = "all" if self.all_media.get() else ",".join(sorted(set(tokens)))
        if not selected_type:
            self.log("Select at least one media type or All media.")
            return
        limit_mode = self.limit_mode.get()
        raw_limit = self.custom_limit.get().strip()
        if limit_mode == "custom" and (not raw_limit.isdecimal() or int(raw_limit) < 1):
            self.log("Enter a positive number for the download scope.")
            return
        custom_limit = int(raw_limit) if limit_mode == "custom" else 20
        if not self.folder_path.get().strip():
            self.log("Choose a destination folder.")
            return

        raw_date = self.cutoff_date.get().strip()
        cutoff_date = None
        if raw_date:
            try:
                cutoff_date = date.fromisoformat(raw_date)
                if cutoff_date.isoformat() != raw_date:
                    raise ValueError
            except ValueError:
                message = "Enter a valid message date as YYYY-MM-DD."
                self.progress_label.configure(text=message)
                self.log(message)
                return

        folder = group_folder(self.folder_path.get(), selected.name, selected.id)

        base_folder = folder
        record_issue('download_started', level='INFO', parallel_downloads=parallel_downloads)
        self.log("Starting download for the selected channel/topic...")
        self.busy = True
        self.sync_reset_btn.configure(state="disabled")
        if not self._activity_visible:
            self.toggle_activity()
        self.activity_tabs.set("Transfer")
        self._render_transfer({"state": "scanning", "downloaded": 0, "skipped": 0})
        # Reset before scheduling so an immediate Cancel cannot be overwritten.
        self.downloader.paused = False
        self.downloader.cancelled = False
        for button in self.channel_buttons.values():
            button.configure(state="disabled")
        self.select_topics_btn.configure(state="disabled")
        self.clear_topics_btn.configure(state="disabled")
        self.channel_search.configure(state="disabled")
        self.topic_search.configure(state="disabled")
        self.sender_query.configure(state="disabled")
        self.sender_toggle.configure(state="disabled")
        self.sender_find.configure(state="disabled")
        self.discussions_toggle.configure(state="disabled")
        self.parallel_menu.configure(state="disabled")
        for _var, check in self.topic_checks.values():
            check.configure(state="disabled")
        reverse = self.reverse.get()
        if limit_mode == "all" or include_discussions:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        self.after(0, lambda: self.progress.set(0))
        self.after(0, lambda: self.progress_label.configure(text="Starting..."))
        self.after(0, lambda: self.start_btn.configure(state="disabled"))
        self.after(0, lambda: self.pause_btn.configure(state="normal"))
        self.after(0, lambda: self.cancel_btn.configure(state="normal"))

        totals = {"downloaded": 0, "skipped": 0}

        def on_progress(count, skipped, fraction):
            self.after(0, lambda: self.progress_label.configure(
                text=f"✅ {count} downloaded  |  ⏭ {skipped} skipped"
            ))
            self.after(0, lambda: self.progress.set(min(fraction, 1.0)))

        def on_transfer(details):
            details = details.copy()
            if details["state"].startswith("scope_"):
                details.update(totals)
            else:
                details["downloaded"] += totals["downloaded"]
                details["skipped"] += totals["skipped"]
            self.after(0, self._render_transfer, details)

        async def run_download():
            try:
                status = "complete"
                for index, current_topic in enumerate(topic_ids or [None]):
                    if self.downloader.cancelled:
                        status = "cancelled"
                        break
                    name = next((label for label, tid in topic_labels.items() if tid == current_topic), "")
                    folder = (topic_folder(base_folder, name.rsplit(" [", 1)[0], selected.id, current_topic)
                              if current_topic is not None else base_folder)
                    scope_name = (f"Topic {index + 1}/{len(topic_ids)} · {selected.name} / {name}"
                                  if current_topic is not None else f"Channel · {selected.name}")
                    self.after(0, lambda text=scope_name: self.transfer_scope.configure(text=text))
                    self.log(f"Scope {index + 1}/{len(topic_ids) or 1}: {name or selected.name}")
                    def done(count, skipped, destination=folder, title=name):
                        totals["downloaded"] += count
                        totals["skipped"] += skipped
                        save_history(selected.name + (f" / {title}" if title else ""), destination, count)
                        self.after(0, self._load_history_tab)
                        self.log(f"Scope finished: {count} downloaded, {skipped} skipped.")
                    result = await self.downloader.download(
                        selected, folder, selected_type, limit_mode, custom_limit,
                        reverse, on_progress, self.log, done, topic_id=current_topic,
                        reset_controls=False, cutoff_date=cutoff_date, on_transfer=on_transfer,
                        sender_id=sender_id, include_discussions=include_discussions,
                        parallel_downloads=parallel_downloads)
                    if result != "complete":
                        status = result
                        if result == "cancelled":
                            break
                if status == "complete":
                    self.after(0, lambda: self.progress.set(1))
                self.after(0, lambda: self.progress_label.configure(text=f"Download {status}"))
                self.after(0, self._render_transfer, dict(totals, state=status))
                record_issue('download_finished', level='INFO' if status == 'complete' else 'WARNING',
                             result=status, **totals)
            except TopicFolderConflict as error:
                record_issue('topic_folder_conflict', error)
                self.log("❌ Topic folder conflict. Check the destination for duplicate topic IDs or files blocking a topic folder.")
                self.after(0, lambda: self.progress_label.configure(text="Topic folder conflict · Check Activity"))
                self.after(0, self._render_transfer, dict(totals, state="failed"))
            except Exception as error:
                record_issue('download_failed', error)
                self.log("❌ Download failed. Check connection and local file permissions.")
                self.after(0, lambda: self.progress_label.configure(text="Download failed"))
                self.after(0, self._render_transfer, dict(totals, state="failed"))
            finally:
                self.after(0, finish)
        def finish():
            self.busy = False
            self.sync_reset_btn.configure(state="normal" if self.channels else "disabled")
            self.progress.stop()
            self.progress.configure(mode="determinate")
            for button in self.channel_buttons.values():
                button.configure(state="normal")
            self.select_topics_btn.configure(state="normal" if self.topics else "disabled")
            self.clear_topics_btn.configure(state="normal" if self.topics else "disabled")
            self.channel_search.configure(state="normal")
            self.sender_query.configure(state="normal")
            self.sender_toggle.configure(state="normal")
            self.sender_find.configure(state="normal")
            self.parallel_menu.configure(state="normal")
            self.discussions_toggle.configure(
                state="normal" if getattr(selected.entity, "broadcast", False) else "disabled")
            self.topic_search.configure(state="normal" if self.topics else "disabled")
            for _var, check in self.topic_checks.values():
                check.configure(state="normal")
            self.start_btn.configure(state="normal")
            self.pause_btn.configure(state="disabled", text="⏸ Pause")
            self.cancel_btn.configure(state="disabled")
        observe_future(asyncio.run_coroutine_threadsafe(run_download(), self.loop))

    def pause(self):
        self.downloader.paused = not self.downloader.paused
        record_issue('download_paused' if self.downloader.paused else 'download_resumed', level='INFO')
        label = "▶ Resume" if self.downloader.paused else "⏸ Pause"
        self.after(0, lambda: self.pause_btn.configure(text=label))
        self.progress_label.configure(text="Paused" if self.downloader.paused else "Downloading…")
        state = "paused" if self.downloader.paused else "resuming"
        self._render_transfer(dict(self._last_transfer, state=state))
        self.log("⏸ Paused." if self.downloader.paused else "▶ Resumed.")

    def cancel(self):
        self.downloader.cancelled = True
        record_issue('download_cancelled', level='INFO')
        self._render_transfer(dict(self._last_transfer, state="cancelling"))
        self.log("⛔ Cancelling...")
        self.after(0, lambda: self.pause_btn.configure(state="disabled"))
        self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
        self.after(0, lambda: self.start_btn.configure(state="disabled"))

