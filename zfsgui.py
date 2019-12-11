import logging, os, sys

from collections import OrderedDict as BaseOrderedDict
from elevate import elevate
from libzfs import ZFSImportablePool, ZFS, ZFSException
from multiprocessing import Lock
from threading import Event
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from Foundation import NSUserNotification, NSUserNotificationCenter, NSObject
from PySide2.QtCore import QThread, QObject, QTimer, Signal
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import QAction, QMenu, QWidgetAction, QVBoxLayout, QGridLayout, QLabel, QProgressBar, QWidget, \
    QApplication, QSystemTrayIcon


#disk_paths = ['/tmp/pools', '/var/run/disk/by-id']
disk_paths = ['/var/run/disk/by-path']
logfile = '/tmp/zfsgui.log'


class ZfsDevEventHandler(FileSystemEventHandler, QObject):

    devs_modified = Signal()

    def __init__(self):
        super().__init__()
        self.observer = Observer()
        for path in disk_paths:
            self.observer.schedule(self, path, recursive=True)

    def on_modified(self, event):
        self.devs_modified.emit()

    def start(self):
        self.observer.start()

    def stop(self):
        self.observer.stop()


class OrderedDict(BaseOrderedDict):

    def __init__(self):
        super().__init__()
        self.updated = Event()
        self.lock = Lock()

    def update(self, e=None, **f):
        keys_m = getattr(e, "keys", False)
        if keys_m and callable(keys_m):
            keys = e.keys
            values = e
        else:
            keys = []
            values = {}
            for k, v in e:
                keys.append(k)
                values[k] = v
        if list(self.keys()) != list(keys):
            self.clear()
            for k in keys:
                self[k] = values[k]
            for k in f:
                self[k] = f[k]
            self.updated.set()


class PoolWorker(QObject):

    terminate = Signal()
    updated = Signal()
    scan_init = Signal()
    scan_finished = Signal()
    new = Signal(object)
    type = 'generic'

    def __init__(self, parent=None, action=None):
        super().__init__(parent)
        self.action = action
        self.counter = 0
        self.pools = OrderedDict()
        self.scanning = Event()
        self.trigger = Event()
        self.notify = Event()
        self.lock = Lock()

    def scan(self):
        # Do not scan if already scanning or when not requested to scan
        if not self.scanning.is_set() and (self.trigger.is_set() or self.notify.is_set()):
            with self.lock:
                self.scanning.set()
                self.trigger.clear()
                self.scan_init.emit()
                logging.debug("Scanning " + self.type + " pools...")
                pools = self._do_scan()
                keys = [p.guid for p in pools]
                with self.pools.lock:
                    okeys = list(self.pools.keys())
                    self.pools.update(zip(keys, pools))
                    if self.pools.updated.is_set():
                        self.updated.emit()
                        if self.notify.is_set():
                            for key in keys:
                                if key not in okeys:
                                    self.new.emit(self.pools[key])
                            self.notify.clear()
                        self.pools.updated.clear()
                self.scan_finished.emit()
                self.scanning.clear()
                self.trigger.clear()

    def _do_scan(self):
        raise NotImplemented()


class ActivePoolWorker(PoolWorker):

    export_success = Signal(object)
    export_error = Signal(object, str)
    type = 'active'

    def _do_scan(self):
        return sorted(list(ZFS().pools), key=lambda pool: str(pool.name))

    def export_pool(self, pool):
        self.pools.pop(pool.guid)
        self.updated.emit()
        try:
            logging.info('Exporting pool ' + str(pool.name) + ' (' + str(pool.guid) + ')')
            ZFS().export_pool(pool)
        except ZFSException as e:
            logging.error('Export failed: ' + str(e))
            self.export_error.emit(pool, str(e).capitalize())
            return
        self.export_success.emit(pool)


class ImportablePoolWorker(PoolWorker):

    import_success = Signal(object)
    import_error = Signal(object, str)
    type = 'importable'

    def _do_scan(self):
        imports = list(ZFS().find_import(search_paths=disk_paths))
        return sorted(imports, key=lambda pool: str(pool.name))

    def import_pool(self, pool):
        self.pools.pop(pool.guid)
        self.updated.emit()
        try:
            logging.info('Importing pool ' + str(pool.name) + ' (' + str(pool.guid) + ')')
            ZFS().import_pool(pool, pool.name, {})
        except ZFSException as e:
            logging.error('Import failed: ' + str(e))
            self.import_error.emit(pool, str(e).capitalize())
            return
        self.import_success.emit(pool)


class MenuWorker(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.importable = {}
        self.active = {}
        self.lock = Lock()

    @staticmethod
    def update_menu(details=None):
        items, pools, next_action = details
        changed = False
        with pools.lock:
            remove = []
            for key in items:
                if key not in pools.keys():
                    logging.debug("Menu worker: removing item " + str(key))
                    submenu, action = items[key]
                    menu.removeAction(action)
                    remove.append(key)
                    changed = True
            for key in remove:
                items.pop(key)
            for key, pool in reversed(pools.items()):
                if key not in items.keys():
                    logging.debug("Menu worker: adding item " + str(key))
                    submenu = PoolMenu(pool)
                    action = menu.insertMenu(next_action, submenu)
                    items[key] = (submenu, action)
                    changed = True
                noop, next_action = items[key]
        return changed

    def update_importable_menu(self):
        with self.lock:
            details = (self.importable, importable_pool_worker.pools, importable_separator)
            self.update_menu(details)

    def importable_scan_running(self):
        importable_action.setText("Scanning importable pools...")

    def update_importable_details(self):
        if len(importable_pool_worker.pools) > 0:
            importable_action.setText("Importable pools")
        else:
            importable_action.setText("No importable pools")

    def update_active_menu(self):
        with self.lock:
            details = (self.active, active_pool_worker.pools, active_separator)
            self.update_menu(details)

    def active_scan_running(self):
        pass

    def update_active_details(self):
        if len(active_pool_worker.pools) > 0:
            active_action.setText("Active pools")
        else:
            active_action.setText("No active pools")


class PoolMenu(QMenu):

    def __init__(self, pool):
        super().__init__()
        self.setTitle(pool.name)
        status = pool.status
        if pool.status == 'ONLINE':
            self.setIcon(green_icon)
            pool_importable = True
        elif pool.status == 'DEGRADED':
            self.setIcon(yellow_icon)
            pool_importable = True
        elif pool.status in ['FAULTED', 'OFFLINE', 'UNAVAIL', 'REMOVED']:
            self.setIcon(red_icon)
            pool_importable = False
        else:
            self.setIcon(grey_icon)
            pool_importable = False
        self.addAction(PoolDetailsAction(pool, self))
        self.addSeparator()
        if pool.properties is not None:
            self.addAction(PoolSpaceAction(pool, self))
            self.addSeparator()
        if isinstance(pool, ZFSImportablePool):
            action = self.addAction("Import")
            action.triggered.connect(lambda: importable_pool_worker.import_pool(pool))
            action.setEnabled(pool_importable)
        else:
            action = self.addAction("Export")
            action.triggered.connect(lambda: active_pool_worker.export_pool(pool))


class PoolDetailsAction(QWidgetAction):

    def __init__(self, pool, parent):
        super().__init__(parent)
        outer_layout = QVBoxLayout()
        inner_layout = QGridLayout()
        inner_layout.setSpacing(2)
        inner_layout.setContentsMargins(0, 0, 0, 3)
        inner_layout.addWidget(QLabel("Name:"), 0, 0)
        inner_layout.addWidget(QLabel(str(pool.name)), 0, 1)
        inner_layout.addWidget(QLabel("GUID:"), 1, 0)
        inner_layout.addWidget(QLabel(str(pool.guid)), 1, 1)
        inner_layout.addWidget(QLabel("Status:"), 2, 0)
        inner_layout.addWidget(QLabel(str(pool.status).lower()), 2, 1)
        outer_layout.addLayout(inner_layout)
        outer_layout.setContentsMargins(21, 0, 15, 0)
        outer_layout.setSpacing(0)
        widget = QWidget()
        widget.setLayout(outer_layout)
        self.setDefaultWidget(widget)


class PoolSpaceAction(QWidgetAction):

    def __init__(self, pool, parent):
        super().__init__(parent)
        outerLayout = QVBoxLayout()
        bar = QProgressBar()
        bar.setValue(int(str(pool.properties['capacity'].value).replace('%', '')))
        outerLayout.addWidget(bar)
        outerLayout.addWidget(QLabel("Size: " + str(pool.properties['size'].value) + ", " +
                                     str(pool.properties['free'].value) + " free"))
        outerLayout.setContentsMargins(21, 0, 15, 0)
        outerLayout.setSpacing(0)
        widget = QWidget()
        widget.setLayout(outerLayout)
        self.setDefaultWidget(widget)


class NotificationDelegator(NSObject):

    def __init__(self):
        super().__init__()
        self.center = None

    def setCenter(self, center=None):
        self.center = center

    def userNotificationCenter_didActivateNotification_(self, center, notification):
        self.center.receive(center, notification)

    def userNotificationCenter_shouldPresentNotification_(self, center, notification):
        return True


class NotificationCenter(QObject):

    def __init__(self):
        super().__init__()
        self.delegator = NotificationDelegator.alloc().init()
        self.delegator.setCenter(self)

    def notify(self, title, subtitle=None, info_text=None, delay=0, sound=False,
               action_button=None, other_button=None, has_reply_button=False, user_info=None):
        """ Python method to show a desktop notification on Mountain Lion. Where:
            title: Title of notification
            subtitle: Subtitle of notification
            info_text: Informative text of notification
            delay: Delay (in seconds) before showing the notification
            sound: Play the default notification sound
            action_button: Action button title
            other_button: Other button title
            userInfo: a dictionary that can be used to handle clicks in your
                      app's applicationDidFinishLaunching:aNotification method
        """

        if user_info is None:
            user_info = {}

        notification = NSUserNotification.alloc().init()
        notification.setTitle_(title)
        if subtitle:
            notification.setSubtitle_(subtitle)
        if info_text:
            notification.setInformativeText_(info_text)
        notification.setUserInfo_(user_info)
        if sound:
            notification.setSoundName_("NSUserNotificationDefaultSoundName")
        if action_button:
            notification.setActionButtonTitle_(action_button)
            notification.set_showsButtons_(True)
        if other_button:
            notification.setOtherButtonTitle_(other_button)
            notification.set_showsButtons_(True)
        if has_reply_button:
            notification.setHasReplyButton_(True)

        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        center.setDelegate_(self.delegator)
        center.deliverNotification_(notification)

    def receive(self, center, notification):
        info = notification.userInfo()
        if 'action' in info.keys() and 'guid' in info.keys():
            if info['action'] == 'import':
                with importable_pool_worker.pools.lock:
                    pool = importable_pool_worker.pools[info['guid']]
                importable_pool_worker.import_pool(pool)
            if info['action'] == 'export':
                pool = active_pool_worker.pools[info['guid']]
                active_pool_worker.export_pool(pool)

    def notify_importable(self, pool, *argv):
        self.notify('New pool available for import', None, 'Pool ' + str(pool.name) + ' is available for import',
                    action_button='Import', other_button='Dismiss', user_info={
                'action': 'import',
                'guid': pool.guid
            })

    def notify_imported(self, pool, *argv):
        self.notify('Import successful', None, 'Pool ' + str(pool.name) + ' was successfully imported',
                    other_button='Dismiss')

    def notify_import_error(self, pool, error, *argv):
        self.notify('Import error', 'Error when importing pool ' + str(pool.name), error,
                    other_button='Dismiss')

    def notify_exported(self, pool, *argv):
        self.notify('Export successful', None, 'Pool ' + str(pool.name) + ' was successfully exported',
                    other_button='Dismiss')

    def notify_export_error(self, pool, error, *argv):
        self.notify('Export error', 'Error when exporting pool ' + str(pool.name), error,
                    other_button='Dismiss')

class AppController(QObject):

    @staticmethod
    def quit_action_clicked():
        timer.stop()
        active_pool_thread.terminate()
        importable_pool_thread.terminate()
        app.quit()


if __name__ == "__main__":

    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    elif __file__:
        application_path = os.path.dirname(__file__)

    logging.basicConfig(level=logging.INFO)

    if os.getuid() != 0:
        logging.info("Elevating privileges...")
        elevate(show_console=False, graphical=True)
    else:
        # Building the app
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        controller = AppController()
        icon = QIcon(os.path.join(application_path, "assets/icons.iconset/icon_128x128.png"))
        green_icon = QIcon(os.path.join(application_path, "assets/green_dot.png"))
        yellow_icon = QIcon(os.path.join(application_path, "assets/yellow_dot.png"))
        red_icon = QIcon(os.path.join(application_path, "assets/red_dot.png"))
        grey_icon = QIcon(os.path.join(application_path, "assets/grey_dot.png"))
        tray = QSystemTrayIcon()
        tray.setIcon(icon)
        tray.setVisible(True)
        nc = NotificationCenter()

        # Building menu
        menu = QMenu()
        importable_action = QAction("No importable pools")
        importable_action.setDisabled(True)
        menu.addAction(importable_action)
        importable_separator = menu.addSeparator()
        active_action = QAction("No active pools")
        active_action.setDisabled(True)
        menu.addAction(active_action)
        active_separator = menu.addSeparator()
        quit_action = QAction("Quit")
        quit_action.triggered.connect(controller.quit_action_clicked)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)

        # Setting up scanning threads
        active_pool_thread = QThread()
        importable_pool_thread = QThread()
        active_pool_thread.start()
        importable_pool_thread.start()
        active_pool_worker = ActivePoolWorker()
        importable_pool_worker = ImportablePoolWorker()
        menu_worker = MenuWorker()
        active_pool_worker.moveToThread(active_pool_thread)
        importable_pool_worker.moveToThread(importable_pool_thread)

        # Setting up timers
        timer = QTimer()
        timer.timeout.connect(active_pool_worker.scan)
        timer.timeout.connect(active_pool_worker.trigger.set)
        timer.timeout.connect(importable_pool_worker.scan)
        timer.start(1000)
        dev_handler = ZfsDevEventHandler()
        dev_handler.devs_modified.connect(importable_pool_worker.notify.set)
        dev_handler.start()

        # Setting scanning events
        active_pool_worker.scan_init.connect(menu_worker.active_scan_running)
        active_pool_worker.scan_finished.connect(menu_worker.update_active_details)
        active_pool_worker.updated.connect(menu_worker.update_active_menu)
        active_pool_worker.updated.connect(importable_pool_worker.trigger.set)
        active_pool_worker.export_success.connect(nc.notify_exported)
        active_pool_worker.export_success.connect(active_pool_worker.trigger.set)
        active_pool_worker.export_success.connect(importable_pool_worker.trigger.set)
        active_pool_worker.export_error.connect(nc.notify_export_error)
        active_pool_worker.export_error.connect(active_pool_worker.trigger.set)
        active_pool_worker.export_error.connect(importable_pool_worker.trigger.set)

        importable_pool_worker.scan_init.connect(menu_worker.importable_scan_running)
        importable_pool_worker.scan_finished.connect(menu_worker.update_importable_details)
        importable_pool_worker.updated.connect(menu_worker.update_importable_menu)
        importable_pool_worker.updated.connect(active_pool_worker.trigger.set)
        importable_pool_worker.new.connect(nc.notify_importable)
        importable_pool_worker.import_success.connect(nc.notify_imported)
        importable_pool_worker.import_success.connect(active_pool_worker.trigger.set)
        importable_pool_worker.import_success.connect(importable_pool_worker.trigger.set)
        importable_pool_worker.import_error.connect(nc.notify_import_error)
        importable_pool_worker.import_error.connect(active_pool_worker.trigger.set)
        importable_pool_worker.import_error.connect(importable_pool_worker.trigger.set)

        active_pool_worker.trigger.set()
        importable_pool_worker.trigger.set()

        app.exec_()
