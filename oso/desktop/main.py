"""GTK 4 desktop client for the same in-process AppService used by web."""
import asyncio
import logging
import threading
from pathlib import Path

from oso.core.browser_login import BrowserLogin
from oso.core.i18n import translate
from oso.core.logging import configureLogging
from oso.core.paths import AppPaths
from oso.core.recorder import RecorderManager
from oso.core.service import AppService

logger = logging.getLogger("oso.desktop")


def main():
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk, GLib, Gio, Gdk, Pango
    except (ImportError, ValueError) as error:
        raise SystemExit("GTK 4 + PyGObject are required; see README for desktop dependencies") from error

    paths = AppPaths.create("desktop")
    configureLogging(paths)
    service = AppService(paths, "desktop")
    browser = BrowserLogin(service)
    manager = RecorderManager(service)

    loop = asyncio.new_event_loop()
    def runLoop():
        asyncio.set_event_loop(loop)
        loop.run_forever()
    threading.Thread(target=runLoop, name="oso-background", daemon=True).start()
    asyncio.run_coroutine_threadsafe(manager.start(), loop).result(timeout=5)

    class DesktopApp(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="com.oso.StreamRecord", flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.window = None
            self.tray = None
            self.view = ("home", None)
            self.content = None
            self.navContent = None
            self.statusLabel = None
            self.openingLogin = False
            self.quitting = False

        def tr(self, key):
            return translate(service.settings()["language"] or "en", key)

        def on_activate(self, *args):
            if self.window is not None:
                self.window.present()
                return
            self.window = Gtk.ApplicationWindow(application=self, title="Oso Stream Record")
            self.window.set_default_size(1400, 900)
            self.window.set_size_request(1000, 700)
            self.window.maximize()
            self.window.connect("close-request", self.onClose)
            self.window.connect("notify::maximized", self.ensureMaximized)
            self.installStyle()
            self.installTray()
            mainBox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            self.window.set_child(mainBox)
            sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            sidebar.add_css_class("sidebar")
            sidebar.set_size_request(260, -1)
            mainBox.append(sidebar)
            brand = Gtk.Label(label="◉  OSO STREAM RECORD")
            brand.add_css_class("brand")
            sidebar.append(brand)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(True)
            sidebar.append(scroll)
            self.navContent = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            scroll.set_child(self.navContent)
            for route, key in (("cloud", "cloud"), ("export", "export"), ("import", "import"), ("settings", "settings")):
                self.button(sidebar, key, lambda _, value=route: self.navigate(value), "nav-button")
            self.button(sidebar, "quit", lambda _: self.confirmQuit(), "nav-button")
            self.contentScroll = Gtk.ScrolledWindow()
            self.contentScroll.set_hexpand(True)
            self.contentScroll.set_vexpand(True)
            mainBox.append(self.contentScroll)
            self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
            self.content.add_css_class("page")
            self.contentScroll.set_child(self.content)
            self.refreshNav()
            self.refreshPage()
            self.window.present()
            if not service.settings()["language"]:
                self.languageDialog()
            GLib.timeout_add_seconds(5, self.poll)

        def installStyle(self):
            css = Gtk.CssProvider()
            css.load_from_data(b"""
            window {background:#f7f8fb;color:#243047;font-size:14px}
            .sidebar{background:#142137;padding:20px 14px;color:#e1e7f2}
            .brand{font-size:17px;font-weight:800;color:white;margin-bottom:18px}
            .nav-button{background:transparent;color:#e2e9fb;border:0;box-shadow:none;text-align:left}
            .nav-button:hover{background:#2d3c57}
            .channel-nav{background:transparent;color:#abb9d0;border:0;box-shadow:none;margin-left:15px}
            .page{padding:36px 42px}
            .headline{font-size:28px;font-weight:800;color:#172239;margin-bottom:5px}
            .section-title{font-size:18px;font-weight:750;margin-bottom:12px}
            .card{background:white;border:1px solid #e2e6ef;border-radius:12px;padding:24px;margin-bottom:16px}
            .primary{background:#5367e9;color:white;border-radius:8px}
            .danger{color:#c94a58}
            .muted{color:#778296}
            .field-name{font-weight:650;color:#526074}
            """)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        def installTray(self):
            try:
                import pystray
                from PIL import Image, ImageDraw
                img = Image.new("RGBA", (64, 64), "#5367e9")
                d = ImageDraw.Draw(img)
                d.ellipse((14, 14, 50, 50), fill="white")
                d.ellipse((23, 23, 41, 41), fill="#5367e9")
                self.tray = pystray.Icon("oso-stream-record", img, "Oso Stream Record",
                    menu=pystray.Menu(
                        pystray.MenuItem("Show", lambda icon, item: GLib.idle_add(self.showWindow), default=True),
                        pystray.MenuItem("Quit", lambda icon, item: GLib.idle_add(self.confirmQuit))))
                self.tray.run_detached()
            except Exception:
                self.tray = None
                logger.warning("System tray unavailable; closing the window will be prevented", exc_info=True)

        def showWindow(self):
            self.window.present()
            return False

        def ensureMaximized(self, win, value):
            if not win.is_maximized():
                GLib.idle_add(win.maximize)

        def onClose(self, win):
            if self.quitting:
                return False
            if self.tray:
                win.hide()
            else:
                self.alert("System tray is unavailable. Use Quit in the sidebar to exit.")
            return True

        def confirmQuit(self):
            self.confirm("Stop all recordings and quit Oso Stream Record?", self.stopApp)
            return False

        def stopApp(self):
            if self.quitting:
                return
            self.quitting = True
            async def stop():
                await manager.shutdown()
                loop.call_soon(loop.stop)
                GLib.idle_add(self.finishQuit)
            asyncio.run_coroutine_threadsafe(stop(), loop)

        def finishQuit(self):
            if self.tray:
                self.tray.stop()
            self.quit()
            return False

        def poll(self):
            if not self.quitting:
                self.refreshNav()
            return not self.quitting

        def work(self, function, after=None):
            async def run():
                try:
                    result = await asyncio.to_thread(function)
                    if after:
                        GLib.idle_add(after, result)
                except Exception as error:
                    logger.exception("Operation failed")
                    GLib.idle_add(self.alert, str(error))
            asyncio.run_coroutine_threadsafe(run(), loop)

        def task(self, coroutine, after=None):
            async def run():
                try:
                    result = await coroutine
                    if after:
                        GLib.idle_add(after, result)
                except Exception as error:
                    logger.exception("Operation failed")
                    GLib.idle_add(self.alert, str(error))
            asyncio.run_coroutine_threadsafe(run(), loop)

        def alert(self, text):
            dialog = Gtk.MessageDialog(transient_for=self.window, modal=True, buttons=Gtk.ButtonsType.OK, text=text)
            dialog.connect("response", lambda d, response: d.destroy())
            dialog.present()
            return False

        def confirm(self, text, callback):
            dialog = Gtk.MessageDialog(transient_for=self.window, modal=True, buttons=Gtk.ButtonsType.OK_CANCEL, text=text)
            def answered(d, response):
                d.destroy()
                if response == Gtk.ResponseType.OK:
                    callback()
            dialog.connect("response", answered)
            dialog.present()

        def button(self, parent, key, callback, style=None):
            button = Gtk.Button(label=self.tr(key))
            if style:
                button.add_css_class(style)
            button.connect("clicked", callback)
            parent.append(button)
            return button

        def label(self, parent, text, style=None):
            label = Gtk.Label(label=str(text), xalign=0, wrap=True, selectable=True)
            if style:
                label.add_css_class(style)
            parent.append(label)
            return label

        def section(self, title):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            card.add_css_class("card")
            self.content.append(card)
            self.label(card, self.tr(title), "section-title")
            return card

        def entry(self, parent, key, value="", password=False):
            line = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            parent.append(line)
            self.label(line, self.tr(key), "field-name")
            edit = Gtk.Entry()
            if password:
                edit.set_visibility(False)
            edit.set_hexpand(True)
            edit.set_text(str(value or ""))
            line.append(edit)
            return edit

        def check(self, parent, key, value):
            check = Gtk.CheckButton(label=self.tr(key))
            check.set_active(bool(value))
            parent.append(check)
            return check

        def dropdown(self, parent, key, options, value=None):
            self.label(parent, self.tr(key), "field-name")
            items = [str(label) for val, label in options]
            dropdown = Gtk.DropDown.new_from_strings(items)
            dropdown.set_selected(next((n for n, (v, _) in enumerate(options) if str(v) == str(value)), 0))
            parent.append(dropdown)
            return dropdown

        def clear(self, box):
            while box.get_first_child() is not None:
                box.remove(box.get_first_child())

        def refreshNav(self):
            if not self.navContent:
                return
            self.clear(self.navContent)
            self.button(self.navContent, "home", lambda _: self.navigate("home"), "nav-button")
            for profile in service.profiles():
                self.button(self.navContent, profile["name"] + ("  [disabled]" if not profile["enabled"] else ""),
                            lambda _, id=profile["id"]: self.navigate("profile", id), "nav-button")
                for channel in service.channels(profile["id"]):
                    state = manager.state(channel["id"])
                    display = "@" + channel["username"]
                    if not channel["enabled"]:
                        display += " [disabled]"
                    if state["recording"]:
                        display += " ● REC"
                    elif state["live"] is True:
                        display += " ● LIVE"
                    elif state["live"] is False:
                        display += " · OFFLINE"
                    self.button(self.navContent, display, lambda _, id=channel["id"]: self.navigate("channel", id), "channel-nav")
            self.button(self.navContent, "newProfile", lambda _: self.newProfile(), "nav-button")

        def navigate(self, view, itemId=None):
            self.view = (view, itemId)
            self.refreshPage()

        def done(self, result=None):
            self.refreshNav()
            self.refreshPage()
            return False

        def refreshPage(self):
            if not self.content:
                return
            self.clear(self.content)
            view, id = self.view
            if view == "home": self.homePage()
            elif view == "profile": self.profilePage(id)
            elif view == "channel": self.channelPage(id)
            elif view == "cloud": self.cloudPage()
            elif view == "videos": self.videosPage(id)
            elif view == "settings": self.settingsPage()
            elif view == "export": self.exportPage()
            elif view == "import": self.importPage()

        def homePage(self):
            self.label(self.content, self.tr("overview"), "headline")
            self.label(self.content, self.tr("homeIntro"), "muted")
            card = self.section("trackedChannels")
            for channel in service.channels():
                state = manager.state(channel["id"])
                self.button(card, "@" + channel["username"] + ("  ● REC" if state["recording"] else ""),
                            lambda _, id=channel["id"]: self.navigate("channel", id))
            self.button(self.content, "newProfile", lambda _: self.newProfile(), "primary")

        def newProfile(self):
            dialog = Gtk.Dialog(title=self.tr("newProfile"), transient_for=self.window, modal=True)
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dialog.add_button("Create", Gtk.ResponseType.OK)
            editor = self.entry(dialog.get_content_area(), "profileName")
            def save(d, response):
                value = editor.get_text()
                d.destroy()
                if response == Gtk.ResponseType.OK:
                    self.work(lambda: service.createProfile(value), self.done)
            dialog.connect("response", save)
            dialog.present()

        def profilePage(self, id):
            p = service.profile(id)
            self.label(self.content, p["name"], "headline")
            card = self.section("recordingPreferences")
            name = self.entry(card, "profileName", p["name"])
            enabled = self.check(card, "profileEnabled", p["enabled"])
            autoUpload = self.check(card, "autoUpload", p["auto_upload"])
            accountOptions = [("", self.tr("noAccount"))] + [(str(a["id"]), a["alias"]) for a in service.cloudAccounts()]
            account = self.dropdown(card, "cloudAccount", accountOptions, p["cloud_id"])
            cloudFolder = self.entry(card, "cloudFolder", p["cloud_folder"])
            deleteUploaded = self.check(card, "deleteUploaded", p["delete_uploaded"])
            older = self.entry(card, "deleteOld", p["delete_older_hours"] or "")
            base = self.entry(card, "defaultVideoDir", p["video_dir"] or str(service.videoRoot(p)))
            def save(_):
                value = accountOptions[account.get_selected()][0]
                self.work(lambda: service.updateProfile(id, name=name.get_text(),enabled=enabled.get_active(),
                    auto_upload=autoUpload.get_active(),cloud_id=value or None,cloud_folder=cloudFolder.get_text(),
                    delete_uploaded=deleteUploaded.get_active(),delete_older_hours=older.get_text(),
                    video_dir=base.get_text()), self.done)
            self.button(card, "saveChanges", save, "primary")
            loginCard = self.section("browserSession")
            self.label(loginCard, self.tr("browserLoginInfo"), "muted")
            self.button(loginCard, "loginBrowser", lambda _: self.work(lambda: browser.desktopLogin(id)), "primary")
            channelCard = self.section("addChannel")
            platform = self.dropdown(channelCard, "platform", [("tiktok","TikTok")])
            username = self.entry(channelCard, "username")
            self.button(channelCard, "addChannel", lambda _: self.work(lambda: service.createChannel(id, "tiktok", username.get_text()), self.done), "primary")
            self.button(self.content, "deleteProfile", lambda _: self.confirm(self.tr("confirmDelete"),
                lambda: self.work(lambda: service.deleteProfile(id), lambda _: self.navigate("home"))), "danger")

        def channelPage(self, id):
            c = service.channel(id)
            state = manager.state(id)
            self.label(self.content, "@" + c["username"], "headline")
            card = self.section("liveStatus")
            self.label(card, f"{self.tr('status')}: {state['status']} | LIVE: {state['live']}")
            if state["error"]:
                self.label(card, state["error"], "danger")
            if state["recording"]:
                if state["manual"]:
                    self.button(card, "stopRecording", lambda _: self.task(manager.stopManual(id), self.done), "primary")
            else:
                self.button(card, "recordNow", lambda _: self.task(manager.beginManual(id), self.done), "primary")
            self.button(card, "checkLive", lambda _: self.task(manager.checkStatus(id), self.done))
            self.button(card, "viewVideos", lambda _: self.navigate("videos", id))
            settings = self.section("channelSettings")
            username = self.entry(settings, "username", c["username"])
            self.label(settings, "TikTok")
            enabled = self.check(settings, "channelEnabled", c["enabled"])
            automatic = self.check(settings, "autoRecord", c["auto_record"])
            self.button(settings, "saveChanges", lambda _: self.work(lambda: service.updateChannel(id,
                username=username.get_text(), enabled=enabled.get_active(), auto_record=automatic.get_active()), self.done), "primary")
            self.label(self.section("statistics"), f"{self.tr('localVideos')}: {len(service.videos(channelId=id))}")
            self.button(self.content, "deleteChannel", lambda _: self.confirm(self.tr("confirmDelete"),
                lambda: self.work(lambda: service.deleteChannel(id), lambda _: self.navigate("home"))), "danger")

        def videosPage(self, channelId):
            self.label(self.content, self.tr("videos"), "headline")
            filters = self.section("recordedFiles")
            search = self.entry(filters, "searchVideos")
            sortOptions = [("date", self.tr("date")), ("name", self.tr("name")), ("channel", self.tr("channel")), ("size", self.tr("size"))]
            sorting = self.dropdown(filters, "sort", sortOptions)
            rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
            filters.append(rows)
            def rebuild(*args):
                self.clear(rows)
                for video in service.videos(channelId=channelId, search=search.get_text(), sort=sortOptions[sorting.get_selected()][0]):
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                    rows.append(row)
                    name = Gtk.Label(label=f"{video['name']} · @{video['username']} · {video['size']//1024} KB", xalign=0)
                    name.set_hexpand(True)
                    name.set_ellipsize(Pango.EllipsizeMode.END)
                    row.append(name)
                    self.button(row, "openFolder", lambda _, path=video["path"]: Gio.AppInfo.launch_default_for_uri(Path(path).parent.as_uri()), "primary")
            search.connect("changed", rebuild)
            sorting.connect("notify::selected", rebuild)
            rebuild()

        def cloudPage(self):
            self.label(self.content, self.tr("cloud"), "headline")
            accounts = self.section("connectedAccounts")
            for account in service.cloudAccounts():
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
                accounts.append(row)
                self.label(row, f"{account['alias']} · {account['email']} (MEGA)")
                self.button(row, "delete", lambda _, id=account["id"]: self.confirm(self.tr("confirmDelete"),
                    lambda: self.work(lambda: service.deleteCloudAccount(id), self.done)))
            card = self.section("addAccount")
            alias = self.entry(card, "alias")
            email = self.entry(card, "email")
            password = self.entry(card, "password", password=True)
            self.button(card, "addAccount", lambda _: self.work(lambda: service.createCloudAccount("mega", alias.get_text(), email.get_text(),password.get_text()), self.done), "primary")

        def settingsPage(self):
            self.label(self.content, self.tr("settings"), "headline")
            card = self.section("generalSettings")
            opts = [("en", "English"), ("es", "Español"), ("pt", "Português")]
            lang = self.dropdown(card, "language", opts, service.settings()["language"])
            directory = self.entry(card, "defaultVideoDir", service.settings()["default_video_dir"])
            passphrase = self.entry(card, "encryptionPassphrase", service.passphrases.load(), password=True)
            self.button(card, "show", lambda _: passphrase.set_visibility(not passphrase.get_visibility()))
            self.button(card, "copy", lambda _: Gdk.Display.get_default().get_clipboard().set(passphrase.get_text()))
            self.label(card, self.tr("passphraseWarning"), "muted")
            self.button(card, "saveChanges", lambda _: self.work(lambda: service.updateSettings(
                language=opts[lang.get_selected()][0], default_video_dir=directory.get_text(),passphrase=passphrase.get_text()), self.done), "primary")

        def exportPage(self):
            self.label(self.content, self.tr("export"), "headline")
            card = self.section("encryptedBackup")
            self.label(card, self.tr("exportInfo"), "muted")
            key = self.entry(card, "encryptionPassphrase", password=True)
            def save(_):
                chooser = Gtk.FileChooserNative(title=self.tr("export"), transient_for=self.window, action=Gtk.FileChooserAction.SAVE,
                                               accept_label=self.tr("export"), cancel_label=self.tr("cancel"))
                chooser.set_current_name("oso-stream-record-backup.zip")
                def selected(dialog, response):
                    if response == Gtk.ResponseType.ACCEPT:
                        target = dialog.get_file().get_path()
                        def write():
                            if key.get_text() != service.passphrases.load():
                                raise ValueError("Incorrect passphrase")
                            Path(target).write_bytes(service.exportArchive(key.get_text()))
                        self.work(write, lambda _: self.alert(self.tr("backupDownloaded")))
                    dialog.destroy()
                chooser.connect("response", selected)
                chooser.show()
            self.button(card, "downloadBackup", save, "primary")

        def importPage(self):
            self.label(self.content, self.tr("import"), "headline")
            card = self.section("restoreBackup")
            self.label(card, self.tr("importWarning"), "danger")
            key = self.entry(card, "encryptionPassphrase", password=True)
            def openFile(_):
                chooser = Gtk.FileChooserNative(title=self.tr("import"), transient_for=self.window, action=Gtk.FileChooserAction.OPEN,
                                               accept_label=self.tr("import"), cancel_label=self.tr("cancel"))
                def picked(dialog, response):
                    if response == Gtk.ResponseType.ACCEPT:
                        path = dialog.get_file().get_path()
                        self.confirm(self.tr("confirmImport"), lambda: self.task(self.importTask(path, key.get_text()), self.done))
                    dialog.destroy()
                chooser.connect("response", picked)
                chooser.show()
            self.button(card, "replaceData", openFile, "primary")

        async def importTask(self, path, key):
            await manager.shutdown()
            try:
                await asyncio.to_thread(service.importArchive, Path(path).read_bytes(), key)
            finally:
                await manager.start()

        def languageDialog(self):
            dialog = Gtk.Dialog(title="Choose your language", transient_for=self.window, modal=True)
            dialog.set_deletable(False)
            for index, label in enumerate(("English", "Español", "Português"), 1):
                dialog.add_button(label, index)
            def choose(d, index):
                d.destroy()
                lang = {1:"en",2:"es",3:"pt"}.get(index,"en")
                self.work(lambda: service.updateSettings(language=lang), self.done)
            dialog.connect("response", choose)
            dialog.present()

    application = DesktopApp()
    application.connect("activate", application.on_activate)
    try:
        return application.run(None)
    finally:
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(manager.shutdown(), loop)
            try: future.result(timeout=30)
            except Exception: logger.exception("Unable to stop worker cleanly")
            loop.call_soon_threadsafe(loop.stop)


if __name__ == "__main__":
    main()
