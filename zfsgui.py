import rumps
import libzfs
import logging
import os

from copy import copy
from collections import OrderedDict
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from threading import Thread, Event, Lock


disk_path = '/var/run/disk/by-id'
icon = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'openzfs.icns')

class ScanningEventHandler(FileSystemEventHandler):

    def on_modified(self, event):
        notified = copy(app.importable)
        app.scan_importable_pools()
        for guid, pool in app.importable.items():
            if guid not in notified.keys():
                rumps.notification('New pool available for import', None,
                                   'Pool ' + str(pool.name) + ' is available for import')


class ScanningTimer(Thread):

    def __init__(self):
        super().__init__()
        self.terminate = Event()

    def run(self):
        while not self.terminate.wait(5):
            app.scan_active_pools()


class OrderedPoolDict(OrderedDict):

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


class PoolMenuItem(rumps.MenuItem):

    def __init__(self, pool):
        super().__init__(pool.guid)
        self.title = pool.name
        self.pool = pool


class ImportablePoolMenuItem(PoolMenuItem):

    def __init__(self, pool):
        super().__init__(pool)
        self.add(rumps.MenuItem('Import', callback=self.import_pool))
        self.add(rumps.MenuItem('GUID: ' + str(pool.guid)))

    def import_pool(self, sender):
        try:
            logging.info('Importing pool ' + str(self.pool.name) + ' (' + str(self.pool.guid) + ')')
            libzfs.ZFS().import_pool(self.pool, self.pool.name, {})
        except libzfs.ZFSException as e:
            logging.error('Import failed: ' + str(e))
            rumps.notification('Import error', 'Error was encountered while importing ' + self.pool.name,
                               str(e).capitalize())
            return
        rumps.notification('Import successful', 'Pool ' + self.pool.name + ' was successfully imported', None)


class ActivePoolMenuItem(PoolMenuItem):

    def __init__(self, pool):
        super().__init__(pool)
        self.add(rumps.MenuItem('Export', callback=self.export_pool))
        self.add(rumps.MenuItem('GUID: ' + str(pool.guid)))

    def export_pool(self, sender):
        try:
            logging.info('Exporting pool ' + str(self.pool.name) + ' (' + str(self.pool.guid) + ')')
            libzfs.ZFS().export_pool(self.pool)
        except libzfs.ZFSException as e:
            logging.error('Export failed: ' + str(e))
            rumps.notification('Export failed', 'Pool ' + self.pool.name + ' could not be exported',
                               str(e).capitalize())
            return
        rumps.notification('Export successful', 'Pool ' + self.pool.name + ' was successfully exported', None)


class ZfsGui(rumps.App):

    def __init__(self):
        super().__init__('ZFS GUI', icon=icon)

        self.menu.add(rumps.MenuItem('importable'))
        self.menu.get('importable').title = 'No pools available for import'
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem('active'))
        self.menu.get('active').title = 'No active pools'
        self.menu.add(rumps.separator)

        self.importable = OrderedPoolDict()
        self.active = OrderedPoolDict()
        self.scan_importable_pools()

    def scan_importable_pools(self):
        logging.debug('Scanning importable pools')
        pools = sorted(list(libzfs.ZFS().find_import(search_paths=[disk_path])),
                       key=lambda pool: str(pool.name), reverse=True)
        keys = [p.guid for p in pools]
        logging.debug(str(pools))
        with self.importable.lock:
            self.importable.update(zip(keys, pools))
        if self.importable.updated.is_set():
            self._update_importable_menu()
            self.scan_active_pools()

    def scan_active_pools(self):
        logging.debug('Scanning active pools')
        pools = sorted(list(libzfs.ZFS().pools), key=lambda pool: str(pool.name), reverse=True)
        keys = [p.guid for p in pools]
        logging.debug(str(pools))
        with self.active.lock:
            self.active.update(zip(keys, pools))
        if self.active.updated.is_set():
            self._update_active_menu()
            self.scan_importable_pools()

    def _update_importable_menu(self):
        self._clean_importable_menu()
        if self.importable:
            if len(self.importable) == 1:
                self.menu.get('importable').title = str(len(self.importable)) + ' pool importable'
            else:
                self.menu.get('importable').title = str(len(self.importable)) + ' pools importable'
        else:
            self.menu.get('importable').title = 'No importable pools'
        with self.importable.lock:
            for pool in self.importable.values():
                self.menu.insert_after('importable', ImportablePoolMenuItem(pool))
            self.importable.updated.clear()

    def _clean_importable_menu(self):
        for key, value in self.menu.iteritems():
            if isinstance(value, ImportablePoolMenuItem):
                self.menu.pop(key)

    def _update_active_menu(self):
        self._clean_active_menu()
        if self.active:
            if len(self.active) == 1:
                self.menu.get('active').title = str(len(self.active)) + ' pool active'
            else:
                self.menu.get('active').title = str(len(self.active)) + ' pools active'
        else:
            self.menu.get('active').title = 'No active pools'
        with self.active.lock:
            for pool in self.active.values():
                self.menu.insert_after('active', ActivePoolMenuItem(pool))
            self.active.updated.clear()

    def _clean_active_menu(self):
        for key, value in self.menu.iteritems():
            if isinstance(value, ActivePoolMenuItem):
                self.menu.pop(key)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = ZfsGui()
    event_handler = ScanningEventHandler()
    observer = Observer()
    observer.schedule(event_handler, disk_path, recursive=True)
    observer.start()
    timer = ScanningTimer()
    timer.start()

    app.run()
