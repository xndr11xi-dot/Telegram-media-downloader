import customtkinter as ctk
from tkinter import filedialog
import asyncio
import threading
import os
from downloader import TelegramDownloader, group_folder
from history import load_history, save_history

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Media Downloader")
        self.geometry(f"{min(1180, self.winfo_screenwidth() - 80)}x{min(900, self.winfo_screenheight() - 80)}")
        self.resizable(True, True)
        self.minsize(700, min(700, self.winfo_screenheight() - 80))
        self.topic_checks = {}
        self.media_checks = {}
        self.downloader = None
        self.loop = None
        self.channels = []
        self.topics = {}
        self.topic_generation = 0
        self.busy = False
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Collapsible account area leaves the workspace available after login.
        account = ctk.CTkFrame(self)
        account.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        account.grid_columnconfigure(0, weight=1)
        heading = ctk.CTkFrame(account, fg_color="transparent")
        heading.grid(row=0, column=0, sticky="ew", padx=12, pady=6)
        ctk.CTkLabel(heading, text="Telegram Media Downloader", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        self.account_toggle = ctk.CTkButton(heading, text="Hide login", width=100, command=self.toggle_account)
        self.account_toggle.pack(side="right")
        self.account_fields = ctk.CTkFrame(account, fg_color="transparent")
        self.account_fields.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
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
        self.otp_btn = ctk.CTkButton(login_row, text="Submit code", width=110, state="disabled", command=self.submit_otp)
        self.otp_btn.grid(row=0, column=2, padx=8)
        self.login_btn = ctk.CTkButton(login_row, text="Log in", width=100, command=self.login)
        self.login_btn.grid(row=0, column=3)
        self._account_visible = True

        # Wide windows show two work areas. Narrow windows switch between them.
        self.workspace = ctk.CTkFrame(self, fg_color="transparent")
        self.workspace.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)
        self.workspace.grid_rowconfigure(1, weight=1)
        self.workspace.grid_columnconfigure(0, weight=1, uniform="workspace")
        self.workspace.grid_columnconfigure(1, weight=1, uniform="workspace")
        self.pane_switch = ctk.CTkSegmentedButton(self.workspace,
            values=["Channels & topics", "Download settings"], command=self.show_workspace_pane)
        self.pane_switch.set("Channels & topics")
        self.source_panel = ctk.CTkFrame(self.workspace)
        self.source_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.settings_panel = ctk.CTkScrollableFrame(self.workspace)
        self.settings_panel.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        self._compact_layout = None
        self.bind("<Configure>", self._on_window_resize)

        source = self.source_panel
        source.grid_columnconfigure(0, weight=1)
        source.grid_rowconfigure(6, weight=1)
        ctk.CTkLabel(source, text="1  Choose channels & topics", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(10, 4))
        self.channel_var = ctk.StringVar()
        self.channel_search = ctk.CTkEntry(source, placeholder_text="Search channels or groups…")
        self.channel_search.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
        self.channel_search.bind("<KeyRelease>", self.filter_channels)
        self.channel_search.bind("<Return>", self.choose_filtered_channel)
        self.channel_menu = ctk.CTkOptionMenu(source, variable=self.channel_var,
            values=["Log in first…"], state="disabled", width=200, command=self.select_channel)
        self.channel_menu.grid(row=2, column=0, sticky="ew", padx=14, pady=4)
        self.channel_hint = ctk.CTkLabel(source, text="Log in to load channels and groups.", anchor="w", wraplength=400)
        self.channel_hint.grid(row=3, column=0, sticky="ew", padx=14, pady=2)
        self.topic_search = ctk.CTkEntry(source, placeholder_text="Search topics…")
        self.topic_search.grid(row=4, column=0, sticky="ew", padx=14, pady=(8, 4))
        self.topic_search.bind("<KeyRelease>", self.filter_topics)
        actions = ctk.CTkFrame(source, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=10, pady=4)
        ctk.CTkButton(actions, text="Select visible", width=125, command=lambda: self.select_topics(True)).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Clear selection", width=125, command=lambda: self.select_topics(False)).pack(side="left", padx=4)
        self.topic_list = ctk.CTkScrollableFrame(source, height=60)
        self.topic_list.grid(row=6, column=0, sticky="nsew", padx=14, pady=4)
        self.topic_count = ctk.CTkLabel(source, text="No topics selected", anchor="w", wraplength=400)
        self.topic_count.grid(row=7, column=0, sticky="ew", padx=14)
        self.topic_var = ctk.StringVar(value="Log in and choose a channel or group.")
        # Retained as controller state for topic loading; the visible UI is checkboxes.
        self.topic_menu = ctk.CTkOptionMenu(source, variable=self.topic_var, values=["No topic required"], state="disabled", width=200)
        self.topic_status = ctk.CTkLabel(source, textvariable=self.topic_var, anchor="w", wraplength=400)
        self.topic_status.grid(row=8, column=0, sticky="ew", padx=14, pady=(0, 10))

        settings = self.settings_panel
        ctk.CTkLabel(settings, text="2  Configure downloads", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=10, pady=(6, 4))
        type_frame = ctk.CTkFrame(settings)
        type_frame.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(type_frame, text="Media types · combine any selections", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=6)
        self.media_type = ctk.StringVar(value="all")
        quick_row = ctk.CTkFrame(type_frame, fg_color="transparent")
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
            ctk.CTkCheckBox(quick_row, text=label, width=80, variable=var).grid(
                row=index//3, column=index%3, sticky="w", padx=4, pady=5)
        self.all_media = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(type_frame, text="All media (overrides selections)", variable=self.all_media).pack(anchor="w", padx=12, pady=6)
        self.custom_ext = ctk.CTkEntry(type_frame, placeholder_text="Custom extensions: .pdf,.csv")
        self.custom_ext.pack(fill="x", padx=12, pady=(0, 10))
        self.custom_ext.bind("<Key>", lambda e: self.media_checks["custom"].set(True))

        limit_frame = ctk.CTkFrame(settings)
        limit_frame.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(limit_frame, text="New files per topic / channel", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=6)
        self.limit_mode = ctk.StringVar(value="all")
        limit_row = ctk.CTkFrame(limit_frame, fg_color="transparent")
        limit_row.pack(fill="x", padx=8)
        for column in range(3):
            limit_row.grid_columnconfigure(column, weight=1)
        for index, (label, value) in enumerate([("Last 20", "20"), ("Last 50", "50"), ("Last 100", "100"), ("All", "all"), ("Custom", "custom")]):
            ctk.CTkRadioButton(limit_row, text=label, width=85, variable=self.limit_mode, value=value).grid(
                row=index//3, column=index%3, sticky="w", padx=4, pady=4)
        self.custom_limit = ctk.CTkEntry(limit_frame, placeholder_text="Custom number, e.g. 23")
        self.custom_limit.pack(fill="x", padx=12, pady=(4, 10))
        self.custom_limit.bind("<Key>", lambda e: self.limit_mode.set("custom"))
        order = ctk.CTkFrame(settings)
        order.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(order, text="Download order", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(6, 0))
        self.reverse = ctk.BooleanVar(value=False)
        for label, value in [("Newest → Oldest", False), ("Oldest → Newest", True)]:
            ctk.CTkRadioButton(order, text=label, variable=self.reverse, value=value).pack(anchor="w", padx=12, pady=4)
        folder_frame = ctk.CTkFrame(settings)
        folder_frame.pack(fill="x", padx=4, pady=(4, 8))
        ctk.CTkLabel(folder_frame, text="Save to", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(6, 0))
        folder_row = ctk.CTkFrame(folder_frame, fg_color="transparent")
        folder_row.pack(fill="x", padx=12, pady=(4, 10))
        self.folder_path = ctk.StringVar(value=os.path.expanduser("~/Downloads/Telegram"))
        ctk.CTkEntry(folder_row, textvariable=self.folder_path).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(folder_row, text="Browse", width=80, command=self.browse).pack(side="right")

        # Activity is outside the settings scroll, as are all download controls.
        self.activity = ctk.CTkFrame(self)
        self.activity.grid(row=2, column=0, sticky="ew", padx=16, pady=4)
        activity_heading = ctk.CTkFrame(self.activity, fg_color="transparent")
        activity_heading.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(activity_heading, text="Activity", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.activity_toggle = ctk.CTkButton(activity_heading, text="Hide activity", width=110, command=self.toggle_activity)
        self.activity_toggle.pack(side="right")
        self.activity_tabs = ctk.CTkTabview(self.activity, height=130)
        self.activity_tabs.pack(fill="x", padx=8, pady=(0, 6))
        self.activity_tabs.add("Log")
        self.activity_tabs.add("History")
        self.log_box = ctk.CTkTextbox(self.activity_tabs.tab("Log"), height=70, font=("Courier", 11), state="disabled")
        self.log_box.pack(fill="both", expand=True)
        self.history_box = ctk.CTkTextbox(self.activity_tabs.tab("History"), height=70, font=("Courier", 11))
        self.history_box.pack(fill="both", expand=True)
        self._activity_visible = True
        self._load_history_tab()
        footer = ctk.CTkFrame(self)
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 12))
        footer.grid_columnconfigure(0, weight=1)
        self.progress_label = ctk.CTkLabel(footer, text="Ready · log in to choose a source", anchor="w")
        self.progress_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(6, 0))
        self.progress = ctk.CTkProgressBar(footer)
        self.progress.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 10))
        self.progress.set(0)
        buttons = ctk.CTkFrame(footer, fg_color="transparent")
        buttons.grid(row=0, column=1, rowspan=2, padx=8, pady=8)
        self.start_btn = ctk.CTkButton(buttons, text="Start", width=88, state="disabled", command=self.start_download)
        self.pause_btn = ctk.CTkButton(buttons, text="Pause", width=88, state="disabled", command=self.pause)
        self.cancel_btn = ctk.CTkButton(buttons, text="Cancel", width=88, state="disabled", fg_color="#963b42", command=self.cancel)
        for button in (self.start_btn, self.pause_btn, self.cancel_btn):
            button.pack(side="left", padx=4)
        if self.winfo_screenheight() < 900:
            self.toggle_activity()
        self.after_idle(self._refresh_layout)

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
            self.activity_tabs.pack(fill="x", padx=8, pady=(0, 6))
        else:
            self.activity_tabs.pack_forget()
        self.activity_toggle.configure(text="Hide activity" if self._activity_visible else "Show activity")

    def _on_window_resize(self, event):
        if event.widget is self:
            self._refresh_layout()

    def _refresh_layout(self):
        compact = self.winfo_width() < 1040
        width = self.winfo_width() - 76 if compact else (self.winfo_width() - 100) // 2
        for label in (self.channel_hint, self.topic_count, self.topic_status):
            label.configure(wraplength=max(260, width))
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        if compact:
            self.workspace.grid_columnconfigure(0, weight=1, uniform="")
            self.workspace.grid_columnconfigure(1, weight=0, uniform="")
            self.pane_switch.grid(row=0, column=0, sticky="ew", pady=(0, 6))
            self.show_workspace_pane(self.pane_switch.get())
        else:
            self.workspace.grid_columnconfigure(0, weight=1, uniform="workspace")
            self.workspace.grid_columnconfigure(1, weight=1, uniform="workspace")
            self.pane_switch.grid_remove()
            self.source_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
            self.settings_panel.grid(row=1, column=1, sticky="nsew", padx=(6, 0))

    def show_workspace_pane(self, pane):
        if not self._compact_layout:
            return
        self.source_panel.grid_remove()
        self.settings_panel.grid_remove()
        panel = self.source_panel if pane == "Channels & topics" else self.settings_panel
        panel.grid(row=1, column=0, sticky="nsew", padx=0)

    def browse(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(folder)

    def log(self, msg):
        self.after(0, self._log_safe, msg)

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
        try:
            self.downloader = TelegramDownloader(int(api_id), api_hash, phone)
        except Exception:
            self.log("Could not initialize Telegram. Check local session permissions.")
            self.loop.close()
            self.loop = None
            return
        self.after(0, lambda: self.login_btn.configure(state="disabled"))
        self.log("🔄 Connecting to Telegram...")
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self._async_login(), self.loop)

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
            self.after(0, lambda: self.api_hash.delete(0, "end"))
            self.after(0, lambda: self.phone.delete(0, "end"))
            self.after(0, lambda: self.api_id.delete(0, "end"))

            channels = await self.downloader.get_channels()
            self.channels = channels
            names = [f"{'📢' if c.is_channel else '👥'} {c.name} [{c.id}]" for c in channels]

            self.after(0, lambda: self.channel_menu.configure(values=names, state="normal"))
            if names:
                self.after(0, lambda: self.channel_menu.set(names[0]))
                self.after(0, self.select_channel)
            self.after(0, self.filter_channels)
            self.log(f"📋 {len(channels)} channels & groups loaded.")

        except Exception:
            self.log("❌ Login failed. Check credentials and account authentication settings.")
            self.after(0, lambda: self.login_btn.configure(state="normal"))
        finally:
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

    def choose_filtered_channel(self, _event=None):
        if self.busy:
            return
        query = self.channel_search.get().strip().casefold()
        matches = [c for c in self.channels if query in c.name.casefold() or query in str(c.id)]
        if matches:
            c = matches[0]
            self.channel_var.set(f"{'📢' if c.is_channel else '👥'} {c.name} [{c.id}]")
            self.select_channel()

    def filter_channels(self, _event=None):
        if self.busy:
            return
        query = self.channel_search.get().strip().casefold()
        names = [f"{'📢' if c.is_channel else '👥'} {c.name} [{c.id}]" for c in self.channels
                 if query in c.name.casefold() or query in str(c.id)]
        self.channel_menu.configure(values=names or ["No matches"], state="normal" if names else "disabled")
        self.channel_hint.configure(text=f"{len(names)} matching channels / groups. Selected: {self.channel_var.get() or 'none'}")

    def filter_topics(self, _event=None):
        query = self.topic_search.get().strip().casefold()
        for label, (_var, check) in self.topic_checks.items():
            check.pack_forget()
            if query in label.casefold():
                check.pack(anchor="w", fill="x", padx=6, pady=4)
        self.update_topic_count()

    def update_topic_count(self):
        count = sum(var.get() for var, _check in self.topic_checks.values())
        visible = sum(self.topic_search.get().strip().casefold() in label.casefold() for label in self.topic_checks)
        self.topic_count.configure(text=f"{count} selected · {visible} matching topics (search preserves selections)")
        self.start_btn.configure(state="normal" if not self.busy and (count or not getattr(self.selected_channel().entity, "forum", False)) else "disabled")

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
        self.topic_generation += 1
        generation = self.topic_generation
        self.topics = {}
        for _var, check in self.topic_checks.values():
            check.destroy()
        self.topic_checks = {}
        self.topic_search.delete(0, "end")
        self.topic_count.configure(text="No topics selected")
        selected = self.selected_channel()
        self.channel_hint.configure(text=f"Selected: {selected.name}")
        self.start_btn.configure(state="disabled")
        self.topic_menu.configure(state="disabled")
        if not getattr(selected.entity, "forum", False):
            self.topic_var.set("No topic required")
            self.start_btn.configure(state="normal")
            return
        self.topic_var.set("Loading topics...")
        async def load():
            try:
                topics = await self.downloader.get_topics(selected)
                self.after(0, apply_topics, topics, None)
            except Exception:
                self.after(0, apply_topics, [], True)
        def apply_topics(topics, error):
            if generation != self.topic_generation:
                return
            self.topics = {f"{t.title} [{t.id}]": t.id for t in topics}
            if error or not topics:
                self.topic_var.set("Topics unavailable — reselect group to retry")
                self.log("❌ Could not load topics. Reselect the group to retry.")
                return
            self.topic_menu.configure(values=list(self.topics), state="normal")
            self.topic_var.set("Choose one or more topics below.")
            for label in self.topics:
                var = ctk.BooleanVar(value=False)
                check = ctk.CTkCheckBox(self.topic_list, text=label, variable=var, command=self.update_topic_count)
                check.pack(anchor="w", fill="x", padx=6, pady=4)
                self.topic_checks[label] = (var, check)
            self.start_btn.configure(state="disabled")
        asyncio.run_coroutine_threadsafe(load(), self.loop)

    def start_download(self):
        if self.busy:
            return
        selected = self.selected_channel()
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
            self.log("Enter a positive number of files per topic.")
            return
        custom_limit = int(raw_limit) if limit_mode == "custom" else 20
        if not self.folder_path.get().strip():
            self.log("Choose a destination folder.")
            return

        folder = group_folder(self.folder_path.get(), selected.name, selected.id)

        base_folder = folder
        self.log("Starting download for the selected channel/topic...")
        self.busy = True
        # Reset before scheduling so an immediate Cancel cannot be overwritten.
        self.downloader.paused = False
        self.downloader.cancelled = False
        self.channel_menu.configure(state="disabled")
        self.channel_search.configure(state="disabled")
        self.topic_search.configure(state="disabled")
        for _var, check in self.topic_checks.values():
            check.configure(state="disabled")
        reverse = self.reverse.get()
        if limit_mode == "all":
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        self.after(0, lambda: self.progress.set(0))
        self.after(0, lambda: self.progress_label.configure(text="Starting..."))
        self.after(0, lambda: self.start_btn.configure(state="disabled"))
        self.after(0, lambda: self.pause_btn.configure(state="normal"))
        self.after(0, lambda: self.cancel_btn.configure(state="normal"))

        def on_progress(count, skipped, fraction):
            self.after(0, lambda: self.progress_label.configure(
                text=f"✅ {count} downloaded  |  ⏭ {skipped} skipped"
            ))
            self.after(0, lambda: self.progress.set(min(fraction, 1.0)))

        async def run_download():
            try:
                status = "complete"
                for index, current_topic in enumerate(topic_ids or [None]):
                    if self.downloader.cancelled:
                        status = "cancelled"
                        break
                    folder = os.path.join(base_folder, f"topic_{current_topic}") if current_topic is not None else base_folder
                    name = next((label for label, tid in topic_labels.items() if tid == current_topic), "")
                    self.log(f"Scope {index + 1}/{len(topic_ids) or 1}: {name or selected.name}")
                    def done(count, skipped, destination=folder, title=name):
                        save_history(selected.name + (f" / {title}" if title else ""), destination, count)
                        self.after(0, self._load_history_tab)
                        self.log(f"Scope finished: {count} downloaded, {skipped} skipped.")
                    result = await self.downloader.download(
                        selected, folder, selected_type, limit_mode, custom_limit,
                        reverse, on_progress, self.log, done, topic_id=current_topic, reset_controls=False)
                    if result != "complete":
                        status = result
                        if result == "cancelled":
                            break
                if status == "complete":
                    self.after(0, lambda: self.progress.set(1))
                self.after(0, lambda: self.progress_label.configure(text=f"Download {status}"))
            except Exception:
                self.log("❌ Download failed. Check connection and local file permissions.")
                self.after(0, lambda: self.progress_label.configure(text="Download failed"))
            finally:
                self.after(0, finish)
        def finish():
            self.busy = False
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.channel_menu.configure(state="normal")
            self.channel_search.configure(state="normal")
            self.topic_search.configure(state="normal")
            for _var, check in self.topic_checks.values():
                check.configure(state="normal")
            self.start_btn.configure(state="normal")
            self.pause_btn.configure(state="disabled", text="⏸ Pause")
            self.cancel_btn.configure(state="disabled")
        asyncio.run_coroutine_threadsafe(run_download(), self.loop)

    def pause(self):
        self.downloader.paused = not self.downloader.paused
        label = "▶ Resume" if self.downloader.paused else "⏸ Pause"
        self.after(0, lambda: self.pause_btn.configure(text=label))
        self.progress_label.configure(text="Paused" if self.downloader.paused else "Downloading…")
        self.log("⏸ Paused." if self.downloader.paused else "▶ Resumed.")

    def cancel(self):
        self.downloader.cancelled = True
        self.log("⛔ Cancelling...")
        self.after(0, lambda: self.pause_btn.configure(state="disabled"))
        self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
        self.after(0, lambda: self.start_btn.configure(state="disabled"))

