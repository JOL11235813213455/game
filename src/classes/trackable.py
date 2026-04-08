import weakref

class Trackable:
    _instances = weakref.WeakSet()
    _subclasses: list = []
    _next_uid: int = 1

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._instances = weakref.WeakSet()
        Trackable._subclasses.append(cls)

    def __init__(self):
        self.uid = Trackable._next_uid
        Trackable._next_uid += 1
        self.__class__._instances.add(self)
        self._timed_events: dict[str, list] = {}

    @classmethod
    def reset_uid_counter(cls):
        """Reset UID counter after loading saved objects.

        Call after all deserialized objects are registered so new objects
        get UIDs that don't collide with loaded ones.
        """
        max_uid = 0
        for obj in cls.all_instances():
            uid = getattr(obj, 'uid', 0)
            if uid > max_uid:
                max_uid = uid
        cls._next_uid = max_uid + 1

    # -- timed event system ------------------------------------------------

    def register_tick(self, name: str, interval_ms: int, callback):
        """Register a named timed event.

        Args:
            name: unique key for this event (e.g. 'hp_regen', 'behavior')
            interval_ms: minimum milliseconds between firings
            callback: function(now) called when the interval elapses
        """
        self._timed_events[name] = [interval_ms, 0, callback]

    def unregister_tick(self, name: str):
        """Remove a named timed event."""
        self._timed_events.pop(name, None)

    def set_tick_interval(self, name: str, interval_ms: int):
        """Update the interval of an existing timed event."""
        if name in self._timed_events:
            self._timed_events[name][0] = interval_ms

    def process_ticks(self, now: int):
        """Fire any timed events whose interval has elapsed."""
        for entry in self._timed_events.values():
            interval, last, callback = entry
            if now - last >= interval:
                callback(now)
                entry[1] = now

    # -- instance tracking -------------------------------------------------

    @classmethod
    def all(cls):
        return list(cls._instances)

    @classmethod
    def all_instances(cls):
        seen = set()
        result = []
        for subcls in Trackable._subclasses:
            for obj in subcls.all():
                if id(obj) not in seen:
                    seen.add(id(obj))
                    result.append(obj)
        return result
