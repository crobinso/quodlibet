# -*- coding: utf-8 -*-
# Copyright 2014 Christoph Reiter
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation

import os
import errno
import signal
import stat
import tempfile

from gi.repository import GLib

from quodlibet.util.path import mkdir


def write_fifo(fifo_path, data):
    """Writes the data to the fifo or raises EnvironmentError"""

    try:
        # This is a total abuse of Python! Hooray!
        signal.signal(signal.SIGALRM, lambda: "" + 2)
        signal.alarm(1)
        f = file(fifo_path, "w")
        signal.signal(signal.SIGALRM, signal.SIG_IGN)
        f.write(data)
        f.close()
    except (OSError, IOError, TypeError):
        # Unable to write to the fifo. Removing it.
        try:
            os.unlink(fifo_path)
        except OSError:
            pass
        raise EnvironmentError("Couldn't write to fifo %r" % fifo_path)


def write_fifo_reply(fifo_path, data):
    """Writes the data to the fifo and returns a response
    or raises EnvironmentError.
    """

    fd, filename = tempfile.mkstemp()
    try:
        os.unlink(filename)
        # mkfifo fails if the file exists, so this is safe.
        os.mkfifo(filename, 0o600)

        write_fifo(fifo_path, data + " " + filename)

        with open(filename, "rb") as h:
            return h.read()
    finally:
        try:
            os.unlink(filename)
        except EnvironmentError:
            pass


def fifo_exists(fifo_path):
    # http://code.google.com/p/quodlibet/issues/detail?id=1131
    # FIXME: There is a race where control() creates a new file
    # instead of writing to the FIFO, confusing the next QL instance.
    # Remove non-FIFOs here for now.
    try:
        if not stat.S_ISFIFO(os.stat(fifo_path).st_mode):
            print_d("%r not a FIFO. Removing it." % fifo_path)
            os.remove(fifo_path)
    except OSError:
        pass
    return os.path.exists(fifo_path)


class FIFO(object):
    """Creates and reads from a FIFO"""

    def __init__(self, path, callback):
        self._callback = callback
        self._path = path

    def open(self):
        self._open(None)

    def destroy(self):
        if self._id is not None:
            GLib.source_remove(self._id)
            self._id = None

        try:
            os.unlink(self._path)
        except EnvironmentError:
            pass

    def _open(self, *args):
        from quodlibet import qltk

        self._id = None
        try:
            if not os.path.exists(self._path):
                mkdir(os.path.dirname(self._path))
                os.mkfifo(self._path, 0600)
            fifo = os.open(self._path, os.O_NONBLOCK)
            f = os.fdopen(fifo, "r", 4096)
            self._id = qltk.io_add_watch(
                f, GLib.PRIORITY_DEFAULT,
                GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                self._process, *args)
        except (EnvironmentError, AttributeError):
            pass

    def _process(self, source, condition, *args):
        if condition in (GLib.IO_ERR, GLib.IO_HUP):
            self._open(*args)
            return False

        while True:
            try:
                data = source.read()
            except (IOError, OSError) as e:
                if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                    return True
                elif e.errno == errno.EINTR:
                    continue
                else:
                    self.__open(*args)
                    return False
            break

        if not data:
            self._open(*args)
            return False

        self._callback(data)

        return True