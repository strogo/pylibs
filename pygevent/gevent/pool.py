# Copyright (c) 2009-2010 Denis Bilenko. See LICENSE for details.

from gevent.hub import GreenletExit, getcurrent
from gevent.greenlet import joinall, Greenlet
from gevent.timeout import Timeout
from gevent.event import Event
from gevent.coros import Semaphore, DummySemaphore

__all__ = ['GreenletSet', 'Pool']


class GreenletSet(object):
    """Maintain a set of greenlets that are still running.

    Links to each item and removes it upon notification.
    """
    greenlet_class = Greenlet

    def __init__(self, *args):
        assert len(args)<=1, args
        self.greenlets = set(*args)
        if args:
            for greenlet in args[0]:
                greenlet.rawlink(self.discard)
        # each item we kill we place in dying, to avoid killing the same greenlet twice
        self.dying = set()
        self._empty_event = Event()
        self._empty_event.set()

    def __repr__(self):
        try:
            classname = self.__class__.__name__
        except AttributeError:
            classname = 'GreenletSet' # XXX check if 2.4 really uses this line
        return '<%s at %s %s>' % (classname, hex(id(self)), self.greenlets)

    def __len__(self):
        return len(self.greenlets)

    def __contains__(self, item):
        return item in self.greenlets

    def __iter__(self):
        return iter(self.greenlets)

    def add(self, greenlet):
        greenlet.rawlink(self.discard)
        self.greenlets.add(greenlet)
        self._empty_event.clear()

    def discard(self, greenlet):
        self.greenlets.discard(greenlet)
        self.dying.discard(greenlet)
        if not self.greenlets:
            self._empty_event.set()

    def start(self, greenlet):
        self.add(greenlet)
        greenlet.start()

    def spawn(self, *args, **kwargs):
        add = self.add
        greenlet = self.greenlet_class.spawn(*args, **kwargs)
        add(greenlet)
        return greenlet

    def spawn_link(self, *args, **kwargs):
        greenlet = self.spawn(*args, **kwargs)
        greenlet.link()
        return greenlet

    def spawn_link_value(self, *args, **kwargs):
        greenlet = self.spawn(*args, **kwargs)
        greenlet.link_value()
        return greenlet

    def spawn_link_exception(self, *args, **kwargs):
        greenlet = self.spawn(*args, **kwargs)
        greenlet.link_exception()
        return greenlet

#     def close(self):
#         """Prevents any more tasks from being submitted to the pool"""
#         self.add = RaiseException("This %s has been closed" % self.__class__.__name__)

    def join(self, timeout=None, raise_error=False):
        if raise_error:
            greenlets = self.greenlets.copy()
            self._empty_event.wait(timeout=timeout)
            for greenlet in greenlets:
                if not greenlet.successful():
                    raise greenlet.exception
        else:
            self._empty_event.wait(timeout=timeout)

    def kill(self, exception=GreenletExit, block=True, timeout=None):
        timer = Timeout.start_new(timeout)
        try:
            try:
                while self.greenlets:
                    for greenlet in list(self.greenlets):
                        if greenlet not in self.dying:
                            greenlet.kill(exception, block=False)
                            self.dying.add(greenlet)
                    if not block:
                        break
                    joinall(self.greenlets)
            except Timeout, ex:
                if ex is not timer:
                    raise
        finally:
            timer.cancel()

    def killone(self, greenlet, exception=GreenletExit, block=True, timeout=None):
        if greenlet not in self.dying and greenlet in self.greenlets:
            greenlet.kill(exception, block=False)
            self.dying.add(greenlet)
            if block:
                greenlet.join(timeout)

    def apply(self, func, args=None, kwds=None):
        """Equivalent of the apply() builtin function. It blocks till the result is ready."""
        if args is None:
            args = ()
        if kwds is None:
            kwds = {}
        if getcurrent() in self:
            return func(*args, **kwds)
        else:
            return self.spawn(func, *args, **kwds).get()

    def apply_cb(self, func, args=None, kwds=None, callback=None):
        result = self.apply(func, args, kwds)
        if callback is not None:
            Greenlet.spawn(callback, result)
        return result

    def apply_async(self, func, args=None, kwds=None, callback=None):
        """A variant of the apply() method which returns a Greenlet object.

        If callback is specified then it should be a callable which accepts a single argument. When the result becomes ready
        callback is applied to it (unless the call failed)."""
        if args is None:
            args = ()
        if kwds is None:
            kwds = {}
        if self.full():
            # cannot call spawn() directly because it will block
            return Greenlet.spawn(self.apply_cb, func, args, kwds, callback)
        else:
            greenlet = self.spawn(func, *args, **kwds)
            if callback is not None:
                greenlet.link(pass_value(callback))
            return greenlet

    def map(self, func, iterable):
        greenlets = [self.spawn(func, item) for item in iterable]
        return [greenlet.get() for greenlet in greenlets]

    def map_cb(self, func, iterable, callback=None):
        result = self.map(func, iterable)
        if callback is not None:
            callback(result)
        return result

    def map_async(self, func, iterable, callback=None):
        """
        A variant of the map() method which returns a Greenlet object.

        If callback is specified then it should be a callable which accepts a
        single argument.
        """
        return Greenlet.spawn(self.map_cb, func, iterable, callback)

    def imap(self, func, iterable):
        """An equivalent of itertools.imap()"""
        # FIXME
        return iter(self.map(func, iterable))

    def imap_unordered(self, func, iterable):
        """The same as imap() except that the ordering of the results from the
        returned iterator should be considered arbitrary."""
        # FIXME
        return iter(self.map(func, iterable))

    def full(self):
        return False

    def wait_available(self):
        pass


class Pool(GreenletSet):

    def __init__(self, size=None, greenlet_class=None):
        if size is not None and size < 0:
            raise ValueError('Invalid size for pool (positive integer or None required): %r' % (size, ))
        GreenletSet.__init__(self)
        self.size = size
        if greenlet_class is not None:
            self.greenlet_class = greenlet_class
        if size is None:
            self._semaphore = DummySemaphore()
        else:
            self._semaphore = Semaphore(size)

    def wait_available(self):
        self._semaphore.wait()

    def full(self):
        return self.free_count() <= 0

    def free_count(self):
        if self.size is None:
            return 1
        return max(0, self.size - len(self))

    def start(self, greenlet):
        self._semaphore.acquire()
        try:
            self.add(greenlet)
        except:
            self._semaphore.release()
            raise
        greenlet.start()

    def spawn(self, *args, **kwargs):
        self._semaphore.acquire()
        try:
            greenlet = self.greenlet_class.spawn(*args, **kwargs)
            self.add(greenlet)
        except:
            self._semaphore.release()
            raise
        return greenlet

    def spawn_link(self, *args, **kwargs):
        self._semaphore.acquire()
        try:
            greenlet = self.greenlet_class.spawn_link(*args, **kwargs)
            self.add(greenlet)
        except:
            self._semaphore.release()
            raise
        return greenlet

    def spawn_link_value(self, *args, **kwargs):
        self._semaphore.acquire()
        try:
            greenlet = self.greenlet_class.spawn_link_value(*args, **kwargs)
            self.add(greenlet)
        except:
            self._semaphore.release()
            raise
        return greenlet

    def spawn_link_exception(self, *args, **kwargs):
        self._semaphore.acquire()
        try:
            greenlet = self.greenlet_class.spawn_link_exception(*args, **kwargs)
            self.add(greenlet)
        except:
            self._semaphore.release()
            raise
        return greenlet

    def discard(self, greenlet):
        GreenletSet.discard(self, greenlet)
        self._semaphore.release()


def get_values(greenlets):
    joinall(greenlets)
    return [x.value for x in greenlets]


class pass_value(object):
    __slots__ = ['callback']

    def __init__(self, callback):
        self.callback = callback

    def __call__(self, source):
        if source.successful():
            self.callback(source.value)

    def __hash__(self):
        return hash(self.callback)

    def __eq__(self, other):
        return self.callback == getattr(other, 'callback', other)

    def __str__(self):
        return str(self.callback)

    def __repr__(self):
        return repr(self.callback)

    def __getattr__(self, item):
        assert item != 'callback'
        return getattr(self.callback, item)
