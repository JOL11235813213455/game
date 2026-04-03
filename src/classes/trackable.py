import weakref

class Trackable:
    _instances = weakref.WeakSet()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._instances = weakref.WeakSet()

    def __init__(self):
        self.__class__._instances.add(self)

    @classmethod
    def all(cls):
        return list(cls._instances)