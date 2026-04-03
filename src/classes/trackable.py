import weakref

class Trackable:
    _instances = weakref.WeakSet()
    _subclasses: list = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._instances = weakref.WeakSet()
        Trackable._subclasses.append(cls)

    def __init__(self):
        self.__class__._instances.add(self)

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
